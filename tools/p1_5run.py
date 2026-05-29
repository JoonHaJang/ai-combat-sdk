"""R15-K P1: v6h5a/b/v6h_e1c + baseline 5-run 측정.

목적: 사용자 가설 "v6h5* 는 P1 분산 — 5-run 으로 catch 확인" 검증.
"""
import os
import re
import subprocess
import statistics
from pathlib import Path

OPPS = [
    "adaptive_eagle_v6h5a",
    "adaptive_eagle_v6h5b",
    "adaptive_eagle_v6h_e1c",
    # 비교 baseline
    "adaptive_eagle_v7",       # WIN ~2 dmg
    "adaptive_eagle_v11_code", # WIN ~7 dmg
    "defensive",                # DRAW
]
RUNS = 5
ROOT = Path(__file__).resolve().parents[1]
DMG_RE = re.compile(r"HP\s*\(데미지\s+([\d.]+)\s+가함\)")


def run_one(opp):
    env = os.environ.copy()
    # current best (R15-J12): K2 only default
    try:
        r = subprocess.run(
            ["python", "scripts/run_match.py",
             "--agent1", "examples/pursuit_chase_v1/pursuit_chase_btcost.yaml",
             "--agent2", opp, "--rounds", "1", "--max-steps", "1500",
             "--scenario", "bt_vs_bt"],
            capture_output=True, text=True, timeout=120, cwd=ROOT, env=env,
        )
        out = r.stdout + r.stderr
        dmgs = DMG_RE.findall(out)
        if len(dmgs) >= 2:
            return float(dmgs[-1]), float(dmgs[-2])
    except Exception:
        pass
    return 0.0, 0.0


def main():
    results = {}
    for opp in OPPS:
        print(f"\n=== {opp} ({RUNS} runs) ===", flush=True)
        runs = []
        for r in range(RUNS):
            us, opp_dmg = run_one(opp)
            runs.append((us, opp_dmg))
            print(f"  run {r+1}: us={us:>5.1f} taken={opp_dmg:>5.1f}",
                  flush=True)
        results[opp] = runs

    print("\n\n=== SUMMARY ===")
    print(f"{'opp':<32} {'deal mean±std':>20} {'taken mean±std':>20} {'WIN/DRAW':>10}")
    for opp in OPPS:
        runs = results[opp]
        deals = [r[0] for r in runs]
        takens = [r[1] for r in runs]
        d_m = statistics.mean(deals)
        d_s = statistics.stdev(deals) if len(deals) > 1 else 0
        t_m = statistics.mean(takens)
        t_s = statistics.stdev(takens) if len(takens) > 1 else 0
        wins = sum(1 for d, t in runs if d > 0)
        print(f"{opp:<32} {d_m:>9.2f} ±{d_s:>6.2f}  "
              f"{t_m:>9.2f} ±{t_s:>6.2f}  {wins}/{RUNS}")


if __name__ == "__main__":
    main()
