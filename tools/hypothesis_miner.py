"""
hypothesis_miner.py — 가설 후보 자동 생성 (통합 miner)

본 도구는 EXPLORE 1-3 단계의 핵심: "데이터로부터 가설을 자동 추출".
hypothesis_tracker.py 의 등록기 앞단에서 후보를 만든다.

Miners (구현됨):
  Miner 1: Rigid-behavior               — per-tick CSV에서 obs 변화 vs action 고정 탐지
  Miner 2: Outcome-Discriminating Features — matches.jsonl 기반 WIN vs LOSS metric 차이
  Miner 5: Node Usage Imbalance         — 과소/과대 사용된 노드
  Miner 8: Tactical Delta (BFM-grounded) — per-tick CSV에서 ego vs enm 상대 관측 비교

Miner 레벨:
  - tick-level (CSV 입력): Miner 1, Miner 8
  - match-level (jsonl 입력): Miner 2, Miner 5

사용:
    # match-level miner만 (matches.jsonl 기반)
    python tools/hypothesis_miner.py mine \
        --matches logs/knowledge/matches.jsonl \
        --top-k 5

    # tick-level miner 추가 (CSV 디렉토리 지정)
    python tools/hypothesis_miner.py mine \
        --matches logs/knowledge/matches.jsonl \
        --csv-dir logs/metadata/v6_baseline \
        --top-k 10
"""

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from itertools import product
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

KNOWLEDGE_DIR = PROJECT_ROOT / "logs" / "knowledge"
MATCHES_DB = KNOWLEDGE_DIR / "matches.jsonl"
QUEUE_DB = KNOWLEDGE_DIR / "hypothesis_queue.json"


# ─── 데이터 로드 ──────────────────────────────────────────────

def load_matches(agent_version=None):
    """Schema 1.0 matches.jsonl 로드 (선택적 버전 필터)."""
    if not MATCHES_DB.exists():
        return []
    out = []
    with open(MATCHES_DB, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if r.get("schema_version") != "1.0":
                    continue
                if agent_version and r.get("tags", {}).get("agent_version") != agent_version:
                    continue
                out.append(r)
            except Exception:
                pass
    return out


def _split_by_outcome(matches):
    wins = [m for m in matches if m["outcome"]["category"].startswith("WIN")]
    draws = [m for m in matches if m["outcome"]["category"].startswith("DRAW")]
    losses = [m for m in matches if m["outcome"]["category"].startswith("LOSS")]
    return wins, draws, losses


def _get(m, *path):
    v = m
    for p in path:
        if isinstance(v, dict) and p in v:
            v = v[p]
        else:
            return None
    return v


def _stats_safe(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {
        "n": len(vals),
        "mean": statistics.mean(vals),
        "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0,
        "min": min(vals),
        "max": max(vals),
    }


def _cohens_d(a, b):
    """Effect size: (mean_a - mean_b) / pooled_std."""
    if not a or not b:
        return 0.0
    if len(a) < 2 or len(b) < 2:
        return 0.0
    ma, mb = statistics.mean(a), statistics.mean(b)
    sa, sb = statistics.stdev(a), statistics.stdev(b)
    pooled = math.sqrt((sa * sa + sb * sb) / 2) if (sa or sb) else 0.0
    if pooled < 1e-9:
        return 0.0
    return (ma - mb) / pooled


# ─── Miner 2: Outcome-Discriminating Features ────────────────

METRIC_PATHS = [
    ("ata_avg",        ["metrics", "ata", "avg"]),
    ("ata_max",        ["metrics", "ata", "max"]),
    ("aa_avg",         ["metrics", "aa", "avg"]),
    ("distance_avg",   ["metrics", "distance", "avg"]),
    ("distance_min",   ["metrics", "distance", "min"]),
    ("closure_avg",    ["metrics", "closure", "avg"]),
    ("energy_diff_avg", ["metrics", "energy_diff", "avg"]),
    ("wez_pct",        ["metrics", "wez_pct"]),
    ("overshoot_pct",  ["metrics", "overshoot_pct"]),
    ("energy_adv_pct", ["metrics", "energy_adv_pct"]),
    ("alt_adv_pct",    ["metrics", "alt_adv_pct"]),
]


def miner_outcome_discriminator(matches, effect_threshold=0.5):
    """Miner 2: WIN vs (LOSS or DRAW) 평균 차이가 큰 metric을 가설로 제안.

    LOSS 수가 적을 때 (예: <3) DRAW를 fallback으로 사용.
    """
    wins, draws, losses = _split_by_outcome(matches)
    if len(wins) < 3:
        return [{
            "miner": "outcome_discriminator",
            "status": "insufficient_data",
            "reason": f"need ≥3 wins; got {len(wins)}",
        }]

    # 비교 대상 결정: LOSS 우선, 부족하면 DRAW도 추가
    if len(losses) >= 3:
        compare_to = losses
        compare_label = "LOSS"
    elif len(losses) + len(draws) >= 3:
        compare_to = losses + draws
        compare_label = "NON-WIN"
    else:
        return [{
            "miner": "outcome_discriminator",
            "status": "insufficient_data",
            "reason": f"need ≥3 non-wins; got {len(losses)} L + {len(draws)} D",
        }]

    candidates = []
    for metric_name, path in METRIC_PATHS:
        win_vals = [_get(m, *path) for m in wins]
        non_vals = [_get(m, *path) for m in compare_to]
        win_vals = [v for v in win_vals if v is not None]
        non_vals = [v for v in non_vals if v is not None]
        if not win_vals or not non_vals:
            continue

        d = _cohens_d(win_vals, non_vals)
        if abs(d) < effect_threshold:
            continue

        direction = "higher" if d > 0 else "lower"
        candidates.append({
            "miner": "outcome_discriminator",
            "comparison": f"WIN_vs_{compare_label}",
            "metric": metric_name,
            "win_mean": round(statistics.mean(win_vals), 2),
            "compare_mean": round(statistics.mean(non_vals), 2),
            "delta": round(statistics.mean(win_vals) - statistics.mean(non_vals), 2),
            "effect_size": round(d, 3),
            "n_wins": len(win_vals),
            "n_compare": len(non_vals),
            "statement": (
                f"WIN vs {compare_label}에서 {metric_name}이 {direction} "
                f"({statistics.mean(win_vals):.1f} vs {statistics.mean(non_vals):.1f}, d={d:.2f}). "
                f"BT가 {metric_name}을 {direction} 방향으로 유도하면 결과 개선 기대."
            ),
            "suggested_change_type": "node_param" if "ata" in metric_name or "closure" in metric_name else "threshold",
            "priority": abs(d),
        })

    candidates.sort(key=lambda c: -c["priority"])
    return candidates


# ─── Miner 5: Node Usage Imbalance ───────────────────────────

def miner_node_usage(matches, fire_threshold_low=0.01, fire_threshold_high=0.40):
    """Miner 5: 과소/과대 발동 노드 탐지."""
    wins, _, losses = _split_by_outcome(matches)
    if not matches:
        return []

    # 매 매치의 노드 발동 비율 (top_nodes는 count)
    node_pct_wins = defaultdict(list)   # node → list of pct
    node_pct_losses = defaultdict(list)

    def _update(target_dict, subset):
        for m in subset:
            n_ticks = m["outcome"]["n_ticks"]
            top = m.get("top_nodes", {})
            for node, cnt in top.items():
                target_dict[node].append(cnt / max(n_ticks, 1))

    _update(node_pct_wins, wins)
    _update(node_pct_losses, losses)

    candidates = []
    all_nodes = set(node_pct_wins) | set(node_pct_losses)

    for node in all_nodes:
        w_pcts = node_pct_wins.get(node, [])
        l_pcts = node_pct_losses.get(node, [])
        w_avg = statistics.mean(w_pcts) if w_pcts else 0.0
        l_avg = statistics.mean(l_pcts) if l_pcts else 0.0

        # 과대 사용 + 패배에서 더 많이 발동
        if l_avg > fire_threshold_high and l_avg > w_avg + 0.05:
            candidates.append({
                "miner": "node_usage",
                "kind": "overused_in_losses",
                "node": node,
                "win_pct": round(w_avg * 100, 1),
                "loss_pct": round(l_avg * 100, 1),
                "delta_pp": round((l_avg - w_avg) * 100, 1),
                "statement": (
                    f"{node}이 패배 매치에서 {l_avg*100:.0f}% 발동 "
                    f"(승리는 {w_avg*100:.0f}%). "
                    f"발동 조건을 좁히거나 다른 노드로 교체 필요."
                ),
                "suggested_change_type": "branch_condition_tighten",
                "priority": (l_avg - w_avg) * 2,
            })

        # 과소 사용 (어디서도 거의 안 발동)
        max_pct = max(w_avg, l_avg)
        if 0 < max_pct < fire_threshold_low:
            candidates.append({
                "miner": "node_usage",
                "kind": "underused",
                "node": node,
                "max_pct": round(max_pct * 100, 2),
                "statement": (
                    f"{node}이 거의 발동 안 됨 ({max_pct*100:.1f}%). "
                    f"발동 조건 임계값 relax 또는 BT 분기 순서 재고."
                ),
                "suggested_change_type": "branch_condition_relax",
                "priority": 0.3,
            })

    candidates.sort(key=lambda c: -c["priority"])
    return candidates


# ─── Tick-level CSV 로더 ──────────────────────────────────────

def _load_csv_match(csv_path: Path):
    """collect_phase1 CSV → 매 tick (ego, enm) dict. result.json도 병합."""
    import csv as _csv
    result_path = csv_path.with_name(csv_path.stem + "_result.json")
    result = {}
    if result_path.exists():
        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)

    rows_ego = []
    rows_enm = []
    ego_id = None
    with open(csv_path, encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        for row in reader:
            if ego_id is None:
                ego_id = row["agent_id"]
            try:
                row_cast = {
                    "step": int(row["step"]),
                    "bfm": row.get("bfm_situation", ""),
                    "dist": float(row.get("distance_ft", 0)),
                    "ata": float(row.get("ata_deg", 0)),
                    "aa": float(row.get("aa_deg", 0)),
                    "hca": float(row.get("hca_deg", 0)),
                    "alt": float(row.get("ego_altitude_ft", 0)),
                    "cas": float(row.get("ego_vc_kts", 0)),
                    "es": float(row.get("specific_energy_ft", 0)),
                    "ps": float(row.get("ps_fts", 0)),
                    "e_diff": float(row.get("energy_diff_ft", 0)),
                    "closure": float(row.get("closure_rate_kts", 0)),
                    "turn_rate": float(row.get("turn_rate_degs", 0)),
                    "in_wez": row.get("in_wez", "").lower() in ("true", "1"),
                    "enm_in_wez": row.get("enm_in_wez", "").lower() in ("true", "1"),
                    "energy_advantage": row.get("energy_advantage", "").lower() in ("true", "1"),
                    "alt_advantage": row.get("alt_advantage", "").lower() in ("true", "1"),
                    "hp": float(row.get("ego_health", 100)),
                    "node": (row.get("active_node", "") or "").strip('"'),
                }
            except Exception:
                continue
            if row["agent_id"] == ego_id:
                rows_ego.append(row_cast)
            else:
                rows_enm.append(row_cast)

    outcome_winner = result.get("winner", "unknown")
    tree1_hp = result.get("tree1_hp", result.get("tree1_health", 100))
    tree2_hp = result.get("tree2_hp", result.get("tree2_health", 100))
    hp_diff = tree1_hp - tree2_hp
    if abs(hp_diff) < 0.5 and tree1_hp > 99:
        outcome = "DRAW_NO_ENGAGEMENT"
    elif hp_diff > 10:
        outcome = "WIN_DOMINANT"
    elif hp_diff > 2:
        outcome = "WIN_MARGINAL"
    elif hp_diff > -2:
        outcome = "DRAW_ENGAGED"
    elif hp_diff > -10:
        outcome = "LOSS_MARGINAL"
    else:
        outcome = "LOSS_DOMINANT"

    return {
        "path": str(csv_path),
        "winner": outcome_winner,
        "hp_diff": hp_diff,
        "outcome": outcome,
        "rows_ego": rows_ego,
        "rows_enm": rows_enm,
        "n": min(len(rows_ego), len(rows_enm)),
    }


# ─── Miner 1: Rigid-behavior (CSV-based, find_rigid_behavior 통합) ────

def miner_rigid_behavior(match, window=20):
    """Miner 1: per-tick 관측 변화 vs action 고정 탐지.

    5개 패턴:
      - DIST_WIDENING_RIGID:  거리 급증 + 같은 action 지속
      - ATA_GROWING_RIGID:    ATA 단조증가 + same action
      - WEZ_OVERSHOOT_RISK:   WEZ 직전 + closure 과다 + 감속 없음
      - YOYO_WIDENING:        Yo-Yo 중 거리 벌어짐 (반경 과대)
      - SAME_ACTION_STREAK:   50 tick 연속 같은 action + closure 음수
    """
    rows = match["rows_ego"]
    n = match["n"]
    if n < window * 2:
        return []
    findings = []

    # 1. Distance widening rigid
    i = window
    while i < n - window:
        past, now = rows[i - window], rows[i]
        d = now["dist"] - past["dist"]
        if d > 500 and past["node"] == now["node"] and now["node"]:
            findings.append({
                "miner": "rigid_behavior",
                "pattern": "DIST_WIDENING_RIGID",
                "match_path": match["path"],
                "tick": i,
                "node": now["node"],
                "dist_change": round(d),
                "ata": round(now["ata"], 1),
                "closure": round(now["closure"], 1),
                "outcome": match["outcome"],
                "statement": (
                    f"{now['node']}이 4초간 {int(d)}ft 벌어짐 + action 불변 "
                    f"(ATA {now['ata']:.0f}°, closure {now['closure']:+.0f}). "
                    f"타이트 턴 또는 가속으로 전환 필요."
                ),
                "suggested_change_type": "branch_condition_add",
                "priority": 0.4 + (0.2 if match["outcome"].startswith("LOSS") else 0),
            })
            i += window
        i += 1

    # 2. ATA monotone growing
    i = window
    while i < n - window:
        atas = [rows[j]["ata"] for j in range(i - window, i + 1)]
        if atas[-1] - atas[0] > 10 and all(atas[j] >= atas[j-1] - 1 for j in range(1, len(atas))):
            now = rows[i]
            findings.append({
                "miner": "rigid_behavior",
                "pattern": "ATA_GROWING_RIGID",
                "match_path": match["path"],
                "tick": i,
                "node": now["node"],
                "ata_start": round(atas[0], 1),
                "ata_end": round(atas[-1], 1),
                "outcome": match["outcome"],
                "statement": (
                    f"{now['node']} 실행 중 ATA {atas[0]:.0f}°→{atas[-1]:.0f}° 단조 증가 "
                    f"(포인팅 실패). 타이트 턴으로 각도 회수 필요."
                ),
                "suggested_change_type": "node_param",
                "priority": 0.5 + (0.2 if match["outcome"].startswith("LOSS") else 0),
            })
            i += window
        i += 1

    # 3. WEZ overshoot risk
    for i in range(1, n):
        now = rows[i]
        if 152 < now["dist"] < 1200 and abs(now["ata"]) < 20 and now["closure"] > 250:
            prev = rows[i - 1]
            if abs(now["closure"] - prev["closure"]) < 10:
                findings.append({
                    "miner": "rigid_behavior",
                    "pattern": "WEZ_OVERSHOOT_RISK",
                    "match_path": match["path"],
                    "tick": i,
                    "node": now["node"],
                    "dist": round(now["dist"]),
                    "ata": round(now["ata"], 1),
                    "closure": round(now["closure"], 1),
                    "outcome": match["outcome"],
                    "statement": (
                        f"WEZ 임박 (dist {now['dist']:.0f}, ATA {now['ata']:.0f}°) + "
                        f"closure {now['closure']:+.0f} 과다 + 감속 없음. "
                        f"Lag pursuit 또는 brake 필요."
                    ),
                    "suggested_change_type": "branch_condition_add",
                    "priority": 0.6 + (0.2 if match["outcome"].startswith("LOSS") else 0),
                })

    # 4. Yo-Yo widening
    i = window
    while i < n - window:
        now = rows[i]
        if now["node"] and "YoYo" in now["node"]:
            past = rows[i - window]
            if now["dist"] - past["dist"] > 800:
                findings.append({
                    "miner": "rigid_behavior",
                    "pattern": "YOYO_WIDENING",
                    "match_path": match["path"],
                    "tick": i,
                    "node": now["node"],
                    "dist_gain": round(now["dist"] - past["dist"]),
                    "outcome": match["outcome"],
                    "statement": (
                        f"{now['node']} 중 {int(now['dist']-past['dist'])}ft 벌어짐. "
                        f"반경 과대 → 즉시 DIVE 또는 lead 전환."
                    ),
                    "suggested_change_type": "node_logic",
                    "priority": 0.5,
                })
                i += window
        i += 1

    # 5. Same-action long streak + negative closure
    i = 0
    streak_node = None
    streak_start = 0
    while i < n:
        node = rows[i]["node"]
        if node == streak_node:
            length = i - streak_start
            if length == 50:
                mid = rows[(streak_start + i) // 2]
                if mid["closure"] < 0:
                    findings.append({
                        "miner": "rigid_behavior",
                        "pattern": "SAME_ACTION_STREAK",
                        "match_path": match["path"],
                        "tick": i,
                        "node": node,
                        "streak_len": length,
                        "avg_closure": round(mid["closure"], 1),
                        "outcome": match["outcome"],
                        "statement": (
                            f"{node} 50 tick(10초) 연속 + closure {mid['closure']:+.0f} 음수. "
                            f"전략 전환 필요."
                        ),
                        "suggested_change_type": "timeout_switch",
                        "priority": 0.45,
                    })
        else:
            streak_node = node
            streak_start = i
        i += 1

    return findings


# ─── Miner 8: Tactical Delta (BFM-grounded ego vs enm) ─────────

def miner_tactical_delta(matches_ticks, sample_tick_ratio=0.2):
    """Miner 8: per-tick ego vs enm 관측 차이를 outcome별로 비교.

    공중전 원리 기반:
      (1) 3D 위치 선점 → (2) WEZ 선진입 → (3) WEZ 유지

    각 group(WIN/DRAW/LOSS)에 대해:
      - delta_turn_rate (ego - enm): 선회율 우위
      - delta_ps: 에너지 획득률 우위
      - delta_cas: 속도 우위
      - delta_alt: 고도 우위
      - delta_energy: specific energy 우위
      - wez_first_tick: 누가 먼저 WEZ
      - wez_duration_ego, wez_duration_enm

    WIN과 LOSS에서 각 delta의 평균 비교 → 유의미한 차이 = 가설 후보.

    Args:
        matches_ticks: list of loaded match dicts (from _load_csv_match)
    """
    # Aggregate features per match
    groups = defaultdict(list)  # outcome → list of feature dicts
    for m in matches_ticks:
        if m["n"] < 50:
            continue
        rows_e = m["rows_ego"]
        rows_n = m["rows_enm"]
        N = min(len(rows_e), len(rows_n))

        # 매 tick delta 계산
        dtr, dps, dcas, dalt, de = [], [], [], [], []
        ego_wez = enm_wez = 0
        ego_first_wez = None
        enm_first_wez = None
        for i in range(N):
            e, nn = rows_e[i], rows_n[i]
            dtr.append(e["turn_rate"] - nn["turn_rate"])
            dps.append(e["ps"] - nn["ps"])
            dcas.append(e["cas"] - nn["cas"])
            dalt.append(e["alt"] - nn["alt"])
            de.append(e["es"] - nn["es"])
            if e["in_wez"]:
                ego_wez += 1
                if ego_first_wez is None:
                    ego_first_wez = i
            if e["enm_in_wez"]:
                enm_wez += 1
                if enm_first_wez is None:
                    enm_first_wez = i

        feat = {
            "outcome": m["outcome"],
            "hp_diff": m["hp_diff"],
            "delta_turn_rate_avg": statistics.mean(dtr) if dtr else 0,
            "delta_ps_avg": statistics.mean(dps) if dps else 0,
            "delta_cas_avg": statistics.mean(dcas) if dcas else 0,
            "delta_alt_avg": statistics.mean(dalt) if dalt else 0,
            "delta_energy_avg": statistics.mean(de) if de else 0,
            "ego_wez_pct": 100 * ego_wez / N,
            "enm_wez_pct": 100 * enm_wez / N,
            "ego_first_wez": ego_first_wez if ego_first_wez is not None else N,
            "enm_first_wez": enm_first_wez if enm_first_wez is not None else N,
        }
        groups[m["outcome"][:3]].append(feat)  # WIN/DRA/LOS

    if "WIN" not in groups or ("LOS" not in groups and "DRA" not in groups):
        return []

    wins = groups.get("WIN", [])
    losses = groups.get("LOS", [])
    draws = groups.get("DRA", [])

    # Compare WIN vs (LOSS + DRAW) if not enough losses
    compare_to = losses if len(losses) >= 3 else (losses + draws)
    compare_label = "LOSS" if len(losses) >= 3 else "NON-WIN"

    if len(wins) < 3 or len(compare_to) < 3:
        return []

    candidates = []
    feature_keys = [
        ("delta_turn_rate_avg", "선회율 차"),
        ("delta_ps_avg",        "Ps (에너지 변화율) 차"),
        ("delta_cas_avg",       "속도 차"),
        ("delta_alt_avg",       "고도 차"),
        ("delta_energy_avg",    "specific energy 차"),
        ("ego_wez_pct",         "우리 WEZ 유지율"),
        ("enm_wez_pct",         "적 WEZ 유지율"),
    ]
    for key, label in feature_keys:
        w_vals = [f[key] for f in wins]
        l_vals = [f[key] for f in compare_to]
        d = _cohens_d(w_vals, l_vals)
        if abs(d) < 0.4:
            continue
        wm = statistics.mean(w_vals)
        lm = statistics.mean(l_vals)
        direction = "높음" if d > 0 else "낮음"

        # BFM 물리 기반 해석 + 가설
        if key == "delta_turn_rate_avg":
            interp = ("선회율 우위가 WIN의 핵심 — 패배에서는 적보다 느리게 선회. "
                      "더 tight turn (max G) 필요.")
            change = "Smart* 노드의 base_turn/intensity를 증가 (예: SmartLeadPursuit.ata_turn_gain 상향)"
        elif key == "delta_ps_avg":
            interp = ("에너지 획득률 우위. 패배에서는 throttle 부족 또는 dive 부족."
                      " SmartLowYoYo/Accelerate 우선순위 상향 필요.")
            change = "IsLowEnergy 조건 relax + SmartLowYoYo 호출 조기화"
        elif key == "delta_cas_avg":
            interp = ("속도 우위 차이. WIN은 코너속도 유지, LOSS는 느려짐."
                      " vel_idx가 상황에 따라 올바르게 선택되는지 점검.")
            change = "SmartXXX 노드의 vel 파라미터 동적화"
        elif key == "delta_alt_avg":
            if d > 0:
                interp = "고도 우위 차이. WIN은 고도 유지. DIVE 타이밍 재조정 필요."
            else:
                interp = "고도 열위. LOSS는 너무 높게 떠서 WEZ 못 잡음. 적극 dive."
            change = "SmartHighYoYo dive 임계값 조정 또는 SmartLowYoYo 조기 호출"
        elif key == "delta_energy_avg":
            interp = "총 에너지 차이. E-M 도표에서 우위 영역 유지 여부."
            change = "IsHighEnergy/IsLowEnergy 임계값 튜닝"
        elif key == "ego_wez_pct":
            interp = ("우리 WEZ 유지율 차. WIN은 오래 머뭄. LOSS는 금방 벗어남."
                      " SmartGunAttack PD 게인 강화로 tracking 안정화.")
            change = "SmartGunAttack kp/kd 튜닝 또는 IsWEZOpportunity 임계 relax"
        elif key == "enm_in_wez":
            interp = "적 WEZ 시간 차. LOSS는 적에게 오래 노출. IsUnderFire → BreakTurn 우선순위 상향."
            change = "IsUnderFire 분기 우선순위 상향, SmartBreakTurn max-G"
        else:
            interp = ""
            change = ""

        candidates.append({
            "miner": "tactical_delta",
            "feature": key,
            "label": label,
            "win_mean": round(wm, 3),
            "compare_mean": round(lm, 3),
            "compare_label": compare_label,
            "effect_size": round(d, 3),
            "n_wins": len(wins),
            "n_compare": len(compare_to),
            "statement": (
                f"[BFM] WIN은 {label}이 {compare_label}보다 {direction} "
                f"({wm:.2f} vs {lm:.2f}, d={d:.2f}). {interp}"
            ),
            "suggested_change": change,
            "suggested_change_type": "node_param",
            "priority": abs(d) + 0.2,  # tactical delta는 priority boost
        })

    candidates.sort(key=lambda c: -c["priority"])
    return candidates


# ─── Miner 9: Coverage Gap Detector ──────────────────────────

# 관측 공간 bin 정의 (BFM 기하학 기반)
OBS_BINS = {
    "ata": [0, 30, 60, 90, 120, 150, 180],      # 6 bins
    "dist": [0, 1000, 3000, 6000, 10000, 20000],  # 5 bins
    "closure": [-400, -100, 0, 100, 400],          # 4 bins
    "energy_diff": [-10000, -3000, 0, 3000, 10000], # 4 bins
}


def _bin_index(val, edges):
    """값을 bin index로 변환."""
    for i in range(len(edges) - 1):
        if val < edges[i + 1]:
            return i
    return len(edges) - 2


def _bin_label(idx, key):
    """bin index를 사람 읽기 좋은 label로."""
    edges = OBS_BINS[key]
    if idx < 0 or idx >= len(edges) - 1:
        return f"{key}=?"
    return f"{key}=[{edges[idx]},{edges[idx+1]})"


def miner_coverage_gap(matches_ticks, min_samples=50, samples_per_match=1):
    """Miner 9: 관측 공간의 빈 영역(gap) 자동 발견.

    관측 공간을 (ATA × dist × closure × energy_diff) 4차원으로 bin화.
    각 bin의 매치 수를 카운트, min_samples 미만인 bin = gap.
    gap은 "이 상황에서 우리 BT가 어떻게 행동하는지 모름" → 상대 생성 대상.

    Args:
        matches_ticks: 매치 tick 데이터
        min_samples: bin당 최소 샘플 수 (미달 시 gap)
        samples_per_match: 매치당 샘플 tick 수
            1  = midpoint만 (기본, 하위호환)
            N>1 = N개 균등 분포 tick (trajectory 커버리지 측정)
            매치가 방문한 고유 bin 수만큼 카운트 (outcome은 bin당 1회만 기록)

    Returns:
        list of gap dicts:
        {
            "miner": "coverage_gap",
            "bin": {"ata": [90,120], "dist": [3000,6000], ...},
            "n_samples": 3,
            "outcome_mix": {"WIN": 0.5, "LOSS": 0.5},
            "statement": "ATA 90-120° + dist 3000-6000ft 영역에서 데이터 부족 (3 samples)",
            "priority": 0.9,
            "suggested_opponent": {
                "ata_range": [90, 120],
                "dist_range": [3000, 6000],
                "description": "이 관측 영역을 강제하는 상대 BT 필요"
            }
        }
    """
    # 4D bin 카운트
    bin_counts = defaultdict(lambda: {"total": 0, "W": 0, "D": 0, "L": 0, "samples": []})

    for m in matches_ticks:
        if m["n"] < 20:
            continue
        rows = m["rows_ego"]
        outcome = m["outcome"][:3]  # WIN/DRA/LOS
        n_rows = len(rows)

        if samples_per_match <= 1:
            indices = [n_rows // 2]
        else:
            indices = sorted({
                min(int(n_rows * i / (samples_per_match - 1)), n_rows - 1)
                for i in range(samples_per_match)
            })

        match_bins = set()
        for idx in indices:
            tick = rows[idx]
            ata_val = tick["ata"] * 180 if tick["ata"] < 2 else tick["ata"]
            ata_bin = _bin_index(ata_val, OBS_BINS["ata"])
            dist_bin = _bin_index(tick["dist"], OBS_BINS["dist"])
            closure_bin = _bin_index(tick["closure"], OBS_BINS["closure"])
            e_bin = _bin_index(tick.get("e_diff", 0), OBS_BINS["energy_diff"])
            match_bins.add((ata_bin, dist_bin, closure_bin, e_bin))

        for key in match_bins:
            entry = bin_counts[key]
            entry["total"] += 1
            if outcome == "WIN":
                entry["W"] += 1
            elif outcome == "DRA":
                entry["D"] += 1
            else:
                entry["L"] += 1

    # 모든 가능한 bin 조합
    all_bins = list(product(
        range(len(OBS_BINS["ata"]) - 1),
        range(len(OBS_BINS["dist"]) - 1),
        range(len(OBS_BINS["closure"]) - 1),
        range(len(OBS_BINS["energy_diff"]) - 1),
    ))

    gaps = []
    for key in all_bins:
        entry = bin_counts.get(key, {"total": 0, "W": 0, "D": 0, "L": 0})
        if entry["total"] >= min_samples:
            continue

        ata_bin, dist_bin, closure_bin, e_bin = key
        ata_range = OBS_BINS["ata"][ata_bin:ata_bin + 2]
        dist_range = OBS_BINS["dist"][dist_bin:dist_bin + 2]
        closure_range = OBS_BINS["closure"][closure_bin:closure_bin + 2]
        e_range = OBS_BINS["energy_diff"][e_bin:e_bin + 2]

        labels = [
            _bin_label(ata_bin, "ata"),
            _bin_label(dist_bin, "dist"),
            _bin_label(closure_bin, "closure"),
            _bin_label(e_bin, "energy_diff"),
        ]
        label_str = " + ".join(labels)
        n = entry["total"]

        # 우선순위: 0 samples > 적은 samples > 패배 비율 높은 bins
        if n == 0:
            priority = 1.0
        else:
            loss_rate = entry["L"] / n if n else 0
            priority = 0.7 + 0.3 * loss_rate

        gaps.append({
            "miner": "coverage_gap",
            "bin_key": list(key),
            "bin_ranges": {
                "ata": ata_range,
                "dist": dist_range,
                "closure": closure_range,
                "energy_diff": e_range,
            },
            "n_samples": n,
            "outcome_mix": {"W": entry["W"], "D": entry["D"], "L": entry["L"]},
            "statement": (
                f"관측 영역 [{label_str}]에서 데이터 부족 ({n}/{min_samples}). "
                f"이 상황에서의 BT 성능 미검증 → 상대 생성 필요."
            ),
            "suggested_change_type": "opponent_generation",
            "priority": priority,
        })

    gaps.sort(key=lambda g: (-g["priority"], g["n_samples"]))
    return gaps


# ─── Synthesizer ──────────────────────────────────────────────

def synthesize(all_candidates, top_k=10):
    """후보 가설을 우선순위 순으로 정렬, top-k 선택, hypothesis_tracker 호환 형식."""
    flat = []
    for cands in all_candidates:
        if isinstance(cands, list):
            flat.extend(cands)
        elif isinstance(cands, dict):
            flat.append(cands)

    # 의미 있는 후보만
    flat = [c for c in flat if c.get("priority")]
    flat.sort(key=lambda c: -c["priority"])
    top = flat[:top_k]

    queue = []
    for i, cand in enumerate(top, 1):
        queue.append({
            "candidate_id": f"M{i}",
            "ts": datetime.now().isoformat(),
            "source_miner": cand.get("miner"),
            "statement": cand.get("statement"),
            "evidence": {k: v for k, v in cand.items()
                         if k not in ("statement", "miner", "priority")},
            "suggested_change_type": cand.get("suggested_change_type"),
            "priority_score": cand.get("priority"),
            "status": "candidate",
        })
    return queue


# ─── CLI ──────────────────────────────────────────────────────

def main():
    global MATCHES_DB
    ap = argparse.ArgumentParser(description="Hypothesis Miner")
    sub = ap.add_subparsers(dest="cmd")

    p_mine = sub.add_parser("mine", help="모든 miner 실행 + queue 출력")
    p_mine.add_argument("--matches", default=str(MATCHES_DB))
    p_mine.add_argument("--output", default=str(QUEUE_DB))
    p_mine.add_argument("--agent-version", default=None)
    p_mine.add_argument("--csv-dir", default=None,
                        help="CSV 디렉토리 (Miner 1/8 tick-level 분석용)")
    p_mine.add_argument("--top-k", type=int, default=10)
    p_mine.add_argument("--effect-threshold", type=float, default=0.5)

    args = ap.parse_args()

    if args.cmd == "mine":
        MATCHES_DB = Path(args.matches)
        matches = load_matches(args.agent_version)
        print(f"\n  Loaded {len(matches)} aggregated matches"
              f"{' for ' + args.agent_version if args.agent_version else ''}")

        all_candidates = []
        if matches:
            m2 = miner_outcome_discriminator(matches, effect_threshold=args.effect_threshold)
            m5 = miner_node_usage(matches)
            all_candidates.extend(m2)
            all_candidates.extend(m5)
            print(f"  Miner 2 (Outcome Discriminator): {sum(1 for c in m2 if c.get('miner'))} candidates")
            print(f"  Miner 5 (Node Usage):             {sum(1 for c in m5 if c.get('miner'))} candidates")

        # Tick-level (Miner 1, 8)
        if args.csv_dir:
            csv_dir = Path(args.csv_dir)
            csv_files = sorted(csv_dir.glob("*_meta.csv"))
            print(f"\n  Loading {len(csv_files)} CSVs from {csv_dir}...")
            tick_matches = []
            for p in csv_files:
                try:
                    tick_matches.append(_load_csv_match(p))
                except Exception as e:
                    print(f"    ! {p.name}: {e}")

            # Miner 1: rigid behavior per match
            m1_all = []
            for tm in tick_matches:
                m1_all.extend(miner_rigid_behavior(tm))
            print(f"  Miner 1 (Rigid Behavior):         {len(m1_all)} findings from {len(tick_matches)} matches")

            # Miner 8: tactical delta aggregation
            m8 = miner_tactical_delta(tick_matches)
            print(f"  Miner 8 (Tactical Delta):         {len(m8)} candidates")

            # Miner 9: coverage gap detection
            m9 = miner_coverage_gap(tick_matches, min_samples=10)
            n_zero = sum(1 for g in m9 if g["n_samples"] == 0)
            n_low = sum(1 for g in m9 if 0 < g["n_samples"] < 10)
            print(f"  Miner 9 (Coverage Gap):           {len(m9)} gaps "
                  f"({n_zero} empty, {n_low} low-coverage)")

            all_candidates.extend(m1_all)
            all_candidates.extend(m8)
            all_candidates.extend(m9[:20])  # top-20 gaps only (너무 많을 수 있으므로)

        if not all_candidates:
            print("\n  No candidates generated.")
            return

        queue = synthesize([all_candidates], top_k=args.top_k)

        # 출력
        print(f"\n  ─── Top {len(queue)} hypothesis candidates ───")
        for c in queue:
            print(f"\n  [{c['candidate_id']}] {c['source_miner']} "
                  f"(prio={c['priority_score']:.2f})")
            print(f"    {c['statement']}")
            ev = c.get("evidence", {})
            if "suggested_change" in ev:
                print(f"    → 제안: {ev['suggested_change']}")

        # 저장
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump({
                "ts": datetime.now().isoformat(),
                "agent_version": args.agent_version,
                "n_matches_analyzed": len(matches),
                "n_total_candidates": len(all_candidates),
                "candidates": queue,
            }, f, ensure_ascii=False, indent=2)
        print(f"\n  Saved → {args.output}")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()