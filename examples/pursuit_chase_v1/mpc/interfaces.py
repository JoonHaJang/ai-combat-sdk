"""Abstract Protocols — Phase 1 ~ Phase 3 호환 layer.

design ref: docs/PHASE1_MPC_DESIGN.md §6.3.

원칙: 구현체 (OracleAdversary, MPPISolver, ...) 가 protocol 만족하면
*phase 전환 시 compute_action 코드 불변* — plug-and-play.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

import numpy as np


# ──────────────────────────────────────────────────────────────────
# AdversaryModel — opp action 예측 (Phase 별 구현 다름)
# ──────────────────────────────────────────────────────────────────


@runtime_checkable
class AdversaryModel(Protocol):
    """opp 의 다음 action 예측.

    Phase 1 = OracleAdversary (core Pursue.update wrapper).
    Phase 2 = EnsembleAdversary (sample 다른 BT type).
    Phase 3 = LearnedAdversary (NN + online ID).
    """

    name: str

    def predict(
        self,
        opp_x: np.ndarray,
        our_x: np.ndarray,
        history: Optional[list] = None,
    ) -> np.ndarray:
        """opp_x, our_x: 6D per-side. returns: opp_u (3,) = (ω, γ̇, a) continuous."""
        ...

    def jacobian(
        self,
        opp_x: np.ndarray,
        our_x: np.ndarray,
    ) -> Optional[np.ndarray]:
        """∂opp_u/∂(opp_x, our_x). None if not differentiable.

        Phase 1 oracle = finite-diff (느림, MPPI 는 어차피 안 씀).
        Phase 3 learned NN = autograd.
        """
        ...


# ──────────────────────────────────────────────────────────────────
# FeatureExtractor — Layer 1/2/3 추출
# ──────────────────────────────────────────────────────────────────


@runtime_checkable
class FeatureExtractor(Protocol):
    """raw obs + 12D z + history → relational/dynamic/semantic features.

    *모든 feature relational + normalized [0,1]* — 절대 threshold 사용 금지.
    """

    def extract(
        self,
        z: np.ndarray,
        obs: dict,
        history: Optional[list] = None,
    ) -> dict:
        """returns dict with keys:
            'layer1_relational': {Es_advantage, omega_advantage, R_advantage, ...}
            'layer2_dynamic':    {dEs_adv_dt, dpos_adv_dt, ...}
            'layer3_semantic':   {is_parallel_chase_forming, ...} all ∈ [0,1]
        """
        ...


# ──────────────────────────────────────────────────────────────────
# TauParameterization — τ-trajectory 표현 방식
# ──────────────────────────────────────────────────────────────────


@runtime_checkable
class TauParameterization(Protocol):
    """결정변수 (params) ↔ τ-trajectory (H, k) 변환.

    Phase 1 = PiecewiseConstant3Segment.
    graduation = FullPerStep (H 자유).
    """

    H: int       # horizon
    n_params: int

    def expand(self, params: np.ndarray) -> np.ndarray:
        """params → tau_trajectory shape (H, n_modes)."""
        ...

    def project(self, params: np.ndarray, admissible: dict) -> np.ndarray:
        """admissible region 으로 clipping + simplex projection."""
        ...

    def sample(
        self,
        prior_mean: np.ndarray,
        sigma: float,
        n_samples: int,
        rng: np.random.Generator,
    ) -> np.ndarray:
        """N samples around prior_mean. shape (N, n_params)."""
        ...

    def shift_warm_start(self, params: np.ndarray) -> np.ndarray:
        """다음 tick warm start — 한 step shift + repeat last."""
        ...


# ──────────────────────────────────────────────────────────────────
# MPCSolver — main solver interface
# ──────────────────────────────────────────────────────────────────


@runtime_checkable
class MPCSolver(Protocol):
    """trajectory optimization over τ.

    Phase 1 = MPPISolver (sample-based, gradient 불요).
    graduation = iLQRSolver (gradient-based, adversary smooth 필요).
    """

    name: str
    tau_param: TauParameterization

    def solve(
        self,
        z0: np.ndarray,
        admissible: dict,
        adversary: AdversaryModel,
        features: dict,
        prior_params: Optional[np.ndarray] = None,
    ) -> tuple[np.ndarray, dict]:
        """returns (tau_trajectory shape (H, k), info dict)."""
        ...
