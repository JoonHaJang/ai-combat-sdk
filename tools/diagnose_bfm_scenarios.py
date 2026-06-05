"""1v1 BFM 시나리오 진단: 매치 데이터로 각 BFM 시나리오에서의 성공/실패 분류.

11가지 표준 BFM 시나리오 (T-45A ACMFP-03 / AETC TTP 11-1 기반):
  1. Head-On Merge (HOM) — both head-on (AA>150, ATA<30)
  2. Offensive Tail Chase — pos_adv>100, dist<5000, ata<30
  3. Offensive Lag — pos_adv>50, dist<5000, ata 30-80
  4. Offensive Lead/Cutoff — pos_adv>50, dist<5000, ata<30 + turn rate adv
  5. Defensive (on tail) — pos_adv<-100, dist<5000
  6. Defensive Spiral — defensive + dist<2000 + nose-low (alt 감소)
  7. Lufbery 1-circle — both turning into each other, similar speeds
  8. Lufbery 2-circle — both turning away, parallel circles
  9. Scissors Flat — post-overshoot, low speed reversal
  10. Scissors Rolling — post-overshoot, vertical reversal
  11. Neutral Extension — distance growing, both flying away

각 매치 → tick별 시나리오 분류 → outcome (dmg dealt/taken) 집계 → 시나리오별 W/L 매트릭스.

사용:
    python tools/diagnose_bfm_scenarios.py [--opps simple,defensive,...] [--runs 2]
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "logs/bfm_diagnose"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

OPPS = ["simple", "defensive", "aggressive", "ace",
        "adaptive_eagle_v6", "adaptive_eagle_v6h4", "adaptive_eagle_v7",
        "adaptive_eagle_v9", "adaptive_eagle_v10", "adaptive_eagle_v11_code",
        "adaptive_eagle_v51"]
SCENARIOS = ["bt_vs_bt", "tail_chase"]
MAX_STEPS = 1500


def classify_tick(obs: dict) -> str:
    """obs 1 tick → BFM scenario name."""
    aa = abs(float(obs.get("aa_deg", 0)))
    ata = abs(float(obs.get("ata_deg", 0)))
    dist = float(obs.get("distance_ft", 99999))
    closure = float(obs.get("closure_rate_kts", 0))
    rel_b = abs(float(obs.get("relative_bearing_deg", 0)))
    alt_gap = float(obs.get("alt_gap_ft", 0))
    # pos_adv proxy = aa - ata
    pos_adv = aa - ata
    # 1. Head-on Merge
    if aa > 150 and ata < 30 and dist > 2000:
        return "HOM"
    # 5/6. Defensive
    if pos_adv < -90 and dist < 5000:
        if dist < 2000 and alt_gap < -500:
            return "DefSpiral"
        return "Defensive"
    # 2/3/4. Offensive
    if pos_adv > 50 and dist < 5000:
        if ata < 25:
            return "Off_TailChase"
        if ata < 80:
            return "Off_Lag"
        return "Off_Lead"
    # 7/8. Lufbery
    if 60 < aa < 120 and 60 < ata < 120 and dist < 4000:
        if abs(rel_b - 90) < 40:
            return "Lufbery_1c"  # nose-to-nose
        return "Lufbery_2c"
    # 9/10. Scissors (post-overshoot, low speed, alt change)
    if dist < 2500 and abs(closure) < 50:
        if abs(alt_gap) > 500:
            return "Sciss_Roll"
        return "Sciss_Flat"
    # 11. Extension
    if dist > 5000 and closure < 0:
        return "Extension"
    # default
    return "Other"


def run_match_with_trace(opp: str, scen: str) -> dict:
    """1 매치 + branch CSV trace + outcome 분류."""
    env = os.environ.copy()
    env["BRANCH_CSV"] = str(RESULTS_DIR / f"trace_{opp}_{scen}.csv")
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
            capture_output=True, text=True, timeout=120, cwd=ROOT, env=env)
        out = r.stdout + r.stderr
        dmgs = re.findall(r"데미지 ([\d.]+) 가함", out)
        us_dmg = float(dmgs[-1]) if len(dmgs) >= 2 else 0.0
        opp_dmg = float(dmgs[0]) if len(dmgs) >= 1 else 0.0
        return {"us_dmg": us_dmg, "opp_dmg": opp_dmg, "ok": True}
    except Exception as e:
        return {"us_dmg": 0.0, "opp_dmg": 0.0, "ok": False, "err": str(e)}


def parse_trace_csv(path: Path) -> list:
    """BRANCH_CSV 의 tick별 (ata, aa, dist, closure, branch) 추출."""
    if not path.exists():
        return []
    rows = []
    try:
        import csv
        with open(path, encoding="utf-8") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                rows.append(row)
    except Exception:
        return []
    return rows


def aggregate(opp_subset, runs):
    """All-opp × all-scen × runs 진단 + 시나리오별 W/L 집계."""
    summary = defaultdict(lambda: {"n_ticks": 0, "matches": []})
    match_results = []
    for opp in opp_subset:
        for scen in SCENARIOS:
            for r in range(runs):
                print(f"  {opp:>30s} @{scen:<12s} run{r}...", flush=True)
                res = run_match_with_trace(opp, scen)
                trace = parse_trace_csv(RESULTS_DIR / f"trace_{opp}_{scen}.csv")
                # classify tick by tick
                scen_ticks = defaultdict(int)
                for tick in trace:
                    obs = {
                        "aa_deg": float(tick.get("aa", 0)),
                        "ata_deg": float(tick.get("ata", 0)),
                        "distance_ft": float(tick.get("dist", 99999)),
                        "closure_rate_kts": float(tick.get("closure", 0)),
                        "relative_bearing_deg": float(tick.get("rel_b", 0)),
                        "alt_gap_ft": float(tick.get("alt_gap", 0)),
                    }
                    s = classify_tick(obs)
                    scen_ticks[s] += 1
                match_results.append({
                    "opp": opp, "scen": scen, "run": r,
                    "us_dmg": res["us_dmg"], "opp_dmg": res["opp_dmg"],
                    "scen_ticks": dict(scen_ticks),
                    "outcome": "win" if res["us_dmg"] > res["opp_dmg"] + 5 else
                              ("loss" if res["opp_dmg"] > res["us_dmg"] + 5 else "draw")
                })
                # aggregate
                for s, n in scen_ticks.items():
                    summary[s]["n_ticks"] += n
    return match_results, dict(summary)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opps", type=str, default="")
    ap.add_argument("--runs", type=int, default=1)
    args = ap.parse_args()

    opp_subset = args.opps.split(",") if args.opps else OPPS
    print(f"=== BFM scenario diagnosis: {len(opp_subset)} opps × {len(SCENARIOS)} scens × {args.runs} runs ===")
    print(f"  opps: {opp_subset}")
    matches, scen_summary = aggregate(opp_subset, args.runs)

    # report per-scenario time spent + correlation with outcome
    print(f"\n=== Per-scenario tick distribution (across all matches) ===")
    total = sum(s["n_ticks"] for s in scen_summary.values())
    for s, info in sorted(scen_summary.items(), key=lambda x: -x[1]["n_ticks"]):
        pct = info["n_ticks"] / total * 100 if total else 0
        print(f"  {s:>15s}: {info['n_ticks']:>6} ticks ({pct:>5.1f}%)")

    # scenario × outcome (W/L/D) correlation
    sc_out = defaultdict(lambda: {"win": 0, "loss": 0, "draw": 0, "ticks": 0})
    for m in matches:
        for s, n in m["scen_ticks"].items():
            sc_out[s][m["outcome"]] += n
            sc_out[s]["ticks"] += n

    print(f"\n=== Scenario × outcome correlation ===")
    print(f"{'scenario':>15s} {'ticks':>7s} {'win%':>6s} {'loss%':>6s} {'draw%':>6s}")
    for s in sorted(sc_out.keys(), key=lambda x: -sc_out[x]["ticks"]):
        c = sc_out[s]
        t = c["ticks"] or 1
        print(f"  {s:>15s} {c['ticks']:>7d} "
              f"{c['win']/t*100:>5.1f}% {c['loss']/t*100:>5.1f}% {c['draw']/t*100:>5.1f}%")

    # 어떤 시나리오에서 LOSS 가 많은가?
    print(f"\n=== 실패 시나리오 (loss% 높은 순) ===")
    fail_rank = sorted(sc_out.items(), key=lambda x: -(x[1]["loss"]/(x[1]["ticks"] or 1)))
    for s, c in fail_rank[:8]:
        t = c["ticks"] or 1
        loss_pct = c["loss"] / t * 100
        if loss_pct > 20:
            print(f"  ❌ {s:>15s} loss% = {loss_pct:.1f} (ticks={c['ticks']})")

    # save
    out_path = RESULTS_DIR / f"diagnosis_{int(__import__('time').time())}.json"
    out_path.write_text(json.dumps({
        "matches": matches,
        "scenario_summary": scen_summary,
        "scenario_outcome": dict(sc_out),
    }, indent=2, ensure_ascii=False))
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
