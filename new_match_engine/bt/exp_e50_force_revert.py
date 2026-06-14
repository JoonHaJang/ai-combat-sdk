"""E50 — 마지막 16/17 시도: t=0부터 강제(A3 변환 위해) + t=50 분류해 *승자만 base 복귀*.

E49: 분류는 t=50라야 깨끗, A3 변환은 t=0 강제 필요(양립불가). 우회: 처음부터 forced merge(A3 변환) →
t=50에 형상분류 → 승자(base형)면 base로 복귀(50s 강제는 회복 가능 가설), A3/D2면 강제 유지.
적BT 결정론이라 강제 하에서도 형상 분류 가능 가설. 검증=전 17. usage: NME_TCLASS=50 python exp_e50_force_revert.py [dur]
"""
from __future__ import annotations
import sys, os, math, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))

from exp_e22_chaseforce import _opp
from exp_e27_adaptive_subset import AdaptivePolicy
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from obs import compute_obs
from tactic import Tactic as T
from exp_e7_champion import _train
from exp_e10_unified import DS_DA

FULL = ["anchor_simple", "anchor_aggressive", "anchor_defensive", "anchor_ace",
        "A1_PurePursuer", "A2_GunTracker", "A3_LagAngler", "B1_EnergyFighter", "B2_Extender",
        "C1_TwoCircleRate", "C2_OneCircleRad", "C3_Lufbery", "D1_Reactive", "D2_LastDitch",
        "D3_Scissors", "E1_AdaptiveAce", "E2_Passive"]
WEZ = 3000.0
T_CLASS = float(os.environ.get("NME_TCLASS", "50.0"))


class ForceRevertPolicy:
    def __init__(self, rf, tac):
        self.base = AdaptivePolicy(rf, tac, corrections=True)
        self.t = 0.0; self.rmin = 9e9; self.aa_min = 999.0; self.typ = None; self.ph = 0
    def select(self, p1, p2):
        o = compute_obs(p1, p2); self.t += 0.1
        if o.ego_alt_ft < 2500: return T.CLIMB
        if self.t <= T_CLASS:
            self.rmin = min(self.rmin, o.distance_ft); self.aa_min = min(self.aa_min, o.aa_deg)
        if self.typ is None and self.t > T_CLASS:
            reopen = o.distance_ft - self.rmin
            self.typ = "A3" if reopen < 3000.0 else ("D2" if (self.aa_min > 30 and self.rmin > 3000) else "base")
        if self.typ == "base":                               # 승자 → base 복귀
            return self.base.select(p1, p2)
        # 강제 단계(t<50 모두 + A3/D2 확정 후): forced merge
        if self.ph == 0 and o.distance_ft < WEZ: self.ph = 1
        if self.ph == 1 and o.distance_ft > WEZ * 1.8: self.ph = 0
        return T.GUN_TRACK if self.ph == 1 else T.LEAD_PURSUIT


def main(dur=240.0):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    print(f"=== E50 force-revert (Tclass={T_CLASS:.0f}) {dur:.0f}s ===", flush=True)
    ng = 0
    for opp in FULL:
        p1, p2 = spawn_adt_neutral(); pol = ForceRevertPolicy(rf, tac)
        m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10), control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
        r = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=lambda o, opp=opp: _opp(opp)(compute_obs(p2, p1)), duration_s=dur)
        mk = "격" if r.health2 <= 0 else ("승" if r.health1 > r.health2 else ("패" if r.health1 < r.health2 else "무"))
        if mk in "격승": ng += 1
        print(f"{opp:<18}{mk}({r.damage_dealt1:.0f})  유형={pol.typ}", flush=True)
    print(f"\nforce-revert 승{ng}/17", flush=True)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 240.0)
