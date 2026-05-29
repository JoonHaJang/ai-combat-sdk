"""R15-J12: K3/K2/NONE noise verification — 3 runs each."""
import os
import re
import subprocess
import statistics
from pathlib import Path

OPPS = [
    "simple", "defensive", "aggressive", "ace",
    "adaptive_eagle_v6", "adaptive_eagle_v6h2", "adaptive_eagle_v6h4",
    "adaptive_eagle_v6h5a", "adaptive_eagle_v6h5b", "adaptive_eagle_v6h5c",
    "adaptive_eagle_v6h_e1", "adaptive_eagle_v6h_e1b",
    "adaptive_eagle_v6h_e1c", "adaptive_eagle_v6h_e1d",
    "adaptive_eagle_v7", "adaptive_eagle_v8",
    "adaptive_eagle_v9", "adaptive_eagle_v10",
    "adaptive_eagle_v11_code", "adaptive_eagle_v51",
]
SETTINGS = ["NONE", "K2", "K3", "K5", "K3,K5"]
RUNS = 3
ROOT = Path(__file__).resolve().parents[1]

DMG_RE = re.compile(r"HP\s*\(데미지\s+([\d.]+)\s+가함\)")


def run_one(opp, ks_env):
    env = os.environ.copy()
    env["R15_J8_KS"] = ks_env
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
            return float(dmgs[-1]), float(dmgs[-2])  # us, opp_to_us
    except Exception:
        pass
    return 0.0, 0.0


def main():
    summary = {}  # {setting: [(deal_run1, taken_run1), ...]}
    for setting in SETTINGS:
        summary[setting] = []
        for run in range(RUNS):
            print(f"\n=== {setting} run {run+1}/{RUNS} ===", flush=True)
            deal_s = 0
            taken_s = 0
            for opp in OPPS:
                us, taken = run_one(opp, setting)
                deal_s += us
                taken_s += taken
            print(f"  deal={deal_s:.1f} taken={taken_s:.1f} "
                  f"net={deal_s - taken_s:+.1f}", flush=True)
            summary[setting].append((deal_s, taken_s))

    print("\n\n=== NOISE ANALYSIS (3 runs each) ===")
    print(f"{'setting':<10} {'deal mean±std':>22} {'taken mean±std':>22} {'net mean':>10}")
    for setting in SETTINGS:
        runs = summary[setting]
        deals = [r[0] for r in runs]
        takens = [r[1] for r in runs]
        d_m = statistics.mean(deals)
        d_s = statistics.stdev(deals) if len(deals) > 1 else 0
        t_m = statistics.mean(takens)
        t_s = statistics.stdev(takens) if len(takens) > 1 else 0
        print(f"{setting:<10} {d_m:>10.1f} ±{d_s:>5.1f}  "
              f"{t_m:>10.1f} ±{t_s:>5.1f}  {d_m - t_m:>+8.1f}")


if __name__ == "__main__":
    main()
