"""E3 (RQ3) — 정책 모델 프런티어 비교.

후보: XGBoost(정확도 천장), EBM(글래스박스), FIGS(최대 투명, GOSDT 대체)
참조선: RandomForest(incumbent), Ridge(linear floor)

타깃: feature 8 → tactic 점수 벡터 (multi-output 가치회귀).
평가(배포 결정 우선): regret(우선), balanced top-1, 가치 R2(회귀형만 보조).
누수 방지: archetype 단위 GroupKFold (leave-archetype-out 일반화).
근거: regret = oracle best 가치 − 모델 argmax 가치 (배포에 유일하게 중요한 결정 품질).

usage: python exp_e3_models.py [dataset.npz]
"""
from __future__ import annotations
import sys, os, time, warnings
import numpy as np

warnings.filterwarnings("ignore")
DS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "results_research_dataset.npz")

from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.multioutput import MultiOutputRegressor
from sklearn.model_selection import GroupKFold
from sklearn.inspection import permutation_importance
import xgboost as xgb
from interpret.glassbox import ExplainableBoostingRegressor
from imodels import FIGSRegressor


def _models():
    return {
        "Ridge(linear)":   lambda: MultiOutputRegressor(Ridge(alpha=1.0)),
        "RandomForest":    lambda: RandomForestRegressor(n_estimators=150, max_depth=10,
                                                         min_samples_leaf=6, n_jobs=-1, random_state=0),
        "XGBoost":         lambda: xgb.XGBRegressor(n_estimators=300, max_depth=5,
                                                    learning_rate=0.05, subsample=0.8,
                                                    colsample_bytree=0.8, n_jobs=-1,
                                                    random_state=0, multi_strategy="multi_output_tree"),
        "EBM(glassbox)":   lambda: MultiOutputRegressor(
            ExplainableBoostingRegressor(interactions=0, random_state=0), n_jobs=-1),
        "FIGS(rules)":     lambda: MultiOutputRegressor(FIGSRegressor(max_rules=15), n_jobs=-1),
    }


def _decision_metrics(Yte, pred):
    """regret, top-1, balanced top-1."""
    oracle = Yte.argmax(1)
    chosen = pred.argmax(1)
    top1 = (oracle == chosen).mean()
    # regret = 선택 tactic 가치와 oracle 가치의 차 (참 가치 기준)
    rows = np.arange(len(Yte))
    regret = (Yte[rows, oracle] - Yte[rows, chosen]).mean()
    # balanced top-1: oracle class 별 recall 평균
    recalls = []
    for c in np.unique(oracle):
        m = oracle == c
        if m.sum() > 0:
            recalls.append((chosen[m] == c).mean())
    bal = float(np.mean(recalls)) if recalls else 0.0
    return regret, top1, bal


def main():
    d = np.load(DS, allow_pickle=True)
    X, Y = d["X"], d["Y"]
    feats = list(d["feats"]); tactics = list(d["tactics"])
    groups = d["archetypes"] if "archetypes" in d.files else np.zeros(len(X))
    print(f"=== E3 모델 프런티어 (데이터 {X.shape[0]} 상태 × {X.shape[1]} feat → {Y.shape[1]} tactic) ===")
    print(f"  archetype 그룹 {len(set(groups))}종, GroupKFold(leave-archetype-out)\n")

    n_splits = min(5, len(set(groups)))
    gkf = GroupKFold(n_splits=n_splits)
    rng_oracle_regret = None

    results = {}
    for name, mk in _models().items():
        regs, t1s, bals, r2s, fits = [], [], [], [], []
        try:
            for tr, te in gkf.split(X, Y, groups):
                m = mk()
                t0 = time.time()
                m.fit(X[tr], Y[tr]); fits.append(time.time() - t0)
                pred = m.predict(X[te])
                rg, t1, bal = _decision_metrics(Y[te], pred)
                regs.append(rg); t1s.append(t1); bals.append(bal)
                ss_res = ((Y[te] - pred) ** 2).sum()
                ss_tot = ((Y[te] - Y[te].mean(0)) ** 2).sum()
                r2s.append(1 - ss_res / ss_tot)
            results[name] = dict(regret=np.mean(regs), top1=np.mean(t1s),
                                 bal=np.mean(bals), r2=np.mean(r2s), fit=np.mean(fits))
            print(f"  [done] {name:<16} regret={np.mean(regs):.2f} top1={np.mean(t1s):.3f} "
                  f"bal={np.mean(bals):.3f} R2={np.mean(r2s):.3f} ({np.mean(fits):.1f}s/fit)", flush=True)
        except Exception as e:
            print(f"  [FAIL] {name}: {repr(e)[:90]}", flush=True)

    # oracle 기준선: 항상 oracle 선택 = regret 0; 무작위/다수결 비교
    maj = np.bincount(Y.argmax(1), minlength=Y.shape[1]).argmax()
    rows = np.arange(len(Y))
    maj_regret = (Y[rows, Y.argmax(1)] - Y[rows, maj]).mean()
    maj_top1 = (Y.argmax(1) == maj).mean()

    print(f"{'model':<16}{'regret↓':>9}{'top1↑':>8}{'bal_top1↑':>10}{'value_R2↑':>10}{'fit(s)':>8}")
    print("-" * 61)
    print(f"{'(다수결 floor)':<16}{maj_regret:>9.2f}{maj_top1:>8.3f}{'-':>10}{'-':>10}{'-':>8}")
    for name, r in results.items():
        print(f"{name:<16}{r['regret']:>9.2f}{r['top1']:>8.3f}{r['bal']:>10.3f}"
              f"{r['r2']:>10.3f}{r['fit']:>8.2f}")

    # permutation 중요도 (RandomForest, 전체 적합 후)
    print(f"\n permutation 중요도 (RandomForest, 전체데이터):")
    rf = RandomForestRegressor(n_estimators=150, max_depth=10, min_samples_leaf=6,
                               n_jobs=-1, random_state=0).fit(X, Y)
    pi = permutation_importance(rf, X, Y, n_repeats=5, random_state=0, n_jobs=-1)
    imp = sorted(zip(feats, pi.importances_mean), key=lambda x: -x[1])
    for f, v in imp:
        print(f"   {f:<10} {v:.3f}")
    # impurity 중요도도 (비교)
    print(f" impurity 중요도 (RandomForest):")
    for f, v in sorted(zip(feats, rf.feature_importances_), key=lambda x: -x[1]):
        print(f"   {f:<10} {v:.3f}")


if __name__ == "__main__":
    main()
