"""상황 클러스터링 — 손정의 상황이 데이터 자연 클러스터와 맞는지 + 몇 개가 맞는지.

★ 측정 먼저: CHASE/CIRCLE/DEFENSIVE(+on-to-on/chased)를 손으로 정하기 전에,
  engagement feature 공간을 클러스터링해 자연스러운 상황 개수·구조를 데이터로 확인.
방법: StandardScaler → KMeans(k 스윕, silhouette) → centroid 해석 + spawn 교차표.
"""
from __future__ import annotations
import os
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.decomposition import PCA
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(__file__)
CSV = os.path.join(HERE, "..", "results_situation_dataset.csv")

# 상황 기술 feature (적 무관 relational/물리). outcome/tactic 은 클러스터링서 제외.
FEATS = ["ata", "aa", "hca", "dist", "closure", "es_diff",
         "ego_omega", "opp_omega", "our_wez", "opp_wez"]


def main():
    df = pd.read_csv(CSV)
    X = df[FEATS].values.astype(float)
    Xs = StandardScaler().fit_transform(X)

    # ── k 스윕 (자연스러운 상황 개수 찾기) ──────────────────────────────
    print("k 스윕 (silhouette — 높을수록 자연스러운 분리):")
    best_k, best_s = 2, -1
    for k in range(2, 9):
        km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(Xs)
        s = silhouette_score(Xs, km.labels_, sample_size=min(1500, len(Xs)), random_state=0)
        print(f"  k={k}: silhouette={s:.3f}")
        if s > best_s:
            best_s, best_k = s, k
    print(f"  → 자연 클러스터 수 (최고 silhouette): k={best_k}")

    # ── best k 클러스터 해석 ────────────────────────────────────────────
    km = KMeans(n_clusters=best_k, n_init=10, random_state=0).fit(Xs)
    df["cluster"] = km.labels_
    print(f"\n클러스터별 평균 feature (k={best_k}) — BFM 상황 해석:")
    hdr = "clst  n   " + "".join(f"{f:>8}" for f in ["ata","aa","hca","dist","clos","es_d","our_wez","opp_wez"])
    print(hdr)
    for c in range(best_k):
        sub = df[df.cluster == c]
        m = sub[FEATS].mean()
        print(f"  {c}  {len(sub):>4} "
              f"{m['ata']:>8.0f}{m['aa']:>8.0f}{m['hca']:>8.0f}{m['dist']:>8.0f}"
              f"{m['closure']:>8.0f}{m['es_diff']:>8.0f}{m['our_wez']:>8.2f}{m['opp_wez']:>8.2f}")
        print(f"       → 해석: {_interpret(m)}")

    # ── spawn·손정의상황 교차표 ─────────────────────────────────────────
    print("\n클러스터 × spawn (어느 spawn 이 어느 클러스터로):")
    print(pd.crosstab(df.cluster, df.spawn))
    print("\n클러스터 × 손정의 situation (현재 분류기와 일치도):")
    print(pd.crosstab(df.cluster, df.situation))

    # ── PCA 2D 시각화 ───────────────────────────────────────────────────
    pca = PCA(n_components=2).fit(Xs)
    P = pca.transform(Xs)
    plt.figure(figsize=(9, 7))
    sc = plt.scatter(P[:, 0], P[:, 1], c=km.labels_, cmap="tab10", s=8, alpha=0.5)
    plt.colorbar(sc, label="cluster")
    plt.xlabel(f"PC1 ({pca.explained_variance_ratio_[0]*100:.0f}%)")
    plt.ylabel(f"PC2 ({pca.explained_variance_ratio_[1]*100:.0f}%)")
    plt.title(f"Engagement situation clusters (k={best_k}, silhouette={best_s:.2f})")
    out = os.path.join(HERE, "..", "results_situation_clusters.png")
    plt.savefig(out, dpi=90, bbox_inches="tight"); plt.close()
    print(f"\n시각화: {os.path.relpath(out)}")


def _interpret(m):
    """centroid 평균 → BFM 상황 라벨 추정."""
    ata, aa, hca, dist = m["ata"], m["aa"], m["hca"], m["dist"]
    ourw, oppw = m["our_wez"], m["opp_wez"]
    if oppw > ourw + 0.15 and aa > 100:
        return "CHASED (적이 우리 뒤 — 피추격/방어)"
    if ourw > oppw + 0.15 and aa < 80 and hca < 60:
        return "CHASE (우리가 적 뒤 정렬 — 추격)"
    if hca > 120 and ata < 60 and aa > 120:
        return "HEAD_ON / on-to-on (정면 상호조준)"
    if hca > 60:
        return "CIRCLE (교차 선회전)"
    return "NEUTRAL / 전환"


if __name__ == "__main__":
    main()
