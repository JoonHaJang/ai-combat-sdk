"""R15-K K12_E energy chase 실험 — defensive/aggressive 격파 + 회귀 검증."""
import os, re, subprocess, statistics
from pathlib import Path

OPPS = ["defensive", "aggressive", "ace", "v10", "v51",
        "v7", "v11_code", "v6h5b"]
def opp_full(o):
    return o if o in ("defensive", "aggressive", "ace", "simple") else f"adaptive_eagle_{o}"

SETTINGS = ["K2,K8,K10,K11", "K2,K8,K10,K11,K12"]
RUNS = 5
ROOT = Path(__file__).resolve().parents[1]
DMG_RE = re.compile(r"HP\s*\(데미지\s+([\d.]+)\s+가함\)")

def run_one(opp, ks):
    env = os.environ.copy()
    env["R15_J8_KS"] = ks
    try:
        r = subprocess.run(
            ["python", "scripts/run_match.py",
             "--agent1", "examples/pursuit_chase_v1/pursuit_chase_btcost.yaml",
             "--agent2", opp_full(opp), "--rounds", "1", "--max-steps", "1500",
             "--scenario", "bt_vs_bt"],
            capture_output=True, text=True, timeout=120, cwd=ROOT, env=env)
        out = r.stdout + r.stderr
        dmgs = DMG_RE.findall(out)
        if len(dmgs) >= 2:
            return float(dmgs[-1]), float(dmgs[-2])
    except Exception:
        pass
    return 0.0, 0.0

def main():
    results = {}
    for ks in SETTINGS:
        results[ks] = {}
        for opp in OPPS:
            runs = []
            for r in range(RUNS):
                us, taken = run_one(opp, ks)
                runs.append((us, taken))
            results[ks][opp] = runs
            deals = [r[0] for r in runs]
            takens = [r[1] for r in runs]
            wins = sum(1 for d, t in runs if d > 0)
            print(f"{ks:<22} {opp:<14} mean={statistics.mean(deals):>5.2f} ±{statistics.stdev(deals) if len(deals)>1 else 0:>4.2f}  "
                  f"taken={statistics.mean(takens):>5.2f}  WIN={wins}/{RUNS}", flush=True)
    print("\n=== SUMMARY (mean dmg / mean taken) ===")
    print(f"{'opp':<14} " + " ".join(f"{ks:>22}" for ks in SETTINGS))
    for opp in OPPS:
        cells = []
        for ks in SETTINGS:
            deals = [r[0] for r in results[ks][opp]]
            takens = [r[1] for r in results[ks][opp]]
            cells.append(f"{statistics.mean(deals):>5.2f}/{statistics.mean(takens):>4.2f}")
        print(f"{opp:<14} " + " ".join(f"{c:>22}" for c in cells))

if __name__ == "__main__":
    main()
