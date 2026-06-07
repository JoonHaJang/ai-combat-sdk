"""E0 — 권위 데이터셋 생성 (설계 zoo × LHS spawn → forward-sim 라벨).

scaled_solver.collect_scaled 재사용. 적 = zoo 111 + 앵커 4. meta 에 opp_name 보존(archetype
분리용). 라벨 base=None(PURE_PURSUIT tail) — clean-slate 1차(옛 정책 의존 제거; base 민감도는
E2에서 별도). 결정론: 고정 seed.

usage: python exp_e0_dataset.py [N_SPAWNS] [STATES] [MATCH_S] [LABEL_H]
출력: ../results_research_dataset.npz  (X, Y, feats, tactics, opp_names, archetypes, spawns)
"""
from __future__ import annotations
import sys, os, glob, time
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

from offline_solver import FEATS, CANDS
from opponents import OPPONENT_BTS
from scaled_solver import collect_scaled

ZOO = os.path.join(os.path.dirname(__file__), "..", "opponents", "zoo")
OUT = os.path.join(os.path.dirname(__file__), "..", "results_research_dataset.npz")


def _opp_jobs():
    jobs = [(n, None) for n in OPPONENT_BTS]          # 앵커 4 (simple/agg/def/ace)
    for f in sorted(glob.glob(os.path.join(ZOO, "*.yaml"))):
        jobs.append((os.path.basename(f)[:-5], f))   # zoo 111
    return jobs


def _archetype(opp_name):
    # zoo: "A1_PurePursuer_03" → "A1_PurePursuer" ; 앵커: 그대로
    if opp_name in OPPONENT_BTS:
        return f"anchor_{opp_name}"
    return opp_name.rsplit("_", 1)[0]


def main(n_spawns=4, states=8, match_s=45.0, label_H=25.0, commit_s=4.0, seed=0):
    n_proc = max(1, min(60, (os.cpu_count() or 4) - 2))
    jobs = _opp_jobs()
    n_match = len(jobs) * n_spawns
    print(f"=== E0 데이터 생성 (clean-slate, base=PURE_PURSUIT tail) ===")
    print(f"  적 {len(jobs)}종(zoo {len(jobs)-len(OPPONENT_BTS)} + 앵커 {len(OPPONENT_BTS)})"
          f" × spawn {n_spawns}(LHS) = 매치 {n_match}건")
    print(f"  상태/매치 {states}, label_H {label_H:.0f}s, commit {commit_s:.0f}s, "
          f"tactic {len(CANDS)}, {n_proc}병렬")
    t0 = time.time()
    X, Y, meta = collect_scaled(jobs, states, match_s, label_H, n_proc, n_spawns,
                                commit_s, base_path=None, seed=seed)
    dt = time.time() - t0
    spawns = np.array([m[0] for m in meta])
    opp_names = np.array([m[1] for m in meta])
    archs = np.array([_archetype(m[1]) for m in meta])
    np.savez(OUT, X=X, Y=Y, feats=FEATS, tactics=[t.name for t in CANDS],
             opp_names=opp_names, archetypes=archs, spawns=spawns)
    print(f"\n  완료: {len(X)} 상태, {dt/60:.1f}분 ({dt/max(1,n_match):.2f}s/매치)")
    print(f"  고유 archetype {len(set(archs))}, 고유 적 {len(set(opp_names))}, spawn {len(set(spawns))}")
    print(f"  저장 → {os.path.relpath(OUT)}")
    # best-tactic 분포
    bt = [CANDS[i].name for i in np.argmax(Y, axis=1)]
    from collections import Counter
    print(f"  best-tactic 분포:", dict(Counter(bt).most_common()))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(int(a[0]) if len(a) > 0 else 4,
         int(a[1]) if len(a) > 1 else 8,
         float(a[2]) if len(a) > 2 else 45.0,
         float(a[3]) if len(a) > 3 else 25.0)
