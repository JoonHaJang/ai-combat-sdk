"""GA 가 끝난 뒤 best_ever.json 의 챔피언 variant 를 cost_branch_selector.py 에 *영구* 적용.

GA fuzz 는 끝나면 backup 으로 되돌리는데, 이 script 는 best variant 를 다시 박는다.
이후 BT-zoo + 다중 run 검증 자동 수행.

사용:
    python tools/apply_ga_champion.py            # apply + verify (runs=3)
    python tools/apply_ga_champion.py --apply-only
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "examples/pursuit_chase_v1/nodes/cost_branch_selector.py"
BEST_PATH = ROOT / "logs/fuzz_genetic/best_ever.json"


def apply_variant(v: dict):
    """fuzz_genetic.py 와 동일한 regex 치환."""
    src = SELECTOR.read_text(encoding="utf-8")
    src = re.sub(r'if self\._branch_tick > \d+:',
                 f"if self._branch_tick > {v['STUCK_THR']}:", src)
    src = re.sub(r'min\([\d.]+, \(self\._branch_tick - \d+\) / 50\.0\)',
                 f"min({v['STUCK_MAX']}, (self._branch_tick - {v['STUCK_THR']}) / 50.0)", src)
    src = re.sub(r'LAMBDA_D = [\d.]+', f"LAMBDA_D = {v['LAMBDA_D']}", src)
    src = re.sub(r'base = -[\d.]+ \* pos_q \* dist_q',
                 f"base = -{v['LAMBDA_OFFENSIVE']} * pos_q * dist_q", src)
    src = re.sub(r'return -[\d.]+ \* ata_q \* \(0\.3 \+ 0\.7 \* closure_q\)',
                 f"return -{v['LAMBDA_CUTOFF']} * ata_q * (0.3 + 0.7 * closure_q)", src)
    src = re.sub(r'return -[\d.]+ \* min\(1\.0, score\)',
                 f"return -{v['LAMBDA_HIGHYOYO']} * min(1.0, score)", src)
    src = re.sub(r'return -[\d.]+ \* threat_score',
                 f"return -{v['LAMBDA_BREAK']} * threat_score", src)
    src = re.sub(r'return -[\d.]+ \* alt_adv_q \* ata_q \* dist_q',
                 f"return -{v['LAMBDA_DIVE']} * alt_adv_q * ata_q * dist_q", src)
    src = re.sub(r'return -[\d.]+ \* closing_penalty \* dist_q \* alt_room',
                 f"return -{v['LAMBDA_TCV']} * closing_penalty * dist_q * alt_room", src)
    src = re.sub(r'return -[\d.]+ \* dist_q \* ata_q',
                 f"return -{v['LAMBDA_EXT']} * dist_q * ata_q", src)
    SELECTOR.write_text(src, encoding="utf-8")


def run_match(opp: str, scen: str) -> float:
    env = os.environ.copy()
    if opp in ("aggressive", "defensive"):
        env["ADVERSARY"] = opp
    else:
        env.pop("ADVERSARY", None)
    try:
        r = subprocess.run(
            ["python", "scripts/run_match.py",
             "--agent1", "examples/pursuit_chase_v1/pursuit_chase_btcost.yaml",
             "--agent2", opp, "--rounds", "1", "--max-steps", "1500",
             "--scenario", scen],
            capture_output=True, text=True, timeout=100, cwd=ROOT, env=env)
        out = r.stdout + r.stderr
        dmgs = re.findall(r"데미지 ([\d.]+) 가함", out)
        return float(dmgs[-1]) if len(dmgs) >= 2 else 0.0
    except Exception:
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply-only", action="store_true")
    ap.add_argument("--runs", type=int, default=3, help="verify runs per cell")
    args = ap.parse_args()

    if not BEST_PATH.exists():
        print(f"NO BEST: {BEST_PATH}")
        return
    best = json.load(open(BEST_PATH, encoding="utf-8"))
    v = best["variant"]
    print(f"=== Apply GA champion (score={best['score']}, gen={best['gen']}) ===")
    print(f"  variant: {v}")
    apply_variant(v)
    print(f"  Applied to {SELECTOR}")

    if args.apply_only:
        return

    # verify with runs
    print(f"\n=== Verify (runs={args.runs}) ===")
    OPPS = [("simple", 1.0), ("defensive", 2.0), ("aggressive", 2.0), ("ace", 1.5)]
    SCENS = ["bt_vs_bt", "tail_chase"]
    total = 0.0
    for opp, weight in OPPS:
        for scen in SCENS:
            dmgs = [run_match(opp, scen) for _ in range(args.runs)]
            avg = sum(dmgs) / len(dmgs)
            std = (sum((d-avg)**2 for d in dmgs)/len(dmgs))**0.5
            total += avg * weight
            print(f"  {opp:>10s}@{scen:<12s}: avg={avg:5.1f}  std={std:4.1f}  runs={dmgs}",
                  flush=True)
    print(f"\nTotal weighted: {total:.2f}")


if __name__ == "__main__":
    main()
