"""R15-J10 ablation: K1-K7 개별 효과 측정."""
import os
import re
import subprocess
import sys
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
KS = ["K1", "K2", "K3", "K4", "K5", "K7", "NONE", "ALL"]
ROOT = Path(__file__).resolve().parents[1]

DMG_RE = re.compile(r"HP\s*\(데미지\s+([\d.]+)\s+가함\)")


def run_one(opp, ks_env):
    env = os.environ.copy()
    env["R15_J8_KS"] = ks_env if ks_env != "ALL" else "K1,K2,K3,K4,K5,K7"
    if ks_env == "NONE":
        env["R15_J8_KS"] = ""
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
        # tree1 line: opp dealt to us; tree2 line: we dealt to opp
        if len(dmgs) >= 2:
            opp_to_us = float(dmgs[-2])
            us_to_opp = float(dmgs[-1])
            return us_to_opp, opp_to_us
    except Exception as e:
        print(f"  ERR: {e}", flush=True)
    return 0.0, 0.0


def main():
    results = {}  # {ks: {opp: (us_dmg, opp_dmg)}}
    for ks in KS:
        print(f"\n=== {ks} ===", flush=True)
        results[ks] = {}
        for opp in OPPS:
            us, opp_dmg = run_one(opp, ks)
            results[ks][opp] = (us, opp_dmg)
            print(f"  {opp:<30} us={us:>5.1f} opp_to_us={opp_dmg:>5.1f}",
                  flush=True)
    # Summary table
    print("\n\n=== SUMMARY (deal sum / taken sum / net) ===")
    print(f"{'KS':<10} {'deal':>8} {'taken':>8} {'net':>8}")
    for ks in KS:
        deal = sum(v[0] for v in results[ks].values())
        taken = sum(v[1] for v in results[ks].values())
        print(f"{ks:<10} {deal:>8.1f} {taken:>8.1f} {deal - taken:>+8.1f}")
    # Per-opp comparison
    print("\n=== PER-OPP COMPARISON (us_dmg dealt) ===")
    hdr = f"{'opp':<30} " + " ".join(f"{ks:>7}" for ks in KS)
    print(hdr)
    for opp in OPPS:
        row = f"{opp:<30} " + " ".join(
            f"{results[ks][opp][0]:>7.1f}" for ks in KS
        )
        print(row)


if __name__ == "__main__":
    main()
