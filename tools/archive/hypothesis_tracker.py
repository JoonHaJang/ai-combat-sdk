"""
hypothesis_tracker.py — 가설 검증 누적 시스템

목적: BT 변경의 효과를 통계적으로 추적.
     각 가설은 "변경 → 매치 결과 → 확정/반박" 사이클로 기록.

스키마: logs/knowledge/hypotheses.jsonl
{
  "id": "H1",
  "ts": "2026-04-13T14:00:00",
  "statement": "IsLostPursuit에 dist>2000 조건 추가하면 alpha2 회귀 복구",
  "baseline": "v51_rigid_v1",   # 비교 대상 버전
  "change": "IsLostPursuit dist_min_ft=2000",
  "results": [
      {"opp": "eagle1", "wins": 2, "losses": 0, "hp_diff_avg": 1.5},
      ...
  ],
  "wr": 0.75,
  "baseline_wr": 0.75,
  "delta_pp": 0.0,
  "verdict": "INCONCLUSIVE",
  "notes": "..."
}

또한 매 가설마다 "유리/불리/교착" 상황 패턴을 자동 추출:

logs/knowledge/situations.jsonl
{
  "category": "ADVANTAGE" | "DISADVANTAGE" | "STALEMATE",
  "condition": "ATA<70 AND closure>50 AND dist<5000",
  "freq": 120,
  "outcome_mix": {"WIN": 0.85, "DRAW": 0.1, "LOSS": 0.05},
  "source": "hypothesis:H1"
}
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.match_knowledge import load_matches, add_all as kb_add_all

HYPO_DB = PROJECT_ROOT / "logs" / "knowledge" / "hypotheses.jsonl"
SIT_DB = PROJECT_ROOT / "logs" / "knowledge" / "situations.jsonl"


def register_hypothesis(hid, statement, baseline, change, results, notes="",
                         baseline_wr=None):
    """가설 테스트 결과를 기록."""
    HYPO_DB.parent.mkdir(parents=True, exist_ok=True)
    total_w = sum(r["wins"] for r in results)
    total_d = sum(r.get("draws", 0) for r in results)
    total_l = sum(r["losses"] for r in results)
    total = total_w + total_d + total_l
    wr = total_w / total if total else 0

    # Verdict logic
    if baseline_wr is None:
        verdict = "UNKNOWN_BASELINE"
        delta = None
    else:
        delta = wr - baseline_wr
        if abs(delta) < 0.05:
            verdict = "INCONCLUSIVE"
        elif delta > 0:
            verdict = "CONFIRMED"
        else:
            verdict = "REFUTED"

    rec = {
        "id": hid,
        "ts": datetime.now().isoformat(),
        "statement": statement,
        "baseline": baseline,
        "change": change,
        "results": results,
        "totals": {"W": total_w, "D": total_d, "L": total_l, "total": total},
        "wr": round(wr, 3),
        "baseline_wr": baseline_wr,
        "delta_pp": round(delta, 3) if delta is not None else None,
        "verdict": verdict,
        "notes": notes,
    }
    with open(HYPO_DB, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def register_situation(category, condition, freq, outcome_mix, source=""):
    """상황 패턴을 저장."""
    SIT_DB.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.now().isoformat(),
        "category": category,   # ADVANTAGE / DISADVANTAGE / STALEMATE
        "condition": condition,
        "freq": freq,
        "outcome_mix": outcome_mix,
        "source": source,
    }
    with open(SIT_DB, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def list_hypotheses():
    if not HYPO_DB.exists():
        print("  No hypotheses recorded yet.")
        return
    print(f"\n{'='*80}")
    print(f"  Hypothesis Log")
    print('='*80)
    with open(HYPO_DB, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            h = json.loads(line)
            verdict = h["verdict"]
            icon = {"CONFIRMED": "✓", "REFUTED": "✗", "INCONCLUSIVE": "~",
                    "UNKNOWN_BASELINE": "?"}.get(verdict, "?")
            print(f"\n  [{h['id']}] {icon} {verdict}")
            print(f"    Statement: {h['statement']}")
            print(f"    Change   : {h['change']}")
            print(f"    Totals   : {h['totals']['W']}W / {h['totals']['D']}D / "
                  f"{h['totals']['L']}L  WR={h['wr']*100:.1f}%")
            if h["delta_pp"] is not None:
                print(f"    Δ vs base: {h['delta_pp']*100:+.1f}pp "
                      f"(baseline {h['baseline_wr']*100:.1f}%)")
            if h["notes"]:
                print(f"    Notes    : {h['notes']}")


def list_situations():
    if not SIT_DB.exists():
        print("  No situations recorded yet.")
        return
    print(f"\n{'='*80}")
    print(f"  Situation Patterns")
    print('='*80)
    categories = {}
    with open(SIT_DB, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            s = json.loads(line)
            categories.setdefault(s["category"], []).append(s)
    for cat, items in categories.items():
        print(f"\n  [{cat}]  {len(items)}건")
        for s in items[:5]:
            mix = s["outcome_mix"]
            mix_str = "  ".join(f"{k}={v:.0%}" for k, v in mix.items())
            print(f"    {s['condition']:50s}  freq={s['freq']:4d}  {mix_str}")


def eval_and_log_hypothesis(hid, statement, change_desc, notes="",
                             agent_yaml="examples/adaptive_eagle/adaptive_eagle.yaml",
                             opponents=None, rounds=2, baseline_wr=None,
                             replay_dir=None):
    """매치 실행 후 가설로 자동 기록."""
    from tools.evaluate import evaluate
    opponents = opponents or ["eagle1", "eagle2", "ace", "viper1", "golden", "alpha2"]
    report = evaluate(agent_yaml, opponents=opponents, rounds=rounds, silent=True,
                       replay_dir=replay_dir)

    results = []
    for opp, d in report["per_opponent"].items():
        results.append({
            "opp": opp,
            "wins": d["W"], "draws": d["D"], "losses": d["L"],
            "hp_diff_avg": d["avg_hp_diff"],
        })

    return register_hypothesis(hid, statement, "v51_rigid_v1", change_desc,
                               results, notes, baseline_wr)


def main():
    ap = argparse.ArgumentParser(description="Hypothesis tracker")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("list", help="가설 목록")
    sub.add_parser("list-situations", help="상황 패턴 목록")

    args = ap.parse_args()

    if args.cmd == "list":
        list_hypotheses()
    elif args.cmd == "list-situations":
        list_situations()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
