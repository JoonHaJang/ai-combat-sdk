"""재라벨 검증 — CANDS에 LEAD_TURN/TIGHT_TURN 추가 시, *데이터(진짜 데미지 라벨)* 가
고-regret 상황(rate/extend)에서 이들을 VERTICAL보다 높게 매기나.

라벨링은 이미 충분(offline_solver._Sim: 실제 적BT + H60 + potential shaping). 유일한 결손=후보집합.
→ 동일 _Sim 라벨러로 12 tactic(기존10 + LEAD_TURN + TIGHT_TURN) 점수화 → per-situation 1위 확인.
이기면 = "후보 추가 + 재학습"이 정답(데이터 증명). usage: python exp_relabel_validate.py
"""
from __future__ import annotations
import sys, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import math, glob
from collections import defaultdict

from offline_solver import _Sim, _feat, CANDS, _AGGR
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from scenarios import spawn_adt_neutral
from opponents import OPPONENT_BTS
from yaml_bt import load_bt
from obs import compute_obs
from tactic import Tactic
from situation import classify as classify_situation
from pilot import Pilot
from plant import F16Plant
from exp_e7_champion import _train

ZOO = os.path.join(os.path.dirname(__file__), "..", "opponents", "zoo")
CANDS_EXT = list(CANDS) + [Tactic.LEAD_TURN, Tactic.TIGHT_TURN]
NEW = {"LEAD_TURN", "TIGHT_TURN"}


def _opp(name):
    if name.startswith("anchor_"):
        return OPPONENT_BTS[name.split("_", 1)[1]]
    fs = sorted(glob.glob(os.path.join(ZOO, name + "_*.yaml")))
    return load_bt(fs[len(fs) // 2])


def _hca(o): return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)


def main(n_sample=10, match_s=80.0):
    rf, tac = _train(os.path.join(os.path.dirname(__file__), "..", "results_research_dagger.npz"))
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    sim = _Sim(gs, H=60.0)
    cfg2 = AutopilotConfig(KP_PSI=0.10)
    opps = ["anchor_ace", "A3_LagAngler", "D2_LastDitch"]
    # 상황별 누적: tactic → 점수 리스트
    bysit = defaultdict(lambda: defaultdict(list))
    print(f"=== 재라벨 검증 (CANDS+LEAD_TURN/TIGHT_TURN, _Sim H60 실제적BT) ===", flush=True)
    for opp_name in opps:
        opp_fn = _opp(opp_name)
        p1, p2 = spawn_adt_neutral()
        pu = Pilot(p1, gs, _AGGR, 1/20.0); po = Pilot(p2, gs, cfg2, 1/20.0)
        cdt = 0.05; nt = int(match_s/cdt); n_ctrl = 6; sample_iv = max(1, nt // n_sample)
        ns = 0
        for k in range(nt):
            o12 = compute_obs(p1, p2); o21 = compute_obs(p2, p1)
            if k % sample_iv == 0 and o12.ego_alt_ft > 2500 and o12.distance_ft < 25000:
                snap_us, snap_op = p1.capture_state(), p2.capture_state()
                sit = classify_situation(o12)
                for t in CANDS_EXT:
                    bysit[sit][t.name].append(sim.eval(snap_us, snap_op, t, opp_fn))
                ns += 1
            # advance: p1 = RF 정책(실제 방문상태), p2 = 적 BT
            x = [[o12.ata_deg, o12.aa_deg, _hca(o12), o12.distance_ft, o12.closure_kts,
                  __import__("real_rollout")._es_diff(o12), o12.ego_r_dps, o12.enm_r_dps]]
            tac1 = Tactic.CLIMB if o12.ego_alt_ft < 2500 else Tactic[tac[int(rf.predict(x)[0].argmax())]]
            u1 = pu.step(p2, tactic=tac1); u2 = po.step(p1, tactic=opp_fn(o21))
            p1.set_input(u1); p2.set_input(u2)
            for _ in range(n_ctrl): p1.step(1); p2.step(1)
        print(f"  {opp_name}: {ns} 상태 라벨", flush=True)

    print(f"\n{'상황':<12}{'n':>4}  per-situation tactic 순위 (평균 라벨점수, ★=신규)")
    for sit, d in bysit.items():
        means = {t: float(np.mean(v)) for t, v in d.items()}
        order = sorted(means, key=lambda t: -means[t])
        n = len(next(iter(d.values())))
        top = "  ".join(f"{'★' if t in NEW else ''}{t}={means[t]:.1f}" for t in order[:5])
        vert = means.get("VERTICAL_PURSUIT", float('nan'))
        lead = means.get("LEAD_TURN", float('nan')); tight = means.get("TIGHT_TURN", float('nan'))
        flag = ""
        if lead > vert or tight > vert: flag = "  ◀ 신규가 VERTICAL 추월!"
        print(f"{sit:<12}{n:>4}  {top}{flag}")
        print(f"{'':16}VERTICAL={vert:.1f}  ★LEAD_TURN={lead:.1f}  ★TIGHT_TURN={tight:.1f}")


if __name__ == "__main__":
    main()
