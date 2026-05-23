"""3-layer feature extraction.

design ref: PHASE1_MPC_DESIGN.md §3.3 (revised 2026-05-18).

원칙 (사용자 통찰):
    - event = obs 차이의 변화 (절대값 아닌 *상태 변화의 의미*)
    - 의미는 *함수가 추출* (semantic features, sigmoid normalized [0,1])
    - 절대 threshold 0 — 적이 누구든 동일 framework

Layer 1: relational (양쪽 차이) — Es_adv, ω_adv, R_adv, pos_adv, ...
Layer 2: dynamic (시간 미분) — d/dt of Layer 1, finite-diff over history
Layer 3: semantic (의미 추출) — is_parallel_chase_forming, is_energy_race_losing, ...
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from . import state as st


# ──────────────────────────────────────────────────────────────────
# scale 상수 (정규화 sigmoid 의 *느낌* — 절대 threshold 아님)
# ──────────────────────────────────────────────────────────────────
SCALE_ES_FT = 2000.0          # Es 차이의 "유의" 척도
SCALE_DES_DT = 200.0          # Es 변화율 (ft/s)
SCALE_OMEGA_RAD_S = 0.10      # 선회율 차이 척도 (≈ 5.7 deg/s)
SCALE_POS_DEG = 30.0          # 위치 우위 척도
SCALE_R_FT = 2000.0           # 선회반경 차이 척도
SCALE_DPOS_DT_DEG_S = 20.0    # 위치 우위 swing 속도
SCALE_CLOSURE_KTS = 100.0     # closure 변화율 척도


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


# ──────────────────────────────────────────────────────────────────
# Layer 1 — Relational features (양쪽 차이)
# ──────────────────────────────────────────────────────────────────


def layer1_relational(z: np.ndarray, obs: dict) -> dict:
    """양쪽 quantity 의 *차이/우위*. 모든 raw value (정규화 X)."""
    x_us = z[st.SLICE_US]
    x_opp = z[st.SLICE_OPP]
    geom = st.geometry_from_z(z)

    Es_us = st.specific_energy_ft(x_us[st.IDX_H], x_us[st.IDX_V])
    Es_opp = st.specific_energy_ft(x_opp[st.IDX_H], x_opp[st.IDX_V])

    R_us = st.turn_radius_ft(x_us[st.IDX_V], x_us[st.IDX_OMEGA])
    R_opp = st.turn_radius_ft(x_opp[st.IDX_V], x_opp[st.IDX_OMEGA])

    omega_us_abs = abs(x_us[st.IDX_OMEGA])
    omega_opp_abs = abs(x_opp[st.IDX_OMEGA])

    return {
        "Es_us": Es_us,
        "Es_opp": Es_opp,
        "Es_advantage": Es_us - Es_opp,
        "omega_us_abs": omega_us_abs,
        "omega_opp_abs": omega_opp_abs,
        "omega_advantage": omega_us_abs - omega_opp_abs,
        "R_us": R_us,
        "R_opp": R_opp,
        "R_advantage": R_opp - R_us,                      # R_opp 클수록 우리 inside 우위
        "positional_advantage_deg": geom["aa_deg"] - geom["ata_deg"],  # AA - ATA
        "dist_ft": geom["dist_ft"],
        "ata_deg": geom["ata_deg"],
        "aa_deg": geom["aa_deg"],
        "hca_deg": geom["hca_deg"],
    }


# ──────────────────────────────────────────────────────────────────
# Layer 2 — Dynamic features (시간 미분, history 필요)
# ──────────────────────────────────────────────────────────────────


def layer2_dynamic(
    layer1_now: dict,
    history_layer1: list,
    dt: float = 0.1,
) -> dict:
    """history 의 Layer1 features 로 변화율 도출. finite-diff."""
    if len(history_layer1) < 2:
        return {
            "dEs_advantage_dt": 0.0,
            "dpositional_advantage_dt": 0.0,
            "domega_advantage_dt": 0.0,
            "dclosure_dt": 0.0,
        }

    # 최근 N=min(5, len) 윈도 1차 fit slope
    window = min(5, len(history_layer1))
    seq_Es = [h["Es_advantage"] for h in history_layer1[-window:]] + [layer1_now["Es_advantage"]]
    seq_pos = [h["positional_advantage_deg"] for h in history_layer1[-window:]] + [layer1_now["positional_advantage_deg"]]
    seq_omg = [h["omega_advantage"] for h in history_layer1[-window:]] + [layer1_now["omega_advantage"]]
    seq_dist = [h["dist_ft"] for h in history_layer1[-window:]] + [layer1_now["dist_ft"]]

    t = np.arange(len(seq_Es)) * dt
    dEs_dt = float(np.polyfit(t, seq_Es, 1)[0])
    dpos_dt = float(np.polyfit(t, seq_pos, 1)[0])
    domg_dt = float(np.polyfit(t, seq_omg, 1)[0])
    ddist_dt = float(np.polyfit(t, seq_dist, 1)[0])
    # closure = -d(dist)/dt
    return {
        "dEs_advantage_dt": dEs_dt,
        "dpositional_advantage_dt": dpos_dt,
        "domega_advantage_dt": domg_dt,
        "dclosure_dt": -ddist_dt,
    }


# ──────────────────────────────────────────────────────────────────
# Layer 3 — Semantic features (의미 추출, sigmoid [0,1])
# ──────────────────────────────────────────────────────────────────


def layer3_semantic(layer1: dict, layer2: dict, history_layer1: list) -> dict:
    """의미 함수들 — 모두 [0,1], 절대 threshold 0."""

    # is_energy_race_losing — 에너지 우위 감소중
    is_energy_race_losing = _sigmoid(-layer2["dEs_advantage_dt"] / SCALE_DES_DT)

    # is_parallel_chase_forming — turn rate 격차 작음 + history 분산 작음
    omega_gap_small = _sigmoid(1.0 - abs(layer1["omega_advantage"]) / SCALE_OMEGA_RAD_S)
    if len(history_layer1) >= 3:
        omg_seq = [h["omega_advantage"] for h in history_layer1[-5:]]
        omg_var = float(np.var(omg_seq))
        omega_stable = _sigmoid(1.0 - omg_var / (SCALE_OMEGA_RAD_S ** 2))
    else:
        omega_stable = 0.5
    is_parallel_chase_forming = omega_gap_small * omega_stable

    # is_position_swinging_to_us — 위치 우위 *증가*중
    is_position_swinging_to_us = _sigmoid(
        layer2["dpositional_advantage_dt"] / SCALE_DPOS_DT_DEG_S
    )

    # opp_committed_to_turn — opp omega 의 부호 일관성 + 크기
    if len(history_layer1) >= 5:
        omg_opp_seq = [h["omega_opp_abs"] for h in history_layer1[-5:]]
        # Phase 1: omega_opp 가 항상 0 으로 추정 → 이 함수 적합도 약함
        # history 길어지면 finite-diff 도입 후 정확해질 예정
        mean_mag = float(np.mean(omg_opp_seq))
        opp_committed_to_turn = _sigmoid(mean_mag / SCALE_OMEGA_RAD_S - 1.0)
    else:
        opp_committed_to_turn = 0.0

    # merge_window_opening — closing + aligning
    closing = _sigmoid(layer2["dclosure_dt"] / SCALE_CLOSURE_KTS)
    ata_aligning_score = _sigmoid(1.0 - layer1["ata_deg"] / 60.0)   # ATA 작을수록 큼 (relational? — 60 은 admissible 영역 표시, threshold 아님)
    merge_window_opening = closing * ata_aligning_score

    # is_inside_us — 우리 R < opp R (1-circle inside)
    is_inside_us = _sigmoid(layer1["R_advantage"] / SCALE_R_FT)

    # is_under_threat — AA 작음 + closing + ATA 큼
    aa_threat = _sigmoid(1.0 - layer1["aa_deg"] / 60.0)  # AA 작으면 threat
    ata_blind = _sigmoid(layer1["ata_deg"] / 60.0 - 1.0)  # ATA 크면 우리 안 보임
    is_under_threat = aa_threat * closing * ata_blind

    return {
        "is_energy_race_losing": is_energy_race_losing,
        "is_parallel_chase_forming": is_parallel_chase_forming,
        "is_position_swinging_to_us": is_position_swinging_to_us,
        "opp_committed_to_turn": opp_committed_to_turn,
        "merge_window_opening": merge_window_opening,
        "is_inside_us": is_inside_us,
        "is_under_threat": is_under_threat,
    }


# ──────────────────────────────────────────────────────────────────
# Combined extractor — Phase 1 default
# ──────────────────────────────────────────────────────────────────


class DefaultFeatureExtractor:
    """default 구현 — 3 layer 통합. FeatureExtractor protocol 만족."""

    def __init__(self, dt: float = 0.1):
        self.dt = dt

    def extract(
        self,
        z: np.ndarray,
        obs: dict,
        history: Optional[list] = None,
    ) -> dict:
        """history = list of past Layer1 dicts (max ~10 entries 권장)."""
        history_layer1 = history or []
        l1 = layer1_relational(z, obs)
        l2 = layer2_dynamic(l1, history_layer1, dt=self.dt)
        l3 = layer3_semantic(l1, l2, history_layer1)
        return {
            "layer1_relational": l1,
            "layer2_dynamic": l2,
            "layer3_semantic": l3,
        }


def _self_test():
    extractor = DefaultFeatureExtractor()
    obs = {
        "ego_altitude_ft": 15000.0,
        "ego_vc_kts": 386.8,
        "turn_rate_degs": 3.0,
        "relative_bearing_deg": 30.0,
        "distance_ft": 5000.0,
        "alt_gap_ft": 200.0,
        "hca_deg": 60.0,
        "energy_diff_ft": -500.0,
        "closure_rate_kts": 10.0,
    }
    z = st.obs_to_state_12d(obs)
    features = extractor.extract(z, obs, history=None)
    print("Layer 1 (relational):")
    for k, v in features["layer1_relational"].items():
        print(f"  {k}: {v:.2f}")
    print("Layer 2 (dynamic, no history → zeros):")
    for k, v in features["layer2_dynamic"].items():
        print(f"  {k}: {v:.4f}")
    print("Layer 3 (semantic, sigmoid [0,1]):")
    for k, v in features["layer3_semantic"].items():
        print(f"  {k}: {v:.3f}")
    # check all semantic in [0,1]
    for k, v in features["layer3_semantic"].items():
        assert 0.0 <= v <= 1.0, f"{k}={v} not in [0,1]"
    print("[features.py] self-test PASS")


if __name__ == "__main__":
    _self_test()
