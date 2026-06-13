"""INDIController — Incremental Nonlinear Dynamic Inversion 내측 (LQR 대체, "엔진 갈아끼우기").

★ 설계 의도: 외측 루프(고도/속도/heading 협조선회)는 Autopilot과 **동일**하게 두고, 내측 자세
  안정만 LQR → INDI 로 교체한다. Autopilot(LQR)은 손대지 않는다 → 교체 가능한 대안 제어기.

근거: Yasin ŞAHİN, *Robust Attitude Control of the F-16 Using INDI*, ITU 2025
      (docs/INDI_NDI_F16_Detailed.md §3.4–3.5).
  INDI 법칙:  Δδ = (1/ḡ)·(ν − ω̇₀),   δ = δ₀ + Δδ
    · ω̇₀ : 직전 각가속도(센서/유한차분) — 전체 모델 f(x) 불필요(센서가 대신).
    · ḡ   : 제어효과 ∂ω̇/∂δ — LQR 선형화 B 의 [q,elev]/[p,ail]/[r,rud] 항(격자 보간).
    · ν   : 외측이 만든 원하는 각가속도(가상입력, PI).
  강건성: 모델오차·외란에 NDI 대비 RMSE~23%↓·ISE~41%↓ (thesis §4.4).

인터페이스: Autopilot 과 동일 — step(sp:Setpoint) → u[thr,elev,ail,rud]. Pilot(controller="indi").

한계(정직): 고AoA/post-stall 은 증분근사 밖(thesis §3.4.9·§5.2.4) — 우리 LQR 문서 §15와 동일.
  액추에이터 동역학(rate-limit) 시 ω̇ 측정·증분 가정 약화 — 결정론 sim 에선 완화.
"""
from __future__ import annotations
import math, os
from dataclasses import dataclass, field
import numpy as np


def _ef(name: str, default: float) -> float:
    """INDI 게인 env override (튜닝 sweep용). 미설정 시 기본값."""
    return float(os.environ.get(name, default))

from plant import F16Plant, STATE_ORDER, INPUT_ORDER
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from guidance import Setpoint
from constants import KNOT_TO_FT_S, DEG_TO_RAD, G_FT_S2, EPS_DENOM

_iV, _iAL, _iTH, _iQ = (STATE_ORDER.index(k) for k in ("V", "alpha", "theta", "q"))
_iBE, _iPH, _iP, _iR = (STATE_ORDER.index(k) for k in ("beta", "phi", "p", "r"))
_iH, _iPSI = STATE_ORDER.index("h"), STATE_ORDER.index("psi")
_uTHR, _uELEV = INPUT_ORDER.index("throttle"), INPUT_ORDER.index("elevator")
_uAIL, _uRUD = INPUT_ORDER.index("aileron"), INPUT_ORDER.index("rudder")


@dataclass
class INDIConfig:
    """INDI 내측 게인 (물리 단위 — ḡ 인버전이 입력정규화 스케일 흡수). 최적화 대상."""
    # 자세각 → 각속도 기준 (외측 P)  ── env override(INDI_*)로 튜닝 sweep
    # ★ 기본값=C3 튜닝(E25, 2026-06-13): 뱅크+피치 동반↑로 LQR 격추 동등 회복(3/3).
    #   구 default(K_PHI=3,K_P=8,K_THETA=2,K_Q=6)는 미튜닝→B2 등 격추 상실(2/3).
    K_THETA: float = field(default_factory=lambda: _ef("INDI_K_THETA", 3.0))   # θ_err→q_ref (2.0→3.0)
    K_PHI:   float = field(default_factory=lambda: _ef("INDI_K_PHI", 5.0))     # φ_err→p_ref (3.0→5.0)
    MAX_RATE: float = field(default_factory=lambda: math.radians(_ef("INDI_MAX_RATE_DEG", 60.0)))
    # 각속도 → 원하는 각가속도 ν (내측 PI)
    K_Q: float = field(default_factory=lambda: _ef("INDI_K_Q", 9.0))           # (6.0→9.0)
    KI_Q: float = field(default_factory=lambda: _ef("INDI_KI_Q", 3.0))
    K_P: float = field(default_factory=lambda: _ef("INDI_K_P", 12.0))          # (8.0→12.0)
    KI_P: float = field(default_factory=lambda: _ef("INDI_KI_P", 3.0))
    INT_MAX: float = 5.0      # rate-error 적분 상한 [rad/s·s]
    # 요 협조 (β→0 + yaw 감쇠) → ν_r
    K_BETA: float = 4.0;  K_R: float = 2.0
    # ḡ 분모 하한 (제어효과 0 근처 발산 방지)
    G_FLOOR: float = 0.3


class INDIController:
    """INDI 내측 + (Autopilot 동일) 외측. step(sp) → u. LQR 와 교체 가능."""

    def __init__(self, plant: F16Plant, lqr: GainScheduledLQR,
                 config: AutopilotConfig | None = None, dt: float = 0.1,
                 indi: INDIConfig | None = None):
        self.plant = plant
        self.lqr = lqr
        self.cfg = config or AutopilotConfig()
        self.indi = indi or INDIConfig()
        self.dt = dt
        self.reset()
        self._u_prev = plant.get_input().copy()      # INDI 증분 기준 δ₀
        self._prev_pqr = None                          # ω̇ 유한차분용

    def reset(self):
        self._int_h = self._int_v = 0.0
        self._int_q = self._int_p = 0.0

    # ── ḡ: LQR 격자 B 를 (alt,vc)로 쌍선형 보간 (제어효과) ──
    def _interp_B(self, alt: float, vc: float) -> np.ndarray:
        L = self.lqr
        a = np.clip(alt, L.alts[0], L.alts[-1]); v = np.clip(vc, L.vcs[0], L.vcs[-1])
        ia = int(np.searchsorted(L.alts, a, side="right")); ia = max(1, min(ia, len(L.alts)-1))
        iv = int(np.searchsorted(L.vcs, v, side="right")); iv = max(1, min(iv, len(L.vcs)-1))
        a0, a1 = L.alts[ia-1], L.alts[ia]; v0, v1 = L.vcs[iv-1], L.vcs[iv]
        wa = (a-a0)/(a1-a0) if a1 != a0 else 0.0; wv = (v-v0)/(v1-v0) if v1 != v0 else 0.0
        g = lambda aa, vv: L.grid[(float(aa), float(vv))].B
        return ((1-wa)*(1-wv)*g(a0,v0) + wa*(1-wv)*g(a1,v0)
                + (1-wa)*wv*g(a0,v1) + wa*wv*g(a1,v1))

    def step(self, sp: Setpoint) -> np.ndarray:
        c = self.cfg; ic = self.indi
        x = self.plant.get_state()

        # ══ 외측 루프 (Autopilot 과 동일 — LQR 버전과 같은 자세목표 생성) ══
        h_star = sp.h_star_ft
        psi_star = sp.psi_star_deg * DEG_TO_RAD
        _, x0_trim, u0 = self.lqr._interp_K(x[_iH], sp.v_star_kts)
        V_star = x0_trim[_iV]
        # 고도 PI → theta_cmd
        h_err = x[_iH] - h_star
        self._int_h = max(-c.INT_H_MAX, min(c.INT_H_MAX, self._int_h + h_err*self.dt))
        theta_cmd = max(-c.MAX_THETA_RAD, min(c.MAX_THETA_RAD,
                        -(c.KP_H*h_err + c.KI_H*self._int_h)))
        # heading P + 협조선회 → phi_cmd
        psi_err = ((x[_iPSI] - psi_star + math.pi) % (2*math.pi)) - math.pi
        psi_rate_cmd = max(-c.MAX_PSI_RATE, min(c.MAX_PSI_RATE, c.KP_PSI*psi_err))
        V_safe = max(x[_iV], 50.0*KNOT_TO_FT_S)
        phi_cmd = max(-c.MAX_PHI_RAD, min(c.MAX_PHI_RAD,
                      -math.atan(psi_rate_cmd*V_safe/G_FT_S2)))
        # 속도 PI → throttle
        V_err = x[_iV] - V_star
        self._int_v = max(-c.INT_V_MAX, min(c.INT_V_MAX, self._int_v + V_err*self.dt))
        thr_cmd = float(np.clip(u0[_uTHR] - (c.KP_V*V_err + c.KI_V*self._int_v), 0.0, 1.0))

        # ══ 각가속도 측정 (유한차분) ══
        pqr = np.array([x[_iP], x[_iQ], x[_iR]])
        if self._prev_pqr is None:
            pdot = qdot = rdot = 0.0
        else:
            d = (pqr - self._prev_pqr) / max(self.dt, EPS_DENOM)
            pdot, qdot, rdot = float(d[0]), float(d[1]), float(d[2])
        self._prev_pqr = pqr

        # ══ 제어효과 ḡ (B 보간) — 부호 유지, 0근처 하한 ══
        B = self._interp_B(x[_iH], x[_iV])
        def _g(val):
            return val if abs(val) > ic.G_FLOOR else math.copysign(ic.G_FLOOR, val if val != 0 else 1.0)
        g_q = _g(B[_iQ, _uELEV]); g_p = _g(B[_iP, _uAIL]); g_r = _g(B[_iR, _uRUD])

        # ══ 내측 INDI (thesis §3.4: Δδ = (ν − ω̇₀)/ḡ, δ = δ₀ + Δδ) ══
        up = self._u_prev
        # pitch: θ_cmd → q_ref(P) → ν_q(PI) → Δelev
        q_ref = max(-ic.MAX_RATE, min(ic.MAX_RATE, ic.K_THETA*(theta_cmd - x[_iTH])))
        eq = q_ref - x[_iQ]
        self._int_q = max(-ic.INT_MAX, min(ic.INT_MAX, self._int_q + eq*self.dt))
        nu_q = ic.K_Q*eq + ic.KI_Q*self._int_q
        elev = up[_uELEV] + (nu_q - qdot)/g_q
        # roll: φ_cmd → p_ref(P) → ν_p(PI) → Δail
        p_ref = max(-ic.MAX_RATE, min(ic.MAX_RATE, ic.K_PHI*(phi_cmd - x[_iPH])))
        ep = p_ref - x[_iP]
        self._int_p = max(-ic.INT_MAX, min(ic.INT_MAX, self._int_p + ep*self.dt))
        nu_p = ic.K_P*ep + ic.KI_P*self._int_p
        ail = up[_uAIL] + (nu_p - pdot)/g_p
        # yaw: 협조(β→0) + yaw 감쇠 → ν_r → Δrud
        nu_r = -ic.K_BETA*x[_iBE] - ic.K_R*x[_iR]
        rud = up[_uRUD] + (nu_r - rdot)/g_r

        u = np.array([thr_cmd, elev, ail, rud], dtype=float)
        u[0] = float(np.clip(u[0], 0.0, 1.0))
        u[1:] = np.clip(u[1:], -1.0, 1.0)
        self._u_prev = u.copy()
        return u


if __name__ == "__main__":
    # INDI vs LQR — heading step + 종합 비교 (lqr.py __main__ 의 INDI 판)
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from lqr import GainScheduledLQR as GS
    print("=" * 60)
    print("  INDI 내측 — heading/alt step 검증 (실엔진)")
    print("=" * 60)
    gs = GS([5000, 15000, 25000], [250, 350, 450]).build()
    p = F16Plant(); p.set_ic(15000.0, 350.0); p.trim(); p.step(2)
    ctl = INDIController(p, gs, AutopilotConfig(KP_PSI=0.25), dt=1/20.0)
    psi0 = math.degrees(p.get_state()[_iPSI])
    sp = Setpoint(psi_star_deg=(psi0 + 20.0) % 360.0, h_star_ft=15000.0, v_star_kts=350.0)
    print(f"heading step +20°  (psi0={psi0:.1f}°)")
    cdt = 1/20.0; n_phys = max(1, int(round(cdt / p.dt)))
    for t_target in (0.0, 5.0, 15.0, 30.0):
        while True:
            x = p.get_state(); t = None
            break
    # 30s 시뮬
    T = 30.0; nt = int(T / cdt); rec = {}
    for k in range(nt):
        u = ctl.step(sp); p.set_input(u)
        for _ in range(n_phys): p.step(1)
        t = (k + 1) * cdt
        for tt in (5.0, 15.0, 30.0):
            if abs(t - tt) < cdt/2: rec[tt] = math.degrees(p.get_state()[_iPSI])
    err = lambda v: ((v - sp.psi_star_deg + 180) % 360) - 180
    print(f"  t=5s  psi_err={err(rec.get(5.0, psi0)):+.1f}°")
    print(f"  t=15s psi_err={err(rec.get(15.0, psi0)):+.1f}°")
    print(f"  t=30s psi_err={err(rec.get(30.0, psi0)):+.1f}°")
    print("  (LQR 내측은 ψ 무시→안 돎; INDI 도 외측 협조선회로 동일하게 선회해야 정상)")
