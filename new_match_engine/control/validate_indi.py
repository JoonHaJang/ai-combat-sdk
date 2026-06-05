"""INDI vs LQR 검증 — 고기동·불확실성에서 INDI가 LQR 한계를 넘는가 (정량).

검증 설계 (사용자 프레임워크 A·B):
  A. 공격적 기동: max-rate 반전·고AoA pull·복합 → 도달 AoA, 각속도, 추종오차, 에너지, LOC.
  B. 강건성(thesis §4.4): 제어 바이어스+노이즈(+ḡ 모델오차) 주입 → 정상 대비 열화 비교.
지표: psi 추종 RMSE/최종오차, max α, max|p,q,r|, 에너지 bleed, 제어 RMS, 발산(LOC) 여부.

★ 정직: deep post-stall/spin 은 JSBSim 공력·INDI 증분근사 둘 다의 신뢰 밖(thesis §5.2.4, LQR §15.2)
  — 본 검증은 *제어상실 직전까지의 공격적 영역*에서 두 제어기 거동을 비교한다.
실행: python validate_indi.py
"""
from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from plant import F16Plant, STATE_ORDER
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from controller import make_controller
from guidance import Setpoint

_iV, _iAL, _iTH, _iQ = (STATE_ORDER.index(k) for k in ("V", "alpha", "theta", "q"))
_iBE, _iPH, _iP, _iR = (STATE_ORDER.index(k) for k in ("beta", "phi", "p", "r"))
_iH, _iPSI = STATE_ORDER.index("h"), STATE_ORDER.index("psi")
_G, _KT = 32.174, 1.68781

# ── 공격적 기동 (setpoint). psi 는 절대 목표(시작 psi0 기준 +offset) ──
MANEUVERS = {
    "hard_reversal_150":  dict(dpsi=150.0, h=15000.0, vc=320.0),   # 코너서 150° 반전
    "lowspeed_pull_+6k":  dict(dpsi=0.0,   h=21000.0, vc=200.0),   # 저속 고AoA 상승
    "combo_aggr":         dict(dpsi=120.0, h=18000.0, vc=240.0),   # 복합
}


def _disturb(u, bias, noise, rng):
    """제어 불확실성: 조종면 바이어스 + 백색잡음 (thesis §4.4). throttle 제외."""
    d = u.copy()
    d[1:] = d[1:] + bias + noise * rng.standard_normal(3)
    d[0] = np.clip(d[0], 0.0, 1.0); d[1:] = np.clip(d[1:], -1.0, 1.0)
    return d


def run(engine, man, disturbed, gs, cfg, T=20.0, ceff=1.0):
    """ceff = 제어효과 배율(1=정상, <1=조종면 효과 저하=모델오차/damage).
       ★ 두 제어기 모두 *모름* — plant 가 실제로 ceff 배만 반응. LQR(고정 K)은 모델오차,
         INDI(ω̇ 측정)는 적응. 이게 thesis 의 '모델 불확실성' 핵심 stress."""
    p = F16Plant(); p.set_ic(15000.0, 350.0); p.trim(); p.step(2)
    ctl = make_controller(engine, p, gs, cfg, 1/20.0)
    psi0 = math.degrees(p.get_state()[_iPSI])
    sp = Setpoint(psi_star_deg=(psi0 + man["dpsi"]) % 360.0,
                  h_star_ft=man["h"], v_star_kts=man["vc"])
    cdt = 1/20.0; n = max(1, int(round(cdt/p.dt))); nt = int(T/cdt)
    rng = np.random.default_rng(0)
    bias = 0.15 if disturbed else 0.0
    noise = 0.05 if disturbed else 0.0
    alpha_max = 0.0; pqr_max = np.zeros(3); es0 = None; es_min = 1e18
    u_rms = 0.0; psi_errs = []; diverged = False
    for k in range(nt):
        u = ctl.step(sp)
        u = _disturb(u, bias, noise, rng)
        u_act = u.copy(); u_act[1:] = u_act[1:] * ceff   # ★ 제어효과 저하 (제어기는 모름)
        p.set_input(u_act)
        for _ in range(n): p.step(1)
        x = p.get_state()
        if not np.all(np.isfinite(x)) or abs(math.degrees(x[_iAL])) > 60.0:
            diverged = True; break
        alpha_max = max(alpha_max, abs(math.degrees(x[_iAL])))
        pqr_max = np.maximum(pqr_max, np.abs(np.degrees([x[_iP], x[_iQ], x[_iR]])))
        es = x[_iH] + (x[_iV]**2)/(2*_G)
        es0 = es if es0 is None else es0; es_min = min(es_min, es)
        u_rms += float(np.sum(u[1:]**2))
        pe = ((math.degrees(x[_iPSI]) - sp.psi_star_deg + 180) % 360) - 180
        psi_errs.append(pe)
    psi_errs = np.array(psi_errs) if psi_errs else np.array([180.0])
    return dict(
        diverged=diverged, alpha_max=alpha_max,
        p_max=pqr_max[0], q_max=pqr_max[1], r_max=pqr_max[2],
        psi_rmse=float(np.sqrt(np.mean(psi_errs**2))),
        psi_final=float(psi_errs[-1]) if len(psi_errs) else 180.0,
        es_bleed=(es0 - es_min) if es0 else 0.0,
        u_rms=math.sqrt(u_rms / max(1, len(psi_errs))),
    )


if __name__ == "__main__":
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    print("=" * 92)
    print("  INDI(B) vs LQR(A) 검증 — 공격적 기동 × {정상, 불확실성(바이어스0.15+노이즈0.05)}")
    print("=" * 92)
    hdr = "%-20s %-5s %-7s | %6s %6s %6s %6s | %7s %7s %7s %6s"
    print(hdr % ("maneuver", "eng", "cond", "αmax", "qmax", "pmax", "rmax",
                 "ψRMSE", "ψfinal", "Esbleed", "LOC"))
    # 조건: 정상 / 외란(바이어스+노이즈) / ★제어효과 저하 0.45 (모델오차·damage)
    CONDS = (("nom", False, 1.0), ("disturb", True, 1.0), ("ceff0.45", False, 0.45))
    for mname, man in MANEUVERS.items():
        for cond, dist, ceff in CONDS:
            row = {}
            for eng in ("lqr", "indi"):
                r = run(eng, man, dist, gs, cfg, ceff=ceff)
                row[eng] = r
                print(hdr % (mname if eng == "lqr" else "", "A" if eng == "lqr" else "B",
                             cond if eng == "lqr" else "",
                             "%.1f" % r["alpha_max"], "%.0f" % r["q_max"], "%.0f" % r["p_max"],
                             "%.0f" % r["r_max"], "%.1f" % r["psi_rmse"], "%+.1f" % r["psi_final"],
                             "%.0f" % r["es_bleed"], "YES" if r["diverged"] else "-"))
        print("-" * 92)
    print("\n해석: 불확실성에서 ψRMSE 열화가 작고 LOC 없는 쪽이 강건. (thesis: INDI 우위 기대)")
