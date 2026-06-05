"""
Action Response Profiler — BT 액션의 control → state 응답 측정

목적:
  Pursuit_Chase_BT 설계의 사전 작업.
  각 BT 액션이 즉발/rate-limited/multi-phase 중 어디에 속하는지 측정하여
  HJI dynamics 모델의 rate constraint 또는 augmented state 결정에 활용.

전략:
  1. 격리 YAML 생성 (HardDeck 안전망 + 단일 측정 대상 액션만)
  2. scripts.run_match.run_match() 호출, --log-csv 로 50-column per-tick CSV 생성
  3. CSV 분석: active_node == <ACTION> 행 필터 → 응답 metric 추출
  4. 11개 액션 × N trial → action_latency_metrics.csv + 분류

실행:
  python tools/profile_action_response.py --action LeadPursuit         # 단일
  python tools/profile_action_response.py --tier 1                     # Tier 1 전체
  python tools/profile_action_response.py --all                        # 11개 전체
  python tools/profile_action_response.py --action LeadPursuit --verify  # 1 trial + CSV 경로 출력

출력:
  logs/profiling/yamls/profile_<action>.yaml       — 격리 BT (자동 생성)
  logs/profiling/<timestamp>_*.csv                 — 매치 CSV (run_match 생성)
  logs/profiling/action_latency_metrics.csv       — 통합 metric (이 도구 작성)
"""

import sys
import os
import argparse
import time
from pathlib import Path
from typing import Dict, List, Optional
from collections import Counter

# Windows cp949 fallback — 한글 환경에서 ✓/✗ 등 유니코드 표시 보장
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_match import run_match  # noqa: E402

# ─── 상수 ──────────────────────────────────────────────────────
DT = 0.2  # BT tick interval (5 Hz) — JSBSim 60Hz 의 12 substep

PROFILING_DIR = PROJECT_ROOT / "logs" / "profiling"
YAMLS_DIR = PROFILING_DIR / "yamls"

# Action → opponent + 기본 파라미터
# 모두 builtin 액션 사용 (src/behavior_tree/nodes/actions.py 등록 노드)
# Smart*/PN* 류는 submission별 custom_actions.py 의존이라 격리 측정에 부적합
ACTION_CONFIG = {
    # ── Tier 1: HJI primitive (즉발 또는 rate-limited 예상) ──
    "LeadPursuit":  {"tier": 1, "opponent": "horizontal_flight", "params": {}},
    "LagPursuit":   {"tier": 1, "opponent": "horizontal_flight", "params": {}},
    "PurePursuit":  {"tier": 1, "opponent": "horizontal_flight", "params": {}},
    "Pursue":       {"tier": 1, "opponent": "horizontal_flight", "params": {}},
    "Accelerate":   {"tier": 1, "opponent": "horizontal_flight", "params": {}},
    "Decelerate":   {"tier": 1, "opponent": "horizontal_flight", "params": {}},
    "ClimbTo":      {"tier": 1, "opponent": "horizontal_flight",
                     "params": {"target_altitude_ft": 18000}},
    "DescendTo":    {"tier": 1, "opponent": "horizontal_flight",
                     "params": {"target_altitude_ft": 12000}},
    "BreakTurn":    {"tier": 1, "opponent": "aggressive",        "params": {}},
    "TurnLeft":     {"tier": 1, "opponent": "horizontal_flight", "params": {}},
    "TurnRight":    {"tier": 1, "opponent": "horizontal_flight", "params": {}},
    "Straight":     {"tier": 1, "opponent": "horizontal_flight", "params": {}},
    "MaintainAltitude": {"tier": 1, "opponent": "horizontal_flight", "params": {}},
    # ── Tier 2: multi-phase composite ──
    "HighYoYo":     {"tier": 2, "opponent": "aggressive",        "params": {}},
    "LowYoYo":      {"tier": 2, "opponent": "aggressive",        "params": {}},
    "Loop":         {"tier": 2, "opponent": "horizontal_flight", "params": {}},
    "ImmelmannTurn":{"tier": 2, "opponent": "horizontal_flight", "params": {}},
    "SplitS":       {"tier": 2, "opponent": "horizontal_flight", "params": {}},
    "BarrelRoll":   {"tier": 2, "opponent": "aggressive",        "params": {}},
    "ClimbingTurn": {"tier": 2, "opponent": "horizontal_flight", "params": {}},
    "DescendingTurn":{"tier": 2, "opponent": "horizontal_flight","params": {}},
    "HammerHead":   {"tier": 2, "opponent": "horizontal_flight", "params": {}},
    "DefensiveManeuver": {"tier": 2, "opponent": "aggressive",   "params": {}},
    "DefensiveSpiral":   {"tier": 2, "opponent": "aggressive",   "params": {}},
    "OvershootAvoidance":{"tier": 2, "opponent": "aggressive",   "params": {}},
    "Evade":        {"tier": 2, "opponent": "aggressive",        "params": {}},
    # ── Tier 3: terminal / composite tactic ──
    "GunAttack":    {"tier": 3, "opponent": "horizontal_flight", "params": {}},
    "EnergyFight":  {"tier": 3, "opponent": "aggressive",        "params": {}},
    "OneCircleFight":{"tier": 3, "opponent": "aggressive",       "params": {}},
    "TwoCircleFight":{"tier": 3, "opponent": "aggressive",       "params": {}},
    "TCFight":      {"tier": 3, "opponent": "aggressive",        "params": {}},
}


# ─── 격리 YAML 생성 ────────────────────────────────────────────

def make_isolation_yaml(action: str, params: Optional[dict] = None) -> Path:
    """단일 액션만 실행하는 격리 BT YAML 생성.

    구조:
      Selector
        ├─ HardDeckAvoidance (안전망 — alt<1200ft 시 ClimbTo)
        └─ Action(<action>, params)  ← 측정 대상, default fallback
    """
    YAMLS_DIR.mkdir(parents=True, exist_ok=True)
    yaml_path = YAMLS_DIR / f"profile_{action}.yaml"

    # Build params block at correct indent level (matches sibling `name:` at 6 spaces)
    params_block = ""
    if params:
        lines = [f"        {k}: {v}" for k, v in params.items()]
        params_block = "      params:\n" + "\n".join(lines) + "\n"

    content = f"""# Auto-generated by tools/profile_action_response.py — DO NOT EDIT
# Isolation BT for measuring response of action: {action}
name: "profile_{action}"
version: "0.0.1"
description: "Action response profiling — {action} only (HardDeck safety + target action)"

tree:
  type: Selector
  children:
    # 안전: hard deck 회피만 유지
    - type: Sequence
      name: HardDeckAvoidance
      children:
        - type: Condition
          name: BelowHardDeck
          params:
            threshold_ft: 1200
        - type: Action
          name: ClimbTo
          params:
            target_altitude_ft: 3000

    # 측정 대상 액션 (default — 조건 없이 무조건 발동)
    - type: Action
      name: {action}
{params_block}"""
    yaml_path.write_text(content, encoding="utf-8")
    return yaml_path


# ─── CSV 찾기 ──────────────────────────────────────────────────

def find_csv_after(output_dir: Path, t_min: float, action: str) -> Optional[Path]:
    """t_min 이후 생성된 CSV 중 가장 최근 것."""
    pattern = f"*profile_{action}*.csv"
    candidates = []
    for p in output_dir.glob(pattern):
        try:
            mtime = p.stat().st_mtime
            if mtime >= t_min - 1:  # 1초 여유
                candidates.append((mtime, p))
        except OSError:
            continue
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


# ─── 단일 trial 실행 ───────────────────────────────────────────

def run_one_trial(action: str, params: dict, opponent: str,
                  max_steps: int = 150) -> Optional[Path]:
    """매치 실행 후 생성된 CSV 경로 반환."""
    yaml_path = make_isolation_yaml(action, params)
    t_start = time.time()

    try:
        run_match(
            agent1=str(yaml_path),
            agent2=opponent,
            rounds=1,
            max_steps=max_steps,
            log_csv=str(PROFILING_DIR),
            verbose=False,
        )
    except Exception as e:
        print(f"    [run_match error] {e}")
        return None

    return find_csv_after(PROFILING_DIR, t_start, action)


# ─── 응답 metric 계산 ──────────────────────────────────────────

def compute_metrics(df: pd.DataFrame, action: str) -> Dict:
    """액션 활성 구간 dataframe → metric dict."""
    metrics = {"action": action}

    # 측정된 변화율 (state derivative — 이미 노출됨)
    if "turn_rate_degs" in df.columns:
        tr = df["turn_rate_degs"].dropna()
        if len(tr) > 0:
            metrics["turn_rate_max_degs"] = float(tr.abs().max())
            metrics["turn_rate_mean_degs"] = float(tr.abs().mean())

    # Ps (Boyd EM)
    if "ps_fts" in df.columns:
        ps = df["ps_fts"].dropna()
        if len(ps) > 0:
            metrics["ps_mean_fts"] = float(ps.mean())
            metrics["ps_std_fts"] = float(ps.std())

    # γ (flight path angle) from velocity vector
    if all(c in df.columns for c in ["ego_vx_kts", "ego_vy_kts", "ego_vz_kts"]):
        vx, vy, vz = df["ego_vx_kts"].values, df["ego_vy_kts"].values, df["ego_vz_kts"].values
        v_mag = np.sqrt(vx ** 2 + vy ** 2 + vz ** 2) + 1e-6
        gamma_deg = np.degrees(np.arcsin(np.clip(vz / v_mag, -1.0, 1.0)))
        if len(gamma_deg) > 1:
            gamma_rate = np.diff(gamma_deg) / DT
            metrics["gamma_max_deg"] = float(np.abs(gamma_deg).max())
            metrics["gamma_rate_max_degs"] = float(np.abs(gamma_rate).max())

    # 속도 변화율
    if "ego_vc_kts" in df.columns:
        v = df["ego_vc_kts"].dropna().values
        if len(v) > 1:
            v_rate = np.diff(v) / DT
            metrics["v_rate_max_ktss"] = float(np.abs(v_rate).max())
            metrics["v_rate_mean_ktss"] = float(np.abs(v_rate).mean())
            metrics["v_range_kts"] = float(v.max() - v.min())

    # 고도 변화율
    if "ego_altitude_ft" in df.columns:
        h = df["ego_altitude_ft"].dropna().values
        if len(h) > 1:
            h_rate = np.diff(h) / DT  # ft/s
            metrics["h_rate_max_fts"] = float(np.abs(h_rate).max())
            metrics["h_range_ft"] = float(h.max() - h.min())

    # 명령 (action_*) 분포 분석
    # 액션이 "원하는" 효과를 파악하기 위해 BT가 출력한 명령의 변동 측정
    for cmd_col in ["action_altitude", "action_heading", "action_velocity"]:
        if cmd_col in df.columns:
            vals = df[cmd_col].dropna().values
            if len(vals) > 2:
                # 명령 값 분포
                metrics[f"{cmd_col}_min"] = float(vals.min())
                metrics[f"{cmd_col}_max"] = float(vals.max())
                metrics[f"{cmd_col}_range"] = float(vals.max() - vals.min())
                metrics[f"{cmd_col}_std"] = float(np.std(vals))
                metrics[f"{cmd_col}_unique"] = int(len(np.unique(vals)))
                # 부호 변경 (다단 시퀀스 검출용 — 충분히 큰 변화만 카운트)
                diff = np.diff(vals)
                if len(diff) > 0 and np.std(diff) > 0:
                    threshold = max(np.std(diff) * 0.5, 0.1)
                    significant = np.abs(diff) > threshold
                    signs = np.sign(diff[significant])
                    if len(signs) > 1:
                        sign_changes = int(((signs[:-1] * signs[1:]) < 0).sum())
                    else:
                        sign_changes = 0
                else:
                    sign_changes = 0
                metrics[f"{cmd_col}_sign_changes"] = sign_changes

    # multi-phase 점수: 명령이 다중 phase 패턴 보이는가
    mp_score = 0
    if metrics.get("action_altitude_sign_changes", 0) >= 3:
        mp_score += 1
    if metrics.get("action_velocity_sign_changes", 0) >= 3:
        mp_score += 1
    if metrics.get("action_heading_sign_changes", 0) >= 5:
        mp_score += 1
    metrics["multi_phase_score"] = mp_score

    metrics["classification"] = classify(metrics)
    return metrics


def classify(m: Dict) -> str:
    """응답 metric → 분류 라벨.

    2단계 분류:
      1) 액션의 INTENT 식별 — BT 명령(action_*)의 변동성으로
      2) 응답 INTENSITY — 측정된 state 변화로

    Multi-phase는 별개로 우선 검출 (명령 시퀀스의 부호 변경).
    """
    if m.get("multi_phase_score", 0) >= 1:
        return "multi_phase"

    # ── 단계 1: BT 명령 의도 (어느 채널이 가장 활발한가) ──
    cmd_act = {
        "altitude": (m.get("action_altitude_unique") or 1) - 1,
        "heading":  (m.get("action_heading_unique") or 1) - 1,
        "velocity": (m.get("action_velocity_unique") or 1) - 1,
    }
    # 모든 채널이 동일 값이면 (1 unique) → 정적 명령
    if max(cmd_act.values()) == 0:
        return "static_command"

    intent = max(cmd_act, key=cmd_act.get)

    # ── 단계 2: state 변화 강도 (envelope 비율) ──
    response_scores = {
        "altitude": (m.get("h_range_ft") or 0) / 5000.0,
        "heading":  (m.get("turn_rate_max_degs") or 0) / 21.0,
        "velocity": (m.get("v_range_kts") or 0) / 260.0,  # V_max-V_min ≈ 260kts
    }
    # intent 채널의 응답 점수
    intensity_score = response_scores.get(intent, 0)

    # 강도 라벨
    if intensity_score < 0.02:
        intensity = "weak"
    elif intensity_score < 0.10:
        intensity = "mild"
    elif intensity_score < 0.30:
        intensity = "moderate"
    elif intensity_score < 0.60:
        intensity = "strong"
    else:
        intensity = "aggressive"

    return f"{intensity}_{intent}"


def analyze_csv(csv_path: Path, action: str) -> Dict:
    """CSV → 측정 metric."""
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        return {"error": f"csv_read_failed: {e}"}

    target_name = f"profile_{action}"
    if "tree_name" in df.columns:
        df_us = df[df["tree_name"] == target_name].sort_values("step").reset_index(drop=True)
    else:
        return {"error": "tree_name column missing"}

    if len(df_us) < 5:
        return {"error": "insufficient_rows", "n_rows": int(len(df_us))}

    # active_node 필터 (격리 BT라 거의 항상 action이지만 HardDeck 발동 가능)
    if "active_node" in df_us.columns:
        active_mask = df_us["active_node"] == action
        df_act = df_us[active_mask].sort_values("step").reset_index(drop=True)
    else:
        df_act = df_us

    if len(df_act) < 5:
        return {
            "error": "action_not_active",
            "n_rows": int(len(df_us)),
            "n_active_rows": int(len(df_act)),
            "most_common_active_node": (df_us["active_node"].mode().iloc[0]
                                        if "active_node" in df_us.columns and len(df_us["active_node"].mode()) > 0
                                        else None),
        }

    m = compute_metrics(df_act, action)
    m["n_rows"] = int(len(df_us))
    m["n_active_rows"] = int(len(df_act))
    m["active_ratio"] = round(len(df_act) / len(df_us), 3)
    return m


# ─── 액션 1개 N trial 측정 ─────────────────────────────────────

def profile_action(action: str, trials: int = 5, max_steps: int = 150,
                   verbose: bool = True) -> Dict:
    config = ACTION_CONFIG.get(action)
    if not config:
        print(f"❌ Unknown action: {action}. Available: {list(ACTION_CONFIG.keys())}")
        return {"action": action, "error": "unknown_action"}

    opponent = config["opponent"]
    params = config["params"]

    if verbose:
        print(f"\n{'='*70}")
        print(f"  Profiling: {action}  (tier {config['tier']}, vs {opponent}, {trials} trial)")
        print(f"{'='*70}")

    trial_results: List[Dict] = []
    csv_paths: List[Path] = []

    for i in range(trials):
        t0 = time.time()
        if verbose:
            print(f"  trial {i + 1}/{trials} ...", end="", flush=True)
        csv_path = run_one_trial(action, params, opponent, max_steps)
        elapsed = time.time() - t0
        if csv_path is None:
            if verbose:
                print(f"  ❌ no CSV  ({elapsed:.1f}s)")
            continue
        csv_paths.append(csv_path)
        m = analyze_csv(csv_path, action)
        trial_results.append(m)
        if verbose:
            cls = m.get("classification") or m.get("error", "?")
            n_act = m.get("n_active_rows", 0)
            print(f"  ✓ {elapsed:5.1f}s  cls={cls}  active_rows={n_act}")

    if not trial_results:
        return {"action": action, "tier": config["tier"], "opponent": opponent,
                "error": "no_successful_trials"}

    # 평균 (numerical fields)
    avg: Dict = {
        "action": action,
        "tier": config["tier"],
        "opponent": opponent,
        "n_trials": len(trial_results),
    }

    # 수집된 모든 키
    keys = set()
    for r in trial_results:
        keys.update(r.keys())

    for k in sorted(keys):
        if k in ("action", "classification", "error", "most_common_active_node"):
            continue
        vals = [r[k] for r in trial_results
                if k in r and isinstance(r[k], (int, float)) and not isinstance(r[k], bool)]
        if vals:
            avg[f"{k}_mean"] = float(np.mean(vals))
            avg[f"{k}_std"] = float(np.std(vals)) if len(vals) > 1 else 0.0

    cls_list = [r.get("classification") for r in trial_results if r.get("classification")]
    if cls_list:
        avg["classification"] = Counter(cls_list).most_common(1)[0][0]
    else:
        # error 케이스
        err_list = [r.get("error") for r in trial_results if r.get("error")]
        if err_list:
            avg["error"] = Counter(err_list).most_common(1)[0][0]

    avg["csv_paths"] = "; ".join(str(p) for p in csv_paths)
    return avg


# ─── 통합 CSV 저장 ─────────────────────────────────────────────

def write_metrics_csv(results: List[Dict], out_path: Path):
    if not results:
        return

    all_keys = set()
    for r in results:
        all_keys.update(r.keys())

    leading = ["action", "tier", "opponent", "n_trials", "classification", "error"]
    others = sorted(k for k in all_keys if k not in leading and k != "csv_paths")
    cols = [c for c in leading if c in all_keys] + others + (["csv_paths"] if "csv_paths" in all_keys else [])

    df = pd.DataFrame(results)
    df = df.reindex(columns=[c for c in cols if c in df.columns])
    df.to_csv(out_path, index=False, encoding="utf-8")
    print(f"\n✓ Metrics saved: {out_path}  ({len(results)} actions)")


# ─── CLI ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BT Action Response Profiler")
    parser.add_argument("--action", type=str, default=None,
                        help="측정할 단일 액션 (예: LeadPursuit)")
    parser.add_argument("--tier", type=int, default=None, choices=[1, 2, 3],
                        help="측정할 tier (1/2/3)")
    parser.add_argument("--all", action="store_true",
                        help="11개 액션 전체 측정")
    parser.add_argument("--trials", type=int, default=5,
                        help="액션당 trial 수 (default 5)")
    parser.add_argument("--max-steps", type=int, default=150,
                        help="매치당 최대 step (default 150 = 30s @ 5Hz tick)")
    parser.add_argument("--verify", action="store_true",
                        help="단일 trial 후 CSV 경로 출력 (사용자 검증용)")
    args = parser.parse_args()

    if args.action:
        actions = [args.action]
    elif args.tier:
        actions = [a for a, c in ACTION_CONFIG.items() if c["tier"] == args.tier]
    elif args.all:
        actions = list(ACTION_CONFIG.keys())
    else:
        # 기본: LeadPursuit 단일 trial verify
        actions = ["LeadPursuit"]
        args.verify = True

    trials = 1 if args.verify else args.trials

    print(f"\n{'='*70}")
    print(f"  Action Response Profiler")
    print(f"{'='*70}")
    print(f"  Actions:           {actions}")
    print(f"  Trials per action: {trials}")
    print(f"  Max steps:         {args.max_steps}")
    print(f"  Profiling dir:     {PROFILING_DIR}")

    PROFILING_DIR.mkdir(parents=True, exist_ok=True)
    YAMLS_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for action in actions:
        r = profile_action(action, trials=trials, max_steps=args.max_steps)
        results.append(r)

    # 종합 출력
    print(f"\n{'='*70}")
    print(f"  Summary")
    print(f"{'='*70}")
    print(f"  {'Action':<22} {'Tier':<5} {'Cls/Err':<32} {'TR°/s':<8}")
    print(f"  {'-'*22} {'-'*5} {'-'*32} {'-'*8}")
    for r in results:
        cls = r.get("classification") or r.get("error", "?")
        tr = r.get("turn_rate_max_degs_mean", "—")
        if isinstance(tr, float):
            tr = f"{tr:.1f}"
        print(f"  {r.get('action', '?'):<22} {str(r.get('tier', '?')):<5} {str(cls)[:32]:<32} {str(tr):<8}")

    # 통합 CSV (verify 모드 아닐 때만)
    if not args.verify and len(results) > 1:
        out_path = PROFILING_DIR / "action_latency_metrics.csv"
        write_metrics_csv(results, out_path)

    # verify 모드는 CSV 경로 안내
    if args.verify:
        print(f"\n{'='*70}")
        print(f"  Verify mode — CSV paths for inspection:")
        print(f"{'='*70}")
        for r in results:
            paths = r.get("csv_paths", "")
            if paths:
                for p in paths.split("; "):
                    print(f"  {p}")

    print()


if __name__ == "__main__":
    main()
