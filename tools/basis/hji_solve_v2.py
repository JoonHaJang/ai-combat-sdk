"""6D HJI v2 — WEZ capture, 정확 envelope, 긴 horizon. PLAN.md §3 의 정정.

기존 hji_solve_6d.py 대비 변경:
  1. Capture set: sphere(1500ft) → WEZ (ATA<12 + 500<dist<3000, 실 채점기준)
  2. ω_max: 19.16°/s (canonical V=386.8 가정) → 22.24°/s (peak doghouse 15000ft, §2.2)
  3. Time horizon: 10s → 30s (실 매치 300s 의 1/10)
  4. Capture distance: 3D sphere → ATA·dist 2D WEZ membership (signed_distance_to_wez_us 그대로)

CPU JAX 환경: 12^6 grid + 30s 시간지평 ≈ 30-60분.

산출:
  logs/hji/V6d_wez_v2.npz — Pursuit_Chase_BT 의 fallback LUT
"""

from __future__ import annotations

import argparse
import time as _time
from pathlib import Path

import numpy as np
import jax
import jax.numpy as jnp
import hj_reachability as hj

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.basis.dynamics_f16_6d_hj import (
    F16Pursuit6D,
    signed_distance_to_wez_us,
    CANONICAL_6D,
    V_MIN_KTS, V_MAX_KTS,
    KTS_TO_FPS,
)
from tools.basis import envelope_f16 as env


# ─── Envelope 정정 (PLAN §2.2 doghouse) ────────────────────────

# Peak omega_max from doghouse @ 15000ft (V_corner=438.6 kts)
OMEGA_MAX_PEAK_DEG = 22.24
OMEGA_MAX_PEAK_RAD = OMEGA_MAX_PEAK_DEG * np.pi / 180.0

# Conservative ω_max (보수적 — pursuer 측은 under-estimate 안 됨)
# 모든 V 영역에서 사용 가능한 ω_max 의 UPPER bound 를 사용 → HJI 가 worst case 분석
OMEGA_MAX_USE_RAD = OMEGA_MAX_PEAK_RAD
GAMMA_MAX_USE_RAD = 0.7 * OMEGA_MAX_USE_RAD   # γ̇_max ≈ 0.7·ω_max (envelope §2.2)
ACCEL_MAX_USE_KTS = 15.0


# ─── Grid — 12^6 (3M cells, ~144 MB float32) ────────────────────

DOMAIN = {
    "dx_ft":   (-6000., +6000.),
    "dy_ft":   (-6000., +6000.),
    "dh_ft":   (-4000., +4000.),
    "dpsi":    (-np.pi, +np.pi),
    "V_p_kts": (V_MIN_KTS, V_MAX_KTS),
    "V_e_kts": (V_MIN_KTS, V_MAX_KTS),
}


def make_grid(shape_per_dim: int = 12):
    lo = jnp.array([d[0] for d in DOMAIN.values()])
    hi = jnp.array([d[1] for d in DOMAIN.values()])
    domain = hj.sets.Box(lo=lo, hi=hi)
    grid = hj.Grid.from_lattice_parameters_and_boundary_conditions(
        domain=domain,
        shape=(shape_per_dim,) * 6,
        periodic_dims=(3,),
    )
    return grid


# ─── Solve ────────────────────────────────────────────────────

def run_solve(grid_per_dim: int = 12,
              time_horizon_s: float = 30.0,
              save_path: str = "logs/hji/V6d_wez_v2.npz",
              verbose: bool = True):
    if verbose:
        print(f"\n{'='*72}")
        print(f"  6D HJI v2 — WEZ capture, doghouse envelope, {time_horizon_s}s horizon")
        print(f"{'='*72}")
        print(f"  JAX devices: {jax.devices()}")
        print(f"  Grid:        {grid_per_dim}⁶ = {grid_per_dim**6:,} cells")
        print(f"  Time:        {time_horizon_s}s backward")
        print(f"  ω_max:       {OMEGA_MAX_PEAK_DEG:.2f}°/s (doghouse peak)")
        print(f"  Capture:     WEZ (ATA<12° + 500<dist<3000)")

    # 1. Grid
    print(f"\n  [1/4] Grid 구축...")
    t0 = _time.time()
    grid = make_grid(grid_per_dim)
    print(f"        ✓ ({_time.time()-t0:.1f}s)  shape={grid.states.shape}")

    # 2. Dynamics (정정 envelope)
    dyn = F16Pursuit6D(
        omega_max_rad_s=OMEGA_MAX_USE_RAD,
        gamma_max_rad=GAMMA_MAX_USE_RAD,
        accel_max_kts_s=ACCEL_MAX_USE_KTS,
    )

    # 3. Initial values (signed distance to WEZ)
    print(f"\n  [2/4] Initial values — WEZ signed distance...")
    t0 = _time.time()
    initial_values = signed_distance_to_wez_us(grid.states)
    n_inside = int(jnp.sum(initial_values < 0))
    print(f"        ✓ ({_time.time()-t0:.1f}s)  WEZ inside (t=0): {n_inside:,} / {grid.states.size//6:,} cells")
    print(f"        V range: [{float(initial_values.min()):+.1f}, {float(initial_values.max()):+.1f}] ft")

    # 4. Solver
    solver_settings = hj.SolverSettings.with_accuracy(
        "low",
        hamiltonian_postprocessor=hj.solver.backwards_reachable_tube,
    )

    V0_canon = float(initial_values[
        tuple(int(jnp.argmin(jnp.abs(grid.coordinate_vectors[d] - CANONICAL_6D[d])))
              for d in range(6))
    ])
    print(f"\n  Initial V(canonical) = {V0_canon:+.1f} ft (-=inside, +=outside WEZ)")

    # 5. Solve
    print(f"\n  [3/4] HJI backward solve {time_horizon_s}s...  (JIT 첫회 수분)")
    t0 = _time.time()
    times = jnp.array([0.0, -time_horizon_s])
    all_values = hj.solve(
        solver_settings, dyn, grid, times, initial_values,
        progress_bar=False,
    )
    final_values = all_values[-1]
    solve_time = _time.time() - t0
    print(f"        ✓ ({solve_time/60:.1f} min)")

    # 6. 결과
    idx_canon = tuple(int(jnp.argmin(jnp.abs(grid.coordinate_vectors[d] - CANONICAL_6D[d])))
                       for d in range(6))
    V_canon = float(final_values[idx_canon])
    n_capturable = int(jnp.sum(final_values < 0))
    n_total = int(final_values.size)

    print(f"\n  [4/4] 결과:")
    print(f"        V*(canonical, t=-{time_horizon_s}s) = {V_canon:+.1f} ft")
    print(f"        Initial V                        = {V0_canon:+.1f} ft")
    print(f"        Δ (수렴):                        = {V_canon - V0_canon:+.1f} ft")
    print(f"        Capturable 영역 (V<0):           = {n_capturable:,} / {n_total:,} ({100*n_capturable/n_total:.1f}%)")

    if V_canon < 0:
        print(f"\n  ★ canonical 에서 WEZ 도달 가능 — Phase A 가설 확인")
    elif V_canon < 200:
        print(f"\n  ~ canonical 이 barrier 근처 — 가변속 우위 marginal")
    else:
        print(f"\n  ! canonical 가 escape 영역 — {time_horizon_s}s 부족, 더 풀어야")

    # 7. Save
    if save_path:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        coord_arrays = {f"coord_{i}": np.asarray(grid.coordinate_vectors[i]) for i in range(6)}
        np.savez_compressed(
            save_path,
            V=np.asarray(final_values),
            V_initial=np.asarray(initial_values),
            grid_shape=np.array(grid.states.shape),
            time_horizon_s=time_horizon_s,
            capture_mode="wez_v2",
            omega_max_rad_s=OMEGA_MAX_USE_RAD,
            gamma_max_rad=GAMMA_MAX_USE_RAD,
            accel_max_kts_s=ACCEL_MAX_USE_KTS,
            **coord_arrays,
        )
        print(f"\n  ✓ Saved: {save_path}  ({save_path.stat().st_size/1e6:.1f} MB)")

    return {
        "V_canonical": V_canon,
        "V0_canonical": V0_canon,
        "delta_V": V_canon - V0_canon,
        "n_capturable": n_capturable,
        "n_total": n_total,
        "solve_time_min": solve_time / 60,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--grid", type=int, default=12)
    p.add_argument("--time", type=float, default=30.0)
    p.add_argument("--save", type=str, default="logs/hji/V6d_wez_v2.npz")
    args = p.parse_args()
    run_solve(grid_per_dim=args.grid, time_horizon_s=args.time, save_path=args.save)
