"""E35 — narrow lagger-게이트 환류 검증 (★ replay 必, [[feedback-replays-mandatory]]).

모든 매치 = .acmi + report.txt + plot.png 저장 + 우리 문제 특화 해석(WEZ dwell·에너지·figure-8) 추출.
base vs ADAPTIVE(narrow lagger): ace/B1/C2 base-승리 보존 + A3 lever 효과(WEZ dwell↑) + D2.
usage: python exp_e35_lagger_verify.py [dur]
"""
from __future__ import annotations
import sys, os, math, warnings, re
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))

from exp_e27_adaptive_subset import AdaptivePolicy
from exp_e22_chaseforce import _opp
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files
from exp_e7_champion import _train
from exp_e10_unified import DS_DA

RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_lagger")
OPPS = ["anchor_ace", "B1_EnergyFighter", "C2_OneCircleRad", "A3_LagAngler", "D2_LastDitch"]


def _report_metrics(rep):
    """report.txt에서 우리 문제 특화 지표 추출."""
    t = open(rep, encoding="utf-8", errors="ignore").read() if os.path.exists(rep) else ""
    def g(pat, d="?"):
        m = re.search(pat, t); return m.group(1) if m else d
    return {
        "outcome": g(r"outcome=(\w+)"),
        "wez_n": g(r"WEZ\(us\):\s*(\d+)회"),
        "dwell": g(r"dwell=([\d.]+)s"),
        "mindist": g(r"min=(\d+)m"),
        "pattern": g(r"pattern=([\w'_]+)"),
        "es_us": g(r"Es us=(-?\d+)"),
        "es_op": g(r"opp=(-?\d+)"),
    }


def main(dur=200.0):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    os.makedirs(RBASE, exist_ok=True)
    print(f"=== E35 narrow lagger 환류 검증 (replay 저장) {dur:.0f}s ===")
    print(f"{'opp':<16}{'mode':<10}{'결과':<6}{'dmg':>4}{'WEZ회':>6}{'dwell':>7}{'minD':>7}{'lag%':>6}{'pattern':<22}")
    for opp_name in OPPS:
        for mode in ["base", "ADAPTIVE"]:
            p1, p2 = spawn_adt_neutral()
            pol = AdaptivePolicy(rf, tac, corrections=(mode == "ADAPTIVE"))
            m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                      control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
            res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=_opp(opp_name), duration_s=dur)
            mk = "격추" if res.health2 <= 0 else ("판정" if res.health1 > res.health2 else "무")
            rd = next_run_dir(RBASE, prefix=f"{opp_name}__{mode}")
            acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
            # ★ replay 必: acmi + csv + report + plot
            write_acmi_plot(res.log, acmi, title=f"{opp_name}_{mode}"); write_csv(res.log, csvp)
            try: analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=f"{opp_name}_{mode}", make_plot=True)
            except Exception: pass
            mtr = _report_metrics(os.path.join(rd, "report.txt"))
            lagp = f"{100*pol.fire_lag/max(1,pol.tot):.0f}%" if mode == "ADAPTIVE" else "-"
            print(f"{opp_name:<16}{mode:<10}{mk:<6}{res.damage_dealt1:>4.0f}"
                  f"{mtr['wez_n']:>6}{mtr['dwell']+'s':>7}{mtr['mindist']+'m':>7}{lagp:>6}  {mtr['pattern']:<22}", flush=True)
        print(flush=True)
    print(f"replay+report+plot: {os.path.relpath(RBASE)}", flush=True)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 200.0)
