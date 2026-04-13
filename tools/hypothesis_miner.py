"""
hypothesis_miner.py — matches.jsonl 에서 가설 후보 자동 생성

본 도구는 EXPLORE 1-3 단계의 핵심: "데이터로부터 가설을 자동 추출" .
hypothesis_tracker.py 의 등록기 앞단에서 후보를 만든다.

Miners (현재 구현):
  Miner 2: Outcome-Discriminating Features  — WIN vs LOSS 평균 차이가 큰 metric
  Miner 5: Node Usage Imbalance              — 과소/과대 사용된 노드

향후 (TBD):
  Miner 1: Rigid-behavior (find_rigid_behavior.py 통합)
  Miner 3: Threshold Discovery               — metric의 임계값 자동 발견
  Miner 4: Failure Mode Clustering           — LOSS 매치 클러스터링
  Miner 6: Counter-factual Mining            — 가장 가까운 win/loss 비교

사용:
    python tools/hypothesis_miner.py mine \
        --matches logs/knowledge/matches.jsonl \
        --output logs/knowledge/hypothesis_queue.json \
        --agent-version v6.0-h1

    python tools/hypothesis_miner.py mine --top-k 5
"""

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
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
    p_mine.add_argument("--top-k", type=int, default=10)
    p_mine.add_argument("--effect-threshold", type=float, default=0.5)

    args = ap.parse_args()

    if args.cmd == "mine":
        MATCHES_DB = Path(args.matches)
        matches = load_matches(args.agent_version)
        print(f"\n  Loaded {len(matches)} matches"
              f"{' for ' + args.agent_version if args.agent_version else ''}")
        if not matches:
            print("  No matches to mine.")
            return

        m2 = miner_outcome_discriminator(matches, effect_threshold=args.effect_threshold)
        m5 = miner_node_usage(matches)

        print(f"\n  Miner 2 (Outcome Discriminator): {len(m2)} candidates")
        print(f"  Miner 5 (Node Usage):             {len(m5)} candidates")

        queue = synthesize([m2, m5], top_k=args.top_k)

        # 출력
        print(f"\n  ─── Top {len(queue)} hypothesis candidates ───")
        for c in queue:
            print(f"\n  [{c['candidate_id']}] {c['source_miner']} "
                  f"(prio={c['priority_score']:.2f})")
            print(f"    {c['statement']}")
            ev = c.get("evidence", {})
            if "metric" in ev:
                print(f"    metric={ev.get('metric')}  win={ev.get('win_mean')}  "
                      f"loss={ev.get('loss_mean')}  d={ev.get('effect_size')}")
            if "node" in ev:
                print(f"    node={ev.get('node')}  win%={ev.get('win_pct')}  "
                      f"loss%={ev.get('loss_pct')}")

        # 저장
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump({
                "ts": datetime.now().isoformat(),
                "agent_version": args.agent_version,
                "n_matches_analyzed": len(matches),
                "candidates": queue,
            }, f, ensure_ascii=False, indent=2)
        print(f"\n  Saved → {args.output}")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()