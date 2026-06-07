"""E1 (RQ1) — 이산 상황분류 대 연속 가치학습.

질문: BFM tactic 선택에 명시적 이산 분류가 필요한가, 아니면 연속 가치회귀가 동등 이상인가.
방법:
  (A) feature 공간 군집 구조 — KMeans silhouette vs k. 이산 구조가 실재하나.
  (B) 세 정책을 같은 데이터/분리로 regret 비교 (손-규칙 없이 순수 비교):
      - 연속:      RandomForest 가치회귀 argmax
      - 이산(손):  classify(ata,aa,hca,dist)→{CHASE/CIRCLE/DEFENSIVE} 별 최적 tactic 고정
      - 이산(데이터): KMeans(k) 군집 별 최적 tactic 고정
      - floor:     전체 단일 최적 tactic
  누수 방지: archetype 단위 GroupKFold.
지표: regret(우선), top-1.  regret 0 = oracle.

usage: python exp_e1_situation.py [dataset.npz]
"""
from __future__ import annotations
import sys, os, warnings
import numpy as np

warnings.filterwarnings("ignore")
DS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "results_research_dataset.npz")

from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import GroupKFold

# FEATS = [ata, aa, hca, dist, closure, es_diff, ego_omega, opp_omega]
I_ATA, I_AA, I_HCA, I_DIST = 0, 1, 2, 3


def classify_feat(x):
    """situation.py classify 를 feature 에서 재현 → 0=DEFENSIVE,1=CHASE,2=CIRCLE."""
    ata, aa, hca, dist = x[I_ATA], x[I_AA], x[I_HCA], x[I_DIST]
    if dist < 4000.0 and aa > 110.0:
        return 0
    if hca < 45.0 and aa < 90.0:
        return 1
    return 2


def _regret_top1(Yte, chosen_idx):
    oracle = Yte.argmax(1)
    rows = np.arange(len(Yte))
    regret = (Yte[rows, oracle] - Yte[rows, chosen_idx]).mean()
    top1 = (oracle == chosen_idx).mean()
    return regret, top1


def _group_best(Ytr, labels_tr, n_groups):
    """그룹별 평균 가치 최대 tactic. 빈 그룹은 전체 최적."""
    glob = Ytr.mean(0).argmax()
    best = {}
    for g in range(n_groups):
        m = labels_tr == g
        best[g] = int(Ytr[m].mean(0).argmax()) if m.sum() > 0 else int(glob)
    return best


def main():
    d = np.load(DS, allow_pickle=True)
    X, Y = d["X"], d["Y"]
    groups = d["archetypes"]
    tactics = list(d["tactics"])
    print(f"=== E1 이산 대 연속 (데이터 {X.shape[0]} 상태) ===\n")

    # (A) 군집 구조
    Xs = StandardScaler().fit_transform(X)
    print("(A) feature 공간 군집 구조 (KMeans silhouette):")
    sil = {}
    for k in range(2, 9):
        km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(Xs)
        sil[k] = silhouette_score(Xs, km.labels_)
        print(f"    k={k}: silhouette={sil[k]:.3f}")
    best_k = max(sil, key=sil.get)
    print(f"    → 최고 silhouette k={best_k} ({sil[best_k]:.3f}). "
          f"{'뚜렷한 이산 구조' if sil[best_k] > 0.5 else '약한/연속적 구조'}")

    # 손-분류 분포
    hand = np.array([classify_feat(x) for x in X])
    names = {0: "DEFENSIVE", 1: "CHASE", 2: "CIRCLE"}
    from collections import Counter
    print(f"\n    손-분류 분포: " + ", ".join(f"{names[g]}:{c}" for g, c in sorted(Counter(hand).items())))

    # (B) 세 정책 regret 비교 (archetype GroupKFold)
    print(f"\n(B) 정책 regret 비교 (leave-archetype-out GroupKFold):")
    gkf = GroupKFold(n_splits=min(5, len(set(groups))))
    acc = {"floor(단일)": [], "이산(손3)": [], f"이산(군집{best_k})": [], "연속(RF)": []}
    acct = {k: [] for k in acc}
    for tr, te in gkf.split(X, Y, groups):
        # floor
        gb = Y[tr].mean(0).argmax()
        r, t = _regret_top1(Y[te], np.full(len(te), gb))
        acc["floor(단일)"].append(r); acct["floor(단일)"].append(t)
        # 이산(손)
        ht = np.array([classify_feat(x) for x in X[tr]])
        hb = _group_best(Y[tr], ht, 3)
        he = np.array([hb[classify_feat(x)] for x in X[te]])
        r, t = _regret_top1(Y[te], he)
        acc["이산(손3)"].append(r); acct["이산(손3)"].append(t)
        # 이산(데이터 군집)
        sc = StandardScaler().fit(X[tr])
        km = KMeans(n_clusters=best_k, n_init=10, random_state=0).fit(sc.transform(X[tr]))
        cb = _group_best(Y[tr], km.labels_, best_k)
        ce = km.predict(sc.transform(X[te]))
        ce = np.array([cb[c] for c in ce])
        r, t = _regret_top1(Y[te], ce)
        acc[f"이산(군집{best_k})"].append(r); acct[f"이산(군집{best_k})"].append(t)
        # 연속
        rf = RandomForestRegressor(n_estimators=150, max_depth=10, min_samples_leaf=6,
                                   n_jobs=-1, random_state=0).fit(X[tr], Y[tr])
        pr = rf.predict(X[te]).argmax(1)
        r, t = _regret_top1(Y[te], pr)
        acc["연속(RF)"].append(r); acct["연속(RF)"].append(t)

    print(f"\n  {'정책':<16}{'regret↓':>10}{'top1↑':>9}")
    print("  " + "-" * 35)
    for k in acc:
        print(f"  {k:<16}{np.mean(acc[k]):>10.2f}{np.mean(acct[k]):>9.3f}")
    print(f"\n  해석: 연속 regret < 이산 regret 이면 연속 가치학습이 우위 (RQ1).")


if __name__ == "__main__":
    main()
