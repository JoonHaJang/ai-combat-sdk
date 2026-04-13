"""
match_knowledge.py — 매치 지식 누적 시스템

매치 replay(ACMI)를 분석하여 구조화된 JSON으로 저장.
시간이 지나면서 매치가 쌓이면 자동으로 패턴 분석 가능.

데이터 스키마:
    logs/knowledge/matches.jsonl (1줄 1매치)
    logs/knowledge/patterns.json (집계 결과)

사용:
    # 단일 replay 분석 후 knowledge DB에 추가
    python tools/match_knowledge.py add replays/ace/adaptive_eagle_vs_ace.acmi

    # 디렉토리 일괄 추가
    python tools/match_knowledge.py add replays/

    # 축적된 패턴 요약
    python tools/match_knowledge.py summary

    # 특정 상대별 필터
    python tools/match_knowledge.py summary --opponent ace

    # 승/패/무 카테고리별 비교
    python tools/match_knowledge.py compare-outcomes
"""

import argparse
import json
import sys
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.analyze_acmi import ACMIParser, analyze, diagnose, classify_phase

KNOWLEDGE_DIR = PROJECT_ROOT / "logs" / "knowledge"
MATCHES_DB = KNOWLEDGE_DIR / "matches.jsonl"
PATTERNS_DB = KNOWLEDGE_DIR / "patterns.json"


def _outcome_category(result):
    hp_diff = result["hp"]["diff"]
    ego_hp = result["hp"]["ego_final"]
    enm_hp = result["hp"]["enm_final"]
    if abs(hp_diff) < 0.5 and ego_hp > 99 and enm_hp > 99:
        return "DRAW_NO_ENGAGEMENT"
    if hp_diff > 10:
        return "WIN_DOMINANT"
    if hp_diff > 2:
        return "WIN_MARGINAL"
    if hp_diff > -2:
        return "DRAW_ENGAGED"
    if hp_diff > -10:
        return "LOSS_MARGINAL"
    return "LOSS_DOMINANT"


def _record_from_analysis(path, result, diag):
    """분석 결과를 knowledge record로 변환."""
    return {
        "timestamp": datetime.now().isoformat(),
        "replay_path": str(path),
        "ego": result["ego_name"],
        "enm": result["enm_name"],
        "duration_s": result["duration_s"],
        "n_frames": result["n_frames"],
        "outcome": _outcome_category(result),
        "hp_ego": result["hp"]["ego_final"],
        "hp_enm": result["hp"]["enm_final"],
        "hp_diff": result["hp"]["diff"],
        "wez_pct": result["wez"]["ego_in_wez_pct"],
        "wez_first_t": result["wez"]["first_wez_t"],
        "dist_min": result["distance"]["min"],
        "dist_avg": result["distance"]["avg"],
        "dist_final": result["distance"]["final"],
        "ata_avg": result["angles"]["avg_ata"],
        "aa_avg": result["angles"]["avg_aa"],
        "closure_avg": result["closure"]["avg_kts"],
        "approach_pct": result["closure"]["approach_pct"],
        "energy_diff_avg": result["energy"]["diff_avg"],
        "energy_diff_end": result["energy"]["end_diff"],
        "energy_adv_pct": result["energy"]["adv_pct"],
        "phases": result["phases"],
        "top_nodes": dict(result["node_usage_top"]),
        "diagnosis": diag,
    }


def add_to_knowledge(acmi_path):
    """단일 ACMI → knowledge DB에 추가."""
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    parser = ACMIParser(acmi_path)
    result = analyze(parser)
    if "error" in result:
        return None
    diag = diagnose(result)
    record = _record_from_analysis(acmi_path, result, diag)
    with open(MATCHES_DB, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def add_all(path):
    """디렉토리 또는 파일 경로에서 모든 ACMI 추가."""
    p = Path(path)
    if p.is_file():
        paths = [p]
    elif p.is_dir():
        paths = sorted(p.rglob("*.acmi"))
    else:
        print(f"ERROR: {p} not found")
        return []

    added = []
    for path in paths:
        try:
            rec = add_to_knowledge(path)
            if rec:
                added.append(rec)
                print(f"  + {path.name}: {rec['outcome']}  hp_diff={rec['hp_diff']:+.1f}  "
                      f"wez={rec['wez_pct']}%  energy={rec['energy_diff_avg']:+d}")
        except Exception as e:
            print(f"  ! {path.name}: {e}")
    return added


def load_matches():
    """knowledge DB 전체 로드."""
    if not MATCHES_DB.exists():
        return []
    matches = []
    with open(MATCHES_DB, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                matches.append(json.loads(line))
    return matches


def summary(opponent_filter=None):
    """축적된 매치의 전체 통계."""
    matches = load_matches()
    if opponent_filter:
        matches = [m for m in matches if m["enm"] == opponent_filter]

    if not matches:
        print(f"No matches found {f'for {opponent_filter}' if opponent_filter else ''}.")
        return

    n = len(matches)
    outcomes = Counter(m["outcome"] for m in matches)
    opponents = Counter(m["enm"] for m in matches)

    print(f"\n{'='*70}")
    print(f"  Knowledge Base Summary  (total: {n} matches)")
    if opponent_filter:
        print(f"  Filter: vs {opponent_filter}")
    print('='*70)

    print(f"\n  Outcomes:")
    for outcome, count in outcomes.most_common():
        pct = 100 * count / n
        print(f"    {outcome:25s}  {count:4d}  ({pct:.1f}%)")

    if not opponent_filter:
        print(f"\n  By opponent:")
        for opp, count in opponents.most_common():
            subset = [m for m in matches if m["enm"] == opp]
            wins = sum(1 for m in subset if m["outcome"].startswith("WIN"))
            losses = sum(1 for m in subset if m["outcome"].startswith("LOSS"))
            draws = sum(1 for m in subset if m["outcome"].startswith("DRAW"))
            print(f"    {opp:15s}  {count:3d} matches  W{wins}/D{draws}/L{losses}")

    # 평균 metrics
    print(f"\n  Average metrics:")
    for key, label in [
        ("hp_diff", "HP diff"),
        ("wez_pct", "WEZ %"),
        ("dist_avg", "avg distance"),
        ("energy_diff_avg", "energy diff"),
        ("approach_pct", "approach %"),
    ]:
        avg = sum(m[key] for m in matches) / n
        print(f"    {label:25s}  {avg:+.1f}")

    # Top node usage (across all matches)
    node_total = Counter()
    for m in matches:
        for node, cnt in m["top_nodes"].items():
            node_total[node] += cnt
    print(f"\n  Top nodes (cumulative ticks):")
    for node, cnt in node_total.most_common(10):
        print(f"    {node:30s}  {cnt:8d}")
    print()


def compare_outcomes():
    """승/무/패 그룹 간 metric 비교 — 왜 이기고 지는지 패턴 발견."""
    matches = load_matches()
    if not matches:
        print("No matches.")
        return

    groups = defaultdict(list)
    for m in matches:
        cat = m["outcome"]
        base = "WIN" if cat.startswith("WIN") else ("LOSS" if cat.startswith("LOSS") else "DRAW")
        groups[base].append(m)

    print(f"\n{'='*70}")
    print(f"  Outcome Comparison  ({len(matches)} matches, {len(groups)} groups)")
    print('='*70)

    metrics = [
        ("wez_pct", "WEZ %"),
        ("dist_min", "min distance"),
        ("dist_avg", "avg distance"),
        ("ata_avg", "avg ATA"),
        ("aa_avg", "avg AA"),
        ("closure_avg", "avg closure"),
        ("approach_pct", "approach %"),
        ("energy_diff_avg", "energy diff avg"),
        ("energy_diff_end", "energy diff end"),
    ]

    print(f"\n  {'Metric':25s}  {'WIN':>12s}  {'DRAW':>12s}  {'LOSS':>12s}")
    print(f"  {'-'*25}  {'-'*12}  {'-'*12}  {'-'*12}")
    for key, label in metrics:
        row = [label]
        for cat in ["WIN", "DRAW", "LOSS"]:
            subset = groups.get(cat, [])
            if subset:
                avg = sum(m[key] for m in subset) / len(subset)
                row.append(f"{avg:+12.1f}")
            else:
                row.append(f"{'—':>12s}")
        print(f"  {row[0]:25s}  {row[1]}  {row[2]}  {row[3]}")

    # Phase 비율 비교
    print(f"\n  Phase distribution:")
    for cat in ["WIN", "DRAW", "LOSS"]:
        subset = groups.get(cat, [])
        if not subset:
            continue
        phase_sum = defaultdict(float)
        for m in subset:
            for p, pct in m["phases"].items():
                phase_sum[p] += pct
        n = len(subset)
        phase_avg = {p: round(v / n, 1) for p, v in phase_sum.items()}
        parts = [f"{p}={pct}%" for p, pct in sorted(phase_avg.items(), key=lambda x: -x[1])]
        print(f"    {cat:5s} ({len(subset)}): {'  '.join(parts)}")

    # 자동 가설 생성
    print(f"\n  Auto-generated hypotheses:")
    wins = groups.get("WIN", [])
    losses = groups.get("LOSS", [])
    if wins and losses:
        for key, label in metrics:
            w_avg = sum(m[key] for m in wins) / len(wins)
            l_avg = sum(m[key] for m in losses) / len(losses)
            delta = w_avg - l_avg
            if abs(delta) > 0.1:
                direction = "higher" if delta > 0 else "lower"
                if abs(delta) / (abs(w_avg) + 1e-6) > 0.3:
                    print(f"    • {label}: WIN is {direction} by {abs(delta):.1f} — potential driver")
    print()


def main():
    ap = argparse.ArgumentParser(description="Match knowledge accumulator")
    sub = ap.add_subparsers(dest="cmd")

    p_add = sub.add_parser("add", help="ACMI 추가")
    p_add.add_argument("path", help="ACMI 파일 또는 디렉토리")

    p_sum = sub.add_parser("summary", help="축적 요약")
    p_sum.add_argument("--opponent", default=None)

    sub.add_parser("compare-outcomes", help="승/무/패 비교")

    args = ap.parse_args()

    if args.cmd == "add":
        added = add_all(args.path)
        print(f"\n  Added {len(added)} matches to {MATCHES_DB}")
        total = len(load_matches())
        print(f"  Total matches in DB: {total}")
    elif args.cmd == "summary":
        summary(args.opponent)
    elif args.cmd == "compare-outcomes":
        compare_outcomes()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
