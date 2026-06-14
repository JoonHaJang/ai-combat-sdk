"""E42 — *형상 게이트*: 상대궤적이 'WEZ밖 plateau orbit'이면 강제 merge(LEAD→GUN). A3 무→승 + 패널 보존.

E41 형상 발견: 격추=궤적이 중심(우리)으로 감김(거리 3000ft 안 붕괴), 무=큰반경 orbit(거리 3276ft plateau).
스칼라(D2≡aggressive) 실패를 *모양*이 가름. 형상 판별자(온라인·함정회피):
  orbit-standoff = (t>T0) ∧ (최근 W초 거리 변동 < PLAT) ∧ (최근 거리 min > WEZ_MAX=3000ft).
  → 격추는 3000ft 안 붕괴라 미발동(보존), 무는 plateau라 발동 → LEAD→GUN 래치. 검증=전 패널.
usage: python exp_e42_shape_gate.py [dur]
"""
from __future__ import annotations
import sys, os, math, warnings
from collections import deque
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


class ShapeGatedPolicy:
    """ADAPTIVE base + *형상 게이트*. 'T0까지 한 번도 WEZ권 미진입'=standoff orbit → LEAD→GUN 래치.

    E42 진단: 승자는 전부 T0(승자 최종진입 105s) 전에 3000ft 진입, 무승부(A3/D2)는 never(rmin 3276 영구).
    → global rmin > WEZ_MAX at t>T0 = orbit 확정(100% 분리). 이전 윈도-plateau는 t~20s 일찍 오판.
    """
    def __init__(self, rf, tac, T0=120.0, close_t=Tactic.LEAD_PURSUIT, align_t=Tactic.GUN_TRACK, gated=True):
        self.base = AdaptivePolicy(rf, tac, corrections=True)
        self.T0, self.close_t, self.align_t, self.gated = T0, close_t, align_t, gated
        self.rmin = 9e9                            # 매치 전체 최소거리(global)
        self.t = 0.0; self.phase = 0; self.fired = 0

    def select(self, p1, p2) -> Tactic:
        o = compute_obs(p1, p2); self.t += 0.1
        if o.ego_alt_ft < SAFE:
            return Tactic.CLIMB
        self.rmin = min(self.rmin, o.distance_ft)
        if not self.gated:
            return self.base.select(p1, p2)
        # ── 형상 판별: T0까지 한 번도 WEZ권 미진입 = orbit-standoff(무승부 모양) ──
        if self.phase == 0 and self.t > self.T0 and self.rmin > WEZ_MAX:
            self.phase = 1                                         # 강제 merge 래치
        if self.phase >= 1:
            self.fired += 1
            if self.phase == 1 and o.distance_ft < WEZ_MAX:
                self.phase = 2
            if self.phase == 2 and o.distance_ft > WEZ_MAX * 1.8:
                self.phase = 1
            return self.align_t if self.phase == 2 else self.close_t
        return self.base.select(p1, p2)


def run_one(gated, opp_name, gs, cfg, rf, tac, dur):
    p1, p2 = spawn_adt_neutral()
    pol = ShapeGatedPolicy(rf, tac, gated=gated)
    m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
              control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
    res = m.run(tactic_fn1=lambda o: pol.select(p1, p2),
                tactic_fn2=lambda o: _opp(opp_name)(compute_obs(p2, p1)), duration_s=dur)
    if res.health2 <= 0: mk = "K"
    elif res.health1 > res.health2: mk = "W"
    elif res.health1 < res.health2: mk = "L"
    else: mk = "-"
    return mk, res.damage_dealt1, pol.fired


def main(dur=160.0):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    print(f"=== E42 형상 게이트 {dur:.0f}s (K격추 W판정 L패 -무) ===", flush=True)
    print(f"{'opp':<18}{'ADAPTIVE':>11}{'SHAPE-GATED':>16}", flush=True)
    ta = {"K": 0, "W": 0, "L": 0, "-": 0}; tg = {"K": 0, "W": 0, "L": 0, "-": 0}
    for opp_name in PANEL:
        a_mk, a_d, _ = run_one(False, opp_name, gs, cfg, rf, tac, dur)
        g_mk, g_d, fired = run_one(True, opp_name, gs, cfg, rf, tac, dur)
        ta[a_mk] += 1; tg[g_mk] += 1
        flag = "  ←개선" if (a_mk == "-" and g_mk in "KW") else ("  ←회귀!" if (a_mk in "KW" and g_mk in "L-") else "")
        print(f"{opp_name:<18}{a_mk+f'({a_d:.0f})':>11}{g_mk+f'({g_d:.0f}) f{fired}':>16}{flag}", flush=True)
    print(f"\nADAPTIVE   : K{ta['K']} W{ta['W']} L{ta['L']} -{ta['-']}  승{ta['K']+ta['W']}/{len(PANEL)}", flush=True)
    print(f"SHAPE-GATED: K{tg['K']} W{tg['W']} L{tg['L']} -{tg['-']}  승{tg['K']+tg['W']}/{len(PANEL)}", flush=True)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 160.0)
