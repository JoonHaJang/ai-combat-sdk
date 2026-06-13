"""데이터 기반 ADAPTIVE 설계 결정 — dagger 데이터(상태×per-tactic 데미지×115적)에서
상황 분할 + per-situation 최적 action + regret(기존 tactic 전멸=신규능력 필요처)을 도출.

목적: doctrine 손분할이 아니라 *데이터가* 상황 개수·경계·per-situation 정답·갭을 결정.
출력: silhouette k 스윕 → 채택 k의 클러스터별 [centroid(물리해석) · 최적tactic · 평균가치 · regret].
usage: python exp_situation_design.py [k]
"""
from __future__ import annotations
import sys, os, warnings
warnings.filterwarnings("ignore")
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

HERE = os.path.dirname(__file__)
DS = os.path.join(HERE, "..", "results_research_dagger.npz")


def _label(c, feats):
    """centroid 물리 해석 → 상황 이름 (ata,aa,hca,dist,closure 기준)."""
    f = {n: c[i] for i, n in enumerate(feats)}
    ata, aa, hca, dist, clos = f["ata"], f["aa"], f["hca"], f["dist"], f["closure"]
    tags = []
    if aa > 110 and dist < 4000: tags.append("DEFENSIVE(적 뒤)")
    elif ata < 35 and aa < 90: tags.append("OFFENSIVE(우리 뒤·정렬)")
    if ata < 45 and aa < 45 and dist > 5000: tags.append("MERGE/HEADON")
    if hca < 45: tags.append("1circle/CHASE(정렬)")
    elif hca > 120: tags.append("2circle/RATE(교차)")
    if clos < -30 and dist > 5000: tags.append("EXTEND(이탈)")
    if dist < 3000 and ata < 20: tags.append("WEZ근접")
    return ", ".join(tags) or "중립/flux"


def main(kfix=None):
    d = np.load(DS, allow_pickle=True)
    X = d["X"].astype(float); Y = d["Y"].astype(float)
    feats = [str(x) for x in d["feats"]]; tacs = [str(x) for x in d["tactics"]]
    print(f"데이터: {X.shape[0]} 상태 × {Y.shape[1]} tactic × {len(set(d['opp_names']))}적")
    Xs = StandardScaler().fit_transform(X)

    print("\n[k 스윕 — silhouette(자연 분리도)]")
    best_k, best_s = 2, -1
    for k in range(2, 10):
        km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(Xs)
        s = silhouette_score(Xs, km.labels_, sample_size=min(2000, len(Xs)), random_state=0)
        print(f"  k={k}: {s:.3f}")
        if s > best_s: best_s, best_k = s, k
    k = kfix or best_k
    print(f"\n채택 k={k} (silhouette 최대={best_s:.3f}{' 또는 지정' if kfix else ''})")

    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(Xs)
    lab = km.labels_
    # 전역 best-possible(각 상태 max tactic) → regret 기준
    best_per_state = Y.max(axis=1)

    print(f"\n{'클러스터':<8}{'n':>6}{'최적tactic':<16}{'평균가치':>8}{'2nd':<14}{'best값평균':>9}{'무능%':>7}  centroid 해석")
    rows = []
    for c in range(k):
        m = lab == c
        n = int(m.sum())
        meanY = Y[m].mean(axis=0)                      # 클러스터 내 tactic별 평균 데미지
        order = np.argsort(-meanY)
        best_t, second_t = tacs[order[0]], tacs[order[1]]
        bestval = best_per_state[m].mean()             # 이 상황 best-possible 평균
        useless = float((best_per_state[m] < 5.0).mean()) * 100   # best조차 <5dmg = 무능 상태%
        cent = X[m].mean(axis=0)
        rows.append((c, n, best_t, meanY[order[0]], second_t, bestval, useless, _label(cent, feats)))
    # regret 큰(무능% 높은) 순 = 신규능력 필요처
    for (c, n, bt, bv, st, bestval, useless, lbl) in sorted(rows, key=lambda r: -r[6]):
        print(f"  c{c:<5}{n:>6}{bt:<16}{bv:>8.1f}{st:<14}{bestval:>9.1f}{useless:>6.0f}%  {lbl}")

    print("\n해석 가이드:")
    print("  · 최적tactic/2nd = 그 상황 데이터가 고른 정답 → per-situation cost 설계 근거")
    print("  · best값평균 낮음 + 무능% 높음 = 기존 10 tactic으로 *어떤 것도* 못 이기는 상황 = ★신규능력(LEAD_TURN/virtual-point) 필요처")
    # feature 중요도 (어느 obs가 상황 가르나) = 클러스터 분산설명
    from sklearn.ensemble import RandomForestClassifier
    rf = RandomForestClassifier(n_estimators=80, random_state=0).fit(X, lab)
    imp = sorted(zip(feats, rf.feature_importances_), key=lambda x: -x[1])
    print("\n[상황 분리 feature 중요도] " + " ".join(f"{n}={v:.2f}" for n, v in imp))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(int(a[0]) if a else None)
