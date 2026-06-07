"""E2 (RQ2) — 라벨 타당성: 재현성 + horizon 스윕(myopia).

질문: forward-sim 데미지 라벨이 (a) 재현가능하고 (b) horizon 따라 best-tactic 순위가 안정되는가.
방법:
  - 몇 (spawn, 적) 매치에서 상태를 capture.
  - 재현성: 같은 상태/tactic eval 두 번 → 동일(결정론) 확인.
  - horizon 스윕: 각 상태에서 H ∈ {10,20,40,60} 로 전 tactic eval → best-tactic.
    H=60 기준 대비 일치율 = 순위 안정성. 어디서 안정되나(myopia 임계).

usage: python exp_e2_labels.py
"""
from __future__ import annotations
import sys, os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from obs import compute_obs
from tactic import Tactic
from plant import F16Plant
from pilot import Pilot
from scenarios import SITUATIONS
from opponents import OPPONENT_BTS
from offline_solver import _Sim, CANDS, _AGGR

HSET = [10.0, 20.0, 40.0, 60.0]


def capture_states(gs, spawn_fn, opp_fn, n=8, match_s=40.0):
    """짧은 매치에서 상태 snapshot 수집."""
    p1, p2 = spawn_fn()
    pu = Pilot(p1, gs, _AGGR, 1/20.0); po = Pilot(p2, gs, AutopilotConfig(KP_PSI=0.10), 1/20.0)
    cdt = 0.05; nt = int(match_s/cdt); n_ctrl = 6
    iv = max(1, nt // n)
    snaps = []
    cur = Tactic.PURE_PURSUIT
    for k in range(nt):
        o12 = compute_obs(p1, p2); o21 = compute_obs(p2, p1)
        if k % iv == 0 and o12.ego_alt_ft > 2500 and o12.distance_ft < 25000:
            snaps.append((p1.capture_state(), p2.capture_state()))
        u1 = pu.step(p2, tactic=(Tactic.CLIMB if o12.ego_alt_ft < 2500 else cur))
        u2 = po.step(p1, tactic=opp_fn(o21))
        p1.set_input(u1); p2.set_input(u2)
        for _ in range(n_ctrl): p1.step(1); p2.step(1)
    return snaps


def main():
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    pairs = [("offensive", "anchor_ace"), ("neutral", "anchor_aggressive"),
             ("defensive", "anchor_defensive")]
    opp_map = dict(OPPONENT_BTS)

    # 상태 수집
    snaps = []
    for spawn_name, opp_name in pairs:
        if spawn_name not in SITUATIONS:
            spawn_name = list(SITUATIONS)[0]
        opp_fn = opp_map[opp_name.replace("anchor_", "")]
        snaps += capture_states(gs, SITUATIONS[spawn_name], opp_fn, n=8)
    print(f"=== E2 라벨 타당성 (상태 {len(snaps)}개, tactic {len(CANDS)}) ===\n")

    # 재현성: H=40 으로 두 번 eval 동일?
    sim = _Sim(gs, H=40.0)
    opp_fn = opp_map["ace"]
    s0 = snaps[0]
    v1 = [sim.eval(s0[0], s0[1], t, opp_fn) for t in CANDS]
    v2 = [sim.eval(s0[0], s0[1], t, opp_fn) for t in CANDS]
    maxdiff = max(abs(a-b) for a, b in zip(v1, v2))
    print(f"(a) 재현성: 같은 상태 2회 eval 최대차 = {maxdiff:.2e}  "
          f"→ {'결정론(동일)' if maxdiff < 1e-6 else '비결정 의심'}")

    # horizon 스윕: 각 상태 best-tactic @ H, H=60 기준 일치율
    print(f"\n(b) horizon 스윕 — best-tactic 안정성 (H=60 기준 일치율):")
    sims = {H: _Sim(gs, H=H) for H in HSET}
    best = {H: [] for H in HSET}
    for (su, so) in snaps:
        for H in HSET:
            vals = [sims[H].eval(su, so, t, opp_fn) for t in CANDS]
            best[H].append(int(np.argmax(vals)))
    ref = np.array(best[60.0])
    for H in HSET:
        agree = (np.array(best[H]) == ref).mean()
        print(f"    H={H:>4.0f}s: best-tactic H60 일치율 = {agree:.2f}")
    print(f"\n  해석: 일치율이 어느 H부터 평탄하면 그 H가 myopia 임계(그 이상은 라벨 안정).")


if __name__ == "__main__":
    main()
