"""E22 (실험 C') — 진짜 chase/turn tactic 을 강제하면 무승부가 닫히나 (가치 myopia vs 실행한계 판별).

C(e20)는 ADAPTIVE(lag=뒤 겨눔)만 봐서 사용자 가설("코너 풀선회 *추격*")을 검증 못 함.
여기선 적을 *겨누는/도는* tactic 을 전 구간 강제: PURE_PURSUIT, LEAD_PURSUIT, ONE_CIRCLE, TWO_CIRCLE, GUN_TRACK.
- 어느 하나라도 무승부(A3/D2)를 닫으면 → 정책은 *이길 수 있는데 과소평가* = 가치 myopia → #2(horizon) 정답.
- 전부 못 닫으면 → 유도/제어 실행한계 → guidance/turn-rate 먼저.
지표(위치/속도 기반, angle-bug 무관): outcome, dmg, HP, maxD, meanD, 코너%.
usage: python exp_e22_chaseforce.py [duration_s]
"""
from __future__ import annotations
import sys, os, math, csv, warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from opponents import OPPONENT_BTS
from yaml_bt import load_bt
from obs import compute_obs
from tactic import Tactic, V_CORNER_KTS
from real_rollout import _es_diff
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files
from exp_e7_champion import _train
from exp_e10_unified import DS_DA
import glob

ZOO = os.path.join(os.path.dirname(__file__), "..", "opponents", "zoo")
RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_chaseforce")
SAFE = 2500.0
FORCE = ["PURE_PURSUIT", "LEAD_PURSUIT", "ONE_CIRCLE", "TWO_CIRCLE", "GUN_TRACK"]


def _hca(o): return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)


class ForcePolicy:
    """forced=None → RF argmax(기본). forced='PURE_PURSUIT' 등 → 전 구간 그 tactic 강제(+안전상승)."""
    def __init__(self, rf, tac, forced=None, bt_hz=10.0):
        self.rf, self.tac, self.forced = rf, tac, forced

    def select(self, p1, p2) -> Tactic:
        o = compute_obs(p1, p2)
        if o.ego_alt_ft < SAFE:
            return Tactic.CLIMB
        if self.forced is not None:
            return Tactic[self.forced]
        x = [[o.ata_deg, o.aa_deg, _hca(o), o.distance_ft, o.closure_kts,
              _es_diff(o), o.ego_r_dps, o.enm_r_dps]]
        return Tactic[self.tac[int(self.rf.predict(x)[0].argmax())]]


def _opp(name):
    if name.startswith("anchor_"):
        return OPPONENT_BTS[name.split("_", 1)[1]]
    fs = sorted(glob.glob(os.path.join(ZOO, name + "_*.yaml")))
    return load_bt(fs[len(fs) // 2])


def _metrics(csvp):
    rows = list(csv.reader(open(csvp))); h = rows[0]; d = rows[1:]
    iv, idi = h.index("vc1"), h.index("dist")
    dists = [float(r[idi]) for r in d]; vcs = [float(r[iv]) for r in d]
    corner = sum(1 for v in vcs if abs(v - V_CORNER_KTS) <= 30.0) / max(1, len(vcs))
    return max(dists), sum(dists) / len(dists), corner


def main(dur=220.0):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    os.makedirs(RBASE, exist_ok=True)
    opps = ["anchor_ace", "A3_LagAngler", "D2_LastDitch"]
    modes = [None] + FORCE
    print(f"=== E22 chase/turn 강제 실험 {dur:.0f}s ===")
    print(f"{'opp':<14}{'forced':<16}{'결과':<6}{'dmg':>5}{'HP us:opp':>11}{'maxD(m)':>9}{'meanD':>7}{'코너%':>7}")
    for opp_name in opps:
        for mode in modes:
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
            print(f"{opp_name:<14}{lbl:<16}{mk:<6}{res.damage_dealt1:>5.0f}"
                  f"{res.health1:>5.0f}:{res.health2:<5.0f}{maxd:>9.0f}{meand:>7.0f}{corner*100:>6.0f}%", flush=True)
        print(flush=True)
    print(f"replay: {os.path.relpath(RBASE)}", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(float(a[0]) if a else 220.0)
