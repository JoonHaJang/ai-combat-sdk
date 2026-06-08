"""E9 (S.4) — DAgger 재라벨: 배포 정책 방문 상태를 라벨해 train-deploy 분포 정합.

문제(U.10): 라벨은 GunTracker 에 TWO_CIRCLE(+10.2)가 최선임을 아는데, 배포 RF 는 매치에서
VERTICAL_PURSUIT 를 골라 무승부. 원인=배포 방문 상태가 학습분포와 어긋남(RQ4).
해법(Ross et al. 2011, DAgger): 현재 정책으로 매치를 돌려 그 정책이 방문하는 상태를 모으고,
그 상태를 forward-sim 으로 라벨(H=60, base=챔피언)해 기존 데이터에 합쳐 재학습.

usage: python exp_e9_dagger.py [n_iter]
출력: ../results_research_dagger.npz (floor + 방문상태 라벨 집계)
"""
from __future__ import annotations
import sys, os, glob, time, pickle
import numpy as np
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from obs import compute_obs
from tactic import Tactic
from pilot import Pilot
from offline_solver import _Sim, _feat, CANDS, FEATS, _AGGR
from real_rollout import _es_diff
from opponents import OPPONENT_BTS
from yaml_bt import load_bt
from scenarios import SITUATIONS

HERE = os.path.dirname(__file__)
FLOOR_NPZ = os.path.join(HERE, "..", "results_research_h60_floor.npz")
DRIVER_PKL = os.path.join(HERE, "policy_floor_driver.pkl")
CHAMP_PKL = os.path.join(HERE, "policy_value.pkl")
OUT = os.path.join(HERE, "..", "results_research_dagger.npz")


def _opp_jobs():
    jobs = [(n, None) for n in OPPONENT_BTS]
    for f in sorted(glob.glob(os.path.join(HERE, "..", "opponents", "zoo", "*.yaml"))):
        jobs.append((os.path.basename(f)[:-5], f))
    return jobs


def _archetype(n):
    return f"anchor_{n}" if n in OPPONENT_BTS else n.rsplit("_", 1)[0]


_WG = {}
def _winit(states, match_s, label_H, commit_s):
    _WG["gs"] = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    _WG["cfg"] = (states, match_s, label_H, commit_s)
    # 라벨 tail = 챔피언 fitted-Q
    from scaled_solver import _load_base
    _WG["base"] = _load_base(CHAMP_PKL)
    dd = pickle.load(open(DRIVER_PKL, "rb"))
    rg = dd["reg"]
    try: rg.n_jobs = 1
    except Exception: pass
    _WG["drv_reg"] = rg; _WG["drv_tac"] = dd["tactics"]
    _WG["spawns"] = dict(SITUATIONS)


def _hca(o):
    return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)


def _driver(p1, p2):
    """floor 배포 정책: feature→RF argmax (+ 안전 상승)."""
    o = compute_obs(p1, p2)
    if o.ego_alt_ft < 2500.0:
        return Tactic.CLIMB
    x = [[o.ata_deg, o.aa_deg, _hca(o), o.distance_ft, o.closure_kts,
          _es_diff(o), o.ego_r_dps, o.enm_r_dps]]
    return Tactic[_WG["drv_tac"][int(_WG["drv_reg"].predict(x)[0].argmax())]]


def _wjob(job):
    """배포 정책으로 매치 구동 → 방문 상태 샘플 + forward-sim 라벨."""
    spawn_name, opp_name, opp_path = job
    gs = _WG["gs"]; states, match_s, label_H, commit_s = _WG["cfg"]
    opp_fn = OPPONENT_BTS[opp_name] if opp_path is None else load_bt(opp_path)
    sim = _Sim(gs, H=label_H, commit_s=commit_s, base=_WG["base"])
    p1, p2 = _WG["spawns"][spawn_name]()
    pu = Pilot(p1, gs, _AGGR, 1/20.0); po = Pilot(p2, gs, AutopilotConfig(KP_PSI=0.10), 1/20.0)
    cdt = 0.05; nt = int(match_s/cdt); n_ctrl = 6; iv = max(1, nt // states)
    Xs, Ys = [], []
    for k in range(nt):
        o12 = compute_obs(p1, p2); o21 = compute_obs(p2, p1)
        if k % iv == 0 and o12.ego_alt_ft > 2500 and o12.distance_ft < 25000:
            su, sp = p1.capture_state(), p2.capture_state()
            scores = [sim.eval(su, sp, t, opp_fn) for t in CANDS]
            Xs.append(_feat(o12)); Ys.append(scores)
            p1.restore_state(su); p2.restore_state(sp)
        u1 = pu.step(p2, tactic=_driver(p1, p2))     # ★ 배포 정책이 구동
        u2 = po.step(p1, tactic=opp_fn(o21))
        p1.set_input(u1); p2.set_input(u2)
        for _ in range(n_ctrl): p1.step(1); p2.step(1)
        if compute_obs(p1,p2).ego_health<=0 or compute_obs(p2,p1).ego_health<=0: break
    return spawn_name, opp_name, Xs, Ys


def main(states=12, match_s=120.0, label_H=60.0, commit_s=4.0):
    n_proc = max(1, min(60, (os.cpu_count() or 4) - 2))
    jobs = _opp_jobs()
    spawn_names = list(SITUATIONS)
    alljobs = [(s, on, op) for s in spawn_names for (on, op) in jobs]
    print(f"=== E9 DAgger 수집 (배포 정책 구동) — 적 {len(jobs)} × spawn {len(spawn_names)} "
          f"= 매치 {len(alljobs)}, H{label_H:.0f}, {n_proc}병렬 ===")
    t0 = time.time(); X, Y, meta = [], [], []
    with ProcessPoolExecutor(max_workers=n_proc, initializer=_winit,
                             initargs=(states, match_s, label_H, commit_s)) as ex:
        done = 0
        for sn, on, Xs, Ys in ex.map(_wjob, alljobs):
            X.extend(Xs); Y.extend(Ys); meta.extend([(sn, on)] * len(Xs)); done += 1
            if done % 50 == 0: print(f"  {done}/{len(alljobs)} 매치, {len(X)} 방문상태...", flush=True)
    Xn, Yn = np.array(X, float), np.array(Y, float)
    print(f"  방문상태 {len(Xn)} 라벨 완료 ({(time.time()-t0)/60:.1f}분)")

    # 집계: floor + DAgger
    d0 = np.load(FLOOR_NPZ, allow_pickle=True)
    Xa = np.vstack([d0["X"], Xn]); Ya = np.vstack([d0["Y"], Yn])
    archs = np.concatenate([d0["archetypes"], np.array([_archetype(m[1]) for m in meta])])
    opps = np.concatenate([d0["opp_names"], np.array([m[1] for m in meta])])
    spw = np.concatenate([d0["spawns"], np.array([m[0] for m in meta])])
    np.savez(OUT, X=Xa, Y=Ya, feats=FEATS, tactics=[t.name for t in CANDS],
             archetypes=archs, opp_names=opps, spawns=spw)
    from collections import Counter
    bt = Counter([CANDS[i].name for i in Yn.argmax(1)])
    print(f"  집계: floor {len(d0['X'])} + DAgger {len(Xn)} = {len(Xa)} → {os.path.relpath(OUT)}")
    print(f"  DAgger 방문상태 best-tactic: {dict(bt.most_common())}")


if __name__ == "__main__":
    main()
