"""R15-J11: K 조합 테스트 — K2/K3/K5 베스트 single K 조합."""
import os
import re
import subprocess
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
COMBOS = ["K2", "K5", "K3", "K2,K5", "K2,K3", "K2,K3,K5",
           "K2,K3,K5,K7", "K3,K5", "K5,K7"]
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
            return float(dmgs[-1]), float(dmgs[-2])  # us, opp
    except Exception:
        pass
    return 0.0, 0.0


def main():
    results = {}
    for cmb in COMBOS:
        print(f"\n=== {cmb} ===", flush=True)
        results[cmb] = {}
        deal_s = 0
        taken_s = 0
        for opp in OPPS:
            us, taken = run_one(opp, cmb)
            results[cmb][opp] = (us, taken)
            deal_s += us
            taken_s += taken
        print(f"  TOTAL deal={deal_s:.1f} taken={taken_s:.1f} "
              f"net={deal_s - taken_s:+.1f}", flush=True)
    print("\n\n=== FINAL ===")
    print(f"{'combo':<20} {'deal':>8} {'taken':>8} {'net':>8}")
    for cmb in COMBOS:
        d = sum(v[0] for v in results[cmb].values())
        t = sum(v[1] for v in results[cmb].values())
        print(f"{cmb:<20} {d:>8.1f} {t:>8.1f} {d - t:>+8.1f}")


if __name__ == "__main__":
    main()
