"""E20 (실험 C) — 초반 머지에 코너+lead(ADAPTIVE) 강제 시 거리확장/closure가 개선되나.

가설: 기본 RF 가치정책이 머지에서 VERTICAL/TWO_CIRCLE를 골라 코너 미달·거리 12~13km 확장 → closure 실패.
초반만 ADAPTIVE(코너속도 lag + lead-collision 블렌딩) 강제하면 머지가 타이트해지고 닫기가 빨라질 것.

3 arm × 3 적(격추 anchor_ace, 무승부 A3_LagAngler/D2_LastDitch):
  base      : RF argmax + 안전상승 (detector 없음 = 순수 가치, 무승부 재현 기준선)
  force45   : t<45s ADAPTIVE 강제, 이후 RF argmax
  pure_adapt: 전 구간 ADAPTIVE (코너+lead 상한 참조)
지표(전부 위치/속도 기반 = angle-bug 무관): outcome, dmg, HP, max_dist, mean_dist, 코너±30kt%.
usage: python exp_e20_forcemerge.py [duration_s]
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
RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_forcemerge")
SAFE = 2500.0


def _hca(o): return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)


class MergePolicy:
    """RF argmax 기본. mode='base'|'force45'|'pure_adapt'."""
    def __init__(self, rf, tac, mode="base", t_force=45.0, bt_hz=10.0):
        self.rf, self.tac, self.mode = rf, tac, mode
        self.t = 0.0; self.dt = 1.0 / bt_hz; self.t_force = t_force

    def select(self, p1, p2) -> Tactic:
        o = compute_obs(p1, p2); self.t += self.dt
        if o.ego_alt_ft < SAFE:
            return Tactic.CLIMB
        if self.mode == "pure_adapt" or (self.mode == "force45" and self.t < self.t_force):
            return Tactic.ADAPTIVE
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


def main(dur=250.0):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    os.makedirs(RBASE, exist_ok=True)
    opps = ["anchor_ace", "A3_LagAngler", "D2_LastDitch"]
    modes = ["base", "force45", "pure_adapt"]
    print(f"=== E20 force-merge 실험 (코너+lead 강제) {dur:.0f}s ===")
    print(f"{'opp':<14}{'mode':<11}{'결과':<6}{'dmg':>5}{'HP us:opp':>11}{'maxD(m)':>9}{'meanD':>7}{'코너%':>7}")
    for opp_name in opps:
        for mode in modes:
            p1, p2 = spawn_adt_neutral(); opp_fn = _opp(opp_name)
            pol = MergePolicy(rf, tac, mode=mode)
            m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                      control_hz=20, bt_hz=10, log_hz=60)
            res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=opp_fn, duration_s=dur)
            mk = "격추" if res.health2 <= 0 else ("패" if res.health1 < res.health2
                 else ("판정" if res.health1 > res.health2 else "무"))
            rd = next_run_dir(RBASE, prefix=f"{opp_name}__{mode}")
            acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
            write_acmi_plot(res.log, acmi, title=f"{opp_name}_{mode}"); write_csv(res.log, csvp)
            try: analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=f"{opp_name}_{mode}", make_plot=False)
            except Exception: pass
            maxd, meand, corner = _metrics(csvp)
            print(f"{opp_name:<14}{mode:<11}{mk:<6}{res.damage_dealt1:>5.0f}"
                  f"{res.health1:>5.0f}:{res.health2:<5.0f}{maxd:>9.0f}{meand:>7.0f}{corner*100:>6.0f}%", flush=True)
        print(flush=True)
    print(f"replay: {os.path.relpath(RBASE)}", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(float(a[0]) if a else 250.0)
