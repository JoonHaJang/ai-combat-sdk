"""E43 — *도망(escape) 형상* 게이트(당신 가설): 닫았다 재이탈 = standoff → 강제 merge. 조기 발동.

E42 진단: range "한번도 미진입"은 느린 승자(ace/B1/C3 t40엔 14000ft) 때문에 T0=120라야 깨끗 → 늦음 →
못 변환. 스냅샷: 무(A3/D2)=닫았다 재이탈(4402→9798), 승=단조감소(절대 안 벌어짐). 당신의 진입/도망 형상.
게이트 = (rmin 갱신 후 range > rmin+MARGIN) ∧ (range>WEZ_MAX) ∧ (t>T0) = '도망 확정' → 강제 merge 래치.
조기(t~50)라 변환시간 충분. forcing tactic도 sweep. 검증=전 패널. usage: python exp_e43_escape_gate.py [dur]
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
           "LDR_PURE": (T.LAG_DISPLACEMENT_ROLL, T.PURE_PURSUIT),
           "PURE_GUN": (T.PURE_PURSUIT, T.GUN_TRACK)}


class EscapeGatedPolicy:
    """ADAPTIVE base + *도망 형상* 게이트. rmin 후 range가 MARGIN 이상 재이탈하면 강제 merge 래치."""
    def __init__(self, rf, tac, T0=25.0, MARGIN=3500.0, ARM=6000.0, forcing="LEAD_GUN", gated=True):
        self.base = AdaptivePolicy(rf, tac, corrections=True)
        self.T0, self.MARGIN, self.ARM, self.gated = T0, MARGIN, ARM, gated
        self.close_t, self.align_t = FORCING[forcing]
        self.rmin = 9e9; self.t = 0.0; self.phase = 0; self.fired = 0; self.armed = False

    def select(self, p1, p2) -> Tactic:
        o = compute_obs(p1, p2); self.t += 0.1
        if o.ego_alt_ft < SAFE:
            return Tactic.CLIMB
        if not self.gated:
            return self.base.select(p1, p2)
        # ── 도망 형상: ①먼저 가까이 닫음(rmin<ARM=무장) ②그 뒤 rmin+MARGIN 넘게 재이탈 = escape 확정 ──
        #    초기 merge pass(다 같이 벌어짐)는 무장 전이라 무시. 단조승자는 닫을 때 단조감소라 재이탈 안 함.
        if self.phase == 0:
            self.rmin = min(self.rmin, o.distance_ft)
            if self.rmin < self.ARM:
                self.armed = True
            if (self.armed and self.t > self.T0 and o.distance_ft > WEZ_MAX
                    and o.distance_ft > self.rmin + self.MARGIN):
                self.phase = 1                                     # 강제 merge 래치
        if self.phase >= 1:
            self.fired += 1
            if self.phase == 1 and o.distance_ft < WEZ_MAX:
                self.phase = 2
            if self.phase == 2 and o.distance_ft > WEZ_MAX * 1.8:
                self.phase = 1
            return self.align_t if self.phase == 2 else self.close_t
        return self.base.select(p1, p2)


def run_one(cfg_kw, opp_name, gs, cfg, rf, tac, dur):
    p1, p2 = spawn_adt_neutral()
    pol = EscapeGatedPolicy(rf, tac, **cfg_kw)
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
        dict(T0=25, MARGIN=3000, ARM=6000, forcing="LEAD_GUN"),
        dict(T0=25, MARGIN=3000, ARM=6000, forcing="PURE_GUN"),
        dict(T0=25, MARGIN=3000, ARM=6000, forcing="LDR_PURE"),
        dict(T0=25, MARGIN=2000, ARM=7000, forcing="LEAD_GUN"),
    ]
    print(f"=== E43 도망 형상 게이트 {dur:.0f}s (K격추 W판정 L패 -무) ===", flush=True)
    for kw in CONFIGS:
        tg = {"K": 0, "W": 0, "L": 0, "-": 0}; line = ""
        for opp_name in PANEL:
            mk, d, fired = run_one(kw, opp_name, gs, cfg, rf, tac, dur)
            tg[mk] += 1
            short = opp_name.replace("anchor_", "").replace("_", "")[:6]
            line += f"{short}:{mk}{'*' if fired else ''} "
        tag = f"T0{kw['T0']}_M{kw['MARGIN']}_{kw['forcing']}"
        print(f"{tag:<26} 승{tg['K']+tg['W']}/10 (K{tg['K']}W{tg['W']}L{tg['L']}-{tg['-']})  {line}", flush=True)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 200.0)
