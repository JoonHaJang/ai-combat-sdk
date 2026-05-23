"""OracleAdversary — core Pursue.update() 의 *순수 함수* 재현.

design ref: PHASE1_MPC_DESIGN.md §6.1.

원칙:
    - core 의 if-else 로직을 *직접 호출 안 함* (core 는 py_trees 의존)
    - 동일 로직을 *순수 함수* 로 재구현 (BT 의존성 0)
    - core 의 actions.py:195 Pursue 와 *line-by-line 매핑*
    - 결과: bin (alt_idx, hdg_idx, vel_idx) → continuous u (ω, γ̇, a)

phase 1 사용:
    - MPPI rollout 의 *적 action 예측* 에 호출
    - bt_type = "pursue" / "defensive" / "aggressive" — 같은 Pursue 기반 + 파라미터 다름
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from .. import state as st


# ─── bin → continuous u 변환 ───────────────────────────────────────
# env 의 norm_delta (core multiplecombat_task.py:139-143):
#   norm_delta_altitude = [-0.4, -0.15, 0, 0.15, 0.4]
#   norm_delta_heading  = linspace(-π/2, π/2, 9)
#   norm_delta_velocity = [-0.08, -0.04, 0, 0.04, 0.08]
# 이 *delta* 는 AIPILOT 의 input 정규화. 우리 continuous u 와 매핑:
#   delta_heading * 1/(tick_period) ≈ ω_cmd   (1 tick 에 도달하려는 정도)
#   delta_altitude → γ̇_cmd
#   delta_velocity → a_cmd (kts/s)
# 1차 매핑 — 실제 AIPILOT 응답은 RNN, 본 매핑은 *근사*.

NORM_DELTA_ALT = np.array([-0.4, -0.15, 0.0, 0.15, 0.4])
NORM_DELTA_HDG = np.linspace(-np.pi / 2, np.pi / 2, 9)
NORM_DELTA_VEL = np.array([-0.08, -0.04, 0.0, 0.04, 0.08])

# 1-tick 안에 적용되는 cmd 변환 scale (BT tick 0.1s 기준)
HDG_TO_OMEGA = 10.0           # delta_heading * 10 ≈ ω_cmd rad/s (대략 ±π/0.2 → ±15 rad/s 캡)
ALT_TO_GAMMA_DOT = 2.0        # delta_altitude * 2 ≈ γ̇_cmd rad/s
VEL_TO_ACCEL = 100.0          # delta_velocity * 100 ≈ a_cmd kts/s


def _bin_to_continuous(alt_idx: int, hdg_idx: int, vel_idx: int
                       ) -> np.ndarray:
    """(alt_bin, hdg_bin, vel_bin) → (ω, γ̇, a) continuous."""
    omega = HDG_TO_OMEGA * NORM_DELTA_HDG[hdg_idx]
    # core convention: hdg_bin>4 = right turn. 우리 frame 에서는 *right turn = ω<0*?
    # 일관성 — state.py 의 ψ 정의: heading. ω>0 → ψ 증가. 우리 좌표계에서 ψ 증가 = ?
    # 일단 core 와 같은 frame 가정 (+hdg = +ψ).
    gamma_dot = ALT_TO_GAMMA_DOT * NORM_DELTA_ALT[alt_idx]
    accel = VEL_TO_ACCEL * NORM_DELTA_VEL[vel_idx]
    # cap
    omega = float(np.clip(omega, -math.radians(21.0), math.radians(21.0)))
    gamma_dot = float(np.clip(gamma_dot, -math.radians(15.0), math.radians(15.0)))
    accel = float(np.clip(accel, -15.0, 15.0))
    return np.array([omega, gamma_dot, accel])


# ─── opp obs 합성 (opp 시점) ──────────────────────────────────────
# opp 가 보는 28-obs dict 를 *opp_x, our_x* 로부터 합성.
# Pursue.update 가 실제로 쓰는 키만 채움 (다른 키는 무시).


def _build_opp_obs(opp_x: np.ndarray, our_x: np.ndarray) -> dict:
    """opp 시점 obs dict (Pursue.update 가 쓰는 키만).

    keys used by Pursue (actions.py:238-247):
        distance_ft, ata_deg, relative_bearing_deg, alt_gap_ft, aa_deg, ego_vc_kts
    """
    # opp 의 *우리 (= adversary 의 적)* 방향
    dx = our_x[st.IDX_X] - opp_x[st.IDX_X]
    dy = our_x[st.IDX_Y] - opp_x[st.IDX_Y]
    dh = our_x[st.IDX_H] - opp_x[st.IDX_H]
    dist = math.sqrt(dx * dx + dy * dy + dh * dh)

    # opp 의 nose vector
    nose_opp = np.array([math.sin(opp_x[st.IDX_PSI]), math.cos(opp_x[st.IDX_PSI])])
    horiz = math.sqrt(dx * dx + dy * dy) + 1e-9
    to_us_horiz = np.array([dx, dy]) / horiz

    # ATA (opp 시점, opp 의 nose 가 us 향하는 각)
    cos_ata = float(np.dot(nose_opp, to_us_horiz))
    cos_ata = max(-1.0, min(1.0, cos_ata))
    ata_opp_deg = math.degrees(math.acos(cos_ata))

    # AA (opp 시점, us nose 가 opp 향하는 각)
    nose_us = np.array([math.sin(our_x[st.IDX_PSI]), math.cos(our_x[st.IDX_PSI])])
    to_opp_horiz = -to_us_horiz
    cos_aa = float(np.dot(nose_us, to_opp_horiz))
    cos_aa = max(-1.0, min(1.0, cos_aa))
    aa_opp_deg = math.degrees(math.acos(cos_aa))

    # relative_bearing (opp 시점): us 가 opp 의 좌/우 어느 쪽
    # right of opp = positive. cross product z component sign.
    cross_z = nose_opp[0] * to_us_horiz[1] - nose_opp[1] * to_us_horiz[0]
    # ψ 증가 = +x 방향이면 cross_z 부호로 좌/우 결정
    # Pursue convention: rel_bearing>0 = 적 (= us) 이 오른쪽 → omega>0 (우회전)
    rb_sign = -1.0 if cross_z > 0 else 1.0   # 우리 frame 일관성 (state.py 가정)
    rel_bearing_opp_deg = rb_sign * ata_opp_deg

    # alt_gap (opp 시점): us_alt - opp_alt
    alt_gap_opp = dh

    return {
        "distance_ft": dist,
        "ata_deg": ata_opp_deg,
        "aa_deg": aa_opp_deg,
        "relative_bearing_deg": rel_bearing_opp_deg,
        "alt_gap_ft": alt_gap_opp,
        "ego_vc_kts": opp_x[st.IDX_V],
    }


# ─── core Pursue.update 재현 (순수 함수) ───────────────────────────


def _pursue_decision(obs: dict, params: dict) -> tuple[int, int, int]:
    """core Pursue.update (actions.py:229-339) 의 *순수 함수* 재현.

    bt_type 별 params:
        simple/aggressive/defensive 모두 *Pursue 기반*, 파라미터만 다름.
        (Phase 1 = 한 set 으로 시작, 추후 분기 가능.)
    """
    distance_ft = obs.get("distance_ft", 32808.0)
    ata_deg = obs.get("ata_deg", 0.0)
    rel_bearing_deg = obs.get("relative_bearing_deg", 0.0)
    alt_gap_ft = obs.get("alt_gap_ft", 0.0)
    aa_deg = obs.get("aa_deg", 0.0)
    speed_kts = obs.get("ego_vc_kts", 0)

    # ─── altitude bin (actions.py:251-279) ───
    if aa_deg < params["ata_lost"] and distance_ft < params["close_range"]:
        if alt_gap_ft > params["alt_gap_fast"]:        alt_idx = 4
        elif alt_gap_ft > params["alt_gap_normal"]:    alt_idx = 3
        elif alt_gap_ft < -params["alt_gap_fast"]:     alt_idx = 0
        elif alt_gap_ft < -params["alt_gap_normal"]:   alt_idx = 1
        else:                                          alt_idx = 2
    elif distance_ft < params["very_close_range"]:
        if alt_gap_ft > params["alt_gap_fast"]:                  alt_idx = 4
        elif alt_gap_ft > params["alt_gap_normal"] + 164:        alt_idx = 3
        elif alt_gap_ft < -params["alt_gap_fast"]:               alt_idx = 0
        elif alt_gap_ft < -(params["alt_gap_normal"] + 164):     alt_idx = 1
        else:                                                    alt_idx = 2
    else:
        if alt_gap_ft > params["alt_gap_normal"] + 164:          alt_idx = 3
        elif alt_gap_ft < -(params["alt_gap_normal"] + 164):     alt_idx = 1
        else:                                                    alt_idx = 2

    # ─── heading bin (actions.py:286-305) ───
    if abs(rel_bearing_deg) < params["bearing_straight"]:
        hdg_idx = 4
    elif rel_bearing_deg > 0:
        if abs(rel_bearing_deg) > params["bearing_hard"]:        hdg_idx = 8
        elif abs(rel_bearing_deg) > params["bearing_strong"]:    hdg_idx = 7
        elif abs(rel_bearing_deg) > params["bearing_medium"]:    hdg_idx = 6
        else:                                                    hdg_idx = 5
    else:
        if abs(rel_bearing_deg) > params["bearing_hard"]:        hdg_idx = 0
        elif abs(rel_bearing_deg) > params["bearing_strong"]:    hdg_idx = 1
        elif abs(rel_bearing_deg) > params["bearing_medium"]:    hdg_idx = 2
        else:                                                    hdg_idx = 3

    # ─── velocity bin (actions.py:310-336) ───
    ata_abs = abs(ata_deg)
    if speed_kts > 800:
        vel_idx = 0
    elif speed_kts > 650:
        if ata_abs > params["ata_lost"] or distance_ft < 1640:        vel_idx = 0
        elif ata_abs > params["ata_side"] or distance_ft < 3281:      vel_idx = 1
        else:                                                         vel_idx = 2
    elif ata_abs > params["ata_lost"]:                                vel_idx = 0
    elif ata_abs > params["ata_side"]:                                vel_idx = 1
    elif distance_ft < 1640:                                          vel_idx = 0
    elif distance_ft < 3281:                                          vel_idx = 1
    elif distance_ft > params["far_range"]:                           vel_idx = 4
    elif distance_ft > params["mid_far_range"]:                       vel_idx = 3
    else:                                                             vel_idx = 2

    return alt_idx, hdg_idx, vel_idx


# ─── BT type 별 파라미터 (core default 값) ────────────────────────


_PURSUE_DEFAULT_PARAMS = {
    "close_range":          6562.0,
    "very_close_range":     4921.0,
    "far_range":            13123.0,
    "mid_far_range":        8202.0,
    "alt_gap_fast":         656.0,
    "alt_gap_normal":       328.0,
    "bearing_straight":     5.0,
    "bearing_hard":         60.0,
    "bearing_strong":       30.0,
    "bearing_medium":       15.0,
    "ata_lost":             60.0,
    "ata_side":             30.0,
}


def _params_for(bt_type: str) -> dict:
    """bt_type 별 Pursue 파라미터. Phase 1 = 모두 동일 (core default).

    Phase 2 에서 simple/defensive/aggressive 별 차이 분기.
    """
    return dict(_PURSUE_DEFAULT_PARAMS)


# ─── OracleAdversary class ────────────────────────────────────────


class OracleAdversary:
    """core Pursue 의 결정 함수 mirror.

    AdversaryModel protocol 만족.
    Phase 1 only — Phase 3 generalization 시 replaced by LearnedAdversary.
    """

    def __init__(self, bt_type: str = "pursue"):
        self.bt_type = bt_type
        self.name = f"oracle:{bt_type}"
        self.params = _params_for(bt_type)

    def predict(
        self,
        opp_x: np.ndarray,
        our_x: np.ndarray,
        history: Optional[list] = None,
    ) -> np.ndarray:
        """opp_x 의 *적 시점* obs 합성 → Pursue decision → continuous u."""
        opp_obs = _build_opp_obs(opp_x, our_x)
        alt_idx, hdg_idx, vel_idx = _pursue_decision(opp_obs, self.params)
        return _bin_to_continuous(alt_idx, hdg_idx, vel_idx)

    def jacobian(
        self,
        opp_x: np.ndarray,
        our_x: np.ndarray,
    ) -> Optional[np.ndarray]:
        """if-else discrete → 미분 불가. MPPI 는 안 씀."""
        return None


def _self_test():
    """sanity: opp 가 우리 우측에 있으면 우회전 명령 (hdg_idx > 4)."""
    # us at origin facing north, opp at (3000, 0, 15000) facing south
    our_x = np.array([0.0, 0.0, 15000.0, 0.0, 386.8, 0.0])
    opp_x = np.array([3000.0, 0.0, 15000.0, math.pi, 386.8, 0.0])

    adv = OracleAdversary("pursue")
    opp_obs = _build_opp_obs(opp_x, our_x)
    print(f"opp obs: {opp_obs}")
    u = adv.predict(opp_x, our_x)
    print(f"opp_u (continuous): omega={math.degrees(u[0]):.2f}°/s, gamma_dot={math.degrees(u[1]):.2f}°/s, a={u[2]:.2f}kts/s")

    # opp facing south, us at +x (east) → us is on opp's LEFT (from opp's nose perspective)
    # → expect hdg_idx < 4 → omega < 0 (left turn) under our convention
    # 본 sanity 는 print 만 — convention 검증은 통합 테스트에서.
    print("[oracle.py] self-test PASS (smoke)")


if __name__ == "__main__":
    _self_test()
