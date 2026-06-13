"""E31 — 상황을 *value 구조*로 재도출 (이론적 당위성). 상태 클러스터링(편향) 폐기.

이론(docs §0,§4.6): 상황 = 미분게임 가치 V의 *최적정책 region*(singular surface가 가름)
                  = MDP 행동-동치 분할(같은 최적행동=같은 상황). *데이터 밀도 아니라 최적행동 구조.*
방법: forward-sim value 라벨(Y, ≈게임가치)에서 최적 tactic argmax → feature공간에서 *그게 전환되는
     경계*를 DecisionTree로 추출(설명가능). 잎=행동-동질 region=상황, 분기=singular surface(읽히는 규칙).
판정: 구별되는 region 수 = 진짜 상황 개수. 5 맞나? scissors/in-WEZ/energy 등 추가 region 있나?
usage: python exp_e31_situation_rederive.py [max_depth] [npz]
"""
from __future__ import annotations
import sys, os, warnings
warnings.filterwarnings("ignore")
import numpy as np
from collections import Counter
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.model_selection import cross_val_score

HERE = os.path.dirname(__file__)


def main(max_depth=5, npz="results_research_dagger.npz"):
    d = np.load(os.path.join(HERE, "..", npz), allow_pickle=True)
    X = d["X"].astype(float); Y = d["Y"].astype(float)
    feats = [str(x) for x in d["feats"]]; tacs = [str(x) for x in d["tactics"]]
    opt = Y.argmax(axis=1)                                  # 각 상태 최적 tactic = 행동
    print(f"데이터 {X.shape[0]} 상태 × {len(tacs)} tactic | feats={feats}")

    # ── 최적행동 분포 (어느 tactic이 *최적 region*을 갖나 = control mode 후보) ──
    cnt = Counter(opt)
    print(f"\n[최적행동 분포 — region을 갖는 control mode]")
    for ti, n in cnt.most_common():
        print(f"  {tacs[ti]:<18} {n:6d} ({100*n/len(opt):4.1f}%)")
    n_modes = sum(1 for _, n in cnt.items() if n >= 0.01 * len(opt))   # ≥1% region
    print(f"  → 유의미(≥1%) control mode 수 = {n_modes}")

    # ── value 마진: 최적 vs 2nd (경계 근처 = 마진 작음 = singular surface) ──
    Ys = np.sort(Y, axis=1)
    margin = Ys[:, -1] - Ys[:, -2]
    print(f"\n[행동 마진] 최적-2nd 평균={margin.mean():.1f}, 마진<2(경계근처) {100*(margin<2).mean():.0f}%")

    # ── 설명가능 경계: DecisionTree(feature→최적행동). 잎=상황 region, 분기=singular surface ──
    clf = DecisionTreeClassifier(max_depth=max_depth, min_samples_leaf=max(30, len(X)//60),
                                 random_state=0).fit(X, opt)
    cv = cross_val_score(clf, X, opt, cv=4).mean()
    n_leaves = clf.get_n_leaves()
    print(f"\n[상황 경계 트리] depth={max_depth} 잎(region)={n_leaves} | argmax 설명 CV acc={cv:.2f}")
    print(f"[분리 feature 중요도] " + " ".join(
        f"{n}={v:.2f}" for n, v in sorted(zip(feats, clf.feature_importances_), key=lambda x:-x[1])))

    # 각 잎의 dominant 행동 = 그 region의 상황 라벨
    leaf_id = clf.apply(X)
    print(f"\n[region(잎)별 상황 = 최적행동, 크기순]")
    for lf, n in Counter(leaf_id).most_common():
        m = leaf_id == lf
        dom = Counter(opt[m]).most_common(1)[0]
        c = X[m].mean(axis=0)
        fd = {feats[i]: c[i] for i in range(len(feats))}
        tag = (f"ata{fd['ata']:.0f} aa{fd['aa']:.0f} hca{fd['hca']:.0f} "
               f"clos{fd['closure']:.0f} es{fd['es_diff']:.0f}")
        print(f"  region{lf:<4} n={n:5d}  최적={tacs[dom[0]]:<16} ({100*dom[1]/n:.0f}%순도)  [{tag}]")

    print(f"\n[읽히는 경계 규칙 (singular surface 후보, 상위)]")
    txt = export_text(clf, feature_names=feats, max_depth=3)
    # tactic 인덱스를 이름으로
    for i, t in enumerate(tacs):
        txt = txt.replace(f"class: {i}", f"→ {t}")
    print("\n".join(txt.splitlines()[:40]))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(int(a[0]) if a else 5, a[1] if len(a) > 1 else "results_research_dagger.npz")
