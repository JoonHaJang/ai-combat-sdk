"""E46 — A3 승리 안착: *one-shot* 형상 판별로 A3에만 강제 merge. 패널 보존 + A3 무→승.

연속 게이트 6번 실패=도그파이트 진동에 다 걸림. one-shot(t=T_CHECK 한 번만) 판별로 회피:
  t=T_CHECK에 (3000 < rmin_so_far < 6000) ∧ (현재거리 > 3000) = 'A3 lagger standoff'
  (3000-6000까지 접근했지만 WEZ 못뚫고 아직 밖). simple/agg=WEZ뚫음(<3000)제외, 느린승자=아직멈(>6000)제외.
  → A3에만 래치 → forced merge(LEAD→GUN). D2도 켜지나 deferred(무 유지 무해). 검증=전 패널.
usage: python exp_e46_a3_oneshot.py [dur]
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
from tactic import Tactic
from exp_e7_champion import _train
from exp_e10_unified import DS_DA

T = Tactic
PANEL = ["anchor_simple", "anchor_aggressive", "anchor_defensive", "anchor_ace",
         "B1_EnergyFighter", "B2_Extender", "C2_OneCircleRad", "C3_Lufbery",
         "A3_LagAngler", "D2_LastDitch"]
SAFE = 2500.0
WEZ_MAX = 3000.0
FORCING = {"LEAD_GUN": (T.LEAD_PURSUIT, T.GUN_TRACK),
           "LDR_PURE": (T.LAG_DISPLACEMENT_ROLL, T.PURE_PURSUIT)}


class OneShotPolicy:
    """ADAPTIVE base + one-shot A3-standoff 판별. t=T_CHECK에 한 번 판정 후 래치."""
    def __init__(self, rf, tac, T_CHECK=55.0, RLO=3000.0, RHI=6000.0, forcing="LEAD_GUN", gated=True):
        self.base = AdaptivePolicy(rf, tac, corrections=True)
        self.T_CHECK, self.RLO, self.RHI, self.gated = T_CHECK, RLO, RHI, gated
        self.close_t, self.align_t = FORCING[forcing]
        self.rmin = 9e9; self.t = 0.0; self.checked = False; self.phase = 0; self.fired = 0

    def select(self, p1, p2) -> Tactic:
        o = compute_obs(p1, p2); self.t += 0.1
        if o.ego_alt_ft < SAFE:
            return Tactic.CLIMB
        self.rmin = min(self.rmin, o.distance_ft)
        if not self.gated:
            return self.base.select(p1, p2)
        # ── one-shot 판별: T_CHECK에 한 번. 접근(3000-6000)했지만 WEZ 못뚫고 밖 = A3 standoff ──
        if not self.checked and self.t >= self.T_CHECK:
            self.checked = True
            if self.RLO < self.rmin < self.RHI and o.distance_ft > WEZ_MAX:
                self.phase = 1                                    # 강제 merge 래치(영구)
        if self.phase >= 1:
            self.fired += 1
            if self.phase == 1 and o.distance_ft < WEZ_MAX:
                self.phase = 2
            if self.phase == 2 and o.distance_ft > WEZ_MAX * 1.8:
                self.phase = 1
            return self.align_t if self.phase == 2 else self.close_t
        return self.base.select(p1, p2)


def run_one(kw, opp_name, gs, cfg, rf, tac, dur):
    p1, p2 = spawn_adt_neutral()
    pol = OneShotPolicy(rf, tac, **kw)
    m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
              control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
    res = m.run(tactic_fn1=lambda o: pol.select(p1, p2),
                tactic_fn2=lambda o: _opp(opp_name)(compute_obs(p2, p1)), duration_s=dur)
    if res.health2 <= 0: mk = "K"
    elif res.health1 > res.health2: mk = "W"
    elif res.health1 < res.health2: mk = "L"
    else: mk = "-"
    return mk, res.damage_dealt1, pol.fired


def main(dur=200.0):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    CONFIGS = [
        dict(T_CHECK=55, forcing="LEAD_GUN"),
        dict(T_CHECK=50, forcing="LEAD_GUN"),
        dict(T_CHECK=55, forcing="LDR_PURE"),
    ]
    print(f"=== E46 A3 one-shot 안착 {dur:.0f}s (K격추 W판정 L패 -무, *=발동) ===", flush=True)
    for kw in CONFIGS:
        tg = {"K": 0, "W": 0, "L": 0, "-": 0}; line = ""
        for opp_name in PANEL:
            mk, d, fired = run_one(kw, opp_name, gs, cfg, rf, tac, dur)
            tg[mk] += 1
            short = opp_name.replace("anchor_", "").replace("_", "")[:6]
            line += f"{short}:{mk}{'*' if fired else ''} "
        tag = f"Tc{kw['T_CHECK']}_{kw['forcing']}"
        print(f"{tag:<18} 승{tg['K']+tg['W']}/10 (K{tg['K']}W{tg['W']}L{tg['L']}-{tg['-']})  {line}", flush=True)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 200.0)
