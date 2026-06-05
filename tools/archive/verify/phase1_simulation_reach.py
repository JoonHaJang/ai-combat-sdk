"""Phase 1 Simulation-based Reachability — v2.1 보정 (2026-05-26).

design ref: PHASE1_MPC_DESIGN.md v2 §9.5.

v2.0 → v2.1 변경 (사용자 통찰 반영):
    - H 짧음 문제: H {10, 30, 50} sweep 지원 (CLI --H multi-value)
    - Z6 너무 엄격: trend-based trigger 추가 (peak/first-reach 측정)
    - random 비효율: --us-mode mppi_informed (실제 MPC 호출)
    - 더 informative metrics: 첫 도달 tick, peak advantage, trajectory mean

목적: 각 semantic event 가 *실제로 도달 가능*한지 측정.

usage:
    python tools/verify/phase1_simulation_reach.py
    python tools/verify/phase1_simulation_reach.py --H 10 30 50 --n-samples 200
    python tools/verify/phase1_simulation_reach.py --us-mode mppi_informed
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from examples.pursuit_chase_v1.mpc import state as st
from examples.pursuit_chase_v1.mpc import features as feat_mod
from examples.pursuit_chase_v1.mpc import joint_dynamics as jd
from examples.pursuit_chase_v1.mpc.opp_model.oracle import OracleModel
from examples.pursuit_chase_v1.mpc.opp_model.constant_action import ConstantActionModel
from examples.pursuit_chase_v1.mpc.solvers.mppi import MPPISolver
from examples.pursuit_chase_v1.mpc.tau_param.piecewise_constant import PiecewiseConstant3Segment

# lazy load — optimal_control needs full project setup
_OPTIMAL_CONTROL = None
def _get_optimal_control():
    global _OPTIMAL_CONTROL
    if _OPTIMAL_CONTROL is None:
        try:
            from examples.pursuit_chase_v1.nodes.continuous_policy import optimal_control
            _OPTIMAL_CONTROL = optimal_control
        except Exception:
            _OPTIMAL_CONTROL = None
    return _OPTIMAL_CONTROL


# global MPPI solver — reuse across rollouts
_MPPI_SOLVER = None
def _get_mppi_solver(H: int = 10):
    global _MPPI_SOLVER
    if _MPPI_SOLVER is None or _MPPI_SOLVER.H != H:
        _MPPI_SOLVER = MPPISolver(
            tau_param=PiecewiseConstant3Segment(H=H),
            N_samples=32, H=H, lambda_temp=0.1, sigma=0.15, seed=42,
        )
    return _MPPI_SOLVER

# OffensiveContext-style admissible — for MPPI test
_TEST_ADMISSIBLE = {
    "pn":         (0.2, 0.8),
    "corner":     (0.0, 0.5),
    "ldt":        (0.0, 0.3),
    "yoyo":       (0.0, 0.3),
    "T":          (0.0, 0.7),
    "lead":       (0.0, 0.8),
    "oneCircle":  (0.0, 0.5),
    "twoCircle":  (0.0, 0.3),
    "energy":     (0.0, 0.3),
}


# ─── IC sampling ────────────────────────────────────────────────


def sample_initial_z(rng: np.random.Generator) -> np.ndarray:
    """aggressive IC: mutual beam."""
    z = np.zeros(12)
    z[st.SLICE_US] = [0.0, 0.0, 15000.0, 0.0, 386.8, 0.0]
    bearing = rng.uniform(-math.pi/2, math.pi/2)
    dist = rng.uniform(3000.0, 5000.0)
    z[6] = dist * math.sin(bearing)
    z[7] = dist * math.cos(bearing)
    z[8] = 15000.0 + rng.uniform(-500.0, 500.0)
    z[9] = bearing + math.pi + rng.uniform(-0.5, 0.5)
    z[10] = rng.uniform(350.0, 420.0)
    z[11] = 0.0
    return z


# ─── control modes ──────────────────────────────────────────────


def sample_us_control(
    rng: np.random.Generator,
    mode: str,
    z: np.ndarray = None,
    history_layer1: list = None,
) -> np.ndarray:
    """우리 control sample.

    modes:
        random      — uniform admissible (v2.0 default)
        corner_only — Z2/Z3 scenario, corner turn 위주
        pn_only     — Z4 scenario, PN dominant
        mppi_informed — actually call MPPI (slow but realistic)
        offensive_intent — heuristic: 적 방향 강선회 + 적당 가속
    """
    if mode == "corner_only":
        omega = rng.uniform(-math.radians(15.0), math.radians(15.0))
        return np.array([omega, 0.0, 5.0])
    elif mode == "pn_only":
        omega = rng.uniform(-math.radians(8.0), math.radians(8.0))
        return np.array([omega, 0.0, 0.0])
    elif mode == "offensive_intent":
        # heuristic: 적 방향 strong PN + accel
        if z is not None:
            opp_x = z[st.SLICE_OPP]
            us_x = z[st.SLICE_US]
            dx = opp_x[st.IDX_X] - us_x[st.IDX_X]
            dy = opp_x[st.IDX_Y] - us_x[st.IDX_Y]
            # turn toward opp — rb=atan2(dx,dy) in our frame (ψ_us=0 assumed)
            rb = math.atan2(dx, dy)   # rad
            # PN-like: ω proportional to rb, max 15°/s
            omega = -math.copysign(min(math.radians(15.0), abs(rb) * 0.5), rb)
            return np.array([omega, 0.0, 5.0])
        else:
            return np.zeros(3)
    elif mode == "mppi_informed":
        # v2 Part B+: actual MPPI call with all 9 BFM modes
        # uses cached singleton solver + OffensiveContext-like admissible
        if z is None:
            return sample_us_control(rng, "random", z, history_layer1)
        try:
            oc_fn = _get_optimal_control()
            solver = _get_mppi_solver(H=10)
            # mock features (Layer 1 only, sufficient for MPPI cost)
            extractor = feat_mod.DefaultFeatureExtractor()
            features = {"layer1_relational": feat_mod.layer1_relational(z, obs={})}
            # build opp model from short pseudo-history
            opp_model = ConstantActionModel(history=None)
            tau_traj, info = solver.solve(
                z0=z, admissible=_TEST_ADMISSIBLE,
                adversary=opp_model, features_init=features,
                prior_params=None,
            )
            tau_0 = info["tau_0"]
            # convert tau_0 → u via optimal_control
            if oc_fn is not None:
                x_rel = st.z_to_relative_6d(z)
                alt_ft = float(z[st.SLICE_US][st.IDX_H])
                u_us, _ = oc_fn(x_rel, tau_0, alt_ft=alt_ft)
                return u_us
            else:
                return sample_us_control(rng, "offensive_intent", z, history_layer1)
        except Exception:
            return sample_us_control(rng, "offensive_intent", z, history_layer1)
    else:
        # random default
        omega = rng.uniform(-math.radians(20.0), math.radians(20.0))
        gamma = rng.uniform(-math.radians(10.0), math.radians(10.0))
        accel = rng.uniform(-10.0, 10.0)
        return np.array([omega, gamma, accel])


# ─── rollout + features ─────────────────────────────────────────


def rollout_with_features(
    z0: np.ndarray,
    H: int,
    us_control_mode: str,
    opp_model,
    rng: np.random.Generator,
    dt: float = 0.1,
) -> dict:
    """H step rollout + per-step Layer 1/3 + Z6 trend metrics."""
    extractor = feat_mod.DefaultFeatureExtractor(dt=dt)
    z = z0.copy()
    layer1_history = []

    semantic_hits = {
        "is_energy_race_losing": False,
        "is_parallel_chase_forming": False,
        "is_position_swinging_to_us": False,
        "opp_committed_to_turn": False,
        "merge_window_opening": False,
        "is_inside_us": False,
        "is_under_threat": False,
    }
    semantic_first_hit_step = {k: -1 for k in semantic_hits}

    # Z6 detailed metrics
    pos_adv_traj = []
    pos_adv_first_above_10 = -1
    pos_adv_first_above_20 = -1
    pos_adv_first_above_30 = -1
    z6_strict_first = -1   # AA-ATA > 30 OR is_position_swinging_to_us > 0.6
    z6_trend_first = -1    # 5+ consecutive steps with d(pos_adv)/dt > 5°/s

    for t in range(H):
        l1 = feat_mod.layer1_relational(z, obs={})
        layer1_history.append(l1)
        pos_adv = l1["positional_advantage_deg"]
        pos_adv_traj.append(pos_adv)

        # graded thresholds
        if pos_adv_first_above_10 < 0 and pos_adv > 10:
            pos_adv_first_above_10 = t
        if pos_adv_first_above_20 < 0 and pos_adv > 20:
            pos_adv_first_above_20 = t
        if pos_adv_first_above_30 < 0 and pos_adv > 30:
            pos_adv_first_above_30 = t

        # layer 2/3 if enough history
        if len(layer1_history) >= 2:
            l2 = feat_mod.layer2_dynamic(l1, layer1_history[:-1], dt=dt)
            l3 = feat_mod.layer3_semantic(l1, l2, layer1_history[:-1])
            for k in semantic_hits:
                if l3.get(k, 0.0) > 0.6:
                    if not semantic_hits[k]:
                        semantic_first_hit_step[k] = t
                    semantic_hits[k] = True

            # Z6 strict (original definition)
            if z6_strict_first < 0:
                if (pos_adv > 30.0 or l3.get("is_position_swinging_to_us", 0.0) > 0.6):
                    z6_strict_first = t

            # Z6 trend — sustained positive d(pos_adv)/dt
            dpos_dt = l2.get("dpositional_advantage_dt", 0.0)
            # check sustained: last 5 steps' avg dpos/dt > 5°/s
            if z6_trend_first < 0 and len(layer1_history) >= 5:
                recent_pos = [layer1_history[i]["positional_advantage_deg"]
                              for i in range(len(layer1_history)-5, len(layer1_history))]
                slope = np.polyfit(np.arange(5)*dt, recent_pos, 1)[0]
                if slope > 5.0:
                    z6_trend_first = t

        # step
        u_us = sample_us_control(rng, us_control_mode, z, layer1_history)
        u_opp = opp_model.predict(z[st.SLICE_OPP], z[st.SLICE_US])
        z = jd.joint_step(z, u_us, u_opp, dt=dt)

    return {
        **semantic_hits,
        **{f"{k}_first_step": v for k, v in semantic_first_hit_step.items()},
        "pos_adv_peak": max(pos_adv_traj) if pos_adv_traj else 0.0,
        "pos_adv_mean": float(np.mean(pos_adv_traj)) if pos_adv_traj else 0.0,
        "pos_adv_first_above_10": pos_adv_first_above_10,
        "pos_adv_first_above_20": pos_adv_first_above_20,
        "pos_adv_first_above_30": pos_adv_first_above_30,
        "z6_strict_first": z6_strict_first,
        "z6_trend_first": z6_trend_first,
    }


# ─── scenarios ──────────────────────────────────────────────────


def run_scenario(
    us_mode: str,
    opp_model,
    n_samples: int,
    H: int,
    seed: int = 42,
) -> dict:
    rng = np.random.default_rng(seed)
    hit_counts = {}
    first_steps = {}
    pos_peaks = []
    pos_means = []
    z6_strict_steps = []
    z6_trend_steps = []
    above_10_steps = []
    above_20_steps = []
    above_30_steps = []

    for n in range(n_samples):
        z0 = sample_initial_z(rng)
        result = rollout_with_features(z0, H, us_mode, opp_model, rng)
        for k, v in result.items():
            if k.endswith("_first_step") or k in ("pos_adv_first_above_10",
                                                    "pos_adv_first_above_20",
                                                    "pos_adv_first_above_30",
                                                    "z6_strict_first",
                                                    "z6_trend_first"):
                if v >= 0:
                    first_steps.setdefault(k, []).append(v)
            elif k == "pos_adv_peak":
                pos_peaks.append(v)
            elif k == "pos_adv_mean":
                pos_means.append(v)
            else:
                # boolean hit
                hit_counts[k] = hit_counts.get(k, 0) + int(v)

    rates = {k: hit_counts[k] / n_samples for k in hit_counts}
    rates["pos_adv_peak_mean"] = float(np.mean(pos_peaks)) if pos_peaks else 0.0
    rates["pos_adv_peak_p95"] = float(np.percentile(pos_peaks, 95)) if pos_peaks else 0.0
    rates["pos_adv_trajectory_mean"] = float(np.mean(pos_means)) if pos_means else 0.0

    # ratios
    for k in ["pos_adv_first_above_10", "pos_adv_first_above_20",
              "pos_adv_first_above_30", "z6_strict_first", "z6_trend_first"]:
        n_reach = len(first_steps.get(k, []))
        rates[f"{k}_reach_rate"] = n_reach / n_samples
        if n_reach > 0:
            rates[f"{k}_mean_tick"] = float(np.mean(first_steps[k]))

    return rates


# ─── main ───────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="Phase 1 simulation reachability v2.1")
    ap.add_argument("--H", type=int, nargs="+", default=[10, 30, 50],
                    help="rollout horizons to sweep (default: 10 30 50)")
    ap.add_argument("--us-mode", default="random",
                    choices=["random", "corner_only", "pn_only",
                             "offensive_intent", "mppi_informed"])
    ap.add_argument("--n-samples", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    print("=" * 78)
    print(f"Phase 1 Simulation Reachability v2.1 (2026-05-26)")
    print(f"  H sweep     = {args.H}")
    print(f"  us_mode     = {args.us_mode}")
    print(f"  n_samples   = {args.n_samples}")
    print("=" * 78)

    opp = OracleModel(bt_type="pursue", noise_sigma_deg=0.0, seed=args.seed)

    # ─── H sweep with selected us_mode ───
    print(f"\n[H sweep] us_mode={args.us_mode}")
    print(f"{'H':>4} {'pos_peak_mean':>14} {'>10°':>8} {'>20°':>8} {'>30°':>8} "
          f"{'Z6_strict':>10} {'Z6_trend':>10}")

    for H in args.H:
        t0 = time.time()
        rates = run_scenario(args.us_mode, opp, args.n_samples, H, args.seed)
        elapsed = time.time() - t0

        peak = rates["pos_adv_peak_mean"]
        r10 = rates["pos_adv_first_above_10_reach_rate"] * 100
        r20 = rates["pos_adv_first_above_20_reach_rate"] * 100
        r30 = rates["pos_adv_first_above_30_reach_rate"] * 100
        rZ6s = rates["z6_strict_first_reach_rate"] * 100
        rZ6t = rates["z6_trend_first_reach_rate"] * 100

        print(f"{H:>4} {peak:>11.1f}° "
              f"{r10:>6.1f}% {r20:>6.1f}% {r30:>6.1f}% "
              f"{rZ6s:>8.1f}% {rZ6t:>8.1f}%  ({elapsed:.1f}s)")

    # ─── interpretation ───
    print()
    print("─" * 78)
    print("LEGEND:")
    print("  pos_peak_mean = mean of per-trial maximum positional_advantage [°]")
    print("  >X°    = % trials reaching positional_advantage > X°")
    print("  Z6_strict = % trials trigger pos>30° OR is_position_swinging_to_us>0.6")
    print("  Z6_trend  = % trials with sustained d(pos)/dt > 5°/s over 5+ steps")
    print()
    print("INTERPRETATION GUIDE:")
    print("  if Z6_trend >> Z6_strict at H=50 → 'reach 가능, 시간 더 필요' (Phase 1 OK)")
    print("  if pos_peak_mean ↑ as H ↑ but never > 15° → BFM 부족 (LeadPursuit 등 필요)")
    print("  if Z6_trend ≈ 0 at all H → us_mode 한계 / BFM 한계 둘 다 가능")
    print("─" * 78)


if __name__ == "__main__":
    main()
