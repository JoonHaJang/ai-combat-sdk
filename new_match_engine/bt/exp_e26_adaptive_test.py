"""E26 (Step B) — 새 관측-차 반응형 ADAPTIVE 검증 (튜닝 INDI 위).

guidance._adaptive를 5상황 relational 블렌딩으로 교체. force ADAPTIVE 전구간 vs base RF.
controller=indi(C3 튜닝). 판정: 격추적(ace/B2/C2) 회귀 없이 + 무승부(A3/D2) 개선되나.
usage: python exp_e26_adaptive_test.py [duration_s] [controller]
"""
from __future__ import annotations
import sys, os, math, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))

from exp_e22_chaseforce import ForcePolicy, _opp, _metrics
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files
from exp_e7_champion import _train
from exp_e10_unified import DS_DA

RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_adaptive")
OPPS = ["anchor_ace", "B2_Extender", "C2_OneCircleRad", "A3_LagAngler", "D2_LastDitch"]


def main(dur=220.0, controller="indi"):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    os.makedirs(RBASE, exist_ok=True)
    print(f"=== E26 새 ADAPTIVE vs base [controller={controller}] {dur:.0f}s ===")
    print(f"{'opp':<16}{'mode':<10}{'결과':<6}{'dmg':>5}{'HP us:opp':>11}{'maxD(m)':>9}")
    for opp_name in OPPS:
        for mode in [None, "ADAPTIVE"]:
            p1, p2 = spawn_adt_neutral(); pol = ForcePolicy(rf, tac, forced=mode)
            m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                      control_hz=20, bt_hz=10, log_hz=60,
                      controller1=controller, controller2="lqr")
            res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=_opp(opp_name), duration_s=dur)
            mk = "격추" if res.health2 <= 0 else ("패" if res.health1 < res.health2
                 else ("판정" if res.health1 > res.health2 else "무"))
            lbl = mode or "base(RF)"
            rd = next_run_dir(RBASE, prefix=f"{opp_name}__{lbl}")
            acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
            write_acmi_plot(res.log, acmi, title=f"{opp_name}_{lbl}"); write_csv(res.log, csvp)
            try: analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=f"{opp_name}_{lbl}", make_plot=False)
            except Exception: pass
            maxd, _, _ = _metrics(csvp)
            print(f"{opp_name:<16}{lbl:<10}{mk:<6}{res.damage_dealt1:>5.0f}"
                  f"{res.health1:>5.0f}:{res.health2:<5.0f}{maxd:>9.0f}", flush=True)
        print(flush=True)
    print(f"replay: {os.path.relpath(RBASE)}", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(float(a[0]) if a else 220.0, a[1] if len(a) > 1 else "indi")
