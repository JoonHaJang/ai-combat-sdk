"""스케일 오프라인 Solver — 970 legacy 적 stratified 샘플 × 다양 spawn → MC 라벨 → 정책.

★ 사용자가 직접 실행(긴 작업). 결과: 데이터셋·정책 파일 저장 + 요약 출력(붙여넣기용).
사용:
    python scaled_solver.py [N_OPP] [STATES_PER_MATCH] [MATCH_S]
    예) python scaled_solver.py 60 20 90     # 적60종 stratified, 매치당 20상태, 90s
기본: 적48 × spawn4 × 상태20 ≈ 3840 라벨상태 (상태당 8tactic×6s sim).

산출:
  ../results_scaled_dataset.npz   — X(feature), Y(tactic별 점수), meta
  policy_value.pkl                — value 회귀 정책 (tree_policy.py 가 로드)
출력 요약: 데이터 규모, tactic 분포, CV R², feature 중요도, 정책 빠른검증 win-rate.
"""
from __future__ import annotations
import sys, os, glob, math, warnings
warnings.filterwarnings("ignore")        # sklearn/joblib UserWarning 억제
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

import numpy as np
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from pilot import Pilot
from match import Match
from scenarios import SITUATIONS, spawn_adt_neutral, diverse_spawns_sampled
from obs import compute_obs
from tactic import Tactic
from opponents import OPPONENT_BTS
from yaml_bt import load_bt
from offline_solver import _Sim, _feat, FEATS, CANDS, _AGGR
from tactic import MATCH_DURATION_S    # 300s (5분, legacy 표준)
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import cross_val_score

PROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _stratified_opponents(n_opp=48):
    """970 stratified 샘플 → [(이름, yaml경로 or None)]. (함수 아님 — 멀티프로세싱 pickle용)
       손포팅4(path=None) + archetype 카테고리별 + opponent_pool 균등."""
    jobs = [(n, None) for n in OPPONENT_BTS]      # 손포팅 4 (simple/agg/def/ace)
    arch = sorted(glob.glob(os.path.join(PROOT, "examples", "archetypes", "*.yaml")))
    pool = sorted(glob.glob(os.path.join(PROOT, "examples", "opponent_pool", "*.yaml")))
    cats = {}
    for f in arch:
        cat = os.path.basename(f).replace("arch_", "").rsplit("_", 1)[0]
        cats.setdefault(cat, []).append(f)
    per_cat = max(1, (n_opp // 2) // max(1, len(cats)))
    for cat, files in cats.items():
        for f in files[::max(1, len(files)//per_cat)][:per_cat]:
            jobs.append((os.path.basename(f)[:-5], f))
    need = n_opp - len(jobs)
    if need > 0 and pool:
        for f in pool[::max(1, len(pool)//need)][:need]:
            jobs.append((os.path.basename(f)[:-5], f))
    return jobs


def _load_base(path):
    """policy_base.pkl → base 정책 callable(p1,p2)→Tactic. 없으면 None(→pursuit fallback)."""
    if not path or not os.path.exists(path):
        return None
    import pickle
    from real_rollout import _es_diff
    with open(path, "rb") as f:
        d = pickle.load(f)
    reg = d["reg"]; tacs = d["tactics"]
    try: reg.n_jobs = 1          # 단일 predict — joblib subprocess 경고·오버헤드 방지
    except Exception: pass
    def _hca(o):
        return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)
    def base(p1, p2):
        o = compute_obs(p1, p2)
        if o.ego_alt_ft < 2500.0:
            return Tactic.CLIMB
        x = [[o.ata_deg, o.aa_deg, _hca(o), o.distance_ft, o.closure_kts,
              _es_diff(o), o.ego_r_dps, o.enm_r_dps]]
        return Tactic[tacs[int(reg.predict(x)[0].argmax())]]
    return base


def _run_one(gs, spawn_fn, opp_fn, states_per_match, match_s, label_H, commit_s, base):
    """1 매치 — 상태 샘플 + ★fitted-Q 라벨(짧은 commit + base 정책). (worker 내부)."""
    sim = _Sim(gs, H=label_H, commit_s=commit_s, base=base)
    p1, p2 = spawn_fn()
    cdt = 0.05; nt = int(match_s/cdt); n_ctrl = 6
    pu = Pilot(p1, gs, _AGGR, 1/20.0); po = Pilot(p2, gs, AutopilotConfig(KP_PSI=0.10), 1/20.0)
    sample_iv = max(1, nt // states_per_match)
    cur = Tactic.PURE_PURSUIT
    Xs, Ys = [], []
    for k in range(nt):
        o12 = compute_obs(p1, p2); o21 = compute_obs(p2, p1)
        if k % sample_iv == 0 and o12.ego_alt_ft > 2500 and o12.distance_ft < 25000:
            snap_us, snap_op = p1.capture_state(), p2.capture_state()
            scores = [sim.eval(snap_us, snap_op, t, opp_fn) for t in CANDS]
            Xs.append(_feat(o12)); Ys.append(scores)
            p1.restore_state(snap_us); p2.restore_state(snap_op)
            cur = CANDS[int(np.argmax(scores))]
        u1 = pu.step(p2, tactic=(Tactic.CLIMB if o12.ego_alt_ft < 2500 else cur))
        u2 = po.step(p1, tactic=opp_fn(o21))
        p1.set_input(u1); p2.set_input(u2)
        for _ in range(n_ctrl): p1.step(1); p2.step(1)
        if compute_obs(p1,p2).ego_health<=0 or compute_obs(p2,p1).ego_health<=0: break
    return Xs, Ys


# ── 멀티프로세싱 worker (매치 독립 → 병렬) ─────────────────────────────────
_WG = {}
def _spawns_for(n_spawns, seed=0):
    """n_spawns>0 → LHS sampled diverse spawn, else canonical 4. (결정론 — worker 재생성용)"""
    return diverse_spawns_sampled(n_spawns, seed) if n_spawns > 0 else dict(SITUATIONS)

def _winit(states, match_s, label_H, n_spawns, seed, commit_s, base_path):
    _WG["gs"] = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    _WG["cfg"] = (states, match_s, label_H, commit_s)
    _WG["spawns"] = _spawns_for(n_spawns, seed)      # 동일 seed → 동일 spawn 재생성
    _WG["base"] = _load_base(base_path)              # fitted-Q: 직전 정책으로 tail 이어감

def _wjob(job):
    spawn_name, opp_name, opp_path = job
    spawn_fn = _WG["spawns"][spawn_name]
    opp_fn = OPPONENT_BTS[opp_name] if opp_path is None else load_bt(opp_path)
    states, match_s, label_H, commit_s = _WG["cfg"]
    Xs, Ys = _run_one(_WG["gs"], spawn_fn, opp_fn, states, match_s, label_H, commit_s, _WG["base"])
    return spawn_name, opp_name, Xs, Ys


def collect_scaled(opp_jobs, states_per_match, match_s, label_H, n_proc, n_spawns,
                   commit_s, base_path, seed=0):
    """opp_jobs=[(opp_name,opp_path)]. spawn(n_spawns 종)×opp 병렬 매치."""
    from concurrent.futures import ProcessPoolExecutor
    spawn_names = list(_spawns_for(n_spawns, seed))
    jobs = [(s, on, op) for s in spawn_names for (on, op) in opp_jobs]
    X, Y, meta = [], [], []
    done = 0
    with ProcessPoolExecutor(max_workers=n_proc, initializer=_winit,
                             initargs=(states_per_match, match_s, label_H, n_spawns, seed,
                                       commit_s, base_path)) as ex:
        for spawn_name, opp_name, Xs, Ys in ex.map(_wjob, jobs):
            X.extend(Xs); Y.extend(Ys); meta.extend([(spawn_name, opp_name)] * len(Xs))
            done += 1
            if done % 20 == 0 or done == len(jobs):
                print(f"  진행 {done}/{len(jobs)} 매치, 누적 {len(X)} 상태...", flush=True)
    return np.array(X, float), np.array(Y, float), meta


def main(n_opp=48, states_per_match=30, match_s=MATCH_DURATION_S, label_H=60.0,
         n_spawns=64, commit_s=4.0, n_proc=None):
    if n_proc is None:
        n_proc = max(1, min(60, (os.cpu_count() or 4) - 2))   # Windows 제한 ≤61
    here = os.path.dirname(__file__)
    # ★ fitted-Q: 직전 정책을 base 로 snapshot (tail 이어가기용). 없으면 pursuit fallback.
    import shutil
    pv = os.path.join(here, "policy_value.pkl"); base_path = os.path.join(here, "policy_base.pkl")
    if os.path.exists(pv):
        shutil.copy(pv, base_path)
        base_str = "직전 정책(fitted-Q)"
    else:
        base_path = None; base_str = "없음→PURE_PURSUIT fallback"
    opp_jobs = _stratified_opponents(n_opp)
    n_sp = n_spawns if n_spawns > 0 else len(SITUATIONS)
    print(f"=== 스케일 Solver: 적 {len(opp_jobs)}종 × spawn {n_sp}종(LHS) × 상태 {states_per_match}"
          f"  (match {match_s:.0f}s, 라벨 H {label_H:.0f}s, commit {commit_s:.0f}s+base={base_str}, {n_proc}병렬) ===")
    print(f"  → 매치 {len(opp_jobs)*n_sp}건, 예상 라벨상태 ~{len(opp_jobs)*n_sp*states_per_match}")
    print(f"  적 샘플(앞 12): {[n for n,_ in opp_jobs][:12]}")
    X, Y, meta = collect_scaled(opp_jobs, states_per_match, match_s, label_H, n_proc,
                                n_spawns, commit_s, base_path)
    np.savez(os.path.join(os.path.dirname(__file__), "..", "results_scaled_dataset.npz"),
             X=X, Y=Y, feats=FEATS, tactics=[t.name for t in CANDS])

    argmax_t = [CANDS[i].name for i in np.argmax(Y, axis=1)]
    import collections
    print(f"\n총 {len(X)} 라벨상태. argmax tactic 분포:")
    for t, c in collections.Counter(argmax_t).most_common():
        print(f"  {t:<14} {c}")

    # ★ 상황 균형 — 상태가 CHASE/CIRCLE에 쏠림(DEFENSIVE 희소). 역빈도 sample_weight.
    aa, hca, dist = X[:, 1], X[:, 2], X[:, 3]
    sit = np.where((dist < 4000) & (aa > 110), "DEF",
          np.where((hca < 45) & (aa < 90), "CHASE", "CIRCLE"))
    cnt = collections.Counter(sit)
    print(f"  상황 분포: {dict(cnt)}")
    w = np.array([1.0 / cnt[s] for s in sit]); w *= len(w) / w.sum()   # 역빈도 정규화

    reg = RandomForestRegressor(n_estimators=150, max_depth=10, min_samples_leaf=6,
                                random_state=0, n_jobs=-1)
    cv = cross_val_score(reg, X, Y, cv=5, scoring="r2")
    reg.fit(X, Y, sample_weight=w)               # ★ 균형 가중 학습
    print(f"\nValue 회귀 RandomForest: CV R²={cv.mean():.3f}±{cv.std():.3f} (균형 가중 학습)")
    print("feature 중요도:", {f: round(i, 3) for f, i in zip(FEATS, reg.feature_importances_)})

    import pickle
    with open(os.path.join(os.path.dirname(__file__), "policy_value.pkl"), "wb") as f:
        pickle.dump({"reg": reg, "feats": FEATS, "tactics": [t.name for t in CANDS]}, f)
    print("\n저장: ../results_scaled_dataset.npz, policy_value.pkl")
    print("→ 검증: python tree_policy.py")


if __name__ == "__main__":
    a = sys.argv
    main(int(a[1]) if len(a) > 1 else 48,        # 적 종수
         int(a[2]) if len(a) > 2 else 30,        # 매치당 상태 샘플
         float(a[3]) if len(a) > 3 else MATCH_DURATION_S,  # 매치 길이(5분)
         float(a[4]) if len(a) > 4 else 60.0,    # 라벨 H (commit + base tail 총길이)
         int(a[5]) if len(a) > 5 else 64,        # spawn 종수(LHS)
         float(a[6]) if len(a) > 6 else 4.0)     # ★ commit_s (T 강제 후 base 정책 이어감 = fitted-Q)
