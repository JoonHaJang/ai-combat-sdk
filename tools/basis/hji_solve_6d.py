"""6D HJI solver — Pursuit_Chase_BT 의 핵심 수치 계산.

목적:
  F-16 1:1 도그파이트 동등 스펙 가변속 게임의 value function V*(x) 산출.
  3D 등속 한계 (hji_air3d_sanity.py) 와 비교하여 가변속이 우리에게 어떤 advantage 를 주는지 정량화.

이론:
  state x ∈ ℝ⁶ = (dx, dy, dh, dpsi, V_p, V_e)
  HJI PDE: V_t + min_{u_p} max_{u_e} { ∇V · f(x, u_p, u_e) } = 0
  Initial: V(x, 0) = l(x) (signed distance to WEZ_us)
  Backwards: V(x, -T) = T초 안에 capture 가능한 영역

  V(canonical_6D, -T) 가 의미:
    < 0: 우리 우위 — 가변속/고도 변경으로 capture 가능
    = 0: barrier — 임계 (DRAW)
    > 0: 적 우위 — capture 불가

실행:
  python tools/basis/hji_solve_6d.py --grid 10 --time 10.0
  python tools/basis/hji_solve_6d.py --grid 12 --time 20.0 --capture sphere
  python tools/basis/hji_solve_6d.py --grid 8 --time 5.0 --save logs/hji/V_6d_8bin.npz

산출:
  V*(canonical 6D) 출력
  V grid 통계 (BRT 비율, V range, etc.)
  Optional .npz 저장 — BT lookup table 용
"""

from __future__ import annotations

import argparse
import time as _time
from pathlib import Path

import numpy as np
import jax
import jax.numpy as jnp
import hj_reachability as hj

# 우리 모듈
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.basis.dynamics_f16_6d_hj import (
    F16Pursuit6D,
    signed_distance_to_wez_us,
    signed_distance_simple_sphere,
    CANONICAL_6D,
    V_MIN_KTS, V_MAX_KTS,
)


# ─── Grid 설정 ─────────────────────────────────────────────────

# 차원별 도메인 (보수적 — F-16 envelope 안에서)
DOMAIN_DEFAULT = {
    "dx_ft":   (-6000., +6000.),
    "dy_ft":   (-6000., +6000.),
    "dh_ft":   (-4000., +4000.),
    "dpsi":    (-jnp.pi, +jnp.pi),    # periodic
    "V_p_kts": (V_MIN_KTS, V_MAX_KTS),
    "V_e_kts": (V_MIN_KTS, V_MAX_KTS),
}


def make_grid(shape_per_dim=10):
    """6D 균등 격자 생성."""
    lo = jnp.array([
        DOMAIN_DEFAULT["dx_ft"][0],
        DOMAIN_DEFAULT["dy_ft"][0],
        DOMAIN_DEFAULT["dh_ft"][0],
        DOMAIN_DEFAULT["dpsi"][0],
        DOMAIN_DEFAULT["V_p_kts"][0],
        DOMAIN_DEFAULT["V_e_kts"][0],
    ])
    hi = jnp.array([
        DOMAIN_DEFAULT["dx_ft"][1],
        DOMAIN_DEFAULT["dy_ft"][1],
        DOMAIN_DEFAULT["dh_ft"][1],
        DOMAIN_DEFAULT["dpsi"][1],
        DOMAIN_DEFAULT["V_p_kts"][1],
        DOMAIN_DEFAULT["V_e_kts"][1],
    ])

    if isinstance(shape_per_dim, int):
        shape = (shape_per_dim,) * 6
    else:
        shape = tuple(shape_per_dim)

    domain = hj.sets.Box(lo=lo, hi=hi)
    grid = hj.Grid.from_lattice_parameters_and_boundary_conditions(
        domain=domain,
        shape=shape,
        periodic_dims=(3,),   # dpsi
    )
    return grid


# ─── Capture set 선택 ──────────────────────────────────────────

def initial_values_for_capture(grid, mode="sphere", sphere_radius_ft=1500.0):
    """Initial signed-distance to capture set on grid.

    mode='sphere':  단순 sphere (Air3d sanity 와 같은 형식, 작동 검증용)
    mode='wez':     WEZ (ATA<12° AND 500<dist<3000) — 실제 게임 조건
    """
    states = grid.states  # (S, S, S, S, S, S, 6)
    if mode == "sphere":
        return signed_distance_simple_sphere(states, sphere_radius_ft)
    elif mode == "wez":
        return signed_distance_to_wez_us(states)
    else:
        raise ValueError(f"unknown capture mode: {mode}")


# ─── Value 보간 (canonical 출력) ───────────────────────────────

def lookup_nearest(values, grid, state):
    """grid 에서 state 에 가장 가까운 셀의 V 값 (nearest neighbor)."""
    idx = []
    for d in range(6):
        c = grid.coordinate_vectors[d]
        i = int(jnp.argmin(jnp.abs(c - state[d])))
        idx.append(i)
    return float(values[tuple(idx)])


# ─── 메인 ─────────────────────────────────────────────────────

def run_6d_hji(grid_per_dim=10, time_horizon=10.0,
               capture_mode="sphere", sphere_radius_ft=1500.0,
               save_path=None, verbose=True):
    """6D HJI 풀이."""
    if verbose:
        print(f"\n{'='*70}")
        print(f"  6D HJI Solver — F-16 1:1 Pursuit-Chase (variable speed)")
        print(f"{'='*70}")
        print(f"  Grid:           {grid_per_dim}⁶ = {grid_per_dim**6:,} cells")
        print(f"  Time horizon:   {time_horizon} s (backward)")
        print(f"  Capture mode:   {capture_mode}" + (f" (r={sphere_radius_ft}ft)" if capture_mode=='sphere' else ''))

    # 1. Grid
    if verbose:
        print(f"\n  [1/4] Grid 구축 중...")
    t0 = _time.time()
    grid = make_grid(grid_per_dim)
    print(f"        ✓ ({_time.time()-t0:.2f}s)  shape={grid.states.shape}, memory ≈ {grid.states.nbytes/1e6:.1f} MB")

    # 2. Dynamics
    dyn = F16Pursuit6D()

    # 3. Initial values (capture set boundary)
    if verbose:
        print(f"\n  [2/4] Initial values (signed distance to capture)...")
    t0 = _time.time()
    initial_values = initial_values_for_capture(grid, mode=capture_mode, sphere_radius_ft=sphere_radius_ft)
    print(f"        ✓ ({_time.time()-t0:.2f}s)  V range: [{float(initial_values.min()):.1f}, {float(initial_values.max()):.1f}] ft")

    # 4. Solver 설정 — BRT 모드
    solver_settings = hj.SolverSettings.with_accuracy(
        "low",  # 빠른 prototype
        hamiltonian_postprocessor=hj.solver.backwards_reachable_tube,
    )

    # Canonical V before solve
    V0_canonical = lookup_nearest(initial_values, grid, CANONICAL_6D)
    if verbose:
        print(f"\n  Initial V at canonical 6D: {V0_canonical:+.1f} ft")

    # 5. Solve
    if verbose:
        print(f"\n  [3/4] HJI backward solve ({time_horizon}s)...  (JIT 컴파일 첫회 ~수 분)")
    t0 = _time.time()
    times = jnp.array([0.0, -time_horizon])
    all_values = hj.solve(
        solver_settings, dyn, grid, times, initial_values,
        progress_bar=False,
    )
    final_values = all_values[-1]
    solve_time = _time.time() - t0
    if verbose:
        print(f"        ✓ ({solve_time:.1f}s)")

    # 6. 결과
    V_canonical = lookup_nearest(final_values, grid, CANONICAL_6D)
    n_captured = int(jnp.sum(final_values < 0))
    n_total = int(final_values.size)
    V_min = float(final_values.min())
    V_max = float(final_values.max())

    if verbose:
        print(f"\n  [4/4] 결과:")
        print(f"        V*(canonical 6D, t=-{time_horizon}s):  {V_canonical:+.1f} ft")
        print(f"        Initial V at canonical:           {V0_canonical:+.1f} ft")
        print(f"        Δ (improvement):                  {V_canonical - V0_canonical:+.1f} ft")
        print(f"\n        BRT 통계:")
        print(f"          capture 가능 영역 (V<0):  {n_captured:,} / {n_total:,} ({100*n_captured/n_total:.1f}%)")
        print(f"          V range:                  [{V_min:.1f}, {V_max:.1f}] ft")

        print(f"\n  해석:")
        if V_canonical < -10:
            print(f"    V* < 0  →  canonical 에서 capture 보장 (가변속/고도 우위!)")
        elif V_canonical < 100:
            print(f"    V* ≈ 0  →  canonical 이 barrier 근처 → DRAW 가설 일치")
        else:
            print(f"    V* > 0  →  canonical 은 escape 영역 → 가변속만으로 부족")
            print(f"              ({time_horizon}s 더 풀면 변화 가능)")

    # 7. Save
    if save_path:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        # 차원별 grid coordinates 보존
        coord_arrays = {f"coord_{i}": np.asarray(grid.coordinate_vectors[i]) for i in range(6)}
        np.savez_compressed(
            save_path,
            V=np.asarray(final_values),
            V_initial=np.asarray(initial_values),
            grid_shape=np.array(grid.states.shape),
            time_horizon_s=time_horizon,
            capture_mode=capture_mode,
            **coord_arrays,
        )
        if verbose:
            print(f"\n  ✓ Saved: {save_path}  ({save_path.stat().st_size/1e6:.1f} MB)")

    return {
        "V_canonical": V_canonical,
        "V0_canonical": V0_canonical,
        "delta_V": V_canonical - V0_canonical,
        "V_range": (V_min, V_max),
        "n_captured": n_captured,
        "n_total": n_total,
        "solve_time_s": solve_time,
        "grid_shape": grid.states.shape[:-1],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--grid", type=int, default=10, help="bins per dim (default 10)")
    parser.add_argument("--time", type=float, default=10.0, help="time horizon (s)")
    parser.add_argument("--capture", choices=["sphere", "wez"], default="sphere",
                        help="capture set mode")
    parser.add_argument("--sphere-radius", type=float, default=1500.0,
                        help="sphere capture radius (ft, used if --capture=sphere)")
    parser.add_argument("--save", type=str, default=None, help="output .npz path")
    args = parser.parse_args()

    print(f"\nJAX devices: {jax.devices()}")

    result = run_6d_hji(
        grid_per_dim=args.grid,
        time_horizon=args.time,
        capture_mode=args.capture,
        sphere_radius_ft=args.sphere_radius,
        save_path=args.save,
    )

    print(f"\n{'='*70}")
    print(f"  요약")
    print(f"{'='*70}")
    for k, v in result.items():
        print(f"  {k:25} {v}")
