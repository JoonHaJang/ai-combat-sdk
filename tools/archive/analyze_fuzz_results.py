"""Analyze fuzz_smart_actions_results.json — best variant identification + delta vs baseline."""
import json
import sys
from pathlib import Path


def main():
    p = Path("logs/fuzz_smart_actions_results.json")
    if not p.exists():
        print(f"NOT FOUND: {p}")
        sys.exit(1)
    d = json.load(open(p, encoding="utf-8"))
    baseline = d.get("baseline", {})
    base_total = sum(b["avg"] for b in baseline.values())
    print(f"{'='*80}")
    print(f"BASELINE total avg dmg: {base_total:.2f}")
    print(f"{'='*80}\n")

    # 각 variant 별 delta + best opp identification
    print(f"{'variant':<20s} {'simple':>8s} {'defens':>8s} {'aggres':>8s} {'ace':>8s} {'total':>8s} {'Δtotal':>10s}")
    rows = []
    for vname, vres in d.items():
        if vname == "baseline":
            continue
        total = sum(v["avg"] for v in vres.values())
        delta = total - base_total
        rows.append((vname, vres, total, delta))
    # sort by delta desc
    rows.sort(key=lambda r: -r[3])
    # baseline first
    bvres = baseline
    btotal = sum(v["avg"] for v in bvres.values())
    print(f"{'baseline':<20s} "
          f"{bvres['simple']['avg']:8.2f} {bvres['defensive']['avg']:8.2f} "
          f"{bvres['aggressive']['avg']:8.2f} {bvres['ace']['avg']:8.2f} "
          f"{btotal:8.2f} {0.0:+10.2f}")
    for vname, vres, total, delta in rows:
        print(f"{vname:<20s} "
              f"{vres['simple']['avg']:8.2f} {vres['defensive']['avg']:8.2f} "
              f"{vres['aggressive']['avg']:8.2f} {vres['ace']['avg']:8.2f} "
              f"{total:8.2f} {delta:+10.2f}")

    # best per opp
    print(f"\n--- best variant per opp ---")
    for opp in ("simple", "defensive", "aggressive", "ace"):
        all_vars = [("baseline", baseline)] + [(vn, vr) for vn, vr, _, _ in rows]
        best = max(all_vars, key=lambda x: x[1][opp]["avg"])
        print(f"  {opp:>10s}: {best[0]:<18s} = {best[1][opp]['avg']:.2f}")


if __name__ == "__main__":
    main()
