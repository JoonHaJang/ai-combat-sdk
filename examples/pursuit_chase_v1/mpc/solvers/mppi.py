"""MPPI (Model Predictive Path Integral) — Phase 1 primary solver.

design ref: PHASE1_MPC_DESIGN.md §8 (decision δ revised 2026-05-18).

algorithm:
    1. SAMPLE N candidate τ-trajectories (gaussian around prior_mean)
    2. SIMULATE each (H step rollout with adversary oracle)
    3. WEIGHT each (w_n = exp(-J_n / λ_temp))
    4. UPDATE mean (weighted avg)
    5. APPLY τ_0 (first step), SHIFT for warm start

hyperparams (Phase 1 1차):
    N=64, λ_temp=0.1, σ=0.15, H=10
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np

from .. import joint_dynamics as jd
from .. import features as feat_mod
from .. import costs as cost_mod
from .. import state as st


class MPPISolver:
    """MPPI solver. MPCSolver protocol 만족."""

    name = "mppi"

    def __init__(
        self,
        tau_param,
        H: int = 10,
        N_samples: int = 64,
        lambda_temp: float = 0.1,
        sigma: float = 0.15,
        dt: float = 0.1,
        seed: Optional[int] = None,
    ):
        self.tau_param = tau_param
        self.H = H
        self.N = N_samples
        self.lambda_temp = lambda_temp
        self.sigma = sigma
        self.dt = dt
        self.rng = np.random.default_rng(seed)
        self.last_iter_count = 1   # MPPI = 1 pass (no iteration)

        # baseline optimal_control 함수 lazy load (lazy import to avoid cycles)
        self._optimal_control = None
        self._optimal_control_loaded = False

    # ─── public API ───────────────────────────────────────────────

    def solve(
        self,
        z0: np.ndarray,
        admissible: dict,
        adversary,
        features_init: dict,
        prior_params: Optional[np.ndarray] = None,
    ) -> tuple[np.ndarray, dict]:
        """N=64 sample → simulate → weight → update.

        Returns (tau_trajectory shape (H, n_modes), info dict).
        """
        t_start = time.time()

        # 1. SAMPLE
        if prior_params is None:
            # cold start — admissible 중앙
            prior_params = self._admissible_center(admissible)
        samples = self.tau_param.sample(prior_params, self.sigma, self.N, self.rng)
        # project each sample to admissible
        samples_projected = np.array([self.tau_param.project(s, admissible)
                                       for s in samples])

        # 2. SIMULATE — each sample
        costs = np.zeros(self.N)
        for n in range(self.N):
            traj = self.tau_param.expand(samples_projected[n])
            costs[n] = self._rollout_cost(z0, traj, adversary, features_init)

        # 3. WEIGHT — exp(-J/λ), normalized
        # subtract min for numerical stability
        cmin = np.min(costs)
        weights = np.exp(-(costs - cmin) / self.lambda_temp)
        weights /= weights.sum() + 1e-12

        # 4. UPDATE — weighted avg
        new_params = (weights[:, None] * samples_projected).sum(axis=0)
        # re-project after avg (might violate admissible slightly)
        new_params = self.tau_param.project(new_params, admissible)

        # 5. expand to trajectory
        new_traj = self.tau_param.expand(new_params)

        elapsed = time.time() - t_start
        best_idx = int(np.argmin(costs))
        info = {
            "solver": "mppi",
            "N_samples": self.N,
            "cost_min": float(cmin),
            "cost_mean": float(costs.mean()),
            "cost_best_idx": best_idx,
            "weight_max": float(weights.max()),
            "elapsed_ms": elapsed * 1000.0,
            "params_new": new_params,
            "tau_0": {m: float(new_traj[0, j])
                       for j, m in enumerate(["pn", "corner", "ldt", "yoyo", "T"])},
        }
        return new_traj, info

    # ─── internals ────────────────────────────────────────────────

    def _ensure_oc(self):
        """lazy load optimal_control to avoid import cycles."""
        if not self._optimal_control_loaded:
            try:
                from ...nodes.continuous_policy import optimal_control
                self._optimal_control = optimal_control
            except Exception:
                # fallback: try sibling import path
                self._optimal_control = None
            self._optimal_control_loaded = True
        return self._optimal_control

    def _rollout_cost(
        self,
        z0: np.ndarray,
        tau_traj: np.ndarray,
        adversary,
        features_init: dict,
    ) -> float:
        """single trajectory rollout + cost."""
        oc = self._ensure_oc()
        z = z0.copy()
        u_prev = None
        f_prev = features_init.get("layer1_relational")
        J = 0.0
        feat_ext = feat_mod.DefaultFeatureExtractor(dt=self.dt)

        for t in range(self.H):
            # build τ dict from trajectory step
            tau_t = {m: float(tau_traj[t, j])
                     for j, m in enumerate(["pn", "corner", "ldt", "yoyo", "T"])}

            # our control via optimal_control
            x_rel = st.z_to_relative_6d(z)
            alt_ft = float(z[st.SLICE_US][st.IDX_H])
            if oc is not None:
                try:
                    u_us, _ = oc(x_rel, tau_t, alt_ft=alt_ft)
                except Exception:
                    u_us = self._fallback_u(tau_t)
            else:
                u_us = self._fallback_u(tau_t)

            # opp control via adversary
            opp_u = adversary.predict(z[st.SLICE_OPP], z[st.SLICE_US])

            # step dynamics
            z_next = jd.joint_step(z, u_us, opp_u, dt=self.dt)
            # extract features for cost
            features_t = feat_ext.extract(z_next, obs={}, history=None)
            f_now = features_t["layer1_relational"]

            # cost
            J += cost_mod.running_cost(z_next, u_us, u_prev, f_now, f_prev, dt=self.dt)
            u_prev = u_us
            f_prev = f_now
            z = z_next

        # terminal
        J += cost_mod.terminal_cost(z, f_prev)
        return J

    @staticmethod
    def _fallback_u(tau_t: dict) -> np.ndarray:
        """optimal_control 호출 실패 시 fallback — τ 가중 단순 명령.

        tau-weighted simple heuristic — corner→neutral, pn→hold, ldt→opposite.
        본격 fallback 은 회귀 안전용 (compute_action 의 try-except 가 큰 단위 fallback).
        """
        # 가장 단순한 default: hold
        return np.array([0.0, 0.0, 0.0])

    @staticmethod
    def _admissible_center(admissible: dict) -> np.ndarray:
        """admissible region 의 중앙 점 → params."""
        from ..tau_param.piecewise_constant import (
            PiecewiseConstant3Segment, MODES, N_SEGMENTS,
        )
        center_dict = {m: 0.5 * (admissible.get(m, (0.0, 1.0))[0]
                                   + admissible.get(m, (0.0, 1.0))[1])
                       for m in MODES}
        # ensure simplex
        s = sum(center_dict.values())
        if s > 1.0:
            for m in MODES:
                center_dict[m] /= s
        seg = np.array([center_dict[m] for m in MODES])
        params = np.concatenate([seg, seg, seg, [3.0, 4.0]])
        return params


def _self_test():
    """smoke test: solve once, check tau_0 in admissible."""
    from ..tau_param.piecewise_constant import PiecewiseConstant3Segment
    from ..adversary.oracle import OracleAdversary

    tau_param = PiecewiseConstant3Segment(H=10)
    solver = MPPISolver(tau_param, N_samples=32, H=10, seed=42)
    adversary = OracleAdversary("pursue")

    # mock state — aggressive IC
    obs = {
        "ego_altitude_ft": 15000.0, "ego_vc_kts": 386.8, "turn_rate_degs": 0.0,
        "relative_bearing_deg": 30.0, "distance_ft": 5000.0, "alt_gap_ft": 0.0,
        "hca_deg": 60.0, "energy_diff_ft": 0.0, "closure_rate_kts": 10.0,
    }
    z0 = st.obs_to_state_12d(obs)
    feat_ext = feat_mod.DefaultFeatureExtractor()
    features = feat_ext.extract(z0, obs)

    admissible = {
        "pn": (0.0, 1.0), "corner": (0.0, 1.0),
        "ldt": (0.0, 0.5), "yoyo": (0.0, 0.5), "T": (0.0, 0.5),
    }

    tau_traj, info = solver.solve(z0, admissible, adversary, features)
    print(f"τ-trajectory shape: {tau_traj.shape}")
    print(f"info: cost_min={info['cost_min']:.4f}, mean={info['cost_mean']:.4f}, "
          f"elapsed={info['elapsed_ms']:.1f}ms")
    print(f"τ_0: {info['tau_0']}")
    print(f"τ_5: {dict(zip(['pn','corner','ldt','yoyo','T'], tau_traj[5]))}")
    print(f"τ_9: {dict(zip(['pn','corner','ldt','yoyo','T'], tau_traj[9]))}")
    print("[mppi.py] self-test PASS")


if __name__ == "__main__":
    _self_test()
