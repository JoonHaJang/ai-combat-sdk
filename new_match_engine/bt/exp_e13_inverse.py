"""E13 — 역설계 단일 BT: champion base(t=0) + 25s에 기동형(롤 높음)→dagger 전환.

근거: champion 은 t=0부터면 nose-chaser dmg9(35s 핸드오프 dmg1). killable 은 ~25s 후 기동(롤↑).
→ champion 으로 시작해 nose-chaser 에 일찍 commit(dmg↑), 25s 에 롤 높으면 killable 로 보고 dagger
   전환(격추). 감지 윈도우 5~25s, 롤 std>THR 이면 maneuverer.

usage: python exp_e13_inverse.py [roll_thr]
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
from exp_e6_winrate import _opps
from exp_e7_champion import _train
from tree_policy import TreePolicy
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files

DS_DA = os.path.join(os.path.dirname(__file__), "..", "results_research_dagger.npz")
RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_inverse")


def _hca(o): return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)


class InversePol:
    DET_START, DET_END = 5.0, 25.0

    def __init__(self, rf, tac, roll_thr=22.0):
        self.rf, self.tac = rf, tac; self.roll_thr = roll_thr
        self.t = 0.0; self.dt = 0.1; self.use_dagger = False; self.decided = False; self.phi = []
        self.champ = TreePolicy()

    def select(self, p1, p2):
        o = compute_obs(p1, p2); self.t += self.dt
        champ_tac = self.champ.select(p1, p2)         # base = champion (t=0부터)
        if o.ego_alt_ft < 2500.0: return Tactic.CLIMB
        if self.DET_START <= self.t <= self.DET_END: self.phi.append(o.enm_phi_deg)
        if (not self.decided) and self.t > self.DET_END:
            self.decided = True
            if len(self.phi) > 5 and statistics.pstdev(self.phi) > self.roll_thr:
                self.use_dagger = True                 # 기동형 = killable → dagger 전환
        if not self.use_dagger:
            return champ_tac                           # nose-chaser → champion 유지
        x = [[o.ata_deg, o.aa_deg, _hca(o), o.distance_ft, o.closure_kts,
              _es_diff(o), o.ego_r_dps, o.enm_r_dps]]
        return Tactic[self.tac[int(self.rf.predict(x)[0].argmax())]]


def main(roll_thr=22.0):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    opps = _opps(); os.makedirs(RBASE, exist_ok=True)
    print(f"=== E13 역설계 BT (champion base + 25s 롤>{roll_thr:.0f}→dagger) 적 {len(opps)} 300s ===\n")
    wins = real = kills = 0; cells = []
    for on, ofn in opps.items():
        p1, p2 = spawn_adt_neutral(); pol = InversePol(rf, tac, roll_thr)
        m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                  control_hz=20, bt_hz=10, log_hz=60)
        res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=ofn, duration_s=300.0)
        win = (res.winner == "agent1") or (res.winner == "draw" and res.health1 > res.health2)
        wins += int(win); kills += int(res.health2 <= 0)
        real += int(res.health2 <= 0 or res.damage_dealt1 >= 40)
        mk = "W" if res.winner == "agent1" else ("L" if res.winner == "agent2" else ("w" if res.health1 > res.health2 else "d"))
        cells.append(f"{on.split('_')[-1][:4]}:{mk}({res.damage_dealt1:.0f}/{res.health2:.0f})")
        rd = next_run_dir(RBASE, prefix=f"inverse__{on}")
        acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
        write_acmi_plot(res.log, acmi, title=f"inverse_{on}"); write_csv(res.log, csvp)
        try: analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=f"inverse_{on}", make_plot=True)
        except Exception: pass
        print(f"  {on:<18} {mk} dmg={res.damage_dealt1:.0f} HP {res.health1:.0f}:{res.health2:.0f} "
              f"dagger={pol.use_dagger}", flush=True)
    print(f"\n  역설계 BT: 판정 {wins}/8, 실력 {real}/8, 격추 {kills}  | {' '.join(cells)}")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 22.0)
