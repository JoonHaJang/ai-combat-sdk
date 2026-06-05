"""R15-K P3 측정: K9 tracking lock + bin rate-limit 효과 + 회귀 확인."""
import os, re, subprocess, statistics
from pathlib import Path

OPPS = [
    "defensive",       # 핵심 — VERDICT MIXED, hard-turn 83%, WEZ 0
    "aggressive",      # MIXED, K8 효과 X
    "ace",             # PHYSICS LIMIT, 회귀 확인
    "adaptive_eagle_v7",        # 회귀
    "adaptive_eagle_v11_code",  # 회귀
    "adaptive_eagle_v6h5b",     # P1 분산
    "adaptive_eagle_v51",       # PHYSICS LIMIT
]
SETTINGS = ["K2,K8", "K2,K8,K9", "K9"]
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
             "--agent2", opp, "--rounds", "1", "--max-steps", "1500",
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
            print(f"{ks:<14} {opp:<28} mean={statistics.mean(deals):>5.2f} ±{statistics.stdev(deals) if len(deals)>1 else 0:>4.2f}  "
                  f"taken={statistics.mean(takens):>5.2f}  WIN={wins}/{RUNS}", flush=True)
    print("\n=== SUMMARY ===")
    print(f"{'opp':<28} " + " ".join(f"{ks:>14}" for ks in SETTINGS))
    for opp in OPPS:
        cells = []
        for ks in SETTINGS:
            deals = [r[0] for r in results[ks][opp]]
            takens = [r[1] for r in results[ks][opp]]
            cells.append(f"{statistics.mean(deals):>5.2f}/{statistics.mean(takens):>4.2f}")
        print(f"{opp:<28} " + " ".join(f"{c:>14}" for c in cells))

if __name__ == "__main__":
    main()
