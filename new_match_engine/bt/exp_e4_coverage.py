"""E4 (RQ4) — 커버리지와 일반화.

질문: 설계 적 풀×LHS spawn 학습분포가 (a) feature 공간을 얼마나 덮고 (b) 배포 방문 상태를
덮으며 (c) 데이터 규모에 따라 어떻게 스케일하는가.
방법:
  (A) feature 점유율 — 각 feature 5-분위 격자 marginal + 핵심 4D(ata,aa,hca,dist) 거친 joint 점유.
  (B) train 대 배포방문 — 배포 정책 매치로 방문 feature 수집, train 최근접거리로 OOD 비율.
  (C) 스케일링 — 적 수 {10,30,60,전체} subsample 학습 → leave-archetype-out regret.

usage: python exp_e4_coverage.py [dataset.npz]
"""
from __future__ import annotations
import sys, os, warnings
import numpy as np

warnings.filterwarnings("ignore")
DS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "results_research_dataset.npz")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))


def occupancy(X, feats):
    print("(A) feature 점유율:")
    print("    marginal 5분위 범위:")
    for i, f in enumerate(feats):
        q = np.percentile(X[:, i], [0, 25, 50, 75, 100])
        print(f"      {f:<10} [{q[0]:8.1f} | {q[1]:7.1f} {q[2]:7.1f} {q[3]:7.1f} | {q[4]:8.1f}]")
    # 핵심 4D 거친 joint 점유 (각 4 bin → 256 셀)
    key = [0, 1, 2, 3]  # ata,aa,hca,dist
    edges = [np.percentile(X[:, i], np.linspace(0, 100, 5)) for i in key]
    cells = set()
    for x in X:
        idx = tuple(min(3, np.searchsorted(edges[j][1:-1], x[key[j]])) for j in range(4))
        cells.add(idx)
    print(f"    핵심4D(ata,aa,hca,dist) 4^4=256 셀 중 점유 {len(cells)} ({len(cells)/256*100:.0f}%)")


def deploy_visited(n_pairs=4, match_s=120.0):
    """배포 TreePolicy 매치로 방문 feature 수집."""
    from lqr import GainScheduledLQR
    from autopilot import AutopilotConfig
    from match import Match
    from scenarios import SITUATIONS
    from opponents import OPPONENT_BTS
    from tree_policy import TreePolicy
    from obs import compute_obs
    from offline_solver import _feat
    import math
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    feats_v = []
    pairs = list(SITUATIONS.items())[:n_pairs]
    for spawn_name, spawn_fn in pairs:
        for opp_name, opp_fn in list(OPPONENT_BTS.items())[:1]:
            p1, p2 = spawn_fn()
            pol = TreePolicy()
            cdt = 0.05; nt = int(match_s/cdt); n_ctrl = 6
            from pilot import Pilot
            pu = Pilot(p1, gs, cfg, 1/20.0); po = Pilot(p2, gs, AutopilotConfig(KP_PSI=0.10), 1/20.0)
            for k in range(nt):
                o12 = compute_obs(p1, p2); o21 = compute_obs(p2, p1)
                if k % 20 == 0 and o12.ego_alt_ft > 2500:
                    feats_v.append(_feat(o12))
                t1 = pol.select(p1, p2)
                u1 = pu.step(p2, tactic=t1); u2 = po.step(p1, tactic=opp_fn(o21))
                p1.set_input(u1); p2.set_input(u2)
                for _ in range(n_ctrl): p1.step(1); p2.step(1)
    return np.array(feats_v, float)


def main():
    d = np.load(DS, allow_pickle=True)
    X, Y = d["X"], d["Y"]
    feats = list(d["feats"]); groups = d["archetypes"]
    opp_names = d["opp_names"]
    print(f"=== E4 커버리지 (train {X.shape[0]} 상태) ===\n")

    occupancy(X, feats)

    # (B) 배포 방문 분포 OOD
    print(f"\n(B) train 대 배포방문 분포:")
    try:
        Xv = deploy_visited()
        from sklearn.preprocessing import StandardScaler
        from sklearn.neighbors import NearestNeighbors
        sc = StandardScaler().fit(X)
        nn = NearestNeighbors(n_neighbors=1).fit(sc.transform(X))
        dist, _ = nn.kneighbors(sc.transform(Xv))
        thr = np.percentile(nn.kneighbors(sc.transform(X))[0], 99)  # train 자체 99분위
        ood = (dist.ravel() > thr).mean()
        print(f"    배포 방문 {len(Xv)} 상태, train 최근접거리 중앙값={np.median(dist):.2f}")
        print(f"    OOD 비율(train 99분위 초과) = {ood*100:.1f}%  "
              f"→ {'커버 양호' if ood < 0.1 else '커버 부족(holes)'}")
    except Exception as e:
        print(f"    [배포 방문 수집 스킵] {repr(e)[:80]}")

    # (C) 스케일링 곡선
    print(f"\n(C) 스케일링 — 적 수 vs leave-archetype-out regret:")
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import GroupKFold
    uniq_opp = sorted(set(opp_names.tolist()))
    rng = np.random.RandomState(0)
    for n_opp in [10, 30, 60, len(uniq_opp)]:
        sel = set(rng.choice(uniq_opp, size=min(n_opp, len(uniq_opp)), replace=False))
        mask = np.array([o in sel for o in opp_names])
        Xs, Ys, gs_ = X[mask], Y[mask], groups[mask]
        if len(set(gs_)) < 3:
            continue
        gkf = GroupKFold(n_splits=min(5, len(set(gs_))))
        regs = []
        for tr, te in gkf.split(Xs, Ys, gs_):
            rf = RandomForestRegressor(n_estimators=120, max_depth=10, min_samples_leaf=6,
                                       n_jobs=-1, random_state=0).fit(Xs[tr], Ys[tr])
            pr = rf.predict(Xs[te]).argmax(1)
            oracle = Ys[te].argmax(1); rows = np.arange(len(te))
            regs.append((Ys[te][rows, oracle] - Ys[te][rows, pr]).mean())
        print(f"    적 {n_opp:>3}종 ({mask.sum():>4} 상태): regret={np.mean(regs):.2f}")
    print(f"\n  해석: regret 이 적 수 늘며 평탄해지면 그 지점이 충분 커버리지.")


if __name__ == "__main__":
    main()
