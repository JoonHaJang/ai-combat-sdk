"""R15-K P2 측정: K8 corner-bleed 효과 + 회귀 확인."""
import os, re, subprocess, statistics
from pathlib import Path

OPPS = [
    "aggressive",      # 핵심 — VERDICT MIXED, hdg=4 91%
    "defensive",       # 비교 — VERDICT MIXED, 다른 케이스
    "ace",             # 회귀 — PHYSICS LIMIT, K8 영향 없어야
    "adaptive_eagle_v7",        # 회귀 — 잘 잡음 (~5)
    "adaptive_eagle_v11_code",  # 회귀 — 잘 잡음 (~7)
    "adaptive_eagle_v6h5b",     # P1 분산 — 영향 확인
    "adaptive_eagle_v51",       # PHYSICS LIMIT
]
SETTINGS = ["K2", "K2,K8", "K8"]
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
            print(f"{ks:<10} {opp:<28} mean={statistics.mean(deals):>5.2f} ±{statistics.stdev(deals) if len(deals)>1 else 0:>4.2f}  "
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
