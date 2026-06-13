"""E23 — 신규 tactic 검증: TIGHT_TURN(최소반경) / LEAD_TURN(머지 전환)이 머지를 닫나.

진단(A/C/C′): 기존 선회는 코너속도(max-rate=큰 반경) → 거리 20~33km 확장. 닫는 손(Lead Turn)·
최소반경 turn 부재가 1차 병목. 신규 V_RADIUS(260kt) 기반 TIGHT_TURN/LEAD_TURN 추가 → 강제 테스트.
판정: base/ONE_CIRCLE 대비 maxD 축소 + closure/격추 개선이면 능력 갭 확정 → action set 추가·재학습.
usage: python exp_e23_newtactics.py [duration_s]
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import warnings; warnings.filterwarnings("ignore")

from exp_e22_chaseforce import ForcePolicy, _opp, _metrics, RBASE as _R
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files
from exp_e7_champion import _train
from exp_e10_unified import DS_DA
import math

RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_newtactics")
MODES = [None, "LEAD_TURN"]   # 보완된 LEAD_TURN(조건부 속도) 재검증


def main(dur=220.0):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    os.makedirs(RBASE, exist_ok=True)
    opps = ["anchor_ace", "A3_LagAngler", "D2_LastDitch"]
    print(f"=== E23 신규 tactic(TIGHT_TURN/LEAD_TURN) 검증 {dur:.0f}s ===")
    print(f"{'opp':<14}{'forced':<14}{'결과':<6}{'dmg':>5}{'HP us:opp':>11}{'maxD(m)':>9}{'meanD':>7}{'코너%':>7}")
    for opp_name in opps:
        for mode in MODES:
            p1, p2 = spawn_adt_neutral()
            pol = ForcePolicy(rf, tac, forced=mode)
            m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                      control_hz=20, bt_hz=10, log_hz=60)
            res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=_opp(opp_name), duration_s=dur)
            mk = "격추" if res.health2 <= 0 else ("패" if res.health1 < res.health2
                 else ("판정" if res.health1 > res.health2 else "무"))
            lbl = mode or "base(RF)"
            rd = next_run_dir(RBASE, prefix=f"{opp_name}__{lbl}")
            acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
            write_acmi_plot(res.log, acmi, title=f"{opp_name}_{lbl}"); write_csv(res.log, csvp)
            try: analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=f"{opp_name}_{lbl}", make_plot=False)
            except Exception: pass
            maxd, meand, corner = _metrics(csvp)
            print(f"{opp_name:<14}{lbl:<14}{mk:<6}{res.damage_dealt1:>5.0f}"
                  f"{res.health1:>5.0f}:{res.health2:<5.0f}{maxd:>9.0f}{meand:>7.0f}{corner*100:>6.0f}%", flush=True)
        print(flush=True)
    print(f"replay: {os.path.relpath(RBASE)}", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(float(a[0]) if a else 220.0)
