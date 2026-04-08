"""
통합 평가 함수 — Phase 1a

모든 평가 도구(test_agent, bt_optimizer, collect_phase1)가 이 함수를 사용.
단일 진입점으로 통계적으로 유의한 평가 + 원인 분석 + 노드 발동 통계를 제공.

사용법 (라이브러리):
    from tools.evaluate import evaluate
    result = evaluate("adaptive_eagle", rounds=50)
    print(result["win_rate"], result["ci_95"])

사용법 (CLI):
    python tools/evaluate.py adaptive_eagle
    python tools/evaluate.py adaptive_eagle --rounds 50 --opponents eagle1 ace
    python tools/evaluate.py adaptive_eagle --rounds 50 --all-opponents
"""

import sys
import math
import json
import argparse
import time
from pathlib import Path
from collections import defaultdict, Counter
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.match.runner import BehaviorTreeMatch

# ─── 기본 상대 풀 ──────────────────────────────────────────────

DEFAULT_OPPONENTS = ["eagle1", "ace", "aggressive", "defensive", "simple", "viper1"]


# ─── 에이전트 경로 해석 ────────────────────────────────────────

def _resolve_agent(name: str) -> str:
    """에이전트 이름 → YAML 파일 절대 경로."""
    # 직접 경로
    if "/" in name or "\\" in name:
        p = Path(name)
        if not p.is_absolute():
            p = PROJECT_ROOT / name
        if p.exists():
            return str(p)
        raise FileNotFoundError(f"Agent not found: {name}")

    # submissions/{name}/{name}.yaml
    p = PROJECT_ROOT / "submissions" / name / f"{name}.yaml"
    if p.exists():
        return str(p)

    # examples/{name}.yaml
    p = PROJECT_ROOT / "examples" / f"{name}.yaml"
    if p.exists():
        return str(p)

    # examples/{name}/{name}.yaml
    p = PROJECT_ROOT / "examples" / name / f"{name}.yaml"
    if p.exists():
        return str(p)

    raise FileNotFoundError(f"Agent not found: {name}")


# ─── 단일 매치 실행 ───────────────────────────────────────────

def _run_single(agent_path: str, opponent_path: str, agent_name: str, opponent_name: str,
                max_steps: int = 1500) -> dict:
    """단일 매치 실행 → 상세 결과 dict 반환."""
    match = BehaviorTreeMatch(
        tree1_file=agent_path,
        tree2_file=opponent_path,
        config_name="1v1/NoWeapon/bt_vs_bt",
        max_steps=max_steps,
        tree1_name=agent_name,
        tree2_name=opponent_name,
    )

    try:
        result = match.run(verbose=False)
    except Exception as e:
        return {"winner": "error", "error": str(e), "success": False}

    winner = getattr(result, "winner", "unknown")
    steps = getattr(result, "steps", getattr(result, "total_steps", 0))
    tree1_reward = getattr(result, "tree1_reward", 0.0)
    tree2_reward = getattr(result, "tree2_reward", 0.0)

    # Health 추출
    t1_hp = 100.0
    t2_hp = 100.0
    h1 = getattr(match, "health1", None)
    h2 = getattr(match, "health2", None)
    if h1 is not None:
        t1_hp = getattr(h1, "current_health", h1)
    if h2 is not None:
        t2_hp = getattr(h2, "current_health", h2)

    # 패배 원인 분류
    loss_cause = None
    if winner == "tree2":
        ego_alt = None
        task1 = getattr(match, "task1", None)
        if task1 is not None:
            bb = getattr(task1, "blackboard", None)
            if bb is not None:
                obs = getattr(bb, "observation", None)
                if obs and isinstance(obs, dict):
                    ego_alt = obs.get("ego_altitude_ft", None)
        if ego_alt is not None and ego_alt < 1100:
            loss_cause = "hard_deck"
        elif steps >= max_steps:
            loss_cause = "timeout"
        else:
            loss_cause = "hp_diff"
    elif winner == "draw":
        loss_cause = "draw"

    return {
        "winner": winner,
        "total_steps": steps,
        "tree1_reward": tree1_reward,
        "tree2_reward": tree2_reward,
        "tree1_health": t1_hp,
        "tree2_health": t2_hp,
        "loss_cause": loss_cause,
        "success": True,
    }


# ─── 신뢰구간 계산 ───────────────────────────────────────────

def _wilson_ci(wins: int, total: int, z: float = 1.96) -> tuple:
    """Wilson score interval — 소표본에서도 안정적인 승률 신뢰구간."""
    if total == 0:
        return (0.0, 0.0)
    p = wins / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    lo = max(0.0, centre - margin)
    hi = min(1.0, centre + margin)
    return (round(lo, 4), round(hi, 4))


# ─── 통합 평가 함수 ──────────────────────────────────────────

def evaluate(
    agent: str,
    opponents: Optional[list] = None,
    rounds: int = 50,
    max_steps: int = 1500,
    silent: bool = False,
) -> dict:
    """통합 평가 — 모든 도구가 이 함수를 사용.

    Args:
        agent: 평가할 에이전트 이름 또는 경로
        opponents: 상대 목록 (None이면 DEFAULT_OPPONENTS 6종)
        rounds: 상대당 라운드 수
        max_steps: 매치당 최대 스텝
        silent: True면 콘솔 출력 최소화

    Returns:
        dict: {
            win_rate, ci_95,
            per_opponent: {name: {W, D, L, win_rate, ci_95, avg_hp_diff, ...}},
            loss_causes: {hard_deck, hp_diff, timeout, draw},
            totals: {W, D, L, total},
            matches: [모든 매치 상세],
        }
    """
    if opponents is None:
        opponents = DEFAULT_OPPONENTS

    agent_path = _resolve_agent(agent)
    agent_name = Path(agent_path).stem

    opponent_paths = {}
    for opp in opponents:
        try:
            opponent_paths[opp] = _resolve_agent(opp)
        except FileNotFoundError:
            if not silent:
                print(f"  [SKIP] Opponent not found: {opp}")

    if not opponent_paths:
        return {"error": "No valid opponents", "win_rate": 0.0}

    # ─── 매치 실행 ────────────────────────────────────────────
    all_matches = []
    per_opponent = {}
    loss_causes = Counter()
    total_w, total_d, total_l = 0, 0, 0
    total_start = time.time()

    for opp_name, opp_path in opponent_paths.items():
        opp_w, opp_d, opp_l = 0, 0, 0
        opp_hp_diffs = []
        opp_matches = []

        for r in range(1, rounds + 1):
            result = _run_single(agent_path, opp_path, agent_name, opp_name, max_steps)
            result["opponent"] = opp_name
            result["round"] = r
            all_matches.append(result)
            opp_matches.append(result)

            if not result.get("success", False):
                continue

            w = result["winner"]
            if w == "tree1":
                opp_w += 1
                total_w += 1
            elif w == "tree2":
                opp_l += 1
                total_l += 1
            else:
                opp_d += 1
                total_d += 1

            hp_diff = result.get("tree1_health", 100) - result.get("tree2_health", 100)
            opp_hp_diffs.append(hp_diff)

            cause = result.get("loss_cause")
            if cause:
                loss_causes[cause] += 1

            if not silent:
                tag = "W" if w == "tree1" else ("D" if w == "draw" else "L")
                hp1 = result.get("tree1_health", 100)
                hp2 = result.get("tree2_health", 100)
                total_done = len(all_matches)
                total_all = len(opponent_paths) * rounds
                print(f"  [{total_done:3d}/{total_all}] vs {opp_name:12s} R{r:02d}: "
                      f"{tag}  HP {hp1:.0f}/{hp2:.0f}", flush=True)

        opp_total = opp_w + opp_d + opp_l
        opp_wr = opp_w / opp_total if opp_total > 0 else 0.0
        opp_ci = _wilson_ci(opp_w, opp_total)
        avg_hp_diff = sum(opp_hp_diffs) / len(opp_hp_diffs) if opp_hp_diffs else 0.0

        per_opponent[opp_name] = {
            "W": opp_w,
            "D": opp_d,
            "L": opp_l,
            "total": opp_total,
            "win_rate": round(opp_wr, 4),
            "ci_95": opp_ci,
            "avg_hp_diff": round(avg_hp_diff, 2),
        }

    # ─── 전체 집계 ────────────────────────────────────────────
    total_all = total_w + total_d + total_l
    overall_wr = total_w / total_all if total_all > 0 else 0.0
    overall_ci = _wilson_ci(total_w, total_all)
    elapsed = time.time() - total_start

    # 최악/최선 상대
    worst_opp = min(per_opponent.items(), key=lambda x: x[1]["win_rate"])[0] if per_opponent else None
    best_opp = max(per_opponent.items(), key=lambda x: x[1]["win_rate"])[0] if per_opponent else None

    report = {
        "agent": agent_name,
        "win_rate": round(overall_wr, 4),
        "ci_95": overall_ci,
        "totals": {"W": total_w, "D": total_d, "L": total_l, "total": total_all},
        "per_opponent": per_opponent,
        "loss_causes": dict(loss_causes),
        "worst_opponent": worst_opp,
        "best_opponent": best_opp,
        "rounds_per_opponent": rounds,
        "elapsed_seconds": round(elapsed, 1),
        "matches": all_matches,
    }

    return report


# ─── 리포트 출력 ──────────────────────────────────────────────

def print_report(report: dict):
    """평가 결과를 사람이 읽기 좋은 형태로 출력."""
    agent = report["agent"]
    wr = report["win_rate"]
    ci = report["ci_95"]
    t = report["totals"]
    elapsed = report.get("elapsed_seconds", 0)

    print(f"\n{'='*60}")
    print(f"  Evaluation Report: {agent}")
    print(f"{'='*60}")
    print(f"\n  Overall: {t['W']}W / {t['D']}D / {t['L']}L  "
          f"({t['total']} matches)")
    print(f"  Win Rate: {wr*100:.1f}%  "
          f"(95% CI: {ci[0]*100:.1f}% - {ci[1]*100:.1f}%)")
    print(f"  Elapsed: {elapsed:.1f}s")

    # 상대별
    print(f"\n  {'Opponent':12s}  {'W':>3s} {'D':>3s} {'L':>3s}  "
          f"{'WR':>6s}  {'95% CI':>15s}  {'HP Diff':>8s}")
    print(f"  {'-'*58}")

    for opp, data in sorted(report["per_opponent"].items(),
                             key=lambda x: x[1]["win_rate"], reverse=True):
        ci_str = f"{data['ci_95'][0]*100:.0f}%-{data['ci_95'][1]*100:.0f}%"
        print(f"  {opp:12s}  {data['W']:3d} {data['D']:3d} {data['L']:3d}  "
              f"{data['win_rate']*100:5.1f}%  {ci_str:>15s}  {data['avg_hp_diff']:>+7.1f}")

    # 패배 원인
    causes = report.get("loss_causes", {})
    if causes:
        print(f"\n  Loss Causes:")
        for cause, count in sorted(causes.items(), key=lambda x: -x[1]):
            print(f"    {cause:12s}: {count}")

    # 최악/최선
    print(f"\n  Best  vs: {report.get('best_opponent', '-')}")
    print(f"  Worst vs: {report.get('worst_opponent', '-')}")
    print(f"{'='*60}\n")


# ─── CLI ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="통합 에이전트 평가")
    parser.add_argument("agent", help="평가할 에이전트 이름")
    parser.add_argument("--rounds", type=int, default=10,
                        help="상대당 라운드 수 (기본 10, 권장 50)")
    parser.add_argument("--opponents", nargs="+", default=None,
                        help="상대 목록 (기본: 6종)")
    parser.add_argument("--all-opponents", action="store_true",
                        help="golden 포함 전체 상대 (7종)")
    parser.add_argument("--max-steps", type=int, default=1500,
                        help="매치당 최대 스텝 (기본 1500)")
    parser.add_argument("--save", type=str, default=None,
                        help="결과 JSON 저장 경로")
    parser.add_argument("--silent", action="store_true",
                        help="매치별 출력 비활성화")

    args = parser.parse_args()

    opponents = args.opponents
    if args.all_opponents:
        opponents = DEFAULT_OPPONENTS + ["golden"]

    report = evaluate(
        agent=args.agent,
        opponents=opponents,
        rounds=args.rounds,
        max_steps=args.max_steps,
        silent=args.silent,
    )

    print_report(report)

    if args.save:
        save_path = Path(args.save)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        # matches 상세는 크므로 별도 저장
        summary = {k: v for k, v in report.items() if k != "matches"}
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"  Saved: {save_path}")


if __name__ == "__main__":
    main()
