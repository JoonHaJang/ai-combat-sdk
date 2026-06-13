"""E34 — A3 싸움 *메커니즘* 정밀 분석 (종결 아니라 *해결*용). CSV angle버그 우회=compute_obs 직접 로깅.

A3=scripted lag-angler=결정론 → *예측 가능한 패턴*이 있고 = exploit 가능해야 정상.
계측: 매 tick 진짜 기하(ata/aa/hca/dist/closure/es) + 우리 tactic + A3 tactic 로깅.
분석: ① 근접 순간의 기하(phase mismatch?) ② A3의 예측패턴(우리X→A3Y) ③ 놓친 사격해 원인.
usage: python exp_e34_a3_mechanism.py [dur]
"""
from __future__ import annotations
import sys, os, math, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))

from exp_e27_adaptive_subset import AdaptivePolicy
from exp_e22_chaseforce import _opp
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from obs import compute_obs
from tactic import Tactic
from exp_e7_champion import _train
from exp_e10_unified import DS_DA
from collections import Counter
import numpy as np

LOG = []   # (t, dist, ata, aa, hca, clos, es_us, es_op, our_tac, a3_tac)


def _hca(o): return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)
def _es(alt, vc): return alt + (vc * 1.68781) ** 2 / (2 * 32.174)


def main(dur=160.0):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    p1, p2 = spawn_adt_neutral()
    pol = AdaptivePolicy(rf, tac, corrections=True)
    a3 = _opp("A3_LagAngler")
    t = [0.0]

    def our_fn(o):
        ob = compute_obs(p1, p2); o2 = compute_obs(p2, p1)
        our_t = pol.select(p1, p2)
        a3_t = a3(o2)
        LOG.append((t[0], ob.distance_ft, ob.ata_deg, ob.aa_deg, _hca(ob), ob.closure_kts,
                    _es(ob.ego_alt_ft, ob.ego_vc_kts), _es(o2.ego_alt_ft, o2.ego_vc_kts),
                    our_t.name, a3_t.name))
        t[0] += 0.1
        return our_t

    res = m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                    control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
    r = m.run(tactic_fn1=our_fn, tactic_fn2=lambda o: a3(compute_obs(p2, p1)), duration_s=dur)
    print(f"=== A3 vs ADAPTIVE: HP {r.health1:.0f}:{r.health2:.0f} dmg {r.damage_dealt1:.0f} ===")
    L = LOG
    dists = [x[1] for x in L]
    print(f"\n[기하 요약] min dist {min(dists)*0.3048:.0f}m | <914m(WEZmax) {100*sum(1 for d in dists if d<3000)/len(dists):.0f}% | <3000ft {sum(1 for d in dists if d<3000)}tick")
    # 사격기회: 진짜 ata<12 ∧ WEZ거리
    wez = [x for x in L if x[2] < 12.0 and 500 <= x[1] <= 3000]
    near = [x for x in L if x[1] <= 3000]
    print(f"[사격해] 진짜 WEZ(ata<12∧500-3000ft) = {len(wez)}tick")
    print(f"[근접 WEZ거리(<3000ft)서 ata 분포] " + (f"평균ata={np.mean([x[2] for x in near]):.0f}° min={min(x[2] for x in near):.0f}°" if near else "근접 없음"))
    # 근접 순간(국소 dist 최소)의 위상
    print(f"\n[근접 순간들 — phase mismatch 확인]")
    print(f"{'t':>4}{'dist(m)':>8}{'ata':>5}{'aa':>5}{'hca':>5}{'Δes':>7}{'our_tac':<14}{'a3_tac':<14}")
    D = dists
    last = -99
    for i in range(30, len(D)-30):
        if D[i] == min(D[i-30:i+30]) and D[i] < 5000 and L[i][0]-last > 3:
            last = L[i][0]; x = L[i]
            print(f"{x[0]:4.0f}{x[1]*0.3048:8.0f}{x[2]:5.0f}{x[3]:5.0f}{x[4]:5.0f}{x[6]-x[7]:7.0f}{x[8]:<14}{x[9]:<14}")
    # A3 예측패턴
    print(f"\n[A3 tactic 분포(예측패턴)] {dict(Counter(x[9] for x in L).most_common())}")
    print(f"[우리 tactic 분포] {dict(Counter(x[8] for x in L).most_common())}")
    # 에너지 추세
    print(f"[에너지] 우리 Es {L[0][6]:.0f}→{L[-1][6]:.0f} | A3 Es {L[0][7]:.0f}→{L[-1][7]:.0f} | 최종Δ {L[-1][6]-L[-1][7]:.0f}")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 160.0)
