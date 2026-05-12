"""3D HJI sanity check — Buzikov-Galyaev (2022) 한계 검증.

목적:
  Pursuit_Chase_BT 의 6D HJI solver 가 정확히 동작하는지 확인하기 위해,
  먼저 3D 한계 케이스 (constant speed, level flight) 를 풀이.
  결과: V*(canonical 3D) ≈ 0 이어야 (동등 스펙 → barrier 위) — 자가대전 DRAW 의 수학적 근거.

이론:
  Game of Two Identical Cars (Isaacs, Merz 1971, Buzikov-Galyaev 2022)
  - 양쪽 동일 속도 V, 동일 최소 선회반경 ρ
  - State (pursuer 상대 좌표): (x, y, ψ)
    x: pursuer 우측 방향 적 위치 (Air3d convention: 우리는 forward 사용)
    y: pursuer 전방 방향
    ψ: 상대 heading
  - Controls: ω_p (우리), ω_e (적), ∈ [-V/ρ, +V/ρ]
  - Capture: dist < l_capture
  - barrier 면 (V*=0) 분석해 by Buzikov-Galyaev — 인볼루트 곡선

본 구현:
  - hj_reachability.systems.Air3d 사용 (정확히 본 문제)
  - F-16 envelope: V=386.8 kts, ω_max=21°/s (@corner)
  - capture radius = 1500 ft (WEZ 중간점)
  - canonical 초기 조건의 V*(x₀) 출력

Expected:
  - V*(canonical 3D 한계) ≈ 0 (barrier 위, 양쪽 동등 → 값 0)
  - 0이 아니라 작은 양수면 → 우리가 살짝 우위
  - 작은 음수면 → 적이 살짝 우위
  - 큰 값 → grid 해상도 또는 dynamics 오류
"""

from __future__ import annotations

import time
import numpy as np

try:
    import jax
    import jax.numpy as jnp
    import hj_reachability as hj
    from hj_reachability.systems.air3d import Air3d
    HJ_AVAILABLE = True
except ImportError as e:
    HJ_AVAILABLE = False
    _IMPORT_ERR = str(e)


# ─── F-16 envelope @ canonical (3D constant-speed slice) ────────

V_CANONICAL_KTS = 386.8                          # 양쪽 동등 속도
KTS_TO_FPS = 1.6878098571012
V_CANONICAL_FPS = V_CANONICAL_KTS * KTS_TO_FPS   # ≈ 653 ft/s

# F-16 @ V=386.8 → omega_max interpolated
# From sim_dogfight_verify.py:54-79
# At 386.8 kts: between 350 (21°/s) and 400 (18.5°/s) → ~ 19.16 °/s
OMEGA_MAX_DEG_S = 19.16
OMEGA_MAX_RAD_S = OMEGA_MAX_DEG_S * np.pi / 180.0

# 최소 선회반경 R = V / ω_max
R_FT = V_CANONICAL_FPS / OMEGA_MAX_RAD_S          # ≈ 1953 ft

# Capture radius — WEZ 중간 (500~3000 ft)
CAPTURE_RADIUS_FT = 1500.0


# ─── Canonical 초기 조건 (Air3d convention) ─────────────────────

# Air3d:
#   state = (x_forward, y_left, psi_relative)
#   x_forward: 적이 우리 nose 방향으로 +
#   y_left:    적이 우리 좌측 +
#   psi:       적 heading 우리 heading
#
# 우리 canonical (NED): 우리 (북향, heading=0°), 적 (남향, heading=180°), 적이 우리 정동 3297.6ft
# → 우리 nose 방향 (북) 으로 적은 0ft 떨어짐, 좌측 (서) 으로 적은 -3297.6ft (즉 적이 우리 우측)
# → Air3d: x_forward=0, y_left=-3297.6, psi=π

CANONICAL_3D_STATE = np.array([0.0, -3297.6, np.pi])


def signed_distance_to_capture(states: jnp.ndarray) -> jnp.ndarray:
    """Signed distance from state to capture circle (radius = CAPTURE_RADIUS_FT).

    < 0: 이미 capture 안 → 우리 승리 영역
    > 0: capture 밖 → 적이 escape 가능
    """
    x = states[..., 0]
    y = states[..., 1]
    return jnp.sqrt(x ** 2 + y ** 2) - CAPTURE_RADIUS_FT


def run_3d_sanity(grid_shape=(40, 40, 40), time_horizon=20.0, verbose=True):
    """Air3d 3D HJI 풀이 + canonical V* 출력.

    Args:
        grid_shape: 각 차원 격자 수 (40³ = 64K cells, ~수십초 on CPU)
        time_horizon: 게임 시간 (초). 길수록 큰 영역으로 확장됨.

    Returns:
        dict: {
            'V_canonical': V*(canonical 3D),
            'solve_time_s': float,
            'grid_shape': tuple,
            'capture_radius_ft': float,
            ...
        }
    """
    if not HJ_AVAILABLE:
        raise ImportError(f"hj_reachability 미설치: {_IMPORT_ERR}")

    if verbose:
        print(f"\n{'='*70}")
        print(f"  3D HJI Sanity Check — Game of Two Identical Cars (Air3d)")
        print(f"{'='*70}")
        print(f"  Speed:           {V_CANONICAL_KTS} kts ({V_CANONICAL_FPS:.0f} ft/s)")
        print(f"  ω_max:           {OMEGA_MAX_DEG_S:.2f} °/s ({OMEGA_MAX_RAD_S:.4f} rad/s)")
        print(f"  Turn radius:     {R_FT:.0f} ft")
        print(f"  Capture radius:  {CAPTURE_RADIUS_FT:.0f} ft")
        print(f"  Grid shape:      {grid_shape}")
        print(f"  Time horizon:    {time_horizon} s")

    # Dynamics: Air3d (Game of Two Identical Cars)
    # control_mode='min' (우리 = pursuer = control), disturbance_mode='max' (적 = evader = disturbance)
    # → V*(x) < 0 in capture region (우리 우위)
    # But Air3d default: control_mode='max' (evader maximizes value), disturbance_mode='min'
    # → V*(x) > 0 escape region, < 0 capture
    dynamics = Air3d(
        evader_speed=V_CANONICAL_FPS,
        pursuer_speed=V_CANONICAL_FPS,
        evader_max_turn_rate=OMEGA_MAX_RAD_S,
        pursuer_max_turn_rate=OMEGA_MAX_RAD_S,
        control_mode="max",       # evader maximizes value (escape)
        disturbance_mode="min",   # pursuer minimizes value (capture)
    )

    # Grid: domain ± 6000 ft, psi periodic [-π, π]
    domain = hj.sets.Box(
        lo=jnp.array([-6000., -6000., -jnp.pi]),
        hi=jnp.array([+6000., +6000., +jnp.pi]),
    )
    grid = hj.Grid.from_lattice_parameters_and_boundary_conditions(
        domain=domain,
        shape=grid_shape,
        periodic_dims=(2,),
    )
    if verbose:
        print(f"\n  Grid initialized: {grid.states.shape}")

    # Initial values = signed distance to capture set
    # V > 0: outside capture set (uncaptured)
    # V < 0: inside capture set (captured)
    initial_values = signed_distance_to_capture(grid.states)

    # Solver settings (low accuracy for speed)
    # CRITICAL: hamiltonian_postprocessor=backwards_reachable_tube — V는 단조 감소 (BRT 정확 의미)
    # 없으면 H가 자유롭게 증가/감소해서 BRT 의미 깨짐 (StanfordASL/hj_reachability quickstart 참조)
    solver_settings = hj.SolverSettings.with_accuracy(
        "low",
        hamiltonian_postprocessor=hj.solver.backwards_reachable_tube,
    )

    # Solve backwards in time from t=0 to t=-time_horizon
    # → BRT(time_horizon) = set of states from which capture is achievable within time_horizon
    if verbose:
        print(f"\n  Solving backwards reachable tube (BRT) over {time_horizon}s...")
    t_start = time.time()

    times = jnp.array([0., -time_horizon])
    all_values = hj.solve(
        solver_settings, dynamics, grid, times, initial_values,
        progress_bar=False,
    )
    final_values = all_values[-1]  # values at t = -time_horizon

    solve_time_s = time.time() - t_start

    # Interpolate V*(canonical 3D)
    # Use grid.interpolate if exists; otherwise nearest-neighbor lookup
    def interpolate(values, state):
        # Find nearest grid indices
        idx = []
        for d in range(3):
            c = grid.coordinate_vectors[d]
            i = int(jnp.argmin(jnp.abs(c - state[d])))
            idx.append(i)
        return float(values[tuple(idx)])

    V_canonical = interpolate(final_values, CANONICAL_3D_STATE)
    V_initial_canonical = interpolate(initial_values, CANONICAL_3D_STATE)

    if verbose:
        print(f"\n  Solve time:       {solve_time_s:.1f} s")
        print(f"\n  Initial V (canonical 3D, t=0):       {V_initial_canonical:+.2f} ft")
        print(f"  Solved  V (canonical 3D, t=-{time_horizon:.0f}s): {V_canonical:+.2f} ft")
        print(f"\n  Interpretation:")
        if abs(V_canonical) < 100:
            print(f"    |V*| < 100 ft  →  canonical 은 거의 barrier 위 → DRAW 예측 ✓")
        elif V_canonical > 0:
            print(f"    V* > 0  →  canonical 에서 evader 가 escape 가능 → 적 우위")
        else:
            print(f"    V* < 0  →  canonical 에서 pursuer 가 capture 가능 → 우리 우위")

        # Distribution stats
        n_captured = int(jnp.sum(final_values < 0))
        n_total = int(final_values.size)
        print(f"\n  BRT 통계 ({time_horizon:.0f}s 안에 capture 가능 영역):")
        print(f"    captured states (V<0):  {n_captured} / {n_total} ({100*n_captured/n_total:.1f}%)")
        print(f"    V range:                [{float(final_values.min()):.1f}, {float(final_values.max()):.1f}] ft")
        print(f"    V at canonical:         {V_canonical:+.1f} ft")

    return {
        "V_canonical": V_canonical,
        "V_initial_canonical": V_initial_canonical,
        "solve_time_s": solve_time_s,
        "grid_shape": grid_shape,
        "capture_radius_ft": CAPTURE_RADIUS_FT,
        "time_horizon_s": time_horizon,
        "speed_kts": V_CANONICAL_KTS,
        "omega_max_deg_s": OMEGA_MAX_DEG_S,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="3D HJI sanity check via Air3d")
    parser.add_argument("--grid", type=int, default=40, help="grid size per dim (default 40)")
    parser.add_argument("--time", type=float, default=10.0, help="time horizon in seconds (default 10)")
    args = parser.parse_args()

    if not HJ_AVAILABLE:
        print(f"❌ hj_reachability 사용 불가: {_IMPORT_ERR}")
        print("   설치: python -m pip install hj-reachability")
        print("        + python -m pip install flax --no-deps  (Windows long-path 우회)")
        exit(1)

    result = run_3d_sanity(
        grid_shape=(args.grid, args.grid, args.grid),
        time_horizon=args.time,
        verbose=True,
    )

    print(f"\n{'='*70}")
    print(f"  결과 요약")
    print(f"{'='*70}")
    for k, v in result.items():
        if isinstance(v, float):
            print(f"  {k:25} {v:+.3f}")
        else:
            print(f"  {k:25} {v}")
