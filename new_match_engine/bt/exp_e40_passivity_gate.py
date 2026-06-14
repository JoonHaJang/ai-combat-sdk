"""E40 — A3 승리행동(LEAD→GUN)을 *적-passivity 게이트*로 발동: 함정 회피 + 패널 보존 검증.

E38/E39 발견: A3는 LEAD→GUN으로 무→판정(이김). 단 *보편 적용*하면 ace/B/C 격추 파괴(A3 hack).
→ *상황 특정 발동* 필요. *우리 상태* 게이트=피드백함정(기확정 실패). *적 행동* 게이트=안정:
  passive-stalemate = (경과>T0) ∧ (아직 WEZ각 미도달) ∧ (적이 우리 후방반구 밖 aa<A0=적 안겨눔=lag).
  → 발동시 LEAD→GUN(closing→align). ace(공격적,aa↑)엔 미발동 → 격추 보존(설명가능 판별자).
검증: 전 패널서 (a) A3 무→승 (b) 나머지 보존. usage: python exp_e40_passivity_gate.py [dur]
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


class PassivityGatedPolicy:
    """ADAPTIVE base + *적-passivity 게이트*로 LEAD→GUN 발동(A3 승리행동, 함정회피).

    게이트 = (t>T0) ∧ (WEZ각 미도달) ∧ (적 aa EMA < A0 = 적이 우리 후방반구 밖=안겨눔=passive lag).
    발동 후엔 closing/align 2-phase(dist<WEZ_MAX→GUN). 적 aa는 *우리 tactic과 무관* → 피드백함정X.
    """
    def __init__(self, rf, tac, T0=22.0, A0=85.0, gated=True):
        self.base = AdaptivePolicy(rf, tac, corrections=True)
        self.T0, self.A0, self.gated = T0, A0, gated
        self.t = 0.0; self.aa_ema = 90.0; self.wez_reached = False
        self.phase = 0      # 0=base, 1=closing, 2=align
        self.fired = 0; self.tot = 0

    def select(self, p1, p2) -> Tactic:
        o = compute_obs(p1, p2); self.tot += 1; self.t += 0.1
        if o.ego_alt_ft < SAFE:
            return Tactic.CLIMB
        self.aa_ema = 0.97 * self.aa_ema + 0.03 * o.aa_deg          # 적 위협각 EMA(안정)
        if o.ata_deg < 15.0 and o.distance_ft < WEZ_MAX:
            self.wez_reached = True                                  # 한번이라도 WEZ각 도달=닫는중
        if not self.gated:
            return self.base.select(p1, p2)
        # ── 적-passivity 게이트 (래치: 한번 passive 확정되면 강제 merge 유지) ──
        passive = (self.t > self.T0) and (not self.wez_reached) and (self.aa_ema < self.A0)
        if passive and self.phase == 0:
            self.phase = 1
        if self.phase >= 1:
            self.fired += 1
            if self.phase == 1 and o.distance_ft < WEZ_MAX:
                self.phase = 2
            if self.phase == 2 and o.distance_ft > WEZ_MAX * 1.8:
                self.phase = 1
            return Tactic.GUN_TRACK if self.phase == 2 else Tactic.LEAD_PURSUIT
        return self.base.select(p1, p2)                              # base-승리 상황 보존


def run_one(pol_name, opp_name, gs, cfg, rf, tac, dur):
    p1, p2 = spawn_adt_neutral()
    if pol_name == "ADAPTIVE":
        pol = PassivityGatedPolicy(rf, tac, gated=False)
    else:
        pol = PassivityGatedPolicy(rf, tac, gated=True)
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
    print(f"=== E40 적-passivity 게이트 {dur:.0f}s (K격추 W판정 L패 -무) ===", flush=True)
    print(f"{'opp':<18}{'ADAPTIVE':>12}{'GATED':>14}", flush=True)
    ta = {"K": 0, "W": 0, "L": 0, "-": 0}; tg = {"K": 0, "W": 0, "L": 0, "-": 0}
    for opp_name in PANEL:
        a_mk, a_d, _ = run_one("ADAPTIVE", opp_name, gs, cfg, rf, tac, dur)
        g_mk, g_d, fired = run_one("GATED", opp_name, gs, cfg, rf, tac, dur)
        ta[a_mk] += 1; tg[g_mk] += 1
        flag = "  ←개선" if (a_mk == "-" and g_mk in "KW") else ("  ←회귀!" if (a_mk in "KW" and g_mk in "L-") else "")
        print(f"{opp_name:<18}{a_mk+f'({a_d:.0f})':>12}{g_mk+f'({g_d:.0f}) f{fired}':>14}{flag}", flush=True)
    print(f"\nADAPTIVE: K{ta['K']} W{ta['W']} L{ta['L']} -{ta['-']}  승{ta['K']+ta['W']}/{len(PANEL)}", flush=True)
    print(f"GATED   : K{tg['K']} W{tg['W']} L{tg['L']} -{tg['-']}  승{tg['K']+tg['W']}/{len(PANEL)}", flush=True)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 160.0)
