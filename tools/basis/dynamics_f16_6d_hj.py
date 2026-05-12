"""F-16 6D dynamics — hj_reachability 호환 (ControlAndDisturbanceAffineDynamics).

dynamics_f16_6d.py 의 numpy 모델을 control-affine 형식으로 변환.
Small-angle 가정 (cos γ ≈ 1, sin γ ≈ γ) — γ가 ±30° 이내일 때 정확도 ~14%.

State (6D, pursuer-rotating frame):
  x[0] = dx       — 적 우측 상대 위치 (ft)
  x[1] = dy       — 적 전방 상대 위치 (ft)
  x[2] = dh       — 적 고도 차 (ft)
  x[3] = dpsi     — 적 heading - 우리 heading (rad)
  x[4] = V_p      — 우리 속도 (kts)
  x[5] = V_e      — 적 속도 (kts)

Controls:
  u_p = (omega_p, gamma_p, a_p)  — 우리 (disturbance in HJI naming, since we minimize V)
  u_e = (omega_e, gamma_e, a_e)  — 적 (control in HJI naming, since they maximize V)

운동방정식 (small-angle 가정):
  dx/dt   = V_e[kts→fts] · sin(dpsi) + omega_p · dy
  dy/dt   = V_e[kts→fts] · cos(dpsi) - V_p[kts→fts] - omega_p · dx
  dh/dt   = V_e[kts→fts] · gamma_e - V_p[kts→fts] · gamma_p
  dpsi/dt = omega_e - omega_p
  dV_p/dt = a_p
  dV_e/dt = a_e

이는 control + disturbance 에 affine:
  f(x, u_p, u_e) = f0(x) + B_c(x) · u_e + B_d(x) · u_p
  여기서 control = evader (적), disturbance = pursuer (우리)
  — Air3d convention 맞춤
"""

from __future__ import annotations

import jax.numpy as jnp
import hj_reachability as hj
from hj_reachability import dynamics, sets


# 단위 변환
KTS_TO_FPS = 1.6878098571012


# F-16 envelope (보수적 — corner 속도 기준)
OMEGA_MAX_DEG = 19.16   # @ V_canonical=386.8 kts (interpolated)
OMEGA_MAX_RAD = OMEGA_MAX_DEG * jnp.pi / 180.0   # ≈ 0.334 rad/s
GAMMA_MAX_RAD = jnp.pi * 30.0 / 180.0            # ±30° flight path angle
ACCEL_MAX_KTS = 15.0                              # kts/s
V_MIN_KTS = 160.0
V_MAX_KTS = 420.0


class F16Pursuit6D(dynamics.ControlAndDisturbanceAffineDynamics):
    """F-16 1:1 도그파이트 6D 미분 게임.

    - control = evader (적). control_mode='max' → 적이 V_value 최대화 (escape)
    - disturbance = pursuer (우리). disturbance_mode='min' → 우리가 V 최소화 (capture)

    V(x) > 0: capture set 밖 (escape 영역)
    V(x) < 0: capture set 안 (capture 영역)
    V(x) = 0: barrier
    """

    def __init__(
        self,
        omega_max_rad_s: float = OMEGA_MAX_RAD,
        gamma_max_rad: float = GAMMA_MAX_RAD,
        accel_max_kts_s: float = ACCEL_MAX_KTS,
        control_mode: str = "max",
        disturbance_mode: str = "min",
    ):
        # 제어 입력 박스 (적의 u = [omega_e, gamma_e, a_e])
        control_space = sets.Box(
            lo=jnp.array([-omega_max_rad_s, -gamma_max_rad, -accel_max_kts_s]),
            hi=jnp.array([+omega_max_rad_s, +gamma_max_rad, +accel_max_kts_s]),
        )
        # 외란 입력 박스 (우리 u = [omega_p, gamma_p, a_p])
        disturbance_space = sets.Box(
            lo=jnp.array([-omega_max_rad_s, -gamma_max_rad, -accel_max_kts_s]),
            hi=jnp.array([+omega_max_rad_s, +gamma_max_rad, +accel_max_kts_s]),
        )
        super().__init__(control_mode, disturbance_mode, control_space, disturbance_space)

    def open_loop_dynamics(self, state, time):
        """f0(x) — 제어 없음 케이스 (양쪽 모두 직선 등속)."""
        dx, dy, dh, dpsi, V_p, V_e = state
        Vp_fts = V_p * KTS_TO_FPS
        Ve_fts = V_e * KTS_TO_FPS
        return jnp.array([
            Ve_fts * jnp.sin(dpsi),               # dx
            Ve_fts * jnp.cos(dpsi) - Vp_fts,      # dy
            0.0,                                  # dh
            0.0,                                  # dpsi
            0.0,                                  # dV_p
            0.0,                                  # dV_e
        ])

    def control_jacobian(self, state, time):
        """B_c(x) — 적 (evader) 제어가 state derivative 에 미치는 영향.

        u_e = [omega_e, gamma_e, a_e]
        """
        _, _, _, _, _, V_e = state
        Ve_fts = V_e * KTS_TO_FPS
        # 6x3: rows = state dim, cols = (omega_e, gamma_e, a_e)
        return jnp.array([
            [0.0,    0.0,    0.0],    # dx ← 적 ω, γ, a 영향 (0 — small-angle)
            [0.0,    0.0,    0.0],    # dy
            [0.0,    Ve_fts, 0.0],    # dh += V_e * γ_e (small-angle)
            [1.0,    0.0,    0.0],    # dpsi += ω_e
            [0.0,    0.0,    0.0],    # dV_p
            [0.0,    0.0,    1.0],    # dV_e += a_e
        ])

    def disturbance_jacobian(self, state, time):
        """B_d(x) — 우리 (pursuer) 제어가 state derivative 에 미치는 영향.

        u_p = [omega_p, gamma_p, a_p]
        """
        dx, dy, _, _, V_p, _ = state
        Vp_fts = V_p * KTS_TO_FPS
        # 6x3
        return jnp.array([
            [ dy,    0.0,    0.0],    # dx += ω_p * dy  (Coriolis)
            [-dx,    0.0,    0.0],    # dy += -ω_p * dx
            [0.0,   -Vp_fts, 0.0],    # dh -= V_p * γ_p
            [-1.0,   0.0,    0.0],    # dpsi -= ω_p
            [0.0,    0.0,    1.0],    # dV_p += a_p
            [0.0,    0.0,    0.0],    # dV_e
        ])


# ─── Capture set / 종단 비용 ──────────────────────────────────

CAPTURE_DIST_MIN_FT = 500.0      # WEZ inner
CAPTURE_DIST_MAX_FT = 3000.0     # WEZ outer
CAPTURE_ATA_MAX_DEG = 12.0       # WEZ angle


def signed_distance_to_wez_us(states):
    """우리 WEZ 까지의 signed distance.

    WEZ = { dist ∈ [500, 3000] AND ATA < 12° }
    음수 = 안 (잡힌 상태), 양수 = 밖 (escape 영역)

    Args:
        states: (..., 6) jnp array
    Returns:
        (..., ) jnp array of signed distance (ft 단위)
    """
    dx = states[..., 0]
    dy = states[..., 1]
    dh = states[..., 2]

    # 수평 거리
    horiz_dist = jnp.sqrt(dx ** 2 + dy ** 2 + 1e-9)
    # 3D 거리 (slant)
    slant_dist = jnp.sqrt(dx ** 2 + dy ** 2 + dh ** 2 + 1e-9)

    # ATA: 우리 nose(+y) 와 적 위치 (dx, dy) 사이 각도
    # 우리 nose unit vec = (0, 1). 적 방향 unit = (dx, dy) / horiz_dist
    cos_ata = dy / horiz_dist
    cos_ata = jnp.clip(cos_ata, -1.0, 1.0)
    ata_rad = jnp.arccos(cos_ata)
    ata_deg = ata_rad * 180.0 / jnp.pi

    # WEZ 안: dist ∈ [500, 3000] AND ata < 12°
    # signed dist = max(dist_violation, ata_violation)
    dist_violation = jnp.maximum(slant_dist - CAPTURE_DIST_MAX_FT,
                                 CAPTURE_DIST_MIN_FT - slant_dist)
    # ata violation: 12° 를 ft 단위로 환산 — 거리에 따라 다름
    # 단순화: angular margin × dist
    ata_violation_ft = (ata_deg - CAPTURE_ATA_MAX_DEG) * slant_dist * jnp.pi / 180.0

    return jnp.maximum(dist_violation, ata_violation_ft)


def signed_distance_simple_sphere(states, capture_radius_ft=1500.0):
    """Simpler capture: sphere of given radius.

    Useful for initial testing — Air3d 와 동일 형식.
    """
    dx = states[..., 0]
    dy = states[..., 1]
    dh = states[..., 2]
    return jnp.sqrt(dx ** 2 + dy ** 2 + dh ** 2 + 1e-9) - capture_radius_ft


# ─── Canonical 초기 (Air3d frame 으로 변환) ───────────────────

# Pursuer frame (NED + heading rotation):
#   우리 (0, 0) facing North (heading=0)
#   적 (3297.6, 0) facing South (heading=π)
# In pursuer body frame (we face +y direction):
#   적 위치: 적이 우리 우측 (+x_body direction) 3297.6 ft
#   상대 heading: 적 heading - 우리 heading = π - 0 = π
CANONICAL_6D = jnp.array([3297.6,   # dx
                          0.0,      # dy
                          0.0,      # dh
                          jnp.pi,   # dpsi
                          386.8,    # V_p
                          386.8])   # V_e


# ─── Self-test ──────────────────────────────────────────────

def _self_test():
    """단위 테스트: canonical 초기에서 dynamics 정합성."""
    print("=" * 70)
    print("F-16 6D Dynamics (hj_reachability compat) — Self Test")
    print("=" * 70)

    dyn = F16Pursuit6D()
    print(f"\nDynamics: F16Pursuit6D")
    print(f"  control_mode='max' (evader 적 escape)")
    print(f"  disturbance_mode='min' (pursuer 우리 capture)")
    print(f"  omega_max: {OMEGA_MAX_DEG:.2f}°/s = {float(OMEGA_MAX_RAD):.4f} rad/s")
    print(f"  gamma_max: ±30°")
    print(f"  accel_max: ±{ACCEL_MAX_KTS:.0f} kts/s")

    x = CANONICAL_6D
    print(f"\nCanonical state x:")
    print(f"  dx={x[0]:.1f} dy={x[1]:.1f} dh={x[2]:.1f} dpsi={float(x[3]):.4f} V_p={x[4]} V_e={x[5]}")

    # f0 (no controls)
    f0 = dyn.open_loop_dynamics(x, 0.0)
    print(f"\nf0(x) (no control):")
    print(f"  dx/dt={float(f0[0]):.2f}  dy/dt={float(f0[1]):.2f}  dh/dt={float(f0[2]):.2f}")
    print(f"  dpsi/dt={float(f0[3]):.4f}  dV_p/dt={float(f0[4]):.4f}  dV_e/dt={float(f0[5]):.4f}")

    # B_c (적 제어 jacobian)
    B_c = dyn.control_jacobian(x, 0.0)
    print(f"\nB_c(x) (evader effect, 6x3 — cols: ω_e, γ_e, a_e):")
    for i, name in enumerate(["dx", "dy", "dh", "dpsi", "V_p", "V_e"]):
        row = [f"{float(B_c[i,j]):+8.2f}" for j in range(3)]
        print(f"  {name:5} {' '.join(row)}")

    # B_d (우리 제어 jacobian)
    B_d = dyn.disturbance_jacobian(x, 0.0)
    print(f"\nB_d(x) (pursuer effect, 6x3 — cols: ω_p, γ_p, a_p):")
    for i, name in enumerate(["dx", "dy", "dh", "dpsi", "V_p", "V_e"]):
        row = [f"{float(B_d[i,j]):+8.2f}" for j in range(3)]
        print(f"  {name:5} {' '.join(row)}")

    # Capture distance
    d_wez = signed_distance_to_wez_us(x)
    d_sphere = signed_distance_simple_sphere(x)
    print(f"\nSigned distance to capture set:")
    print(f"  WEZ (ATA<12 + dist 500-3000): {float(d_wez):+.1f} ft")
    print(f"  Simple sphere (r=1500ft):     {float(d_sphere):+.1f} ft")

    print(f"\n✓ Self-test 완료")


if __name__ == "__main__":
    _self_test()
