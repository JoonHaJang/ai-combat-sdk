"""Joint 12D dynamics — per-side 6D ODE 결합.

각 side state: (x, y, h, ψ, V, ω_turn)
    x, y, h: ft (위치, world frame)
    ψ: rad (heading)
    V: kts (calibrated airspeed)
    ω_turn: rad/s (current turn rate, state — rolling-in dynamics)

control u = (ω_cmd, γ̇_cmd, a_cmd):
    ω_cmd: 요구 turn rate (rad/s) — first-order lag → ω 갱신
    γ̇_cmd: flight path angle rate (rad/s) — instantaneous (point-mass 가정 유지)
    a_cmd: thrust accel (kts/s)

ω 동역학: dω/dt = (ω_cmd - ω) / τ_ω    — first-order lag
    τ_ω ≈ 0.4s (F-16 roll-in time constant 근사, BT_TICK_RATE_ANALYSIS 참조)
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np

from . import state as st


# F-16 envelope (단순 — tools/basis/dynamics_f16_6d.py 의 핵심값)
OMEGA_MAX_RAD_S = math.radians(21.0)   # peak turn rate
GAMMA_MAX_RAD_S = math.radians(15.0)
ACCEL_MAX_KTS_S = 15.0
V_MAX_KTS = 720.0
V_MIN_KTS = 160.0
H_MIN_FT = 500.0   # hard physical floor (game LOSS 는 1000 ft)
H_MAX_FT = 50000.0

# turn-rate first-order lag
TAU_OMEGA_S = 0.4


def per_side_step(
    x: np.ndarray,
    u: np.ndarray,
    dt: float = 0.1,
) -> np.ndarray:
    """단일 side 6D → 6D 다음 step (Euler integration).

    x = (x, y, h, ψ, V, ω)
    u = (ω_cmd, γ̇_cmd, a_cmd)
    """
    pos_x, pos_y, h, psi, V, omega = x
    omega_cmd, gamma_dot_cmd, a_cmd = u

    # control clipping
    omega_cmd = float(np.clip(omega_cmd, -OMEGA_MAX_RAD_S, OMEGA_MAX_RAD_S))
    gamma_dot_cmd = float(np.clip(gamma_dot_cmd, -GAMMA_MAX_RAD_S, GAMMA_MAX_RAD_S))
    a_cmd = float(np.clip(a_cmd, -ACCEL_MAX_KTS_S, ACCEL_MAX_KTS_S))

    # ω first-order lag toward ω_cmd
    omega_next = omega + (omega_cmd - omega) * (dt / TAU_OMEGA_S)
    # envelope: ω scales with V (rough approximation — 정확 envelope 는 envelope_f16.py)
    omega_cap = OMEGA_MAX_RAD_S * np.clip((V - V_MIN_KTS) / 250.0, 0.2, 1.0)
    omega_next = float(np.clip(omega_next, -omega_cap, omega_cap))

    # V 갱신 + envelope
    V_next = V + a_cmd * dt
    V_next = float(np.clip(V_next, V_MIN_KTS, V_MAX_KTS))

    # ψ 갱신 (use *current* ω avg with next)
    omega_avg = 0.5 * (omega + omega_next)
    psi_next = psi + omega_avg * dt

    # γ̇ 영향 → flight path angle, 즉 vertical speed component
    # point-mass approximation: V_horiz = V cos γ, V_vert = V sin γ
    # γ̇ direct → γ at next step: γ_next = γ̇ * dt (γ state 안 들고 있으니 instantaneous)
    gamma_next = gamma_dot_cmd * dt   # 짧은 horizon 가정 (즉답)
    V_fps = V_next * 1.6878098571012
    vh_x = V_fps * math.cos(gamma_next) * math.sin(psi_next)
    vh_y = V_fps * math.cos(gamma_next) * math.cos(psi_next)
    vh_z = V_fps * math.sin(gamma_next)

    pos_x_next = pos_x + vh_x * dt
    pos_y_next = pos_y + vh_y * dt
    h_next = h + vh_z * dt
    h_next = float(np.clip(h_next, H_MIN_FT, H_MAX_FT))

    return np.array([pos_x_next, pos_y_next, h_next, psi_next, V_next, omega_next])


def joint_step(
    z: np.ndarray,
    u_us: np.ndarray,
    u_opp: np.ndarray,
    dt: float = 0.1,
) -> np.ndarray:
    """12D joint state 한 step.

    각 side 독립 dynamics (interaction 없음, point-mass).
    interaction 은 cost / adversary BT 에서 발생.
    """
    z_next = np.zeros(12)
    z_next[st.SLICE_US] = per_side_step(z[st.SLICE_US], u_us, dt)
    z_next[st.SLICE_OPP] = per_side_step(z[st.SLICE_OPP], u_opp, dt)
    return z_next


def rollout(
    z0: np.ndarray,
    u_us_seq: np.ndarray,
    u_opp_seq: np.ndarray,
    dt: float = 0.1,
) -> np.ndarray:
    """H step rollout. returns (H+1, 12) trajectory."""
    H = len(u_us_seq)
    assert len(u_opp_seq) == H
    z_traj = np.zeros((H + 1, 12))
    z_traj[0] = z0
    for t in range(H):
        z_traj[t + 1] = joint_step(z_traj[t], u_us_seq[t], u_opp_seq[t], dt)
    return z_traj


def _self_test():
    """sanity: 직진 비행 시 위치 증가, turn 시 heading 변경."""
    # initial: us at origin heading north, opp 3000ft north at 200ft above
    z0 = np.array([
        0.0, 0.0, 15000.0, 0.0, 386.8, 0.0,         # us
        0.0, 3000.0, 15200.0, math.pi, 386.8, 0.0,  # opp facing south
    ])

    # us: straight + maintain
    u_us = np.array([0.0, 0.0, 0.0])
    # opp: turn left, accel
    u_opp = np.array([math.radians(10.0), 0.0, 5.0])

    z_traj = rollout(z0, [u_us] * 10, [u_opp] * 10, dt=0.1)

    print("us trajectory (x, y, h, ψ, V):")
    for t in [0, 5, 10]:
        x = z_traj[t][st.SLICE_US]
        print(f"  t={t*0.1:.1f}s: x={x[0]:.1f}, y={x[1]:.1f}, h={x[2]:.1f}, "
              f"ψ={math.degrees(x[3]):.1f}°, V={x[4]:.1f}, ω={math.degrees(x[5]):.2f}°/s")
    print("opp trajectory:")
    for t in [0, 5, 10]:
        x = z_traj[t][st.SLICE_OPP]
        print(f"  t={t*0.1:.1f}s: x={x[0]:.1f}, y={x[1]:.1f}, h={x[2]:.1f}, "
              f"ψ={math.degrees(x[3]):.1f}°, V={x[4]:.1f}, ω={math.degrees(x[5]):.2f}°/s")

    # checks
    assert z_traj[10][st.SLICE_US][1] > 600, "us should move north"
    assert abs(z_traj[10][st.SLICE_OPP][3] - math.pi) > 0.05, "opp should turn"
    assert z_traj[10][st.SLICE_OPP][4] > 386.8, "opp should accelerate"
    print("[joint_dynamics.py] self-test PASS")


if __name__ == "__main__":
    _self_test()
