"""E41 — 궤적 *형상* 시그니처: 스칼라로 못 가른 무승부(A3/D2)를 *모양*으로 가르는가.

사용자 통찰: 단순 값(평균/분산) 실패 → 궤적의 *모양*이 시그니처. D2 first-20s 스칼라 ≡ aggressive인데
결과 무 vs 승 → 차이는 형상/타이밍(last-ditch 급반전 등). 위치(x,y,z)만 사용(각도 CSV 버그 회피).
상대궤적을 *우리 body frame*으로 회전 → 형상 descriptor + 2D plot 저장(replay 규율). 무 vs 격 비교.
usage: python exp_e41_shape_signature.py [dur]
"""
from __future__ import annotations
import sys, os, math, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from exp_e22_chaseforce import _opp
from exp_e27_adaptive_subset import AdaptivePolicy
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from obs import compute_obs, _ned, P_LAT, P_LON, P_ALT
from exp_e7_champion import _train
from exp_e10_unified import DS_DA

RDIR = os.path.join(os.path.dirname(__file__), "..", "replays", "research_shape")
OPPS = [("anchor_aggressive", "격"), ("C2_OneCircleRad", "격"),
        ("A3_LagAngler", "무"), ("D2_LastDitch", "무")]


def _rec_traj(p1, p2, rf, tac, gs, cfg, opp_name, dur):
    """매치 돌리며 (우리xy, 적xy, 우리heading) 기록. 위치만(각도버그 회피)."""
    ap = AdaptivePolicy(rf, tac, corrections=True)
    lat0, lon0, alt0 = p1[P_LAT], p1[P_LON], p1[P_ALT]      # 고정 기준점(우리 초기)
    rec = {"ux": [], "uy": [], "ox": [], "oy": [], "uh": [], "rng": []}
    def fn(o):
        ob = compute_obs(p1, p2)
        e_n, e_e, _ = _ned(p1, lat0, lon0, alt0); o_n, o_e, _ = _ned(p2, lat0, lon0, alt0)
        rec["ux"].append(e_n); rec["uy"].append(e_e)
        rec["ox"].append(o_n); rec["oy"].append(o_e)
        rec["uh"].append(math.radians(ob.ego_psi_deg)); rec["rng"].append(ob.distance_ft)
        return ap.select(p1, p2)
    m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
              control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
    res = m.run(tactic_fn1=lambda o: fn(o), tactic_fn2=lambda o: _opp(opp_name)(compute_obs(p2, p1)), duration_s=dur)
    return rec, res


def _shape_feats(rec):
    """형상 descriptor (위치만). 상대위치를 우리 body frame으로 회전 → 모양 특징."""
    relx, rely = [], []
    for i in range(len(rec["ux"])):
        dx = rec["ox"][i] - rec["ux"][i]; dy = rec["oy"][i] - rec["uy"][i]
        h = rec["uh"][i]                                   # 우리 heading으로 회전(body frame)
        relx.append(dx * math.cos(-h) - dy * math.sin(-h))
        rely.append(dx * math.sin(-h) + dy * math.cos(-h))
    rng = rec["rng"]
    n = len(rng)
    # 형상 특징들
    rmin = min(rng); rfin = rng[-1]
    # 거리율 부호변화 = 반전 횟수(닫았다 벌어졌다 = orbit/last-ditch)
    dr = [rng[i] - rng[i - 1] for i in range(1, n)]
    revs = sum(1 for i in range(1, len(dr)) if dr[i] * dr[i - 1] < 0)
    # 상대방위 누적 스윕(우리 주위 얼마나 도나 = orbit이면 큼)
    bear = [math.atan2(rely[i], relx[i]) for i in range(n)]
    sweep = sum(abs(((bear[i] - bear[i - 1]) + math.pi) % (2 * math.pi) - math.pi) for i in range(1, n))
    # spiral score: 거리 닫히는 동안 방위 단조전진(꼬리잡기) vs 일정반경 orbit
    closing_frac = sum(1 for d in dr if d < 0) / max(1, len(dr))
    return relx, rely, dict(rmin=rmin, rfin=rfin, revs=revs, sweep_deg=math.degrees(sweep),
                            closing_frac=closing_frac)


def main(dur=120.0):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    os.makedirs(RDIR, exist_ok=True)
    fig, axes = plt.subplots(1, 4, figsize=(20, 5))
    print(f"=== E41 궤적 형상 시그니처 {dur:.0f}s (적 상대위치, 우리 body frame) ===", flush=True)
    print(f"{'opp':<20}{'결과':<5}{'rmin':>8}{'rfin':>8}{'반전':>6}{'sweep°':>9}{'closing%':>9}", flush=True)
    for ax, (opp, exp) in zip(axes, OPPS):
        p1, p2 = spawn_adt_neutral()
        rec, res = _rec_traj(p1, p2, rf, tac, gs, cfg, opp, dur)
        relx, rely, f = _shape_feats(rec)
        ax.plot([x / 6076.0 for x in relx], [y / 6076.0 for y in rely], lw=0.8)  # nm
        ax.scatter([0], [0], c="r", marker="^", s=80, label="us")
        ax.scatter([relx[0] / 6076.0], [rely[0] / 6076.0], c="g", s=40, label="opp start")
        ax.set_title(f"{opp} [{exp}]\nrev={f['revs']} sweep={f['sweep_deg']:.0f}° close={f['closing_frac']:.0%}")
        ax.set_xlabel("forward (nm)"); ax.set_ylabel("right (nm)"); ax.axis("equal"); ax.grid(alpha=0.3)
        ax.legend(fontsize=7)
        print(f"{opp:<20}{exp:<5}{f['rmin']:>8.0f}{f['rfin']:>8.0f}{f['revs']:>6}{f['sweep_deg']:>9.0f}{f['closing_frac']:>8.0%}", flush=True)
    plt.tight_layout()
    out = os.path.join(RDIR, "shape_compare.png")
    plt.savefig(out, dpi=110); plt.close()
    print(f"\n형상 plot: {os.path.relpath(out)}", flush=True)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 120.0)
