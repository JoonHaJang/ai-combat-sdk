"""F-16 점-질량 6D dynamics for HJI solver.

상태 (pursuer 좌표계 상대):
  x = (dx, dy, dh, dpsi, V_p, V_e) ∈ ℝ⁶

제어:
  u_p = (omega_h_p, gamma_p, a_p)   — pursuer
  u_e = (omega_h_e, gamma_e, a_e)   — evader

점-질량 가정:
  - γ (flight path angle) 은 즉시 제어 (rate constraint 없음)
  - heading rate ω_h 와 thrust accel a 는 envelope 한계
  - aerodynamic stall, AOA, G-induced loss 등은 무시 (1차 근사)

JSBSim 매칭:
  - envelope 테이블: sim_dogfight_verify.py:54-79 (실측 + NASA TP-1538 보정)
  - canonical 초기 조건: ATA=90°, dist=3297.6ft, V=386.8kts, alt=15000ft, HCA=180°

References:
  - Bryson-Ho (1975) Applied Optimal Control
  - Buzikov-Galyaev (2022) arXiv:2206.10199 (3D 등속 한계 sanity check)
  - JSBSim F-16 flight dynamics model
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


# ─── Constants ────────────────────────────────────────────────────

# 단위
KTS_TO_FPS = 1.6878098571012   # 1 kt = 1.6878 ft/s
DEG_TO_RAD = np.pi / 180.0
RAD_TO_DEG = 180.0 / np.pi

# Gravity (ft/s²) — Boyd EM 의 에너지 변환에 필요
G_FTS2 = 32.174


# ─── F-16 Envelope (JSBSim 매칭, sim_dogfight_verify.py:54-79) ───

# Speed (KIAS) 별 max 순간 선회율 (°/s)
# 데이터 출처: JSBSim 실측 + F-16 Flight Manual / NASA TP-1538 보정
_ENV_V_KTS = np.array([0,   160,  200,  250,  300,  350,  400,  420,  500], dtype=np.float64)
_ENV_TR_DEG_S = np.array([6.0, 9.0, 12.0, 15.0, 18.0, 21.0, 18.5, 16.0, 14.0], dtype=np.float64)
_ENV_R_FT     = np.array([1600,1700,1600,1700,1800,1650,2100,2500,2800], dtype=np.float64)


def omega_max_at(v_kts: float) -> float:
    """속도 V (KIAS) 에서 최대 수평 선회율 ω_max (°/s) — JSBSim 매칭."""
    return float(np.interp(v_kts, _ENV_V_KTS, _ENV_TR_DEG_S))


def turn_radius_at(v_kts: float) -> float:
    """속도 V (KIAS) 에서 최소 선회 반경 R (ft) — JSBSim 매칭."""
    return float(np.interp(v_kts, _ENV_V_KTS, _ENV_R_FT))


@dataclass(frozen=True)
class F16Envelope:
    """F-16 비행 envelope (HJI 제어 한계).

    모든 한계는 보수적(JSBSim 실측의 ~80~90% 채택 권장).
    """
    V_MIN: float = 160.0          # kts (실속 직전)
    V_MAX: float = 420.0          # kts (운영 최대)
    V_CORNER: float = 350.0       # kts (ω_max 발생 코너 속도)

    OMEGA_MAX_AT_CORNER: float = 21.0  # °/s @ V_CORNER
    GAMMA_MAX_DEG: float = 60.0        # 최대 flight path angle (점-질량 가정)
    GAMMA_RATE_MAX: float = 15.0       # °/s — 즉시는 아니지만 우리 점-질량 가정
                                       # (실 JSBSim 더 빠를 수 있음)

    ACCEL_MAX_KTSS: float = 15.0       # kts/s — Accelerate 측정값 기반
    DECEL_MAX_KTSS: float = 15.0       # kts/s — Decelerate

    HARD_DECK_FT: float = 1000.0       # 추락 한계 — HJI 외부 safety branch
    OPERATIONAL_ALT_MAX_FT: float = 30000.0  # 그리드 상한

    def omega_max(self, V: float) -> float:
        return omega_max_at(V)


DEFAULT_ENVELOPE = F16Envelope()


# ─── State / Control 데이터 클래스 ───────────────────────────────

@dataclass
class State6D:
    """6D 상태: pursuer 좌표계 상대 위치 + 양쪽 속도.

    pursuer 좌표계 정의:
      - 원점: pursuer 위치
      - +y 축: pursuer heading 방향 (전방)
      - +x 축: pursuer 우측 (heading + 90°)
      - +h 축: 절대 고도 차 (적 - 우리)
    """
    dx: float       # ft, 적 상대 위치 (pursuer 우측 +)
    dy: float       # ft, 적 상대 위치 (pursuer 전방 +)
    dh: float       # ft, 고도 차 (적 - 우리)
    dpsi: float     # rad, 적 heading - pursuer heading
    V_p: float      # kts, pursuer 속도
    V_e: float      # kts, evader 속도

    def to_array(self) -> np.ndarray:
        return np.array([self.dx, self.dy, self.dh, self.dpsi, self.V_p, self.V_e],
                        dtype=np.float64)

    @classmethod
    def from_array(cls, x: np.ndarray) -> "State6D":
        return cls(dx=x[0], dy=x[1], dh=x[2], dpsi=x[3], V_p=x[4], V_e=x[5])


@dataclass
class Control:
    """제어 입력 (한 플레이어).

    omega_h: 수평 선회율 (rad/s) — 양수=우선회, 음수=좌선회
    gamma:   flight path angle (rad) — 양수=상승, 음수=하강 (즉시 제어 가정)
    accel:   throttle 가속 (kts/s) — 양수=가속, 음수=감속
    """
    omega_h: float
    gamma: float
    accel: float

    def to_array(self) -> np.ndarray:
        return np.array([self.omega_h, self.gamma, self.accel], dtype=np.float64)


# ─── Initial Conditions ─────────────────────────────────────────

def canonical_initial_state() -> State6D:
    """JSBSim core 의 canonical 초기 조건.

    출처: logs/metadata/v11_analysis/*.json 실측, 사용자 검증
      ego_pos = (0, 0, 15000ft), heading=0° (북향)
      enm_pos = (3297.6, 0, 15000ft), heading=180° (남향)
      양쪽 V = 386.8kts, γ = 0
      → pursuer 기준: 적이 +x 방향 3297.6ft, dh=0, dpsi=π
    """
    return State6D(
        dx=3297.6,      # 적이 우리 정동(우측) 3297.6ft
        dy=0.0,         # 정북도 정남도 아님
        dh=0.0,         # 동일 고도
        dpsi=np.pi,     # 적 heading 180° (남) - 우리 0° (북) = π rad
        V_p=386.8,
        V_e=386.8,
    )


# ─── Dynamics ────────────────────────────────────────────────────

def dynamics(x: np.ndarray, u_p: np.ndarray, u_e: np.ndarray,
             env: F16Envelope = DEFAULT_ENVELOPE) -> np.ndarray:
    """6D 상태 미분 dx/dt = f(x, u_p, u_e).

    Args:
        x: (6,) [dx, dy, dh, dpsi, V_p, V_e]
        u_p: (3,) pursuer 제어 [omega_h_p, gamma_p, a_p]
        u_e: (3,) evader 제어 [omega_h_e, gamma_e, a_e]
        env: F-16 envelope (제어 한계 적용)

    Returns:
        dx_dt: (6,) 시간 미분

    Note:
        - 속도는 kts 로 입력, 거리 미분은 ft/s 로 환산
        - omega_h, gamma 는 rad 단위
        - pursuer 가 (0, 0, 0) 에서 +y 방향 비행 가정 (lock 좌표계)
        - 운동 방정식:
            dx_p = V_p cos(gamma_p) [pursuer 자체 운동은 +y 방향]
            적 위치 (절대): 적의 NED 운동
            상대 위치 미분: 적 절대 - 우리 절대, 그리고 우리 heading 회전 보정
    """
    dx_rel, dy_rel, dh, dpsi, V_p, V_e = x
    omega_h_p, gamma_p, a_p = u_p
    omega_h_e, gamma_e, a_e = u_e

    # 제어 한계 적용 (clipping)
    omega_h_p = np.clip(omega_h_p, -env.OMEGA_MAX_AT_CORNER * DEG_TO_RAD,
                        env.OMEGA_MAX_AT_CORNER * DEG_TO_RAD)
    omega_h_e = np.clip(omega_h_e, -env.OMEGA_MAX_AT_CORNER * DEG_TO_RAD,
                        env.OMEGA_MAX_AT_CORNER * DEG_TO_RAD)
    gamma_p = np.clip(gamma_p, -env.GAMMA_MAX_DEG * DEG_TO_RAD,
                      env.GAMMA_MAX_DEG * DEG_TO_RAD)
    gamma_e = np.clip(gamma_e, -env.GAMMA_MAX_DEG * DEG_TO_RAD,
                      env.GAMMA_MAX_DEG * DEG_TO_RAD)
    a_p = np.clip(a_p, -env.DECEL_MAX_KTSS, env.ACCEL_MAX_KTSS)
    a_e = np.clip(a_e, -env.DECEL_MAX_KTSS, env.ACCEL_MAX_KTSS)

    # 속도 한계 (envelope)
    # V_p, V_e 가 한계에 닿으면 가속/감속 적용 안 함
    if V_p >= env.V_MAX and a_p > 0:
        a_p = 0.0
    if V_p <= env.V_MIN and a_p < 0:
        a_p = 0.0
    if V_e >= env.V_MAX and a_e > 0:
        a_e = 0.0
    if V_e <= env.V_MIN and a_e < 0:
        a_e = 0.0

    # 속도 ft/s 변환
    Vp_fts = V_p * KTS_TO_FPS
    Ve_fts = V_e * KTS_TO_FPS

    # 상대 운동 (pursuer body frame, +y 가 pursuer heading 방향)
    # pursuer 자체 운동: 자기 frame 에서는 항상 (0, V_p cos gamma_p, V_p sin gamma_p)
    # evader 운동 (pursuer body frame 에서 본): 회전 + 평행 이동
    #
    # 핵심: pursuer body frame 은 pursuer 와 함께 회전하므로
    #   d(dx_rel)/dt = V_e_in_pursuer_frame_x - 0 + omega_h_p * dy_rel
    #   d(dy_rel)/dt = V_e_in_pursuer_frame_y - V_p cos(gamma_p) - omega_h_p * dx_rel
    #
    # evader 의 ground velocity (heading = pursuer + dpsi):
    #   v_e_north_abs = V_e cos(gamma_e) cos(psi_e)
    #   v_e_east_abs  = V_e cos(gamma_e) sin(psi_e)
    # pursuer body frame (rotation by pursuer heading psi_p):
    #   v_e_x_body = v_e_east_cos(psi_p) - v_e_north sin(psi_p) ...
    #
    # 간소화: pursuer heading 을 좌표계 +y 로 정의하면
    #   v_e_x_body = V_e cos(gamma_e) sin(dpsi)
    #   v_e_y_body = V_e cos(gamma_e) cos(dpsi)
    #
    # pursuer 의 좌표계가 회전하므로 Coriolis-like term 추가:
    #   d(dx_rel)/dt = v_e_x_body + omega_h_p * dy_rel     (frame rotation)
    #   d(dy_rel)/dt = v_e_y_body - V_p cos(gamma_p) - omega_h_p * dx_rel

    cos_g_e = np.cos(gamma_e)
    sin_g_e = np.sin(gamma_e)
    cos_g_p = np.cos(gamma_p)
    sin_g_p = np.sin(gamma_p)
    cos_dpsi = np.cos(dpsi)
    sin_dpsi = np.sin(dpsi)

    v_e_x_body = Ve_fts * cos_g_e * sin_dpsi
    v_e_y_body = Ve_fts * cos_g_e * cos_dpsi

    d_dx_rel = v_e_x_body + omega_h_p * dy_rel
    d_dy_rel = v_e_y_body - Vp_fts * cos_g_p - omega_h_p * dx_rel
    d_dh = Ve_fts * sin_g_e - Vp_fts * sin_g_p   # ft/s
    d_dpsi = omega_h_e - omega_h_p               # rad/s
    d_V_p = a_p
    d_V_e = a_e

    return np.array([d_dx_rel, d_dy_rel, d_dh, d_dpsi, d_V_p, d_V_e], dtype=np.float64)


# ─── 파생 관측값 (game rules 계산에 필요) ────────────────────────

def compute_ata_deg(x: np.ndarray) -> float:
    """ATA (Antenna Train Angle) — 우리 nose 와 적 사이의 각도 (°).

    Pursuer 좌표계에서 적의 위치 (dx_rel, dy_rel) 방향과 +y 축 (우리 nose) 사이.
    """
    dx_rel, dy_rel = x[0], x[1]
    return float(np.degrees(np.arctan2(abs(dx_rel), dy_rel)))


def compute_aa_deg(x: np.ndarray) -> float:
    """AA (Aspect Angle) — 적 nose 와 우리 사이의 각도 (°).

    적 좌표계에서 우리 위치 방향과 적 nose (적 heading) 사이.
    """
    dx_rel, dy_rel, _, dpsi, _, _ = x
    # 적의 위치에서 우리 방향: -dx_rel, -dy_rel (적 좌표계는 아직 pursuer frame)
    # 적 heading: pursuer heading + dpsi → pursuer frame 에서 적 nose 방향 = (sin dpsi, cos dpsi)
    nose_e_x, nose_e_y = np.sin(dpsi), np.cos(dpsi)
    # 적 → 우리 방향 (pursuer frame): (-dx_rel, -dy_rel) / |.|
    norm = np.sqrt(dx_rel**2 + dy_rel**2) + 1e-9
    to_us_x, to_us_y = -dx_rel / norm, -dy_rel / norm
    # 내적
    dot = nose_e_x * to_us_x + nose_e_y * to_us_y
    return float(np.degrees(np.arccos(np.clip(dot, -1.0, 1.0))))


def compute_dist_ft(x: np.ndarray) -> float:
    """수평 거리 — pursuer frame 의 (dx_rel, dy_rel) 평면 거리."""
    return float(np.sqrt(x[0]**2 + x[1]**2))


def compute_slant_range_ft(x: np.ndarray) -> float:
    """경사 거리 — 3D 거리 (dh 포함)."""
    return float(np.sqrt(x[0]**2 + x[1]**2 + x[2]**2))


def compute_closure_kts(x: np.ndarray, dx_dt: np.ndarray) -> float:
    """접근율 — d(slant_range)/dt 의 -1 (kts 단위, 양수=가까워짐)."""
    r = compute_slant_range_ft(x) + 1e-9
    dr_dt = (x[0] * dx_dt[0] + x[1] * dx_dt[1] + x[2] * dx_dt[2]) / r  # ft/s
    return float(-dr_dt / KTS_TO_FPS)  # kts


# ─── WEZ / 종단 조건 ───────────────────────────────────────────

def in_wez_us(x: np.ndarray, dx_dt: Optional[np.ndarray] = None) -> bool:
    """우리 WEZ (= 우리 capture 조건):
       ATA < 12°  AND  500 < dist < 3000 ft  AND  closure > 0
    """
    ata = compute_ata_deg(x)
    dist = compute_dist_ft(x)
    if not (500.0 < dist < 3000.0):
        return False
    if not (ata < 12.0):
        return False
    if dx_dt is not None:
        cl = compute_closure_kts(x, dx_dt)
        if cl <= 0:
            return False
    return True


def in_wez_them(x: np.ndarray, dx_dt: Optional[np.ndarray] = None) -> bool:
    """적 WEZ (적 capture 조건):
       AA < 12°  AND  500 < dist < 3000 ft  AND  closure > 0
    """
    aa = compute_aa_deg(x)
    dist = compute_dist_ft(x)
    if not (500.0 < dist < 3000.0):
        return False
    if not (aa < 12.0):
        return False
    if dx_dt is not None:
        cl = compute_closure_kts(x, dx_dt)
        if cl <= 0:
            return False
    return True


# ─── 유틸: RK4 적분 (단위 테스트용) ────────────────────────────

def rk4_step(x: np.ndarray, u_p: np.ndarray, u_e: np.ndarray,
             dt: float, env: F16Envelope = DEFAULT_ENVELOPE) -> np.ndarray:
    """단일 RK4 적분 스텝."""
    k1 = dynamics(x, u_p, u_e, env)
    k2 = dynamics(x + 0.5 * dt * k1, u_p, u_e, env)
    k3 = dynamics(x + 0.5 * dt * k2, u_p, u_e, env)
    k4 = dynamics(x + dt * k3, u_p, u_e, env)
    return x + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)


# ─── 자체 검증 (모듈 실행 시) ─────────────────────────────────

def _self_test():
    """단위 테스트: canonical 초기 상태에서 dx/dt 계산 정합성."""
    print("=" * 70)
    print("F-16 6D Dynamics — Self Test")
    print("=" * 70)

    x0 = canonical_initial_state()
    print(f"\nCanonical x₀:")
    print(f"  dx_rel = {x0.dx:.1f} ft  (적 정동)")
    print(f"  dy_rel = {x0.dy:.1f} ft")
    print(f"  dh     = {x0.dh:.1f} ft")
    print(f"  dpsi   = {x0.dpsi:.4f} rad ({np.degrees(x0.dpsi):.1f}°)")
    print(f"  V_p    = {x0.V_p:.1f} kts")
    print(f"  V_e    = {x0.V_e:.1f} kts")

    print(f"\nDerived geometry:")
    x_arr = x0.to_array()
    print(f"  ATA  = {compute_ata_deg(x_arr):.2f}°  (expected 90° per canonical)")
    print(f"  AA   = {compute_aa_deg(x_arr):.2f}°  (expected 90° per canonical)")
    print(f"  dist = {compute_dist_ft(x_arr):.2f} ft  (expected 3297.6)")
    print(f"  slant_range = {compute_slant_range_ft(x_arr):.2f} ft")

    # No-op control (양쪽 직선 비행)
    u_zero = np.zeros(3)
    dx_dt = dynamics(x_arr, u_zero, u_zero)
    print(f"\nf(x₀, 0, 0):")
    print(f"  d(dx_rel)/dt = {dx_dt[0]:.2f} ft/s")
    print(f"  d(dy_rel)/dt = {dx_dt[1]:.2f} ft/s  (적이 남으로 움직이고 우린 정지하면 빠른 양수 예상은 안 됨)")
    print(f"  d(dh)/dt     = {dx_dt[2]:.2f} ft/s")
    print(f"  d(dpsi)/dt   = {dx_dt[3]:.4f} rad/s")
    print(f"  d(V_p)/dt    = {dx_dt[4]:.2f} kts/s")
    print(f"  d(V_e)/dt    = {dx_dt[5]:.2f} kts/s")

    closure_kts = compute_closure_kts(x_arr, dx_dt)
    print(f"  closure      = {closure_kts:.2f} kts  (expected ~0 at canonical head-on perpendicular)")

    # 10s integration test
    print(f"\n10초 무제어 시뮬레이션 (RK4 dt=0.1s):")
    x = x_arr.copy()
    for t in [0, 1, 2, 5, 10]:
        steps = int(t / 0.1) - int(0 / 0.1) if t == 0 else 10
        if t > 0:
            for _ in range(int((t - (0 if t == 1 else (t - 1 if t <= 5 else 5))) / 0.1)):
                x = rk4_step(x, u_zero, u_zero, 0.1)
        dist = compute_dist_ft(x)
        ata = compute_ata_deg(x)
        print(f"  t={t:3d}s: dist={dist:7.1f}ft  ATA={ata:6.2f}°  "
              f"dh={x[2]:6.1f}ft  V_p={x[4]:.1f}  V_e={x[5]:.1f}")

    # Envelope sanity
    print(f"\nEnvelope:")
    print(f"  omega_max @ V=350 kts: {omega_max_at(350):.1f} °/s  (corner — expected 21)")
    print(f"  omega_max @ V=420 kts: {omega_max_at(420):.1f} °/s")
    print(f"  omega_max @ V=200 kts: {omega_max_at(200):.1f} °/s")
    print(f"  turn_radius @ V=350 kts: {turn_radius_at(350):.0f} ft")

    # WEZ test
    print(f"\nWEZ 조건 테스트:")
    x_wez = np.array([0.0, 1500.0, 0.0, np.pi, 350.0, 350.0])  # ATA=0, dist=1500, head-on
    dx_dt_wez = dynamics(x_wez, u_zero, u_zero)
    print(f"  x = (0, 1500ft, 0, π, 350, 350)")
    print(f"  ATA={compute_ata_deg(x_wez):.2f}°  dist={compute_dist_ft(x_wez):.1f}ft  "
          f"cl={compute_closure_kts(x_wez, dx_dt_wez):.1f}kts")
    print(f"  in_wez_us = {in_wez_us(x_wez, dx_dt_wez)}  (expected True)")
    print(f"  in_wez_them = {in_wez_them(x_wez, dx_dt_wez)}")

    print(f"\n✓ Self-test 완료")


if __name__ == "__main__":
    _self_test()
