"""E45 — D2 전환: 압박으로 덱에 핀 시킨 뒤 *고→저 commit 강하공격*으로 격추 (에너지우위 현금화).

E44 기제: PURE 압박→D2 즉시 hard deck(1260ft)·저속·우리 에너지우위 +10000ft. 교과서 승리 위치인데 전환
기동 부재로 HP100. → phase1=압박(덱 핀), phase2(enm_alt<TH ∧ es_diff>E)=강하공격. phase2 tactic sweep.
이기는 전환 찾으면 D2 response 확정. usage: python exp_e45_d2_convert.py [dur]
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
PRESS = [T.PURE_PURSUIT, T.LEAD_PURSUIT]
CONVERT = [T.GUN_TRACK, T.PURE_PURSUIT, T.LOW_YOYO, T.TIGHT_TURN, T.LEAD_TURN, T.HIGH_YOYO]
ALT_TH = 4000.0
ES_TH = 4000.0


def make(p1, p2, press_t, conv_t):
    st = {"phase": 1}
    def pol(o):
        ob = compute_obs(p1, p2)
        if ob.ego_alt_ft < 2500.0:
            return Tactic.CLIMB
        # phase1=압박, D2 덱에 핀(저고도+에너지우위) → phase2=강하공격. 다시 높이 오르면 재압박.
        if st["phase"] == 1 and ob.enm_alt_ft < ALT_TH and _es_diff(ob) > ES_TH:
            st["phase"] = 2
        if st["phase"] == 2 and ob.enm_alt_ft > ALT_TH * 1.8:
            st["phase"] = 1
        return conv_t if st["phase"] == 2 else press_t
    return pol


def main(dur=200.0):
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    print(f"=== E45 D2 전환 (압박→고저 강하) {dur:.0f}s ===", flush=True)
    print(f"{'press→convert':<24}{'결과':<6}{'dmg':>5}{'oppHP':>7}", flush=True)
    best = ("?", -1)
    for pt in PRESS:
        for ct in CONVERT:
            p1, p2 = spawn_adt_neutral()
            pol = make(p1, p2, pt, ct)
            m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                      control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
            res = m.run(tactic_fn1=lambda o: pol(o),
                        tactic_fn2=lambda o: _opp("D2_LastDitch")(compute_obs(p2, p1)), duration_s=dur)
            mk = "격추" if res.health2 <= 0 else ("판정" if res.health1 > res.health2 else "무")
            lbl = f"{pt.name[:4]}→{ct.name}"
            print(f"{lbl:<24}{mk:<6}{res.damage_dealt1:>5.0f}{res.health2:>7.0f}", flush=True)
            if res.damage_dealt1 > best[1]: best = (lbl, res.damage_dealt1)
    print(f"\n★ 최선: {best[0]}  dmg={best[1]:.0f}", flush=True)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 200.0)
