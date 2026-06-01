"""Rule fire analysis (Framework B, 2026-05-31).

사용자 요청: "각 if then 상황끼리 부딪치지 않게 조건을 확인하는 것들도 도구나 방법론".

BRANCH_CSV trace 활용:
1. 매치 별로 chosen branch (K_* / SUB_* / cost branch) 시계열
2. 각 K-rule 의 fire 빈도 + tick 분포 (어떤 phase에 fire)
3. 인접 fire 사이 충돌 패턴 식별
4. K-rule 우선순위 vs 실제 fire — dead code 식별

usage:
    BRANCH_CSV=./trace.csv python scripts/run_match.py ...
    python tools/analyze_rule_fire.py ./trace.csv ./trace2.csv ...
"""
from __future__ import annotations
import sys, csv, glob
from collections import Counter, defaultdict
from pathlib import Path


def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def phase(s):
    s = int(s)
    if s < 30:  return "A spawn"
    if s < 100: return "B 30-100"
    if s < 300: return "C 100-300"
    if s < 800: return "D 300-800"
    return "E 800+"


def analyze(path):
    rows = load(path)
    name = Path(path).stem.replace("_trace_", "_").replace("agg", "AGG ").replace("def", "DEF ").replace("v51", "V51 ").replace("ace", "ACE ")
    print(f"\n{'='*80}\n {name} ({len(rows)} ticks)\n{'='*80}")

    # 1. chosen branch distribution
    chosens = Counter(r["chosen"] for r in rows)
    print(f"\n--- Branch fire count (top 12) ---")
    for b, c in chosens.most_common(12):
        pct = 100 * c / len(rows)
        print(f"  {c:5d} ({pct:5.1f}%)  {b}")

    # 2. fire by phase
    print(f"\n--- Fire by phase ---")
    print(f"  {'phase':12s} {'A':>6} {'B':>6} {'C':>6} {'D':>6} {'E':>6}")
    by_phase_branch = defaultdict(lambda: Counter())
    for r in rows:
        p = phase(r["tick"])[0]
        by_phase_branch[r["chosen"]][p] += 1
    top_branches = [b for b, _ in chosens.most_common(10)]
    for b in top_branches:
        cnt = by_phase_branch[b]
        print(f"  {b:30s} {cnt['A']:>4d} {cnt['B']:>4d} {cnt['C']:>4d} {cnt['D']:>4d} {cnt['E']:>4d}")

    # 3. K-rule fire 식별
    print(f"\n--- K-rule fire only (SUB_*, K*_) ---")
    k_rules = {b: c for b, c in chosens.items() if b.startswith(("SUB_", "K"))}
    for b, c in sorted(k_rules.items(), key=lambda x: -x[1]):
        print(f"  {c:5d}  {b}")

    # 4. consecutive fire pattern — branch transitions
    print(f"\n--- Branch transitions (top 8 — 충돌 후보) ---")
    transitions = Counter()
    for i in range(1, len(rows)):
        prev = rows[i-1]["chosen"]
        cur = rows[i]["chosen"]
        if prev != cur:
            transitions[(prev, cur)] += 1
    for (a, b), c in transitions.most_common(8):
        print(f"  {c:4d}  {a:30s} → {b}")

    # 5. dead K-rules — never fire even when enabled
    expected_ks = ["K2", "K8", "K10", "K11", "K12", "K3", "K1", "K4", "K5", "K7", "K9"]
    dead = []
    fire = []
    for kr in expected_ks:
        if any(b.startswith(kr + "_") or b == f"K{kr[1:]}_*" or kr in b for b in chosens):
            fire.append(kr)
        else:
            dead.append(kr)
    print(f"\n--- K-rule fire summary ---")
    print(f"  FIRED:  {', '.join(fire) if fire else '(none)'}")
    print(f"  DEAD:   {', '.join(dead) if dead else '(none)'}")


if __name__ == "__main__":
    paths = []
    for pattern in sys.argv[1:]:
        paths.extend(sorted(glob.glob(pattern)))
    if not paths:
        print("usage: python analyze_rule_fire.py <trace1.csv> [trace2.csv] ...")
        sys.exit(1)
    for p in paths:
        analyze(p)
