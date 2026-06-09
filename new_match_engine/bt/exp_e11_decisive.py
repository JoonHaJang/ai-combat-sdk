"""E11 — nose-chaser 를 더 강하게(decisive) 이기기. fallback 모드 sweep (GunTracker, aggressive).

현재 champion fallback 은 적을 하드덱으로 몰아 thin HP승(dmg 1). 더 강한 승(데미지/격추)을 위해
fallback 거동 후보를 비교:
  - champion: 현재(TreePolicy)
  - two_circle: 선회율 압박만
  - gun_convert: 선회율로 적 소진 + 에너지우위·정렬 시 GUN_TRACK 전환
  - yoyo_convert: 에너지우위 시 HIGH_YOYO(수직 우위) → 근접·정렬 시 GUN_TRACK

35s 이른 감지(적 롤 std<18)는 동일. 적 2종 × 300s.

usage: python exp_e11_decisive.py
"""
from __future__ import annotations
import sys, os, math, statistics
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from obs import compute_obs
from tactic import Tactic, WEZ_ATA_DEG, WEZ_MIN_FT, WEZ_MAX_FT
from real_rollout import _es_diff
from opponents import OPPONENT_BTS
from exp_e7_champion import _train, DS_H60
from tree_policy import TreePolicy
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files

DS_DA = os.path.join(os.path.dirname(__file__), "..", "results_research_dagger.npz")
RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_decisive")


def _hca(o): return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)
def _in_wez(o): return o.ata_deg < WEZ_ATA_DEG and WEZ_MIN_FT <= o.distance_ft <= WEZ_MAX_FT


class Pol:
    def __init__(self, rf, tac, mode):
        self.rf, self.tac, self.mode = rf, tac, mode
        self.t = 0.0; self.dt = 0.1; self.latch = False; self.decided = False; self.phi = []
        self.champ = TreePolicy()

    def _fallback(self, o):
        es = _es_diff(o)                          # us - opp
        if self.mode == "champion":
            return None                            # champ_tac 사용
        if self.mode == "two_circle":
            return Tactic.TWO_CIRCLE
        if self.mode == "gun_convert":
            if o.distance_ft < 2800 and o.ata_deg < 40: return Tactic.GUN_TRACK
            if es > 1500 and o.ata_deg < 55:       return Tactic.GUN_TRACK
            return Tactic.TWO_CIRCLE
        if self.mode == "yoyo_convert":
            if o.distance_ft < 2500 and o.ata_deg < 35: return Tactic.GUN_TRACK
            if es > 2000:                          return Tactic.HIGH_YOYO   # 수직 우위
            return Tactic.TWO_CIRCLE
        return Tactic.TWO_CIRCLE

    def select(self, p1, p2):
        o = compute_obs(p1, p2); self.t += self.dt
        champ_tac = self.champ.select(p1, p2)
        if o.ego_alt_ft < 2500.0: return Tactic.CLIMB
        if 10.0 <= self.t <= 35.0: self.phi.append(o.enm_phi_deg)
        if (not self.decided) and self.t > 35.0:
            self.decided = True
            if len(self.phi) > 5 and statistics.pstdev(self.phi) < 18.0: self.latch = True
        if self.latch:
            fb = self._fallback(o)
            return champ_tac if fb is None else fb
        x = [[o.ata_deg, o.aa_deg, _hca(o), o.distance_ft, o.closure_kts,
              _es_diff(o), o.ego_r_dps, o.enm_r_dps]]
        return Tactic[self.tac[int(self.rf.predict(x)[0].argmax())]]


def main():
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    opps = {"GunTracker": OPPONENT_BTS["aggressive"], "aggressive": OPPONENT_BTS["aggressive"]}
    # 실제 GunTracker yaml + aggressive 앵커
    import glob
    from yaml_bt import load_bt
    gt = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "opponents", "zoo", "A2_GunTracker_*.yaml")))
    opps = {"GunTracker": load_bt(gt[len(gt)//2]), "aggressive": OPPONENT_BTS["aggressive"]}
    os.makedirs(RBASE, exist_ok=True)
    print("=== E11 nose-chaser decisive sweep (300s) ===")
    print(f"  {'mode':<14}{'GunTracker':>22}{'aggressive':>22}")
    for mode in ["champion", "two_circle", "gun_convert", "yoyo_convert"]:
        cells = []
        for on, ofn in opps.items():
            p1, p2 = spawn_adt_neutral(); pol = Pol(rf, tac, mode)
            m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                      control_hz=20, bt_hz=10, log_hz=60)
            res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=ofn, duration_s=300.0)
            mk = "W" if res.winner == "agent1" else ("L" if res.winner == "agent2" else ("w" if res.health1 > res.health2 else "d"))
            cells.append(f"{mk} dmg{res.damage_dealt1:.0f} HP{res.health1:.0f}:{res.health2:.0f}")
            rd = next_run_dir(RBASE, prefix=f"{mode}__{on}")
            acmi = os.path.join(rd, "match.acmi"); write_acmi_plot(res.log, acmi, title=f"{mode}_{on}")
            write_csv(res.log, os.path.join(rd, "match.csv"))
        print(f"  {mode:<14}{cells[0]:>22}{cells[1]:>22}", flush=True)
    print(f"\n  replay: {os.path.relpath(RBASE)}")


if __name__ == "__main__":
    main()
