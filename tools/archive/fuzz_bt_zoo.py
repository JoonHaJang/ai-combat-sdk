"""BT-zoo head-to-head: our agent vs ALL adaptive_eagle 변종 + base opps.

목적: 사용자 명령 (2026-05-27) — "현재 폴더에 존재하는 수많은 BT들이 존재하잖아? 각각의 BT들과,
우리 BT 그리고 서로 교전 시켜서, 정보를 도출해 낼까? 우리가 놓치는 포인트가 존재해"

이 도구는 cost_branch_selector.py 를 *수정하지 않음* — pure measurement.
GA fuzz 가 끝나고 best variant 적용 후 실행하면, broader coverage 의 health check.

사용:
    python tools/fuzz_bt_zoo.py --scenarios bt_vs_bt,tail_chase --runs 1
"""
import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "logs/fuzz_bt_zoo"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# 14 adaptive_eagle + 4 base
ALL_OPPS = [
    # base
    "simple", "defensive", "aggressive", "ace",
    # adaptive_eagle series
    "adaptive_eagle_v6",
    "adaptive_eagle_v6h2",
    "adaptive_eagle_v6h4",
    "adaptive_eagle_v6h5a", "adaptive_eagle_v6h5b", "adaptive_eagle_v6h5c",
    "adaptive_eagle_v6h_e1", "adaptive_eagle_v6h_e1b",
    "adaptive_eagle_v6h_e1c", "adaptive_eagle_v6h_e1d",
    "adaptive_eagle_v7", "adaptive_eagle_v8",
    "adaptive_eagle_v9", "adaptive_eagle_v10",
    "adaptive_eagle_v11_code",
    "adaptive_eagle_v51",
]
SCENARIOS = ["bt_vs_bt", "tail_chase_us_attack", "tail_chase_us_defend"]  # R15 (2026-05-29): tail_chase side switch 발견 후 분리. 우리 항상 추격/도주 deterministic.
MAX_STEPS = 1500
TIMEOUT = 100


def run_match(opp: str, scen: str) -> dict:
    """{us_dmg_dealt, us_hp_left} via re-parse stdout."""
    env = os.environ.copy()
    if opp in ("aggressive", "defensive"):
        env["ADVERSARY"] = opp
    else:
        env.pop("ADVERSARY", None)
    try:
        r = subprocess.run(
            ["python", "scripts/run_match.py",
             "--agent1", "examples/pursuit_chase_v1/pursuit_chase_btcost.yaml",
             "--agent2", opp, "--rounds", "1", "--max-steps", str(MAX_STEPS),
             "--scenario", scen],
            capture_output=True, text=True, timeout=TIMEOUT, cwd=ROOT, env=env)
        out = r.stdout + r.stderr
        # 데미지 X 가함 — 마지막 = opp 한테 가한 dmg (= 우리 dmg dealt)
        dmgs = re.findall(r"데미지 ([\d.]+) 가함", out)
        us_dmg = float(dmgs[-1]) if len(dmgs) >= 2 else 0.0
        opp_dmg = float(dmgs[0]) if len(dmgs) >= 1 else 0.0
        # 승리/패배 키워드
        win = "승리" in out or "WIN" in out.upper()
        loss = "패배" in out
        return {"us_dmg": us_dmg, "opp_dmg": opp_dmg, "win": win, "loss": loss}
    except Exception as e:
        return {"us_dmg": 0.0, "opp_dmg": 0.0, "win": False, "loss": False, "err": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=str, default="bt_vs_bt,tail_chase_us_attack,tail_chase_us_defend")
    ap.add_argument("--opps", type=str, default="",
                    help="comma subset (default = all 18)")
    ap.add_argument("--runs", type=int, default=1)
    args = ap.parse_args()

    scens = args.scenarios.split(",")
    if args.opps:
        opps = [o for o in args.opps.split(",") if o]
    else:
        opps = ALL_OPPS

    print(f"=== BT-zoo head-to-head: {len(opps)} opps × {len(scens)} scens × {args.runs} runs ===", flush=True)
    print(f"  opps: {opps}", flush=True)
    print(f"  scens: {scens}", flush=True)

    results = {}
    t_start = time.time()
    for opp in opps:
        results[opp] = {}
        for scen in scens:
            dmgs = []
            opp_dmgs = []
            for r in range(args.runs):
                t0 = time.time()
                rr = run_match(opp, scen)
                dt = time.time() - t0
                dmgs.append(rr["us_dmg"])
                opp_dmgs.append(rr["opp_dmg"])
                print(f"  {opp:>30s}@{scen:<12s} run{r}: "
                      f"us={rr['us_dmg']:>6.1f}  opp={rr['opp_dmg']:>6.1f}  ({dt:.1f}s)",
                      flush=True)
            avg_us = sum(dmgs) / len(dmgs)
            avg_opp = sum(opp_dmgs) / len(opp_dmgs)
            results[opp][scen] = {
                "us_dmg_avg": round(avg_us, 2),
                "opp_dmg_avg": round(avg_opp, 2),
                "us_runs": dmgs, "opp_runs": opp_dmgs,
                "delta": round(avg_us - avg_opp, 2),
            }
        # per-opp summary
        total_us = sum(results[opp][s]["us_dmg_avg"] for s in scens)
        total_opp = sum(results[opp][s]["opp_dmg_avg"] for s in scens)
        print(f"  {opp:>30s} TOTAL: us={total_us:.1f}  opp={total_opp:.1f}  Δ={total_us-total_opp:+.1f}",
              flush=True)

    out = RESULTS_DIR / f"bt_zoo_{int(time.time())}.json"
    out.write_text(json.dumps({"opps": opps, "scens": scens,
                               "runs": args.runs, "results": results},
                              indent=2, ensure_ascii=False))
    print(f"\n=== DONE in {time.time()-t_start:.0f}s ===", flush=True)
    print(f"Saved: {out}", flush=True)

    # ranking
    print(f"\n--- Ranking by total delta (us_dmg - opp_dmg) ---")
    ranked = []
    for opp in opps:
        total_d = sum(results[opp][s]["delta"] for s in scens)
        total_u = sum(results[opp][s]["us_dmg_avg"] for s in scens)
        ranked.append((opp, total_d, total_u))
    ranked.sort(key=lambda x: -x[1])
    for opp, d, u in ranked:
        marker = "✅" if d > 10 else ("⚠️" if d > -10 else "❌")
        print(f"  {marker}  {opp:>30s}  Δ={d:+7.1f}  us_total={u:6.1f}", flush=True)


if __name__ == "__main__":
    main()
