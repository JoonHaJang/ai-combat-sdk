"""E48 — 적-유형 classifier 1단계: 초기창 *형상 특징*으로 A3·D2가 15와 분리되나 (반증가능 검증).

9번 threshold 실패 ≠ 형상분류 실패. 차이: 단일 순간값이 아니라 *초기창(0~T_win)의 궤적 형상 벡터*.
특징: range 기울기/재이탈/rmin, LOS sweep(orbit지표), 적 선회 mean/std, aa_min(꼬리잡았나), closure부호.
{A3,D2} vs 나머지15 분리되면 → classifier 가능. 안 되면 조기 구분 원천불가(정직 보고).
base ADAPTIVE 하 추출. usage: python exp_e48_type_features.py [T_win]
"""
from __future__ import annotations
import sys, os, math, warnings
import statistics as st
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))

from exp_e22_chaseforce import _opp
from exp_e27_adaptive_subset import AdaptivePolicy
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from obs import compute_obs
from exp_e7_champion import _train
from exp_e10_unified import DS_DA

FULL = ["anchor_simple", "anchor_aggressive", "anchor_defensive", "anchor_ace",
        "A1_PurePursuer", "A2_GunTracker", "A3_LagAngler", "B1_EnergyFighter", "B2_Extender",
        "C1_TwoCircleRate", "C2_OneCircleRad", "C3_Lufbery", "D1_Reactive", "D2_LastDitch",
        "D3_Scissors", "E1_AdaptiveAce", "E2_Passive"]
DRAWS = {"A3_LagAngler", "D2_LastDitch"}


def _slope(ys):
    n = len(ys); xs = list(range(n))
    mx = sum(xs) / n; my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs) or 1.0
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / den


def feats(opp, rf, tac, gs, cfg, T_win):
    p1, p2 = spawn_adt_neutral(); ap = AdaptivePolicy(rf, tac, corrections=True)
    R = []; AA = []; ROPP = []; BEAR = []; CLOS = []
    rec = {"t": 0.0}
    def fn(o):
        ob = compute_obs(p1, p2); rec["t"] += 0.1
        if rec["t"] <= T_win:
            R.append(ob.distance_ft); AA.append(ob.aa_deg); ROPP.append(abs(ob.enm_r_dps))
            BEAR.append(ob.rel_b_deg); CLOS.append(ob.closure_kts)
        return ap.select(p1, p2)
    m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
              control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
    res = m.run(tactic_fn1=lambda o: fn(o), tactic_fn2=lambda o: _opp(opp)(compute_obs(p2, p1)), duration_s=max(T_win + 5, 60))
    rmin = min(R); rmin_i = R.index(rmin)
    reopen = R[-1] - rmin                                   # 최저후 재이탈량
    sweep = sum(abs(((BEAR[i] - BEAR[i - 1]) + 180) % 360 - 180) for i in range(1, len(BEAR)))
    return {
        "rslope": _slope(R),                               # range 기울기(+열림/-닫힘)
        "rmin": rmin, "reopen": reopen,                    # 최접근·재이탈
        "sweep": sweep,                                    # LOS 총 sweep(orbit)
        "ropp_m": st.mean(ROPP), "ropp_sd": st.pstdev(ROPP),
        "aa_min": min(AA),                                 # 최소 aspect(꼬리 잡았나)
        "clneg": sum(1 for c in CLOS if c < 0) / len(CLOS),  # 멀어진 시간비
    }


def main(T_win=50.0):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    print(f"=== E48 초기창 {T_win:.0f}s 형상 특징 (★=무승부 A3/D2) ===", flush=True)
    hdr = f"{'opp':<18}{'★':<2}{'rslope':>8}{'rmin':>7}{'reopen':>8}{'sweep':>7}{'ropp_m':>7}{'aa_min':>7}{'clneg':>6}"
    print(hdr, flush=True)
    rows = {}
    for opp in FULL:
        f = feats(opp, rf, tac, gs, cfg, T_win); rows[opp] = f
        mark = "★" if opp in DRAWS else ""
        print(f"{opp:<18}{mark:<2}{f['rslope']:>8.1f}{f['rmin']:>7.0f}{f['reopen']:>8.0f}"
              f"{f['sweep']:>7.0f}{f['ropp_m']:>7.2f}{f['aa_min']:>7.0f}{f['clneg']:>6.0%}", flush=True)
    # 분리성: 각 특징별로 무승부2가 나머지15와 겹치나
    print("\n--- 분리성 검사 (무승부 범위 vs 승자 범위 겹침?) ---", flush=True)
    for k in ["rslope", "rmin", "reopen", "sweep", "ropp_m", "aa_min", "clneg"]:
        dv = [rows[o][k] for o in DRAWS]
        wv = [rows[o][k] for o in FULL if o not in DRAWS]
        dlo, dhi = min(dv), max(dv); wlo, whi = min(wv), max(wv)
        overlap = not (dhi < wlo or dlo > whi)
        # 무승부가 한쪽 극단이고 승자와 분리되는 마진
        sep = "겹침" if overlap else ("분리✓" if dlo > whi else "분리✓")
        print(f"  {k:<8} 무승부[{dlo:.1f},{dhi:.1f}] 승자[{wlo:.1f},{whi:.1f}]  → {sep}", flush=True)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 50.0)
