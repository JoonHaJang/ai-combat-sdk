"""E52 — D2 전역 trajectory 최적화 (결정적 방법): 우리 tactic 시퀀스를 실엔진+실D2로 평가, 데미지 최대화.

"모든 방법 다 했나"의 답: 반응형 ~70개는 소진했지만 *전역 최적화*는 미시도. D2=결정론이라 fitness 결정적.
phase별 tactic 시퀀스(N phase)를 GA로 탐색. 격추 찾으면 D2 풀림(+설명가능 추출), 수백 eval 0이면
barrier 결정적 증거. real-engine forward-eval(myopic 아님, full-horizon). usage: python exp_e52_d2_optimize.py [gens] [pop]
"""
from __future__ import annotations
import sys, os, math, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))

from exp_e22_chaseforce import _opp
from exp_e27_adaptive_subset import AdaptivePolicy
from exp_e7_champion import _train
from exp_e10_unified import DS_DA
import guidance
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from obs import compute_obs
from tactic import Tactic as T

PREFIX_S = 40.0   # base 40s prefix(분류시점)후 시퀀스 — 통합 맥락 재현
_RF = _TAC = None

# 후보 tactic (공격·기동·수직 전부)
PALETTE = [T.LEAD_PURSUIT, T.PURE_PURSUIT, T.LAG_PURSUIT, T.LAG_DISPLACEMENT_ROLL, T.GUN_TRACK,
           T.ETM_TRACK, T.ONE_CIRCLE, T.TWO_CIRCLE, T.HIGH_YOYO, T.LOW_YOYO, T.LEAD_TURN,
           T.TIGHT_TURN, T.VERTICAL_PURSUIT, T.SCISSORS]
N_PHASE = 6
DUR = 180.0
OPP = "D2_LastDitch"
SEED = [1, 7, 3, 13, 5, 11, 2, 17, 19, 23, 29, 31, 37, 41]   # 결정론 의사난수(Date.now 금지)


def _rng(state):
    """LCG 의사난수 (재현가능)."""
    state[0] = (1103515245 * state[0] + 12345) & 0x7FFFFFFF
    return state[0] / 0x7FFFFFFF


def evalseq(seq, gs, cfg):
    p1, p2 = spawn_adt_neutral()
    opp = _opp(OPP)
    base = AdaptivePolicy(_RF, _TAC, corrections=True)   # 통합 맥락: base prefix
    dt = (DUR - PREFIX_S) / N_PHASE
    rec = {"t": 0.0, "dmin": 9e9, "wez": 0}
    def fn(o):
        ob = compute_obs(p1, p2); rec["t"] += 0.1
        if ob.ego_alt_ft < 2500: return T.CLIMB
        rec["dmin"] = min(rec["dmin"], ob.distance_ft)
        if ob.ata_deg < 12 and 500 < ob.distance_ft < 3000: rec["wez"] += 1
        if rec["t"] <= PREFIX_S:                          # base 40s prefix
            return base.select(p1, p2)
        i = min(N_PHASE - 1, int((rec["t"] - PREFIX_S) / dt))
        return seq[i]
    m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
              control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
    res = m.run(tactic_fn1=lambda o: fn(o), tactic_fn2=lambda o: opp(compute_obs(p2, p1)), duration_s=DUR)
    # ★ fitness: *순이득*(우리HP−적HP) 우선 — 받지 않고 주는 시퀀스. 동률시 근접·WEZ.
    net = res.health1 - res.health2
    fit = net * 1000.0 + max(0.0, 6000.0 - rec["dmin"]) + rec["wez"] * 5.0
    return fit, res.damage_dealt1, rec["dmin"], rec["wez"], res.health1, res.health2


def main(gens=12, pop=24):
    global _RF, _TAC
    _RF, _TAC = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(30.0)
    guidance.ETM_TAU = 2.0
    st = [12345]
    npal = len(PALETTE)
    # 초기 population: seeded 랜덤 시퀀스
    P = [[PALETTE[int(_rng(st) * npal) % npal] for _ in range(N_PHASE)] for _ in range(pop)]
    best = None
    print(f"=== E52 D2 전역 최적화 GA (gens={gens} pop={pop} N_PHASE={N_PHASE}) ===", flush=True)
    for g in range(gens):
        scored = []
        for seq in P:
            fit, dmg, dmin, wez, h1, h2 = evalseq(seq, gs, cfg)
            scored.append((fit, dmg, dmin, wez, seq, h1, h2))
        scored.sort(key=lambda x: -x[0])
        if best is None or scored[0][0] > best[0]:
            best = scored[0]
        b = scored[0]
        net = b[5] - b[6]
        print(f"gen{g:2d} best 순이득={net:+.0f}(HP{b[5]:.0f}:{b[6]:.0f}) dmg={b[1]:.0f} dmin={b[2]:.0f} wez={b[3]} | {'>'.join(t.name[:4] for t in b[4])}", flush=True)
        if net > 0.5:   # 순이득 양수 → D2 판정승 가능 신호
            print(f"  ★ 순이득 양수! D2 판정승 가능 시퀀스", flush=True)
        # 선택+교배+변이 (상위 절반 부모)
        elite = [s[4] for s in scored[:max(2, pop // 4)]]
        newP = [scored[0][4], scored[1][4]]    # elitism
        while len(newP) < pop:
            a = elite[int(_rng(st) * len(elite)) % len(elite)]
            bp = elite[int(_rng(st) * len(elite)) % len(elite)]
            child = [a[i] if _rng(st) < 0.5 else bp[i] for i in range(N_PHASE)]
            for i in range(N_PHASE):
                if _rng(st) < 0.25:           # 변이
                    child[i] = PALETTE[int(_rng(st) * npal) % npal]
            newP.append(child)
        P = newP
    net = best[5] - best[6]
    print(f"\n★★ 최종 best: 순이득={net:+.0f} HP{best[5]:.0f}:{best[6]:.0f} dmg={best[1]:.0f} dmin={best[2]:.0f} wez={best[3]}", flush=True)
    print(f"   seq={'>'.join(t.name for t in best[4])}", flush=True)
    if net > 0.5:
        print("→ ★ D2 판정승 시퀀스 발견! (순이득 양수)", flush=True)
    else:
        print("→ 순이득 양수 시퀀스 못 찾음 — D2 net-win은 barrier 가능성", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(int(a[0]) if a else 12, int(a[1]) if len(a) > 1 else 24)
