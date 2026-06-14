"""E47 — 자율 response 발견(분석 반영): A3·D2를 이기는 기동 전수 탐색. forced(탐지 분리).

반영된 분석: ①탐지는 clean(t=120, 15승보존) → response 전용특화 자유 ②A3=lag 결정론(cutoff/scissors)
③D2=aa>130(우리 6시)에 spiral-dive → *off-6 deflection*(lag/beam)이면 트리거 안함 ④D2 압박시 덱bleed
→에너지우위(에너지-first 시퀀스). 미시도 응답 집중. dmg>0 찾으면 그게 response. usage: python exp_e47_response_loop.py [opp]
"""
from __future__ import annotations
import sys, os, math, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))

from exp_e22_chaseforce import _opp
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from obs import compute_obs
from tactic import Tactic
from real_rollout import _es_diff

T = Tactic
WEZ = 3000.0


def two_phase(p1, p2, a, b, switch_close=True):
    """switch_close=True: dist<WEZ서 a→b. False: dist>WEZ서 a→b(재이탈시 close)."""
    st = {"ph": 0}
    def pol(o):
        ob = compute_obs(p1, p2)
        if ob.ego_alt_ft < 2500: return T.CLIMB
        if st["ph"] == 0 and ob.distance_ft < WEZ: st["ph"] = 1
        if st["ph"] == 1 and ob.distance_ft > WEZ * 1.8: st["ph"] = 0
        return b if st["ph"] == 1 else a
    return pol


def energy_first(p1, p2, conv):
    """에너지-first: 먼저 EXTENSION으로 에너지 우위 쌓고(es_diff>3000) → conv로 강하전환."""
    st = {"ph": 0}
    def pol(o):
        ob = compute_obs(p1, p2)
        if ob.ego_alt_ft < 2500: return T.CLIMB
        if st["ph"] == 0 and _es_diff(ob) > 3000: st["ph"] = 1
        if st["ph"] == 1 and _es_diff(ob) < 500: st["ph"] = 0
        return conv if st["ph"] == 1 else T.EXTENSION
    return pol


def off6_deflection(p1, p2):
    """D2 exploit: 적 6시(우리 aa 낮음=적이 spiral 트리거) 피해 beam서 gun. aa 적당하면 GUN, 너무 뒤면 LAG로 빠짐."""
    def pol(o):
        ob = compute_obs(p1, p2)
        if ob.ego_alt_ft < 2500: return T.CLIMB
        # 적 UnderThreat(우리가 적 6시) 안 만들게: 우리가 적 후방 깊이(aa<40) 들어가면 LAG로 각 유지, 아니면 GUN
        if ob.aa_deg < 40.0: return T.LAG_PURSUIT        # 너무 뒤 → 적 spiral 유발 → 각 빼기
        return T.GUN_TRACK if ob.distance_ft < WEZ else T.LEAD_TURN
    return pol


def main(opp_name="A3_LagAngler", dur=200.0):
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    STRATS = {
        "scissors_sustain": lambda p1, p2: (lambda o: T.CLIMB if compute_obs(p1, p2).ego_alt_ft < 2500 else T.SCISSORS),
        "leadturn_sustain": lambda p1, p2: (lambda o: T.CLIMB if compute_obs(p1, p2).ego_alt_ft < 2500 else T.LEAD_TURN),
        "lag_sustain":      lambda p1, p2: (lambda o: T.CLIMB if compute_obs(p1, p2).ego_alt_ft < 2500 else T.LAG_PURSUIT),
        "SCISSORS→GUN":     lambda p1, p2: two_phase(p1, p2, T.SCISSORS, T.GUN_TRACK),
        "LEADTURN→GUN":     lambda p1, p2: two_phase(p1, p2, T.LEAD_TURN, T.GUN_TRACK),
        "LAG→GUN":          lambda p1, p2: two_phase(p1, p2, T.LAG_PURSUIT, T.GUN_TRACK),
        "VERT→GUN":         lambda p1, p2: two_phase(p1, p2, T.VERTICAL_PURSUIT, T.GUN_TRACK),
        "Efirst→GUN":       lambda p1, p2: energy_first(p1, p2, T.GUN_TRACK),
        "Efirst→HIYOYO":    lambda p1, p2: energy_first(p1, p2, T.HIGH_YOYO),
        "Efirst→LEADTURN":  lambda p1, p2: energy_first(p1, p2, T.LEAD_TURN),
        "off6_deflection":  lambda p1, p2: off6_deflection(p1, p2),
    }
    print(f"=== E47 response 발견 vs {opp_name} {dur:.0f}s ===", flush=True)
    best = ("?", -1)
    for name, build in STRATS.items():
        p1, p2 = spawn_adt_neutral()
        fn = build(p1, p2)
        m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                  control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
        res = m.run(tactic_fn1=lambda o: fn(o),
                    tactic_fn2=lambda o: _opp(opp_name)(compute_obs(p2, p1)), duration_s=dur)
        mk = "격추" if res.health2 <= 0 else ("판정" if res.health1 > res.health2 else "무")
        print(f"  {name:<20}{mk:<6} dmg={res.damage_dealt1:.0f} oppHP={res.health2:.0f}", flush=True)
        if res.damage_dealt1 > best[1]: best = (name, res.damage_dealt1)
    print(f"\n★ 최선: {best[0]}  dmg={best[1]:.0f}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "A3_LagAngler",
         float(sys.argv[2]) if len(sys.argv) > 2 else 200.0)
