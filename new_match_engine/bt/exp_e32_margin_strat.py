"""E32 — margin 층화 예측도. 38% argmax 예측도가 *history 필요* vs *near-tie 경계 noise* 판별.

이론: 미분게임 최적정책은 *고-margin 영역=crisp 특이면(상황 core)*, 저-margin=평활 blend(near-tie).
가설: 고-margin 상태만 보면 argmax(최적행동)가 *기하로 잘 예측됨* → crisp core는 깨끗한 상황,
     전체 38%는 저-margin tie noise가 끌어내린 것. (그럼 cost=crisp core 명시 + 중간 blend가 정답.)
반대로 고-margin도 안 오르면 → 순간기하 부족(=상태증강/history 필요)이 진짜 원인.
usage: python exp_e32_margin_strat.py [npz]
"""
from __future__ import annotations
import sys, os, warnings
warnings.filterwarnings("ignore")
import numpy as np
from collections import Counter
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import cross_val_score

HERE = os.path.dirname(__file__)


def main(npz="results_research_dagger.npz"):
    d = np.load(os.path.join(HERE, "..", npz), allow_pickle=True)
    X = d["X"].astype(float); Y = d["Y"].astype(float); tacs = [str(x) for x in d["tactics"]]
    opt = Y.argmax(axis=1)
    Ys = np.sort(Y, axis=1); margin = Ys[:, -1] - Ys[:, -2]
    print(f"데이터 {X.shape[0]} 상태 | margin 평균 {margin.mean():.1f} 중앙 {np.median(margin):.1f}")

    print(f"\n{'margin>':>8}{'n':>7}{'비율':>6}{'argmax CV acc':>14}{'최빈행동(순도)':>22}")
    for thr in [0, 2, 5, 10, 20, 35, 50]:
        m = margin > thr
        n = int(m.sum())
        if n < 200:
            print(f"{thr:>8}{n:>7}  (표본 부족)"); continue
        Xm, om = X[m], opt[m]
        clf = DecisionTreeClassifier(max_depth=5, min_samples_leaf=max(20, n // 60), random_state=0)
        acc = cross_val_score(clf, Xm, om, cv=4).mean()
        top_t, top_n = Counter(om).most_common(1)[0]
        print(f"{thr:>8}{n:>7}{100*n/len(opt):>5.0f}%{acc:>14.2f}"
              f"{tacs[top_t][:14]+f'({100*top_n/n:.0f}%)':>22}", flush=True)

    # 고-margin(>20) crisp core 들의 행동 분포 (진짜 상황 후보)
    m = margin > 20
    print(f"\n[고-margin(>20) crisp core 행동 분포 — 진짜 상황 후보] n={int(m.sum())}")
    for ti, n in Counter(opt[m]).most_common():
        if n < 0.02 * m.sum(): continue
        c = X[m & (opt == ti)].mean(axis=0)
        feats = ['ata', 'aa', 'hca', 'dist', 'closure', 'es_diff', 'ego_omega', 'opp_omega']
        tag = f"ata{c[0]:.0f} aa{c[1]:.0f} hca{c[2]:.0f} dist{c[3]:.0f} clos{c[4]:.0f} es{c[5]:.0f}"
        print(f"  {tacs[ti]:<16} {n:5d} ({100*n/m.sum():4.1f}%)  [{tag}]")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results_research_dagger.npz")
