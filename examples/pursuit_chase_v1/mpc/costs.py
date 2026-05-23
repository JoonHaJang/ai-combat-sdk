"""Fully Relational Cost — running + terminal.

design ref: PHASE1_MPC_DESIGN.md §3 (revised 2026-05-18).

원칙 (사용자 통찰 2026-05-18):
    1. 모든 performance 항 = 양쪽 quantity 의 *차이/우위/변화율*
    2. 절대 threshold 금지 — 적이 누구든 동일 framework
    3. hard safety (V_STALL, HARD_DECK) 만 예외

cost weights (1차값, 측정 후 튜닝):
    λ_D=1.0, λ_E_rel=0.3, λ_W_rel=0.2, λ_POS=0.1, λ_CLOSURE=0.05, λ_U_JERK=0.1
    SAFETY_BIG=100
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from . import state as st


# ─── weights (Phase 1 1차값) ──────────────────────────────────────
LAMBDA_D = 1.0           # damage diff
LAMBDA_E_REL = 0.3       # energy advantage decrease rate
LAMBDA_W_REL = 0.2       # omega advantage
LAMBDA_POS = 0.1         # positional advantage
LAMBDA_CLOSURE = 0.05    # closure with sign of advantage
LAMBDA_U_JERK = 0.1      # control smoothness
SAFETY_BIG = 100.0       # hard safety violation penalty
LAMBDA_TERMINAL = 1.0    # terminal cost scale

# safety hard limits (absolute, *only here*)
V_STALL_HARD_KTS = 200.0
HARD_DECK_HARD_FT = 1000.0


# ─── damage rate (core 정합, wez_damage_rate.py 와 동일 공식) ─────


WEZ_ATA_DEG = 12.0
WEZ_DIST_MIN_FT = 500.0
WEZ_DIST_MAX_FT = 3000.0
WEZ_BASE_DPS = 25.0


def damage_rate(ata_deg: float, dist_ft: float) -> float:
    """core 정합 — 선형 감쇠, sweet spot 없음."""
    if abs(ata_deg) >= WEZ_ATA_DEG:
        return 0.0
    if dist_ft < WEZ_DIST_MIN_FT or dist_ft > WEZ_DIST_MAX_FT:
        return 0.0
    w_ata = 1.0 - abs(ata_deg) / WEZ_ATA_DEG
    w_dist = (WEZ_DIST_MAX_FT - dist_ft) / (WEZ_DIST_MAX_FT - WEZ_DIST_MIN_FT)
    return WEZ_BASE_DPS * w_ata * w_dist


# ─── running cost ─────────────────────────────────────────────────


def running_cost(
    z: np.ndarray,
    u_us: np.ndarray,
    u_us_prev: Optional[np.ndarray],
    features_now: dict,
    features_prev: Optional[dict],
    dt: float = 0.1,
) -> float:
    """fully relational running cost.

    features_now, features_prev: layer1_relational dict (subset).
    features_prev 가 None 이면 변화율 항 0.
    """
    x_us = z[st.SLICE_US]
    x_opp = z[st.SLICE_OPP]
    l1 = features_now   # layer1_relational

    cost = 0.0

    # ─── 1. damage diff (relational, instant) ───
    D_us = damage_rate(l1["ata_deg"], l1["dist_ft"])
    D_them = damage_rate(l1["aa_deg"], l1["dist_ft"])
    cost += LAMBDA_D * (D_them - D_us) * dt

    # ─── 2. energy advantage *변화율* (Boyd EM relative) ───
    if features_prev is not None:
        dEs_adv = (l1["Es_advantage"] - features_prev["Es_advantage"]) / dt
        # 우리에게 *불리한 변화율* 만 페널티 (우리 advantage 감소 = dEs_adv < 0)
        cost += LAMBDA_E_REL * max(0.0, -dEs_adv) * dt

    # ─── 3. omega advantage (선회율 우위) ───
    # 우리가 적보다 느리면 페널티 (열위)
    cost += LAMBDA_W_REL * max(0.0, -l1["omega_advantage"]) * dt

    # ─── 4. positional advantage (AA - ATA) ───
    # 우리가 적 6시 쪽이면 cost 감소 (우위)
    cost -= LAMBDA_POS * l1["positional_advantage_deg"] / 180.0 * dt

    # ─── 5. closure × advantage sign ───
    if features_prev is not None:
        ddist_dt = (l1["dist_ft"] - features_prev["dist_ft"]) / dt
        closure = -ddist_dt
        advantage_sign = 1.0 if l1["positional_advantage_deg"] > 0 else -1.0
        cost -= LAMBDA_CLOSURE * advantage_sign * closure / 100.0 * dt

    # ─── 6. control jerk (smoothness, regularization) ───
    if u_us_prev is not None:
        jerk = np.sum((u_us - u_us_prev) ** 2)
        cost += LAMBDA_U_JERK * jerk * dt

    # ─── 7. SAFETY (hard, absolute — only place allowed) ───
    if x_us[st.IDX_V] < V_STALL_HARD_KTS:
        cost += SAFETY_BIG
    if x_us[st.IDX_H] < HARD_DECK_HARD_FT:
        cost += SAFETY_BIG

    return cost


# ─── terminal cost ────────────────────────────────────────────────


def terminal_cost(z_H: np.ndarray, features_H: dict) -> float:
    """terminal Φ(z_H) — relational features 만 사용.

    Phase 1: 단순 — final positional + Es advantage.
    Phase 2+ graduation: 기존 ∇V_i 의 V_i(x_rel) 재사용.
    """
    l1 = features_H
    cost = 0.0
    # positional advantage (작을수록 cost 작음 — 우리가 적 후방에 위치)
    cost -= LAMBDA_TERMINAL * l1["positional_advantage_deg"] / 180.0
    # Es advantage (작을수록 cost 작음 — 우리가 에너지 우위)
    cost -= LAMBDA_TERMINAL * np.tanh(l1["Es_advantage"] / 5000.0)
    # final dist 도 너무 멀면 페널티 (engage 가능성 보전)
    dist_norm = min(l1["dist_ft"] / 10000.0, 2.0)
    cost += LAMBDA_TERMINAL * 0.2 * dist_norm
    return cost


def trajectory_cost(
    z_traj: np.ndarray,
    u_us_traj: np.ndarray,
    features_traj: list,
    dt: float = 0.1,
) -> float:
    """H step trajectory 총 cost.

    z_traj: (H+1, 12)
    u_us_traj: (H, 3)
    features_traj: list of (H+1) Layer1 dicts
    """
    H = len(u_us_traj)
    J = 0.0
    for t in range(H):
        u_prev = u_us_traj[t - 1] if t > 0 else None
        feat_prev = features_traj[t - 1] if t > 0 else None
        J += running_cost(z_traj[t], u_us_traj[t], u_prev,
                          features_traj[t], feat_prev, dt)
    J += terminal_cost(z_traj[H], features_traj[H])
    return J


def _self_test():
    """sanity check."""
    from . import features as feat_mod
    extractor = feat_mod.DefaultFeatureExtractor()

    obs1 = {
        "ego_altitude_ft": 15000.0, "ego_vc_kts": 386.8, "turn_rate_degs": 3.0,
        "relative_bearing_deg": 5.0, "distance_ft": 1800.0, "alt_gap_ft": 0.0,
        "hca_deg": 170.0, "energy_diff_ft": 0.0, "closure_rate_kts": 50.0,
    }
    z1 = st.obs_to_state_12d(obs1)
    f1 = extractor.extract(z1, obs1)["layer1_relational"]
    u = np.array([0.0, 0.0, 0.0])
    c = running_cost(z1, u, None, f1, None)
    print(f"running cost (close engagement): {c:.4f}")
    print(f"  ATA={f1['ata_deg']:.1f}, dist={f1['dist_ft']:.0f}, D_us-D_them={damage_rate(f1['ata_deg'], f1['dist_ft']) - damage_rate(f1['aa_deg'], f1['dist_ft']):.2f}")
    tc = terminal_cost(z1, f1)
    print(f"terminal cost: {tc:.4f}")
    print("[costs.py] self-test PASS")


if __name__ == "__main__":
    _self_test()
