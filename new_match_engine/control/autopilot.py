"""Autopilot — Outer PI/P (자세 유도) + Inner LQR (자세 안정).

★ 단위 변환 유일 책임자: kts/ft/deg ↔ fps/ft/rad.

아키텍처 (Stevens & Lewis §8 cascaded autopilot):
  Outer:
    고도  h(ft)   → theta_cmd(rad) via PI
    헤딩  psi(rad) → phi_cmd(rad)  via 협조선회 공식 + P
    속도  V(fps)  → thr_cmd       via PI (trim feedforward + 보정)
  Inner LQR:
    (theta_cmd, phi_cmd) → x_star → K·err → u(조종면)

협조선회 공식 (flight mechanics 표준):
  d(psi)/dt = g * tan(phi) / V  →  phi = atan(psi_rate * V / g)
  psi_rate_cmd = KP_PSI * psi_err (P 게인)
  → P-only로도 정확한 bank 각도, 오버슈트 없음.

파라미터화:
  모든 튜닝 파라미터는 AutopilotConfig에 집중.
  Optuna / scipy.optimize 등 최적화 도구로 바로 접근 가능하도록 설계.

단위 참조:
  TACTIC_SPEC.md §0 — 전체 단위 시스템
  plant.py STATE_ORDER — x 벡터 인덱스·단위
  lqr.py INPUT_ORDER   — u 벡터 인덱스

참조:
  Stevens & Lewis & Johnson, Aircraft Control and Simulation, 3rd ed. §8
  협조선회: Nelson, Flight Stability and Automatic Control, 2nd ed. §4
  Bryson's method: Q/R = 1/(max_err)², 1/(max_input)²
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
import numpy as np

from plant import F16Plant, STATE_ORDER, INPUT_ORDER
from lqr import GainScheduledLQR
from guidance import Setpoint
from constants import (
    KNOT_TO_FT_S, FT_S_TO_KNOT,   # reciprocal 보장 (kts↔fps 왕복 오차 ~0)
    DEG_TO_RAD, RAD_TO_DEG,
    G_FT_S2,                        # ft/s² = 32.17404856...
    EPS_DENOM,                       # 0나눗셈 방지 최소 분모
)

# ── 상태·입력 인덱스 ───────────────────────────────────────────────────────
_iV   = STATE_ORDER.index("V")
_iALP = STATE_ORDER.index("alpha")
_iTH  = STATE_ORDER.index("theta")
_iQ   = STATE_ORDER.index("q")
_iBETA= STATE_ORDER.index("beta")
_iPHI = STATE_ORDER.index("phi")
_iP   = STATE_ORDER.index("p")
_iR   = STATE_ORDER.index("r")
_iH   = STATE_ORDER.index("h")
_iPSI = STATE_ORDER.index("psi")

_uTHR  = INPUT_ORDER.index("throttle")
_uELEV = INPUT_ORDER.index("elevator")
_uAIL  = INPUT_ORDER.index("aileron")
_uRUD  = INPUT_ORDER.index("rudder")

def _wrap(a: float) -> float:
    """psi 오차 정규화 → [−π, +π]. 제어 오차 계산 전용.

    ★ 관례: err = _wrap(current - target)
      err < 0 → current가 target보다 반시계(우회전 필요) → phi_cmd > 0
      err > 0 → current가 target보다 시계(좌회전 필요) → phi_cmd < 0
    참고: guidance.py 의 _normalize_0_360() 과 다름 (setpoint 출력용).
    """
    return (a + math.pi) % (2.0 * math.pi) - math.pi


# ── AutopilotConfig — 모든 튜닝 파라미터 집중 관리 ─────────────────────────
@dataclass
class AutopilotConfig:
    """Autopilot 튜닝 파라미터.

    최적화 도구(Optuna, scipy.optimize 등)로 바로 접근 가능하도록
    모든 게인·한계·적분기 상한을 한 곳에 모았다.

    [Outer PI — 고도]
    KP_H, KI_H: theta_cmd(rad) = -(KP_H * h_err + KI_H * int_h)
    MAX_THETA:  theta_cmd 포화 한계 (rad)

    [Outer P — 헤딩, 협조선회]
    KP_PSI:    psi_rate_cmd(rad/s) = KP_PSI * psi_err(rad)
    MAX_PSI_RATE: 최대 선회율 (rad/s) — F-16 한계 ≈ 0.15rad/s(≈9°/s)
    MAX_PHI:   phi_cmd 포화 한계 (rad)

    [Outer PI — 속도]
    KP_V, KI_V: thr 보정 = -(KP_V * V_err + KI_V * int_v)

    [Anti-windup 적분기 상한]
    INT_H_MAX, INT_PSI_MAX, INT_V_MAX

    [JSBSim 물리 상수 — 변경 금지]
    g_ft_s2: ft/s²
    """
    # 고도 PI
    KP_H:          float = 0.0008
    KI_H:          float = 4e-5
    MAX_THETA_RAD: float = math.radians(15.0)  # 포화 ±15°

    # 헤딩 P (협조선회) — BFM 전투기동 한계 (측정: bank60°=2G·6°/s 너무 느림)
    #   bank78° = 5G ≈ 16°/s @corner. F-16 구조한계 9G 내, BFM 선회전 필수.
    KP_PSI:        float = 0.10            # rad/s per rad err (선회 적극화)
    MAX_PSI_RATE:  float = math.radians(16.0)  # ≈16°/s (corner speed, ~5G)
    MAX_PHI_RAD:   float = math.radians(78.0)  # 78° bank = 4.8G (BFM 하드선회)

    # 속도 PI
    KP_V:          float = 0.003
    KI_V:          float = 8e-5

    # Anti-windup
    INT_H_MAX:     float = 1500.0   # ft·s
    INT_PSI_MAX:   float = 0.0      # rad·s (P-only → 적분기 없음)
    INT_V_MAX:     float = 400.0    # fps·s

    def to_dict(self) -> dict:
        """최적화 도구용 — 튜닝 가능 파라미터만 dict 반환."""
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "AutopilotConfig":
        return cls(**d)


@dataclass
class AutopilotState:
    """매 tick 진단 (단위 명시)."""
    V_fps:         float = 0.0  # fps
    h_ft:          float = 0.0  # ft MSL
    psi_deg:       float = 0.0  # 0~360°
    V_star_kts:    float = 0.0  # kts (guidance 입력)
    h_star_ft:     float = 0.0  # ft
    psi_star_deg:  float = 0.0  # °
    err_V_fps:     float = 0.0  # fps
    err_h_ft:      float = 0.0  # ft
    err_psi_deg:   float = 0.0  # ° (wrap됨)
    theta_cmd_deg: float = 0.0  # ° (outer → inner)
    phi_cmd_deg:   float = 0.0  # ° (outer → inner)
    u_throttle:    float = 0.0  # [0,1]
    u_elevator:    float = 0.0  # [-1,1]
    u_aileron:     float = 0.0  # [-1,1]
    u_rudder:      float = 0.0  # [-1,1]


class Autopilot:
    """Outer PI/P + Inner LQR cascaded autopilot.

    Parameters
    ----------
    plant  : F16Plant
    lqr    : GainScheduledLQR
    config : AutopilotConfig  (기본값 또는 최적화 결과)
    dt     : float  outer PI 적분 주기 (s) = BT tick
    """

    def __init__(self,
                 plant:  F16Plant,
                 lqr:    GainScheduledLQR,
                 config: AutopilotConfig | None = None,
                 dt:     float = 0.1):
        self.plant  = plant
        self.lqr    = lqr
        self.cfg    = config or AutopilotConfig()
        self.dt     = dt
        self._int_h = 0.0   # ft·s
        self._int_v = 0.0   # fps·s
        self.state  = AutopilotState()

    def reset(self):
        """전술 전환 시 적분기 초기화."""
        self._int_h = self._int_v = 0.0

    # ──────────────────────────────────────────────────────────────────────
    def step(self, sp: Setpoint) -> np.ndarray:
        """setpoint → u = [throttle, elevator, aileron, rudder].

        단위 변환 (이 메서드가 유일한 변환 지점):
          sp.psi_star_deg → rad
          sp.h_star_ft   → ft (동일)
          V_star          = x0_trim[V] (TAS, fps) — CAS/TAS 혼동 방지

        Returns
        -------
        u : ndarray shape(4,)  [thr, elev, ail, rud]
        """
        c = self.cfg
        x = self.plant.get_state()

        # A. 단위 변환 ────────────────────────────────────────────────────
        h_star   = sp.h_star_ft
        psi_star = sp.psi_star_deg * DEG_TO_RAD   # rad

        # B. gain scheduling 보간 ─────────────────────────────────────────
        _, x0_trim, u0 = self.lqr._interp_K(x[_iH], sp.v_star_kts)
        V_star = x0_trim[_iV]   # TAS(fps) — trim 점 기준. kts→fps 직접 변환 금지.

        # C. Outer — 고도 PI ───────────────────────────────────────────────
        h_err = x[_iH] - h_star                             # ft
        self._int_h = max(-c.INT_H_MAX,
                     min(c.INT_H_MAX, self._int_h + h_err * self.dt))
        theta_cmd = -(c.KP_H * h_err + c.KI_H * self._int_h)  # rad
        theta_cmd = max(-c.MAX_THETA_RAD, min(c.MAX_THETA_RAD, theta_cmd))

        # D. Outer — 헤딩 P (협조선회 공식) ──────────────────────────────
        # 협조선회: d(psi)/dt = g*tan(phi)/V  →  phi = atan(psi_rate * V / g)
        # Nelson, Flight Stability and Automatic Control §4.
        psi_err = _wrap(x[_iPSI] - psi_star)                # rad [-π,π]
        psi_rate_cmd = c.KP_PSI * psi_err                   # rad/s
        psi_rate_cmd = max(-c.MAX_PSI_RATE,
                       min(c.MAX_PSI_RATE, psi_rate_cmd))
        # V 최소값 클램프: 실속 이하에서도 0나눗셈 방지 + 물리적으로 의미 있는 하한
        V_safe = max(x[_iV], 50.0 * KNOT_TO_FT_S)  # 50kts 이하 clamp (실속 안전 마진)
        phi_cmd = -math.atan(psi_rate_cmd * V_safe / G_FT_S2)  # rad
        phi_cmd = max(-c.MAX_PHI_RAD, min(c.MAX_PHI_RAD, phi_cmd))

        # E. Outer — 속도 PI ───────────────────────────────────────────────
        V_err = x[_iV] - V_star                              # fps TAS
        self._int_v = max(-c.INT_V_MAX,
                     min(c.INT_V_MAX, self._int_v + V_err * self.dt))
        thr_cmd = u0[_uTHR] - (c.KP_V * V_err + c.KI_V * self._int_v)

        # F. Inner LQR — 자세 안정 ────────────────────────────────────────
        # x_star: theta_cmd·phi_cmd만 교체, 나머지는 현재 x (자세 오차=0)
        x_star = x.copy()
        x_star[_iTH]  = theta_cmd   # rad ★
        x_star[_iPHI] = phi_cmd     # rad ★
        K, _, _ = self.lqr._interp_K(x[_iH], sp.v_star_kts)
        err = x - x_star
        u = u0 - K @ err

        # G. throttle override + 포화 처리 ────────────────────────────────
        u[_uTHR] = thr_cmd
        u[_uTHR] = float(np.clip(u[_uTHR], 0.0, 1.0))
        u[1:]    = np.clip(u[1:], -1.0, 1.0)

        # H. 진단 ─────────────────────────────────────────────────────────
        self.state = AutopilotState(
            V_fps        = x[_iV],
            h_ft         = x[_iH],
            psi_deg      = x[_iPSI] * RAD_TO_DEG % 360.0,
            V_star_kts   = sp.v_star_kts,
            h_star_ft    = sp.h_star_ft,
            psi_star_deg = sp.psi_star_deg,
            err_V_fps    = V_err,
            err_h_ft     = h_err,
            err_psi_deg  = psi_err * RAD_TO_DEG,
            theta_cmd_deg= theta_cmd * RAD_TO_DEG,
            phi_cmd_deg  = phi_cmd  * RAD_TO_DEG,
            u_throttle   = float(u[_uTHR]),
            u_elevator   = float(u[_uELEV]),
            u_aileron    = float(u[_uAIL]),
            u_rudder     = float(u[_uRUD]),
        )
        return u

    def resolution_report(self) -> dict:
        x = self.plant.get_state()
        K, _, _ = self.lqr._interp_K(x[_iH], x[_iV] * FT_S_TO_KNOT)
        k_th = abs(K[_uELEV, _iTH])
        k_ph = abs(K[_uAIL,  _iPHI])
        return {
            "min_theta_deg": round(0.01 / k_th * RAD_TO_DEG, 3) if k_th > 0 else float('inf'),
            "min_phi_deg":   round(0.01 / k_ph * RAD_TO_DEG, 3) if k_ph > 0 else float('inf'),
            "config": self.cfg.to_dict(),
        }


if __name__ == "__main__":
    print("▶ Autopilot first-light: Outer P(협조선회) + PI + Inner LQR")
    print()

    plant = F16Plant()
    plant.set_ic(alt_ft=15000.0, vc_kts=350.0)
    plant.trim()
    plant.step(5)

    gs = GainScheduledLQR(
        alts_ft=[5_000.0, 15_000.0, 25_000.0],
        vcs_kts=[250.0,   350.0,    450.0],
    ).build()

    cfg = AutopilotConfig(KP_PSI=0.06, KP_H=0.0008, KP_V=0.003)
    ap  = Autopilot(plant, gs, config=cfg, dt=0.1)

    res = ap.resolution_report()
    print(f"Inner LQR 분해능: theta={res['min_theta_deg']:.3f}°  phi={res['min_phi_deg']:.3f}°")
    print()

    x0    = plant.get_state()
    psi0  = x0[_iPSI] * RAD_TO_DEG % 360.0
    sp    = Setpoint(psi_star_deg=(psi0+30.0)%360.0, h_star_ft=15000.0, v_star_kts=350.0)

    print(f"=== Heading step +30° ({psi0:.1f}° → {sp.psi_star_deg:.1f}°) ===")
    print(f"{'t':>5}  {'psi':>7}  {'err_psi':>9}  {'h':>7}  {'V':>6}  "
          f"{'thr':>5}  {'elev':>5}  {'phi_cmd':>8}")
    print("-" * 68)

    DT_SIM = plant.dt
    BT_DT  = 0.1
    N      = int(BT_DT / DT_SIM)

    for tick in range(600):   # 60s
        u = ap.step(sp)
        plant.set_input(u)
        for _ in range(N):
            plant.step(1)
        s = ap.state
        if tick % 20 == 0:
            print(f"{tick*BT_DT:>5.1f}  {s.psi_deg:>7.2f}  {s.err_psi_deg:>+9.2f}  "
                  f"{s.h_ft:>7.0f}  {s.V_fps*FT_S_TO_KNOT:>6.1f}  "
                  f"{s.u_throttle:>5.3f}  {s.u_elevator:>+5.3f}  "
                  f"{s.phi_cmd_deg:>+8.1f}")

    s = ap.state
    print()
    print(f"최종 heading 오차: {s.err_psi_deg:+.2f}°")
    print(f"최종 고도   오차: {s.err_h_ft:+.0f} ft")
    print(f"최종 속도   오차: {s.err_V_fps*FT_S_TO_KNOT:+.1f} kts")
