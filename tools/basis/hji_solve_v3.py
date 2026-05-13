"""HJI 6D v3 — 정정된 솔버 설정 (R7 의 v2 한계 극복).

v2 의 결함 (PLAN §2.5.9 정직 기록):
  - accuracy="low" → 1-2 big step → BRT propagation 사실상 없음
  - times=[0, -T] 2점 → 출력 checkpoint 없어 내부 step 강제 안 됨
  - 결과: solve 6초, V(canonical) 거의 변화 X, capturable 영역 미증가

v3 정정:
  1. accuracy="medium" (Godunov-type discretization)
  2. times = linspace(0, -T, 31) — 2s 간격 dense checkpoint
  3. progress_bar=True — 실제 step 진행률 확인
  4. capture set = WEZ (동일)

예상 (CPU JAX):
  - 솔브 시간: 30-90분 (v2 의 6초 × 300-900배)
  - BRT 확장: 0.46% → 5-30% 목표
  - V(canonical) 가 진정으로 감소 (예상 음수 또는 매우 작은 양수)
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
)


# v2 와 동일 envelope (doghouse peak)
OMEGA_MAX_PEAK_RAD = 22.24 * np.pi / 180.0
GAMMA_MAX_USE_RAD = 0.7 * OMEGA_MAX_PEAK_RAD
ACCEL_MAX_USE_KTS = 15.0


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
    return hj.Grid.from_lattice_parameters_and_boundary_conditions(
        domain=domain,
        shape=(shape_per_dim,) * 6,
        periodic_dims=(3,),
    )


def run_v3(grid_per_dim: int = 12,
           time_horizon_s: float = 60.0,
           n_checkpoints: int = 31,
           accuracy: str = "medium",
           save_path: str = "logs/hji/V6d_wez_v3.npz",
           verbose: bool = True):
    if verbose:
        print(f"\n{'='*72}")
        print(f"  HJI 6D v3 — 정정 솔버 (accuracy={accuracy}, dense checkpoints)")
        print(f"{'='*72}")
        print(f"  JAX devices:  {jax.devices()}")
        print(f"  Grid:         {grid_per_dim}⁶ = {grid_per_dim**6:,} cells")
        print(f"  Time horizon: {time_horizon_s}s, {n_checkpoints} checkpoints")
        print(f"  dt avg:       {time_horizon_s/(n_checkpoints-1):.2f}s per checkpoint")
        print(f"  accuracy:     {accuracy}")

    # 1. Grid
    print(f"\n  [1/4] Grid 구축...")
    t0 = _time.time()
    grid = make_grid(grid_per_dim)
    print(f"        ✓ ({_time.time()-t0:.1f}s)")

    # 2. Dynamics
    dyn = F16Pursuit6D(
        omega_max_rad_s=float(OMEGA_MAX_PEAK_RAD),
        gamma_max_rad=float(GAMMA_MAX_USE_RAD),
        accel_max_kts_s=ACCEL_MAX_USE_KTS,
    )

    # 3. Initial WEZ signed distance
    print(f"\n  [2/4] Initial WEZ signed distance...")
    t0 = _time.time()
    initial_values = signed_distance_to_wez_us(grid.states)
    n_inside = int(jnp.sum(initial_values < 0))
    print(f"        ✓ ({_time.time()-t0:.1f}s)  WEZ inside: {n_inside:,} cells")
    print(f"        V range: [{float(initial_values.min()):+.1f}, {float(initial_values.max()):+.1f}] ft")

    # 4. Solver — 정정된 설정
    solver_settings = hj.SolverSettings.with_accuracy(
        accuracy,
        hamiltonian_postprocessor=hj.solver.backwards_reachable_tube,
    )

    idx_canon = tuple(int(jnp.argmin(jnp.abs(grid.coordinate_vectors[d] - CANONICAL_6D[d])))
                       for d in range(6))
    V0_canon = float(initial_values[idx_canon])
    print(f"\n  Initial V(canonical) = {V0_canon:+.1f} ft")

    # 5. Solve — dense checkpoints
    print(f"\n  [3/4] HJI backward solve, dense checkpoints...")
    print(f"        예상: JIT 컴파일 1-3분, 솔브 본체 30분-2시간")
    t0 = _time.time()
    times = jnp.linspace(0.0, -time_horizon_s, n_checkpoints)
    all_values = hj.solve(
        solver_settings, dyn, grid, times, initial_values,
        progress_bar=False,   # tqdm 미설치
    )
    final_values = all_values[-1]
    solve_time = _time.time() - t0
    print(f"\n        ✓ 총 {solve_time/60:.1f} 분")

    # 6. 결과 — 중간 checkpoint 도 확인
    print(f"\n  [4/4] 결과:")
    print(f"        V*(canonical) trajectory through time:")
    for i in range(0, n_checkpoints, max(1, n_checkpoints // 6)):
        V_at_i = float(all_values[i][idx_canon])
        n_cap_i = int(jnp.sum(all_values[i] < 0))
        t_i = float(times[i])
        print(f"          t={t_i:+5.1f}s: V(canonical)={V_at_i:+8.1f} ft, "
              f"capturable={n_cap_i:,} ({100*n_cap_i/final_values.size:.2f}%)")

    V_canon = float(final_values[idx_canon])
    n_capturable = int(jnp.sum(final_values < 0))
    n_total = int(final_values.size)
    print(f"\n        최종 (t=-{time_horizon_s}s):")
    print(f"          V(canonical) = {V_canon:+.1f} ft  (Δ from initial: {V_canon-V0_canon:+.1f})")
    print(f"          Capturable   = {n_capturable:,} / {n_total:,} ({100*n_capturable/n_total:.2f}%)")
    print(f"          V range      = [{float(final_values.min()):+.1f}, {float(final_values.max()):+.1f}]")

    if V_canon < 0:
        print(f"\n  ★★ V*(canonical) < 0 — capture 보장 (가변속 우위 입증)")
    elif V_canon < 200:
        print(f"\n  ★ V*(canonical) < 200 — barrier 근처")
    else:
        print(f"\n  ~ V*(canonical) > 200 — 더 긴 horizon 필요 또는 grid 한계")

    # 7. Save
    if save_path:
        sp = Path(save_path)
        sp.parent.mkdir(parents=True, exist_ok=True)
        coord_arrays = {f"coord_{i}": np.asarray(grid.coordinate_vectors[i]) for i in range(6)}
        np.savez_compressed(
            sp,
            V=np.asarray(final_values),
            V_initial=np.asarray(initial_values),
            V_trajectory=np.asarray(all_values),
            times=np.asarray(times),
            grid_shape=np.array(grid.states.shape),
            time_horizon_s=time_horizon_s,
            accuracy=accuracy,
            n_checkpoints=n_checkpoints,
            capture_mode="wez_v3",
            **coord_arrays,
        )
        print(f"\n  ✓ Saved: {sp}  ({sp.stat().st_size/1e6:.1f} MB)")

    return {
        "V_canonical": V_canon, "V0_canonical": V0_canon,
        "n_capturable": n_capturable, "solve_time_min": solve_time / 60,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--grid", type=int, default=12)
    p.add_argument("--time", type=float, default=60.0)
    p.add_argument("--checkpoints", type=int, default=31)
    p.add_argument("--accuracy", choices=["low", "medium", "high"], default="medium")
    p.add_argument("--save", type=str, default="logs/hji/V6d_wez_v3.npz")
    args = p.parse_args()
    run_v3(
        grid_per_dim=args.grid,
        time_horizon_s=args.time,
        n_checkpoints=args.checkpoints,
        accuracy=args.accuracy,
        save_path=args.save,
    )
