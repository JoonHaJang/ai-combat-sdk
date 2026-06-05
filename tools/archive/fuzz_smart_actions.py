"""Fuzz Smart* action swap variants + 3-run avg matches.

Each variant:
  - baseline (no Smart)
  - lead/lag/highyoyo/lowyoyo/breakturn/purepursuit individually swapped
  - all swapped

Output: matrix of (variant, opp) → avg dmg + std + n_runs.
"""
import subprocess
import re
import sys
import os
import json
import statistics as stats
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTOR_PATH = ROOT / "examples/pursuit_chase_v1/nodes/cost_branch_selector.py"

# Branch action swap configs: each variant = list of (orig_action, smart_action) pairs.
VARIANTS = {
    "baseline": [],
    "lead_only": [("action_lead_pursuit", "action_smart_lead")],
    "lag_only": [("action_lag_pursuit", "action_smart_lag")],
    "highyoyo_only": [("action_high_yoyo", "action_smart_highyoyo")],
    "lowyoyo_only": [("action_dive_attack", "action_smart_lowyoyo")],
    "breakturn_only": [("action_break_turn", "action_smart_breakturn")],
    "offensive_only": [("action_offensive_pursuit", "action_smart_purepursuit")],
    "all_smart": [
        ("action_lead_pursuit", "action_smart_lead"),
        ("action_lag_pursuit", "action_smart_lag"),
        ("action_high_yoyo", "action_smart_highyoyo"),
        ("action_dive_attack", "action_smart_lowyoyo"),
        ("action_break_turn", "action_smart_breakturn"),
        ("action_offensive_pursuit", "action_smart_purepursuit"),
    ],
}

OPPS = ["simple", "defensive", "aggressive", "ace"]
N_RUNS = 3
MAX_STEPS = 1500
TIMEOUT = 150


def apply_variant(swap_pairs):
    """Swap action names in BRANCHES list of cost_branch_selector.py."""
    src = SELECTOR_PATH.read_text(encoding="utf-8")
    # Find BRANCHES list block and modify
    for orig, smart in swap_pairs:
        # action 칼럼은 줄 끝에 있음:  ", action_orig)," 형식
        # 안전한 패턴: action 이름이 single token
        src = re.sub(
            r'(\(\s*"[^"]+"\s*,\s*[^,]+,\s*)' + re.escape(orig) + r'\b',
            r'\1' + smart, src)
    SELECTOR_PATH.write_text(src, encoding="utf-8")


def restore():
    """Revert all swaps back to baseline action_*."""
    src = SELECTOR_PATH.read_text(encoding="utf-8")
    pairs = [
        ("action_smart_lead", "action_lead_pursuit"),
        ("action_smart_lag", "action_lag_pursuit"),
        ("action_smart_highyoyo", "action_high_yoyo"),
        ("action_smart_lowyoyo", "action_dive_attack"),
        ("action_smart_breakturn", "action_break_turn"),
        ("action_smart_purepursuit", "action_offensive_pursuit"),
    ]
    for smart, orig in pairs:
        src = re.sub(
            r'(\(\s*"[^"]+"\s*,\s*[^,]+,\s*)' + re.escape(smart) + r'\b',
            r'\1' + orig, src)
    SELECTOR_PATH.write_text(src, encoding="utf-8")


def run_match(opp):
    """Run 1 match, return opp dmg as float."""
    env = os.environ.copy()
    if opp in ("aggressive", "defensive"):
        env["ADVERSARY"] = opp
    else:
        env.pop("ADVERSARY", None)
    try:
        r = subprocess.run(
            ["python", "scripts/run_match.py",
             "--agent1", "examples/pursuit_chase_v1/pursuit_chase_btcost.yaml",
             "--agent2", opp, "--rounds", "1", "--max-steps", str(MAX_STEPS)],
            capture_output=True, text=True, timeout=TIMEOUT, cwd=ROOT, env=env)
        out = r.stdout + r.stderr
        # last 데미지 X.Y 매치
        dmgs = re.findall(r"데미지 ([\d.]+)", out)
        return float(dmgs[-1]) if len(dmgs) >= 2 else 0.0
    except Exception:
        return 0.0


def main():
    results = {}
    print("=" * 70)
    print(f"Fuzzing {len(VARIANTS)} variants × {len(OPPS)} opps × {N_RUNS} runs")
    print(f"  {len(VARIANTS) * len(OPPS) * N_RUNS} total matches expected")
    print("=" * 70)
    for vname, swap_pairs in VARIANTS.items():
        print(f"\n--- variant: {vname} ---", flush=True)
        restore()
        apply_variant(swap_pairs)
        variant_results = {}
        for opp in OPPS:
            dmgs = []
            for r in range(N_RUNS):
                d = run_match(opp)
                dmgs.append(d)
                print(f"  {opp:>10s} run {r+1}: {d:5.1f}", flush=True)
            avg = sum(dmgs) / len(dmgs)
            sd = stats.stdev(dmgs) if len(dmgs) > 1 else 0.0
            variant_results[opp] = {"avg": round(avg, 2), "std": round(sd, 2),
                                     "runs": dmgs}
            print(f"  {opp:>10s} AVG={avg:.2f} ± {sd:.2f}", flush=True)
        results[vname] = variant_results

    restore()
    out_path = ROOT / "logs/fuzz_smart_actions_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print("\n" + "=" * 70)
    print("=== SUMMARY (avg dmg) ===")
    header = "variant".ljust(20) + "".join(f"{o:>12s}" for o in OPPS) + "  total"
    print(header)
    for vn, vr in results.items():
        line = vn.ljust(20)
        total = 0.0
        for o in OPPS:
            avg = vr[o]["avg"]
            line += f"{avg:12.2f}"
            total += avg
        line += f"  {total:6.2f}"
        print(line)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
