"""Dispatcher v2 — 3-tier Safety + 5-tier Context.

design ref: PHASE1_MPC_DESIGN.md §2.2 (revised 2026-05-18).

원칙 (사용자 통찰):
    - Tier 1 SAFETY: hard threshold OK (물리/게임 한계)
    - Tier 2 CONTEXT: semantic features 기반 (no abs threshold)
    - Tier 3 (= MPPI): behavior 선택 — Tier 2 가 admissible region 제공

기존 branch_dispatcher.py 와 분리 — backward compat 유지.
compute_action 가 어느 dispatcher 사용할지 선택 (env var or arg).
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np


# ─── Tier 1 — SAFETY thresholds (absolute, *only here* OK) ────────
ALT_HARD_DECK_FT = 1200.0     # 우리 safety margin (core game LOSS = 1000ft, 200ft 여유)
V_STALL_HARD_KTS = 200.0      # 물리 stall
# ImmediateBreak — 적이 이미 우리 WEZ 내 → 반응적 escape

# ─── Tier 2 — CONTEXT thresholds (semantic features, normalized [0,1]) ─
# threshold 값은 semantic 가 이미 정규화 → meaning 의 *유의수준* (튜닝 가능, 절대 obs threshold 아님)
SEM_OFFENSIVE = 0.6
SEM_DEFENSIVE = 0.6
SEM_NEUTRAL = 0.5
SEM_ENGAGEMENT = 0.5


# ─── Tier 1 SAFETY branches ───────────────────────────────────────


def _check_safety(obs: dict, alt_ft: float) -> Optional[dict]:
    """SAFETY tier — heuristic cmd 반환 (MPPI 우회).

    return: branch_info if safety triggered, else None.
    """
    # 1. HardDeck
    if alt_ft < ALT_HARD_DECK_FT:
        return {
            "branch": "HardDeck",
            "tier": "SAFETY",
            "reason": f"alt={alt_ft:.0f} < {ALT_HARD_DECK_FT:.0f} (game-terminal 회피)",
            "use_mpc": False,   # MPPI 우회, heuristic cmd
        }

    # 2. StallRecovery
    V_us = float(obs.get("ego_vc_kts", 386.8))
    if V_us < V_STALL_HARD_KTS:
        return {
            "branch": "StallRecovery",
            "tier": "SAFETY",
            "reason": f"V={V_us:.0f} < {V_STALL_HARD_KTS:.0f} (물리 stall)",
            "use_mpc": False,
        }

    # 3. ImmediateBreak — 적이 이미 우리 WEZ 안 (reactive, 너무 늦은 escape)
    enm_in_wez = bool(obs.get("enm_in_wez", False))
    if enm_in_wez:
        return {
            "branch": "ImmediateBreak",
            "tier": "SAFETY",
            "reason": "enm_in_wez=True (이미 피격중, reactive escape)",
            "use_mpc": False,
        }
    return None


# ─── Tier 2 CONTEXT branches (semantic) ───────────────────────────


def _select_context(semantic: dict, layer1: dict) -> dict:
    """CONTEXT tier — semantic 기반, MPPI admissible region 결정.

    return: branch_info with admissible.
    """
    # priority: most decisive first
    if semantic["is_under_threat"] >= SEM_DEFENSIVE:
        return {
            "branch": "DefensiveContext",
            "tier": "CONTEXT",
            "reason": f"under_threat={semantic['is_under_threat']:.2f}",
            "admissible": {
                "pn":     (0.0, 0.4),
                "corner": (0.0, 0.8),
                "ldt":    (0.0, 0.8),
                "yoyo":   (0.0, 0.5),
                "T":      (0.0, 0.2),
            },
            "use_mpc": True,
        }

    if (semantic["is_position_swinging_to_us"] >= SEM_OFFENSIVE
            or layer1["positional_advantage_deg"] > 30.0):
        return {
            "branch": "OffensiveContext",
            "tier": "CONTEXT",
            "reason": (f"pos_swing={semantic['is_position_swinging_to_us']:.2f} "
                       f"or pos_adv={layer1['positional_advantage_deg']:.0f}°"),
            "admissible": {
                "pn":     (0.3, 1.0),
                "corner": (0.0, 0.5),
                "ldt":    (0.0, 0.3),
                "yoyo":   (0.0, 0.3),
                "T":      (0.0, 0.7),
            },
            "use_mpc": True,
        }

    if semantic["merge_window_opening"] >= SEM_ENGAGEMENT:
        return {
            "branch": "EngagementContext",
            "tier": "CONTEXT",
            "reason": f"merge_window={semantic['merge_window_opening']:.2f}",
            "admissible": {
                "pn":     (0.2, 1.0),
                "corner": (0.0, 0.5),
                "ldt":    (0.0, 0.5),
                "yoyo":   (0.0, 0.2),
                "T":      (0.1, 0.7),
            },
            "use_mpc": True,
        }

    if semantic["is_parallel_chase_forming"] >= SEM_NEUTRAL:
        return {
            "branch": "NeutralContext",
            "tier": "CONTEXT",
            "reason": f"parallel_lock={semantic['is_parallel_chase_forming']:.2f}",
            "admissible": {
                "pn":     (0.0, 0.5),
                "corner": (0.3, 1.0),
                "ldt":    (0.0, 0.3),
                "yoyo":   (0.0, 0.5),
                "T":      (0.0, 0.7),
            },
            "use_mpc": True,
        }

    # Default — full admissible
    return {
        "branch": "DefaultContext",
        "tier": "CONTEXT",
        "reason": "no specific context",
        "admissible": {
            "pn":     (0.0, 1.0),
            "corner": (0.0, 1.0),
            "ldt":    (0.0, 0.5),
            "yoyo":   (0.0, 0.5),
            "T":      (0.0, 0.5),
        },
        "use_mpc": True,
    }


# ─── Top-level dispatcher v2 ──────────────────────────────────────


def select_branch_v2(
    obs: dict,
    alt_ft: float,
    features: dict,
) -> dict:
    """3-tier dispatcher: SAFETY → CONTEXT.

    Args:
        obs: 28-key obs dict
        alt_ft: ego altitude (호환용, obs 에서도 추출 가능)
        features: DefaultFeatureExtractor.extract() 의 출력
            keys: 'layer1_relational', 'layer2_dynamic', 'layer3_semantic'

    Returns:
        branch_info dict with keys:
            - branch: str
            - tier: "SAFETY" or "CONTEXT"
            - reason: str
            - use_mpc: bool (False = heuristic cmd, True = MPPI)
            - admissible: dict (mode → (lo, hi), CONTEXT only)
    """
    # Tier 1 — Safety
    safety = _check_safety(obs, alt_ft)
    if safety is not None:
        return safety

    # Tier 2 — Context (always returns something)
    return _select_context(features["layer3_semantic"],
                           features["layer1_relational"])


# ─── Heuristic commands for SAFETY tier ───────────────────────────


def cmd_HardDeck(obs: dict) -> tuple[float, float, float]:
    """alt < 1200 → 강제 상승, straight, accel."""
    return (0.0, math.radians(15.0), 15.0)


def cmd_StallRecovery(obs: dict) -> tuple[float, float, float]:
    """V < 200 → nose-down + max accel."""
    return (0.0, math.radians(-10.0), 15.0)


def cmd_ImmediateBreak(obs: dict) -> tuple[float, float, float]:
    """enm_in_wez → 적 반대 hard turn (기존 cmd_DefensiveBreak 와 동일 로직)."""
    rb_raw = obs.get("relative_bearing_deg", 0.0)
    rb = rb_raw * 180.0 if abs(rb_raw) <= 1.5 else rb_raw
    omega = math.copysign(math.radians(19.0), rb if rb != 0.0 else 1.0)
    return (omega, math.radians(-3.0), 15.0)


SAFETY_CMD = {
    "HardDeck": cmd_HardDeck,
    "StallRecovery": cmd_StallRecovery,
    "ImmediateBreak": cmd_ImmediateBreak,
}


def _self_test():
    """sanity: each tier branch reachable from constructed obs."""
    from ..mpc import state as st
    from ..mpc import features as feat_mod
    extractor = feat_mod.DefaultFeatureExtractor()

    # case 1: low altitude → HardDeck
    obs_low = {"ego_altitude_ft": 1000.0, "ego_vc_kts": 386.8, "turn_rate_degs": 0.0,
               "relative_bearing_deg": 0, "distance_ft": 5000, "alt_gap_ft": 0,
               "hca_deg": 0, "energy_diff_ft": 0, "closure_rate_kts": 0}
    z = st.obs_to_state_12d(obs_low)
    feats = extractor.extract(z, obs_low)
    info = select_branch_v2(obs_low, 1000.0, feats)
    print(f"case 1 (alt=1000): {info['branch']} [{info['tier']}]")
    assert info['branch'] == 'HardDeck'

    # case 2: WEZ threat → ImmediateBreak
    obs_wez = dict(obs_low)
    obs_wez["ego_altitude_ft"] = 15000.0
    obs_wez["enm_in_wez"] = True
    z2 = st.obs_to_state_12d(obs_wez)
    feats2 = extractor.extract(z2, obs_wez)
    info2 = select_branch_v2(obs_wez, 15000.0, feats2)
    print(f"case 2 (in_wez): {info2['branch']} [{info2['tier']}]")
    assert info2['branch'] == 'ImmediateBreak'

    # case 3: default context
    obs_def = {"ego_altitude_ft": 15000, "ego_vc_kts": 386.8, "turn_rate_degs": 0,
               "relative_bearing_deg": 30, "distance_ft": 5000, "alt_gap_ft": 0,
               "hca_deg": 90, "energy_diff_ft": 0, "closure_rate_kts": 0}
    z3 = st.obs_to_state_12d(obs_def)
    feats3 = extractor.extract(z3, obs_def)
    info3 = select_branch_v2(obs_def, 15000.0, feats3)
    print(f"case 3 (mid-engagement): {info3['branch']} [{info3['tier']}]")
    print(f"  reason: {info3['reason']}")
    print(f"  admissible: {info3.get('admissible', '(safety)')}")
    print("[branch_dispatcher_v2.py] self-test PASS")


if __name__ == "__main__":
    _self_test()
