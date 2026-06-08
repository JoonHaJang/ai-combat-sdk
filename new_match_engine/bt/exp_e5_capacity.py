"""E5 (레드팀 갭1) — RQ1 공정화: 이산 대 연속이 '용량' 혼동이 아님을 보인다.

레드팀 지적: 이산(3상황)은 저용량 lookup, 연속 RF 는 고용량. 차이가 '이산이라서'인지
'용량이 작아서'인지 모른다. → 이산 군집 수 k 를 늘리며 regret 을 본다. k 가 커지면 이산이
연속에 수렴해야 한다(이산은 곧 조각상수 근사이므로). 수렴하면 연속 우위는 '용량'이지
'연속 자체'가 아니라는 정직한 결론.

usage: python exp_e5_capacity.py [dataset.npz]
"""
from __future__ import annotations
import sys, os, warnings
import numpy as np

warnings.filterwarnings("ignore")
DS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "results_research_dataset.npz")

from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import GroupKFold


def _regret(Yte, idx):
    o = Yte.argmax(1); r = np.arange(len(Yte))
    return (Yte[r, o] - Yte[r, idx]).mean()


def main():
    d = np.load(DS, allow_pickle=True)
    X, Y, groups = d["X"], d["Y"], d["archetypes"]
    print(f"=== E5 용량 공정화 (이산 k-군집 → 연속 수렴) {X.shape[0]} 상태 ===\n")
    gkf = GroupKFold(n_splits=min(5, len(set(groups))))

    print(f"  {'정책':<22}{'regret↓':>10}")
    print("  " + "-" * 32)
    # floor
    fl = []
    for tr, te in gkf.split(X, Y, groups):
        fl.append(_regret(Y[te], np.full(len(te), Y[tr].mean(0).argmax())))
    print(f"  {'floor(k=1)':<22}{np.mean(fl):>10.2f}")
    # 이산 k-군집
    for k in [3, 7, 15, 30, 60, 120]:
        accs = []
        for tr, te in gkf.split(X, Y, groups):
            sc = StandardScaler().fit(X[tr])
            km = KMeans(n_clusters=k, n_init=5, random_state=0).fit(sc.transform(X[tr]))
            best = {g: int(Y[tr][km.labels_ == g].mean(0).argmax())
                    for g in range(k) if (km.labels_ == g).any()}
            glob = int(Y[tr].mean(0).argmax())
            ce = km.predict(sc.transform(X[te]))
            idx = np.array([best.get(c, glob) for c in ce])
            accs.append(_regret(Y[te], idx))
        print(f"  {'이산 군집 k='+str(k):<22}{np.mean(accs):>10.2f}")
    # 연속 RF
    rf = []
    for tr, te in gkf.split(X, Y, groups):
        m = RandomForestRegressor(n_estimators=150, max_depth=10, min_samples_leaf=6,
                                  n_jobs=-1, random_state=0).fit(X[tr], Y[tr])
        rf.append(_regret(Y[te], m.predict(X[te]).argmax(1)))
    print(f"  {'연속(RF, k=무한)':<22}{np.mean(rf):>10.2f}")
    print(f"\n  해석: k↑ 일수록 이산 regret 이 연속에 수렴하면, 연속 우위의 본질은")
    print(f"        '용량(분해능)'이며 '이산 분류라는 형식 자체'가 불리한 게 아니다.")
    print(f"        실무 함의: 손으로 박은 소수 이산 상황(3~7개)은 분해능 부족으로 손해.")


if __name__ == "__main__":
    main()
