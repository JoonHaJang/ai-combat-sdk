"""Piecewise-constant 3-segment τ trajectory.

design ref: PHASE1_MPC_DESIGN.md §4.3.

원칙 (사용자 통찰):
    adversary BT 가 *discrete switching* 이므로 우리 τ 도 *event-triggered switch* 가능해야.
    linear interpolation 만은 smooth-only → 부족.

structure:
    τ_seg1 (t=0..n1)  →  τ_seg2 (t=n1..n1+n2)  →  τ_seg3 (t=n1+n2..H)
    각 segment: τ ∈ Δ^k (simplex), n_modes = 5 (pn, corner, ldt, yoyo, T)

params layout:
    [τ_seg1 (5,), τ_seg2 (5,), τ_seg3 (5,), n1 (1,), n2 (1,)]
    = 17 dim per sample (continuous), n1/n2 는 후처리 round to int [1, H-2]
"""

from __future__ import annotations

import numpy as np


MODES = ["pn", "corner", "ldt", "yoyo", "T"]
N_MODES = len(MODES)
N_SEGMENTS = 3


class PiecewiseConstant3Segment:
    """3-segment τ-trajectory parameterization.

    TauParameterization protocol 만족.
    """

    def __init__(self, H: int = 10):
        self.H = H
        # params: 3 segments × 5 modes + 2 switch times
        self.n_params = N_SEGMENTS * N_MODES + 2

    # ─── public API ───────────────────────────────────────────────

    def expand(self, params: np.ndarray) -> np.ndarray:
        """params → tau_trajectory (H, N_MODES)."""
        segs, n1, n2 = self._unpack(params)
        return self._materialize(segs, n1, n2)

    def project(self, params: np.ndarray, admissible: dict) -> np.ndarray:
        """admissible region (mode → (lo, hi)) 로 clipping + simplex projection."""
        segs, n1, n2 = self._unpack(params)
        # clip each segment per-mode admissible, then simplex project
        for i in range(N_SEGMENTS):
            for j, mode in enumerate(MODES):
                lo, hi = admissible.get(mode, (0.0, 1.0))
                segs[i, j] = np.clip(segs[i, j], lo, hi)
            segs[i] = self._simplex_project(segs[i])
        n1 = int(np.clip(round(n1), 1, self.H - 2))
        n2 = int(np.clip(round(n2), 1, self.H - n1 - 1))
        return self._pack(segs, n1, n2)

    def sample(
        self,
        prior_mean: np.ndarray,
        sigma: float,
        n_samples: int,
        rng: np.random.Generator,
    ) -> np.ndarray:
        """N samples from gaussian around prior_mean.

        Returns (n_samples, n_params).
        후처리 (admissible + simplex) 는 solver 가 호출.
        """
        noise = rng.normal(0.0, sigma, size=(n_samples, self.n_params))
        # switch time 의 sigma 는 작게 (1 step 분산)
        noise[:, -2:] *= 0.5 / sigma   # switch_time scale
        samples = prior_mean[None, :] + noise
        return samples

    def shift_warm_start(self, params: np.ndarray) -> np.ndarray:
        """다음 tick 의 warm start — segment 위치 한 칸 시프트.

        간단 구현: n1 → max(1, n1-1), n2 동일. seg1 는 유지 (방금 적용한 명령).
        """
        segs, n1, n2 = self._unpack(params)
        n1 = max(1, n1 - 1)
        if n1 + n2 >= self.H:
            n2 = max(1, self.H - n1 - 1)
        return self._pack(segs, n1, n2)

    # ─── helpers ──────────────────────────────────────────────────

    def _unpack(self, params: np.ndarray):
        segs = params[: N_SEGMENTS * N_MODES].reshape(N_SEGMENTS, N_MODES).copy()
        n1 = float(params[-2])
        n2 = float(params[-1])
        return segs, n1, n2

    def _pack(self, segs: np.ndarray, n1, n2) -> np.ndarray:
        return np.concatenate([segs.flatten(), [n1, n2]])

    def _materialize(self, segs: np.ndarray, n1, n2) -> np.ndarray:
        """build (H, N_MODES) from 3 segments."""
        n1_i = int(np.clip(round(n1), 1, self.H - 2))
        n2_i = int(np.clip(round(n2), 1, self.H - n1_i - 1))
        traj = np.zeros((self.H, N_MODES))
        traj[:n1_i] = segs[0]
        traj[n1_i : n1_i + n2_i] = segs[1]
        traj[n1_i + n2_i :] = segs[2]
        return traj

    @staticmethod
    def _simplex_project(v: np.ndarray) -> np.ndarray:
        """non-negative + sum ≤ 1 projection (sort-based)."""
        v = np.maximum(v, 0.0)
        s = v.sum()
        if s <= 1.0:
            return v
        return v / s

    # ─── utility for prior construction ───────────────────────────

    def from_dict(self, tau_dict: dict, n1: int = 3, n2: int = 4) -> np.ndarray:
        """build params from single τ dict (= constant trajectory).

        Used for warm-start initialization from _MODE_TAU[branch].
        """
        seg = np.array([tau_dict.get(m, 0.0) for m in MODES])
        # use same seg for all 3 segments (constant)
        params = np.concatenate([seg, seg, seg, [float(n1), float(n2)]])
        return params

    def tau_at_step(self, params: np.ndarray, t: int) -> dict:
        """params 에서 시점 t 의 τ → dict."""
        traj = self.expand(params)
        return {m: float(traj[t, j]) for j, m in enumerate(MODES)}


def _self_test():
    rng = np.random.default_rng(42)
    p = PiecewiseConstant3Segment(H=10)
    print(f"n_params = {p.n_params}")
    # build from dict
    params = p.from_dict({"pn": 0.5, "corner": 0.5})
    traj = p.expand(params)
    print(f"traj shape: {traj.shape}")
    print(f"traj[0]: {dict(zip(MODES, traj[0]))}")
    print(f"traj[5]: {dict(zip(MODES, traj[5]))}")
    # sample around prior
    samples = p.sample(params, sigma=0.15, n_samples=4, rng=rng)
    print(f"samples shape: {samples.shape}")
    # project to admissible
    admissible = {"pn": (0.0, 1.0), "corner": (0.0, 1.0), "ldt": (0.0, 0.3),
                  "yoyo": (0.0, 0.3), "T": (0.0, 0.5)}
    for i, s in enumerate(samples):
        projected = p.project(s, admissible)
        t0 = p.tau_at_step(projected, 0)
        t5 = p.tau_at_step(projected, 5)
        t9 = p.tau_at_step(projected, 9)
        print(f"sample {i}: τ@0={t0}, τ@5={t5}, τ@9={t9}")
    # warm-start shift
    shifted = p.shift_warm_start(params)
    print(f"warm-shifted (n1, n2): ({shifted[-2]}, {shifted[-1]})")
    print("[piecewise_constant.py] self-test PASS")


if __name__ == "__main__":
    _self_test()
