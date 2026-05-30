"""Cost-based branch selector v3.8 (사용자 통찰 2026-05-27).

v11_code 분기 구조 + MPC 에서 정제한 cost components 를 SPA framework 로 통합.

SPA (Sense-Plan-Act):
    Sense: obs (engine 제공 28-key) + obs_history (rolling N=5, Layer 2 dynamics)
    Plan : 11 branch 의 multi-component cost 평가 → argmin
           각 cost = engine threshold (WEZ/HardDeck) + Layer 1 (relational) +
                    Layer 2 (dynamics, prev obs 비교) + WEZ_AVOID (방어 mirror)
    Act  : 선택 branch 의 action 함수 → bin → adaptive_bin_modulation 후처리

Multi-component cost (MPC 의 정제 항):
    A. engine threshold-anchored (WEZ 12°/[500,3000]ft, HardDeck 1000ft)
    B. WEZ corridor (dist sweet spot 1750ft Gaussian)
    C. dist × positional_advantage 조합 (D1)
    D. R_advantage (선회반경 우위 — 1-circle inside)
    E. Layer 2 dynamics (d(Es)/dt, d(positional)/dt, closure)
    F. WEZ_AVOID mirror (적 정렬 위험)
    G. Es advantage (에너지 우위)

11 branches:
    safety:   HardDeck (hard override)
    offense:  GunEngagement, OffensivePursuit, CutoffPursuit, LeadPursuit
    energy:   HighYoYo (1-circle outside / Es loss recovery)
    defense:  BreakTurn, DefensiveSpiral (강한 위협 시), LostPursuit (적이 우리 6시 → 회피)
    cruise:   Extension (closure 만들기), StaleChaseBreak (장기 정체 시 vertical 분리)
"""

from __future__ import annotations

import math
import os
import logging
from collections import deque

import numpy as np
import py_trees

logger = logging.getLogger(__name__)


# ─── Engine constants (ai-combat-core-main/src/control/health_manager.py) ──
WEZ_ATA_MAX_DEG = 12.0
WEZ_MIN_FT = 500.0
WEZ_MAX_FT = 3000.0
WEZ_CENTER_FT = 1750.0
HARD_DECK_FT = 1000.0
WEZ_AVOID_BAND_FT = 4500.0      # 적 정렬 위험 감지 band

# tunable
HISTORY_LEN = 5                 # Layer 2 dynamics rolling window

# ─── v3.40 (2026-05-29): Adaptive action params (v6h4 SmartXXX 스타일, 사용자 원칙).
# 매 tick 관측 → 5-rule BFM 분기 → 적응형 출력 — fixed pattern 종식.
# action_gun_engagement PD control
PD_GUN_KP = 1.2
PD_GUN_KD = 0.5
PD_GUN_VEL_APPROACH = 3
PD_GUN_VEL_WEZ = 1
# action_offensive_pursuit 5-rule thresholds
OFFP_DIST_WIDEN_THRESH = 30.0
OFFP_ATA_WORSEN_THRESH = 3.0
OFFP_OVERSHOOT_CLOSURE = 280.0
OFFP_FAR_DIST = 7000.0
OFFP_SPRINT_ATA_MAX = 30.0
OFFP_ENERGY_DIVE_THRESH = 2500.0
# v3.41 (2026-05-29): One-circle vs Two-circle (사용자 자료 § 4)
# "마지막에 도는 자가 fight 종류를 결정. one-circle 시 vel↓, two-circle 시 vel↑"
ONE_CIRCLE_VEL = 1
ONE_CIRCLE_TURN_INTENSITY = 4
TWO_CIRCLE_VEL = 4
TWO_CIRCLE_TURN_INTENSITY = 3
OPP_REVERSAL_OMEGA_THRESH = 5.0  # 적 omega 부호 반전 임계
ONECIRCLE_RADIUS_PRIORITY_WEIGHT = 4.0


# ─── v3.29: 상황별 cost multiplier (사용자 명확화 2026-05-28) ────────────────
# "글로벌 single 강화 trade-off 못 풀음 → 상황별로 cost 함수 분리. if-then 분기."
# GA fuzz 가 각 상황 multiplier 를 *독립적으로* 튜닝. on_to_on 과 chase 별도 최적화.

# on_to_on (head-on spawn, dist>2500 + aa>150): 정면 gun engagement / merge / break-turn 중요
SITMULT_OTO_GUN = 1.35
SITMULT_OTO_BREAK = 0.91
SITMULT_OTO_OFFENSIVE = 0.88
SITMULT_OTO_CUTOFF = 0.8
SITMULT_OTO_DIVE = 0.86
SITMULT_OTO_TCV = 0.6
SITMULT_OTO_EXT = 0.57

# chase (tail_chase or close-range chase): pursuit / dive / tail_chase_vertical 중요
SITMULT_CHASE_GUN = 0.69
SITMULT_CHASE_BREAK = 0.9
SITMULT_CHASE_OFFENSIVE = 1.57
SITMULT_CHASE_CUTOFF = 1.11
SITMULT_CHASE_DIVE = 1.41
SITMULT_CHASE_TCV = 1.27
SITMULT_CHASE_EXT = 0.97

# branch name → situation multiplier 이름 mapping (cost 적용 시 사용)
_SITUATION_MULT_MAP = {
    "GunEngagement":     {"on_to_on": "SITMULT_OTO_GUN",       "chase": "SITMULT_CHASE_GUN"},
    "BreakTurn":         {"on_to_on": "SITMULT_OTO_BREAK",     "chase": "SITMULT_CHASE_BREAK"},
    "OffensivePursuit":  {"on_to_on": "SITMULT_OTO_OFFENSIVE", "chase": "SITMULT_CHASE_OFFENSIVE"},
    "CutoffPursuit":     {"on_to_on": "SITMULT_OTO_CUTOFF",    "chase": "SITMULT_CHASE_CUTOFF"},
    "DiveAttack":        {"on_to_on": "SITMULT_OTO_DIVE",      "chase": "SITMULT_CHASE_DIVE"},
    "TailChaseVertical": {"on_to_on": "SITMULT_OTO_TCV",       "chase": "SITMULT_CHASE_TCV"},
    "Extension":         {"on_to_on": "SITMULT_OTO_EXT",       "chase": "SITMULT_CHASE_EXT"},
}


def _apply_situation_multiplier(branch_name: str, cost: float, situation: str) -> float:
    """상황별 cost multiplier 적용. cost 음수 (reward) 면 multiplier 가 magnitude 조절."""
    if situation not in ("on_to_on", "chase"):
        return cost
    map_entry = _SITUATION_MULT_MAP.get(branch_name)
    if not map_entry:
        return cost
    mult_name = map_entry[situation]
    mult = globals().get(mult_name, 1.0)
    return cost * float(mult)


def _gauss(x: float, sigma: float) -> float:
    return math.exp(-(x / sigma) ** 2)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


# ────────────────────────────────────────────────────────────────
# Layer 1/2 features computation (per-tick + history)
# ────────────────────────────────────────────────────────────────


G_FT_S2 = 32.174   # ft/s²
KTS_TO_FPS_RATIO = 1.68781


def compute_features(obs: dict, obs_history: deque) -> dict:
    """obs + history → relational + dynamic features.

    v3.9 (2026-05-27): R_opp 누적 추정 추가 (omega_opp finite diff).
    - V_opp = obs 의 energy_diff_ft + alt_gap_ft 로 도출
    - omega_opp ≈ |d(aa)/dt| (적 꼬리방향 변화율 = 적 turn rate proxy)
    - R_opp = V_opp / omega_opp
    - R_advantage = R_opp - R_us (양수 = 우리 inside)
    """
    ata = float(obs.get("ata_deg", 90.0))
    aa = float(obs.get("aa_deg", 90.0))
    dist = float(obs.get("distance_ft", 10000.0))
    closure_kts = float(obs.get("closure_rate_kts", 0.0))
    energy_diff_ft = float(obs.get("energy_diff_ft", 0.0))
    alt_gap_ft = float(obs.get("alt_gap_ft", 0.0))
    ego_alt = float(obs.get("ego_altitude_ft", 15000.0))
    ego_vc = float(obs.get("ego_vc_kts", 400.0))
    turn_rate = abs(float(obs.get("turn_rate_degs", 0.0)))
    overshoot_risk = bool(obs.get("overshoot_risk", False))
    in_39 = bool(obs.get("in_39_line", False))

    pos_adv = aa - ata
    # 우리 R (ft) = V_us(fps) / omega_us(rad/s)
    if turn_rate > 0.5:
        R_us_ft = ego_vc * KTS_TO_FPS_RATIO / math.radians(turn_rate)
    else:
        R_us_ft = 3000.0   # 직진 시 fallback

    # === 적 V, omega, R 누적 추정 (v3.9 NEW) ===
    # V_opp via Es: Es_opp = Es_us - energy_diff_ft
    #               V_opp² = 2g (Es_opp - h_opp), h_opp = ego_alt + alt_gap_ft
    Es_us_ft = ego_alt + (ego_vc * KTS_TO_FPS_RATIO) ** 2 / (2.0 * G_FT_S2)
    Es_opp_ft = Es_us_ft - energy_diff_ft
    h_opp_ft = ego_alt + alt_gap_ft
    V_opp_kts = 400.0   # default fallback
    V_opp_sq_fps = 2.0 * G_FT_S2 * max(0.0, Es_opp_ft - h_opp_ft)
    if V_opp_sq_fps > 0:
        V_opp_fps = math.sqrt(V_opp_sq_fps)
        V_opp_kts_calc = V_opp_fps / KTS_TO_FPS_RATIO
        if 100.0 < V_opp_kts_calc < 800.0:
            V_opp_kts = V_opp_kts_calc

    # omega_opp ≈ |d(aa)/dt| — 적 꼬리방향 변화율
    # (단순 휴리스틱: ego frame 무관 가정, aa 변화 ≈ opp turn)
    omega_opp_degs = 0.0
    d_aa = 0.0
    if len(obs_history) >= 2:
        prev = obs_history[-2]
        dt_proxy = 0.1
        d_aa = (aa - float(prev.get("aa_deg", aa))) / dt_proxy   # deg/s
        omega_opp_degs = abs(d_aa)

    # R_opp = V_opp / omega_opp
    if omega_opp_degs > 0.5:
        R_opp_ft = V_opp_kts * KTS_TO_FPS_RATIO / math.radians(omega_opp_degs)
    else:
        R_opp_ft = 3000.0   # 직진 가정
    R_advantage_ft = R_opp_ft - R_us_ft   # +값 = 적 R 크다 = 우리 inside (advantage)

    # Layer 2 dynamics
    d_ata = 0.0
    d_dist = 0.0
    d_pos = 0.0
    d_es = 0.0
    if len(obs_history) >= 2:
        prev = obs_history[-2]
        dt_proxy = 0.1
        d_ata = (ata - float(prev.get("ata_deg", ata))) / dt_proxy
        d_dist = (dist - float(prev.get("distance_ft", dist))) / dt_proxy
        d_pos = (pos_adv - (float(prev.get("aa_deg", aa)) - float(prev.get("ata_deg", ata)))) / dt_proxy
        d_es = (energy_diff_ft - float(prev.get("energy_diff_ft", energy_diff_ft))) / dt_proxy

    # v3.34 (2026-05-28): TCA (track crossing angle) from hca_deg
    # 사용자 자료: Tracking (저 TCA, saddled) vs Snapshot (고 TCA, transient) 분기점
    tca = abs(float(obs.get("hca_deg", 0)))
    return {
        "ata": ata, "aa": aa, "dist": dist, "tca": tca,
        "closure_kts": closure_kts, "energy_diff_ft": energy_diff_ft,
        "ego_alt": ego_alt, "ego_vc": ego_vc, "turn_rate": turn_rate,
        "overshoot_risk": overshoot_risk, "in_39": in_39,
        "pos_adv": pos_adv, "R_us_ft": R_us_ft,
        # v3.9 NEW (omega_opp finite diff 누적 → R_opp → R_advantage)
        "V_opp_kts": V_opp_kts,
        "omega_opp_degs": omega_opp_degs,
        "R_opp_ft": R_opp_ft,
        "R_advantage_ft": R_advantage_ft,
        "d_ata": d_ata, "d_aa": d_aa, "d_dist": d_dist, "d_pos": d_pos, "d_es": d_es,
    }


# ────────────────────────────────────────────────────────────────
# WEZ_AVOID — 적 정렬 위험 (mirror cost, 모든 branch 공통 추가)
# ────────────────────────────────────────────────────────────────


def common_threat_cost(f: dict) -> float:
    """common threat — v3.8.1: 0 (회귀 fix). branch-specific defense (BreakTurn) 가 대응.

    v3.8 시도 (threat=3.0) 가 공격 branch 모두 cost 올려 → 도주 trajectory 선호.
    """
    return 0.0


# ────────────────────────────────────────────────────────────────
# Branch cost functions — multi-component
# ────────────────────────────────────────────────────────────────


# ─── v3.37 (2026-05-29): All-aspect WEZ envelope (사용자 자료, DTIC AD1130933).
# "WEZ를 6시 단일점이 아니라 전종횡(all-aspect) 엔벨로프로 정의" — McGrew 보상구조 비판.
# 6시 (low ATA) tracking + 고종횡 (high TCA) snapshot 둘 다 보상.

WEZ_ENVELOPE_WEIGHT = 13.52
WEZ_HIGHASPECT_ATA_OPT = 30.0         # 고종횡 ATA 중심 (snapshot 영역)
WEZ_HIGHASPECT_TCA_OPT = 90.0         # 고종횡 TCA 중심 (cross-flow)


def cost_wez_envelope(f: dict) -> float:
    """v3.39 (2026-05-29 사용자 자료 § B): 연속 Ω(R,AOT,TCA) + log-WEZ + ψ_pipper TOF.

    Ω = α(AOT)·Ω_track + β(AOT)·Ω_snap  — 두 모드 분해 (Dirac 함정 탈출)
    P_R(R) = σ(k_min·(R-Rmin)) · σ(k_max·(Rmax-R))  — one-sided sigmoid
    Reward = log(1 + λ·Ω·P_R)  — dense compressed signal
    """
    import math as _m
    ata = f.get("ata", 999)
    dist = f.get("dist", 99999)
    tca = f.get("tca", 0)
    aa = f.get("aa", 999)
    d_ata = f.get("d_ata", 0)
    closure = f.get("closure_kts", 0)
    # P_R one-sided sigmoid (k_min > k_max — 너무 가까이 가는 위험 가파르게)
    P_R = _sigmoid((dist - WEZ_MIN_FT) / 100.0) * _sigmoid((WEZ_MAX_FT - dist) / 200.0)
    # t_TOF (자료 § A.2 ψ_pipper 와 공유)
    t_tof = dist / BULLET_VELOCITY_FPS  # seconds
    pipper_err = abs(ata - d_ata * t_tof)  # TOF-propagated
    # Ω_track (6시 saddled)
    aot_q_t = _gauss(aa, WEZ_HIGHASPECT_ATA_OPT)
    tca_q_t = _gauss(tca, 25.0)
    pipper_q_t = _gauss(pipper_err, 6.0)
    no_overshoot_q = _sigmoid((150.0 - closure) / 50.0)
    ata_q_t = _gauss(ata, 6.0)
    omega_track = aot_q_t * tca_q_t * pipper_q_t * no_overshoot_q * ata_q_t
    # Ω_snap (고종횡 + pipper sweep)
    tca_q_s = _gauss(tca - WEZ_HIGHASPECT_TCA_OPT, 30.0)
    sweep_q = _sigmoid((abs(d_ata) - 4.0) / 3.0)
    aot_q_s = _gauss(aa - WEZ_HIGHASPECT_ATA_OPT, 25.0)
    omega_snap = tca_q_s * sweep_q * aot_q_s
    # α(AOT) — 6시에서 1, 측면에서 0 → β = 1 - α
    alpha = _sigmoid((WEZ_HIGHASPECT_ATA_OPT - aa) / 20.0)
    beta = 1.0 - alpha
    omega_total = alpha * omega_track + beta * omega_snap
    # log-WEZ dense reward
    lambda_compress = 5.0
    log_wez = _m.log(1.0 + lambda_compress * omega_total * P_R)
    return -WEZ_ENVELOPE_WEIGHT * log_wez


# ─── v3.37: Lead with bullet TOF propagation (사용자 자료, fire-control patents).
# "lead_offset = V_target × t_TOF, t_TOF ≈ R / V_bullet"
# 가속도(jink) 추적 금지 — TOF propagated mean-path 만.

BULLET_VELOCITY_FPS = 3300.0          # 20mm 약 3300 fps (M61 Vulcan 평균)
LEAD_TOF_PIPPER_SIGMA = 8.0           # pipper_error_after_TOF 의 gauss sigma


def cost_lead_tof(f: dict) -> float:
    """Tracking 시 TOF propagated lead error 보상.

    pipper_after_TOF ≈ current_ata - (omega_target × t_TOF)
    t_TOF = R / V_bullet (ft / fps = s)
    omega_target proxy = d_aa (적의 LOS rate)
    """
    ata = f.get("ata", 999)
    dist = f.get("dist", 99999)
    if not (WEZ_MIN_FT <= dist <= WEZ_MAX_FT) or ata > 30:
        return 3.0
    t_tof = dist / BULLET_VELOCITY_FPS  # seconds
    omega_target = f.get("d_aa", 0)
    # pipper error after TOF (deg)
    pipper_err = abs(ata - omega_target * t_tof)
    pipper_q = _gauss(pipper_err, LEAD_TOF_PIPPER_SIGMA)
    dist_q = _gauss(dist - WEZ_CENTER_FT, 700.0)
    return -8.0 * pipper_q * dist_q


# ─── v3.34 (2026-05-28): Gun fight two-mode separation (사용자 자료).
# Tracking (저 TCA, control zone, saddled) vs Snapshot (고 TCA, transient firing window).
# "두 모드 합치면 saddle 못 만들고 진동" 명시.

GUN_TRACKING_TCA_MAX_DEG = 40.0       # tracking 모드 조건: TCA < 40
GUN_SNAPSHOT_TCA_MIN_DEG = 60.0       # snapshot 모드: TCA > 60 (firing window 순간)
GUN_TRACKING_WEIGHT = 12.0            # tracking 강한 reward (saddled)
GUN_SNAPSHOT_WEIGHT = 6.0             # snapshot 약한 (순간만)


def cost_gun_engagement(f: dict) -> float:
    """단일 cost (legacy fallback). v3.34: tracking/snapshot 으로 분리 우선.

    BRANCHES 에서 GunTracking / GunSnapshot 가 dominant 하면 이건 거의 안 active.
    """
    ata, dist = f["ata"], f["dist"]
    if not (WEZ_MIN_FT <= dist <= WEZ_MAX_FT) or ata >= WEZ_ATA_MAX_DEG:
        return 5.0
    ata_q = _gauss(ata, 6.0)
    dist_q = _gauss(dist - WEZ_CENTER_FT, 800.0)
    return -10.0 * ata_q * dist_q


def cost_gun_tracking(f: dict) -> float:
    """저 TCA (saddled tracking) + control zone + 안정 추적.

    조건: WEZ in + TCA<40 (자료: "비행경로가 표적의 비행경로를 따른다" LCOS 가정).
    Lead pursuit 으로 pipper 안정 → 탄 TOF 동안 유지.
    """
    ata, dist, tca = f["ata"], f["dist"], f.get("tca", 999)
    if not (WEZ_MIN_FT <= dist <= WEZ_MAX_FT) or ata >= WEZ_ATA_MAX_DEG:
        return 4.0
    if tca > GUN_TRACKING_TCA_MAX_DEG:
        return 4.0  # not in tracking mode
    ata_q = _gauss(ata, 6.0)
    dist_q = _gauss(dist - WEZ_CENTER_FT, 800.0)
    tca_q = _gauss(tca, 25.0)  # 낮을수록 좋음
    return -GUN_TRACKING_WEIGHT * ata_q * dist_q * tca_q


def cost_gun_snapshot(f: dict) -> float:
    """고 TCA (snap guns, transient firing window) — 순간 교차 사격.

    조건: WEZ in + TCA>60 + pipper sweep (ata 빠르게 변함). 짧은 firing window.
    Lead 과도 금지 (자료: "excessive lead 금지").
    """
    ata, dist, tca = f["ata"], f["dist"], f.get("tca", 0)
    if not (WEZ_MIN_FT <= dist <= WEZ_MAX_FT) or ata >= WEZ_ATA_MAX_DEG:
        return 4.0
    if tca < GUN_SNAPSHOT_TCA_MIN_DEG:
        return 4.0  # not in snapshot mode
    ata_q = _gauss(ata, 6.0)
    dist_q = _gauss(dist - WEZ_CENTER_FT, 1000.0)  # 더 넓게 (순간만)
    # firing window 트리거: pipper sweep proxy = |d_ata| 적당
    d_ata = abs(f.get("d_ata", 0))
    sweep_q = _gauss(d_ata - 8.0, 6.0)  # ~8°/s sweep ideal
    return -GUN_SNAPSHOT_WEIGHT * ata_q * dist_q * sweep_q


# ─── v3.35 (2026-05-28): Counter-defense lookup (사용자 두번째 자료).
# 적 방어 type → 카운터 cost adjustment.
# 적 break → barrel-roll attack / lead-fill
# 적 out-of-plane → 평면 재정합 + lag roll
# 적 jink → mean-path tracking (instantaneous 추종 금지)


# ─── v3.38 (2026-05-29): Sub-situation if-then framework (사용자 vision).
# "마주하는 독립된 상황별로 실험 → branch에 최적화된 cost로 if-then 분기"
# 7 sub-situations 명시 + per-sub-situation branch boost. Runtime detect → dispatch.

# Per-sub-situation knob sets (default 1.0 = neutral). GA fuzz range 0.0~3.0.
# HOM (Head-On Merge) — spawn 직후 + post-merge head-on
HOM_GUN_BOOST = 0.92
HOM_BREAK_BOOST = 1.04
HOM_CUTOFF_BOOST = 1.28
HOM_DIVE_BOOST = 0.75
HOM_EXT_PENALTY = 1.0  # extension 자제 (도주 금지)
# Off_TailChase (직선 6시 추격)
OFFTC_GUN_BOOST = 1.0
OFFTC_ACCEL_BOOST = 0.97
OFFTC_DIVE_BOOST = 0.95
OFFTC_TCV_BOOST = 1.44
OFFTC_LEAD_BOOST = 1.26
# Off_Lag (control zone 진입 중)
OFFLAG_DWELL_BOOST = 1.0
OFFLAG_TCV_BOOST = 0.74
OFFLAG_HIGHYOYO_BOOST = 1.0
OFFLAG_CUTOFF_BOOST = 1.33
OFFLAG_PATIENCE = 1.23
# Lufbery (평행 stalemate)
LUFB_VERTICAL_BOOST = 0.99
LUFB_HIGHYOYO_BOOST = 1.04
LUFB_DIVE_BOOST = 0.59
LUFB_BREAK_BOOST = 1.0
LUFB_BARRELROLL_BOOST = 1.05
# DefSpiral (extreme defensive low alt)
DEFSPIRAL_BREAK_BOOST = 1.0
DEFSPIRAL_HARD_DECK_PENALTY = 1.01


def _detect_sub_situation(f: dict) -> str:
    """R15-G2 (2026-05-29): 8 BFM sub-situations — bt_vs_bt 통합용 NeutralMerge 추가.

    분기 우선순위 (top → bottom):
      1. HOM         — head-on gun opportunity
      2. Defensive   — 적이 우리 6시 close
      3. DefSpiral   — 극단 defensive + 저고도
      4. Off_TailChase — 우리 직선 추격 (us_attack 핵심)
      5. Off_Lag    — 우리 LAG 추격 (offset)
      6. NeutralMerge (NEW) — perpendicular merge (bt_vs_bt 시작점)
      7. Lufbery   — sustained turning fight
      8. Other      — default
    """
    aa = abs(f.get("aa", 0))
    ata = abs(f.get("ata", 0))
    dist = f.get("dist", 99999)
    pos_adv = f.get("pos_adv", 0)
    alt_gap = f.get("alt_gap_ft", 0)
    closure = f.get("closure_kts", 0)
    if aa > 150 and ata < 30 and dist > 2000:
        return "HOM"
    if pos_adv < -90 and dist < 5000:
        if dist < 2000 and alt_gap < -500:
            return "DefSpiral"
        return "Defensive"
    if pos_adv > 50 and dist < 5000:
        if ata < 25:
            return "Off_TailChase"
        if ata < 80:
            return "Off_Lag"
    # R15-G2 NEW: perpendicular merge (bt_vs_bt 시작점 + 양쪽 perpendicular crossing)
    # pos_adv 작음 (양쪽 angular advantage 없음) + dist 중거리 + ata/aa ~90°
    if (abs(pos_adv) < 50 and 2500 < dist < 5500
            and 60 < ata < 120 and 60 < aa < 120):
        return "NeutralMerge"
    if 60 < aa < 120 and 60 < ata < 120 and dist < 4000:
        return "Lufbery"
    return "Other"


_SUB_SIT_BOOST_MAP = {
    "HOM": {
        "GunEngagement": "HOM_GUN_BOOST", "GunTracking": "HOM_GUN_BOOST",
        "GunSnapshot": "HOM_GUN_BOOST", "GunEnvelope": "HOM_GUN_BOOST",
        "BreakTurn": "HOM_BREAK_BOOST", "CutoffPursuit": "HOM_CUTOFF_BOOST",
        "DiveAttack": "HOM_DIVE_BOOST", "Extension": "HOM_EXT_PENALTY",
    },
    "Off_TailChase": {
        "GunEngagement": "OFFTC_GUN_BOOST", "GunTracking": "OFFTC_GUN_BOOST",
        "InitPursuitAccel": "OFFTC_ACCEL_BOOST", "DiveAttack": "OFFTC_DIVE_BOOST",
        "TailChaseVertical": "OFFTC_TCV_BOOST", "LeadPursuit": "OFFTC_LEAD_BOOST",
    },
    "Off_Lag": {
        "TailChaseVertical": "OFFLAG_TCV_BOOST",
        "HighYoYo": "OFFLAG_HIGHYOYO_BOOST",
        "CutoffPursuit": "OFFLAG_CUTOFF_BOOST",
    },
    "Lufbery": {
        "VerticalScissors": "LUFB_VERTICAL_BOOST",
        "HighYoYo": "LUFB_HIGHYOYO_BOOST",
        "DiveAttack": "LUFB_DIVE_BOOST",
        "BreakTurn": "LUFB_BREAK_BOOST",
        "BarrelRoll": "LUFB_BARRELROLL_BOOST",
    },
    "DefSpiral": {
        "BreakTurn": "DEFSPIRAL_BREAK_BOOST",
        "HardDeck": "DEFSPIRAL_HARD_DECK_PENALTY",
    },
}


def _sub_situation_dispatch(f: dict, sub_sit: str, spawn_tick: int, obs: dict):
    """R15-G3 (2026-05-29): 서브시나리오 → 행동 직접 매핑 (cost framework override).

    각 sub-situation 의 us_attack/us_defend baseline 에서 검증된 winning pattern.
    None 반환 = cost framework fallback (sub-situation 매핑 없음).
    """
    # NeutralMerge: bt_vs_bt 시작 + perpendicular crossing
    # R15-I H4 (2026-05-29): side_flag asymmetric vertical commit 으로 대칭 깨기.
    # 가정: self-play 가 mirror lock 의 원인. side_flag 부호로 vertical 비대칭 strategy.
    # - side_flag > 0 (적 우측) → CLIMB MAX (alt=4) + hard right turn
    # - side_flag < 0 (적 좌측) → DIVE MAX (alt=0) + hard left turn
    # 두 BT 가 opposite side_flag 보면 → vertical asymmetric → energy split → break
    if sub_sit == "NeutralMerge" and spawn_tick <= 60:
        if os.environ.get("R15_H4_ENABLED", "0") == "1":
            # H4 결과 (2026-05-29): ace 회귀 (21→0). NeutralMerge 의 climb-soft-lead pattern 이
            # 다양한 opp 에 균등 효과적이라 side asym 가 깨뜨림. 비활성.
            side_flag = float(obs.get("side_flag", 0.0))
            if side_flag > 0.1:
                return (4, 8, 4)
            if side_flag < -0.1:
                return (0, 0, 4)
        rel_b = float(obs.get("relative_bearing_deg", 0.0))
        # 약한 lead-turn (적 방향 약간 트래킹, dist 유지)
        hdg = max(0, min(8, 4 + int(round(np.clip(rel_b / 22.5, -2, 2)))))
        return (3, hdg, 4)  # mild climb + soft lead + max throttle
    # Defensive: us_defend baseline = action_defensive_escape (split-S 포함)
    if sub_sit == "Defensive":
        return action_defensive_escape(f)
    # DefSpiral: 극단 defensive_spiral
    if sub_sit == "DefSpiral":
        return action_defensive_spiral(f)
    # Off_TailChase: us_attack baseline = action_gun_engagement (closure-aware vel)
    if sub_sit == "Off_TailChase":
        return action_gun_engagement(f)
    # Off_Lag: LeadPursuit + high yoyo
    if sub_sit == "Off_Lag":
        return action_lead_pursuit(f)
    # HOM: head-on gun
    if sub_sit == "HOM":
        return action_gun_engagement_oto(f)
    # Lufbery, Other: cost framework fallback
    return None


def _apply_sub_situation_boost(f: dict, branch_name: str) -> float:
    """Sub-situation 검출 → branch cost multiplier 적용.
    boost > 1 = 강화 (음수 cost 더 음수, 매력적), < 1 = 약화.
    """
    sub_sit = _detect_sub_situation(f)
    map_entry = _SUB_SIT_BOOST_MAP.get(sub_sit, {})
    boost_var = map_entry.get(branch_name)
    if boost_var is None:
        return 1.0
    return float(globals().get(boost_var, 1.0))


COUNTER_BARRELROLL_WEIGHT = 4.0
COUNTER_LAG_WEIGHT = 2.33
COUNTER_PATIENCE_WEIGHT = 2.23
# v3.36 (2026-05-29 사용자 명령): gap-driven anti-reversal (v51 케이스)
ANTI_REVERSAL_WEIGHT = 3.7


def _gap_signal(value: float, threshold: float, sigma: float) -> float:
    """Smooth sigmoid ramp: value < threshold ≈ 0, value >> threshold ≈ 1.
    Continuous gradient — discrete if-then 대체. 사용자 명령 (2026-05-29).
    """
    return _sigmoid((value - threshold) / max(sigma, 0.1))


def cost_counter_defense(f: dict, branch_name: str) -> float:
    """v3.36 gap-driven (사용자 명령): 관측 gap 의 *연속적 크기* 가 cost 결정.

    discrete classification 폐기. 각 signal magnitude (0~1) → branch cost 에 *비례*.
    관측: omega_opp, d_aa, d_ata, closure, pos_adv, d_pos
    """
    omega_opp = f.get("omega_opp_degs", 0)
    d_aa = abs(f.get("d_aa", 0))
    d_ata = abs(f.get("d_ata", 0))
    closure = f.get("closure_kts", 0)
    pos_adv = f.get("pos_adv", 0)
    d_pos = f.get("d_pos", 0)

    # === 연속 signal 들 (0~1) ===
    # 적 break: omega_opp 큰 + closure 큼
    omega_signal = _gap_signal(omega_opp, 5.0, 4.0)
    closure_signal = _gap_signal(closure, 50.0, 60.0)
    break_strength = omega_signal * closure_signal

    # 적 out-of-plane: d_aa 큰 (aspect 빠르게 변함)
    oop_signal = _gap_signal(d_aa, 8.0, 8.0)

    # 적 jink/scissors: closure 작 + d_ata 변동 큰
    low_closure_signal = _gap_signal(40.0 - abs(closure), 0, 30.0)
    d_ata_signal = _gap_signal(d_ata, 4.0, 4.0)
    jink_strength = low_closure_signal * d_ata_signal

    # 적 reversal (v51 케이스): 우리 회복 중 + 적 omega 큰 + 우리 defensive
    recovery_signal = _gap_signal(d_pos, 2.0, 4.0)
    defensive_signal = _gap_signal(-pos_adv, 50.0, 60.0)
    reversal_strength = recovery_signal * omega_signal * defensive_signal

    # === Branch 별 bonus (gap signal × weight, smooth) ===
    if branch_name == "BarrelRoll":
        # break 카운터 + reversal 카운터 (둘 다)
        return -(COUNTER_BARRELROLL_WEIGHT * break_strength
                 + ANTI_REVERSAL_WEIGHT * reversal_strength)
    if branch_name == "CrossOverTurn":
        return -COUNTER_BARRELROLL_WEIGHT * 0.7 * break_strength
    if branch_name in ("TailChaseVertical", "HighYoYo"):
        return -COUNTER_LAG_WEIGHT * oop_signal
    if branch_name == "Extension":
        # patience: jink + oop signal 클수록 Extension 선호
        return -COUNTER_PATIENCE_WEIGHT * (0.6 * jink_strength + 0.4 * oop_signal)
    if branch_name in ("OffensivePursuit", "CutoffPursuit", "LeadPursuit"):
        # jink 추적 금지 페널티 (continuous)
        return +COUNTER_PATIENCE_WEIGHT * 0.5 * jink_strength
    if branch_name == "GunTracking":
        # anti-reversal: 적 reversal 시 GunTracking 선호 (회복 → snap shot)
        return -ANTI_REVERSAL_WEIGHT * reversal_strength
    return 0.0


def cost_offensive_pursuit(f: dict) -> float:
    """우리 6시 잡힘 + 근거리 (v3.30: WEZ dwell quality 적용).

    pos_adv > 0 면 적극 추구. closing 추세 + dist 가까이 면 더 큰 reward.
    v3.30: dwell_quality (closure+dist+drot 복합) 으로 overshoot 방지.
    """
    pos_adv = f["pos_adv"]
    dist = f["dist"]
    if pos_adv < -10.0 or dist > 6000.0:
        return 3.0
    pos_q = max(0.0, pos_adv / 180.0)
    dist_q = _gauss(dist - 2000.0, 2000.0)
    base = -3.15 * pos_q * dist_q
    # Layer 2: 위치 우위 swing bonus
    if f["d_pos"] > 0:
        base -= 0.5 * min(1.0, f["d_pos"] / 20.0)
    # v3.30: WEZ dwell quality bonus (overshoot 방지 + 긴 dmg 기간)
    base -= WEZ_DWELL_WEIGHT * cost_wez_dwell_quality(f)
    return base


def cost_cutoff_pursuit(f: dict) -> float:
    """ata 중간 (15-60°) + closing — cutoff (v3.30: dwell quality)."""
    ata = f["ata"]
    dist = f["dist"]
    if not (15.0 < ata < 80.0) or dist > 6000.0:
        return 2.0
    ata_q = _gauss(ata - 30.0, 25.0)
    closure_q = max(0.0, min(1.0, f["closure_kts"] / 100.0))
    base = -4.65 * ata_q * (0.3 + 0.7 * closure_q)
    base -= WEZ_DWELL_WEIGHT * cost_wez_dwell_quality(f)
    return base


def cost_high_yoyo(f: dict) -> float:
    """Es 열세 or 1-circle outside.

    v3.10.1 (2026-05-27, trace 분석 기반): dist>8000ft 면 비활성.
    진단: defensive/aggressive 매치에서 dist 24000ft 인데도 HighYoYo dominate →
    영원히 closure 못 만듦. 멀리서 vertical 은 무의미, Extension 우선해야.
    """
    energy_diff = f["energy_diff_ft"]
    closure = f["closure_kts"]
    ata = f["ata"]
    dist = f["dist"]
    # v3.10.1: 너무 멀면 비활성 (closure 만들기 우선)
    if dist > 8000.0:
        return 2.0
    score = 0.0
    if energy_diff < -500.0:
        score += min(1.0, -energy_diff / 3000.0)
    if abs(closure) < 30.0 and 30.0 < ata < 120.0 and dist < 5000.0:
        score += 0.5
    if score < 0.1:
        return 2.0
    return -1.11 * min(1.0, score)


def cost_inside_chase(f: dict) -> float:
    """v3.9.1: 우리 inside (R_advantage > 1500ft, strong) — 매우 엄격 조건만 활성.

    R_opp 추정이 noise 클 수 있어 *큰 R_adv* 만 trigger.
    """
    R_adv = f.get("R_advantage_ft", 0.0)
    ata = f["ata"]
    dist = f["dist"]
    closure = f["closure_kts"]
    omega_opp = f.get("omega_opp_degs", 0.0)
    # 매우 엄격: R_adv 큼 + omega_opp 의미 있는 값 (>2°/s) + ata 잡고 있음
    if R_adv < 1500.0 or omega_opp < 2.0 or ata > 80.0 or dist > 5000.0:
        return 3.0
    R_q = min(1.0, (R_adv - 1500.0) / 2000.0)
    ata_q = _gauss(ata - 30.0, 30.0)
    closing_q = max(0.2, min(1.0, closure / 100.0 + 0.5))
    return -2.5 * R_q * ata_q * closing_q


# ─── v3.31 (2026-05-28): Doctrine-based defensive escape (T-45A ACMFP-03)
# 4-phase 결정 트리: Survive → Force Overshoot → Bugout Gate → Last-ditch
# 사용자 자료: "적이 우리 on-tail 시 따돌리는 것" 미해결 과제 해결.

# Tunable (GA-fuzzable)
DEFESC_ATA_THRESHOLD = 150.0          # 적 우리 6시 detect: ata>150° (적 우리 후방)
DEFESC_AA_THRESHOLD = 30.0            # AA<30° (우리에서 본 적 정면 = 적 nose 우리 향함)
DEFESC_DIST_DANGER_FT = 4000.0        # 격추 위험 거리
DEFESC_BUGOUT_AOT_DEG = 150.0         # bugout gate: AOT≥150°
DEFESC_LASTDITCH_DIST_FT = 1500.0     # 최후 last-ditch trigger
DEFESC_WEIGHT_SURVIVE = 8.0           # phase 1 (가장 강함)
DEFESC_WEIGHT_OVERSHOOT = 6.0         # phase 2
DEFESC_WEIGHT_BUGOUT = 5.0            # phase 3
DEFESC_WEIGHT_LASTDITCH = 10.0        # phase 4 (가장 강함, 죽기 직전)
# v3.44 (2026-05-29 R15-D): split-s imminent kill 차단 — original 파라미터 (R15-F ace KILL 96 회복)
DEFESC_SPLITS_DIST_FT = 2200.0        # split-s trigger dist
DEFESC_SPLITS_ATA_DEG = 170.0         # 적 nose lock 정밀도
DEFESC_SPLITS_CLOSURE_KTS = 20.0      # 적 추격 의지 (양수 closure)
# v3.45 (2026-05-29 R15-D): bt_vs_bt neutral merge Layer 1 plan — trigger 확장
NEUTRAL_MERGE_PLAN_TICKS = 40         # 초기 40 tick 동안 dispatch override
NEUTRAL_MERGE_DIST_MIN = 2500.0       # perpendicular merge geometry detect
NEUTRAL_MERGE_DIST_MAX = 5000.0       # loosened 3500 → 5000 (실제 첫 cost-tick 3512 catch)
NEUTRAL_MERGE_ATA_MIN = 60.0
NEUTRAL_MERGE_ATA_MAX = 120.0
NEUTRAL_MERGE_AA_MIN = 60.0
NEUTRAL_MERGE_AA_MAX = 120.0


def _is_defensive_state(f: dict) -> bool:
    """적이 우리 6시 (ata 큰 + aa 작은 = 적 우리 후방+적 nose 우리 향함)."""
    return (f.get("ata", 0) > DEFESC_ATA_THRESHOLD
            and f.get("aa", 0) < DEFESC_AA_THRESHOLD
            and f.get("dist", 1e6) < DEFESC_DIST_DANGER_FT)


def cost_defensive_escape(f: dict) -> float:
    """v3.43 (2026-05-29 자료 § A): Imminence I(t) sigmoid product (continuous).

    I(t) = σ(R_buf - R) × σ(δ_ψ - ψ_gun) × σ(-ψ̇_gun) × σ(-d_aa)
    AND-게이트 4개 신호 합성 — discrete phase 대신 continuous gradient.
    4개 phase weight 는 I(t) magnitude 에 따라 자동 분배.
    """
    if not _is_defensive_state(f):
        return 4.0
    dist = f["dist"]
    closure = f["closure_kts"]
    ata = f["ata"]
    aa = f["aa"]
    d_aa = f.get("d_aa", 0)
    energy_diff = f.get("energy_diff_ft", 0.0)
    # Imminence signals (continuous sigmoid)
    R_signal = _sigmoid((3000.0 - dist) / 500.0)          # 가까울수록 1
    psi_gun = abs(ata - 180)                              # 적 nose 와 우리 위치 정렬도
    psi_signal = _sigmoid((30.0 - psi_gun) / 10.0)        # 정렬 잘 됐을수록 1
    psi_dot = -d_aa                                       # ψ̇_gun ≈ -d_aa (적 LOS 수렴)
    psidot_signal = _sigmoid(psi_dot / 3.0)
    d_aa_signal = _sigmoid(-abs(d_aa) / 5.0 + 1.0)        # 적 안정 추적 시 1
    closure_signal = _sigmoid((closure - 50.0) / 50.0)    # closure 큼 = 임박
    # I(t) = AND of all signals (continuous product)
    I = R_signal * psi_signal * psidot_signal * d_aa_signal
    aot = 360.0 - aa if aa < 180 else aa
    # Phase weights blend via I magnitude
    # Phase 4 LAST-DITCH dominate when I 매우 큼 (>0.8)
    # Phase 1 SURVIVE dominate when I 작음
    # Continuous gradient (not discrete)
    lastditch_w = DEFESC_WEIGHT_LASTDITCH * _sigmoid((I - 0.7) / 0.1)
    overshoot_w = DEFESC_WEIGHT_OVERSHOOT * closure_signal * (1 - lastditch_w / DEFESC_WEIGHT_LASTDITCH)
    bugout_signal = _sigmoid((aot - 150.0) / 20.0) * _sigmoid(energy_diff / 1000.0)
    bugout_w = DEFESC_WEIGHT_BUGOUT * bugout_signal * (1 - I)
    survive_w = DEFESC_WEIGHT_SURVIVE * _sigmoid((3000 - dist) / 1000.0) * (1 - lastditch_w / DEFESC_WEIGHT_LASTDITCH)
    return -(lastditch_w + overshoot_w + bugout_w + survive_w)


# ─── v3.32 (2026-05-28): Offensive pursuit curve modulator (AETC TTP 11-1)
# LAG/PURE/LEAD dynamic 선택 — control point + closure sign aware.
# 사용자 자료: "우리 추격 시 유리한 상태 최적화" 미해결 과제 해결.

PURSUIT_CONTROL_RADIUS_FT = 6000.0    # control point ~1 turn radius 후방
PURSUIT_LEAD_TURNRATE_MIN = 1.0       # Δω > 0 (우리 turn rate 우세)
PURSUIT_LAG_CLOSURE_LIMIT_KTS = 200.0 # closure 과다 시 LAG 우선
PURSUIT_LEAD_WEIGHT = 3.0             # LEAD bonus (control zone 내)
PURSUIT_LAG_WEIGHT = 3.0              # LAG bonus (overshoot 위험)


def cost_pursuit_curve_select(f: dict, branch_name: str) -> float:
    """LEAD 계열 (CutoffPursuit, GunEngagement) 또는 LAG 계열 (Extension, TailChaseVertical)
    branch 에 dynamic bonus.

    조건: 우리 offensive 상태 (pos_adv > 80) + dist < 8000.
    """
    pos_adv = f.get("pos_adv", 0)
    dist = f.get("dist", 1e6)
    if pos_adv < 80 or dist > 8000:
        return 0.0
    closure = f.get("closure_kts", 0)
    # closure 과다 = overshoot 위험 → LAG 우선
    overshoot_risk = closure > PURSUIT_LAG_CLOSURE_LIMIT_KTS
    # control zone: dist 1 turn radius 근처
    in_control_zone = abs(dist - PURSUIT_CONTROL_RADIUS_FT) < 2000
    # turn rate margin proxy: |d_pos| > threshold = 우리가 angle 변화 만듦
    turn_rate_adv = abs(f.get("d_pos", 0)) > PURSUIT_LEAD_TURNRATE_MIN
    if branch_name in ("CutoffPursuit", "GunEngagement"):
        # LEAD bonus: turn rate 우세 + control zone 내 + overshoot 위험 없음
        if turn_rate_adv and in_control_zone and not overshoot_risk:
            return -PURSUIT_LEAD_WEIGHT
        return 0.0
    if branch_name in ("Extension", "TailChaseVertical", "HighYoYo"):
        # LAG bonus: overshoot 위험 or turn rate 부족
        if overshoot_risk or not turn_rate_adv:
            return -PURSUIT_LAG_WEIGHT
        return 0.0
    return 0.0


# ─── v3.33 (2026-05-28): Initial pursuit acceleration (사용자 명령).
# "우리가 on chase 일 때, 제일 먼저 초기 가속 쭉 해야 하는 거 아니야?"
# Doctrine: lag pursuit 진입 전 에너지 적립 (full thrust + minimal turn).

INITACC_DIST_MIN_FT = 4000.0          # 초기 가속 trigger: 우리 offensive + dist 4000+
INITACC_SPEED_MIN_KTS = 350.0         # 가속 필요 trigger: 우리 속도 350 미만
INITACC_WEIGHT = 5.0                  # bonus magnitude


def cost_initial_pursuit_accel(f: dict) -> float:
    """우리가 offensive 진입 직후 + dist 충분 + 우리 속도 부족 → 직선 가속."""
    pos_adv = f.get("pos_adv", 0)
    dist = f.get("dist", 0)
    our_speed = f.get("ego_vc", 999)  # KIAS
    if pos_adv < 80 or dist < INITACC_DIST_MIN_FT or our_speed > INITACC_SPEED_MIN_KTS:
        return 3.0  # not eligible
    speed_q = max(0.0, min(1.0, (INITACC_SPEED_MIN_KTS - our_speed) / 100.0))
    dist_q = min(1.0, (dist - INITACC_DIST_MIN_FT) / 4000.0)
    return -INITACC_WEIGHT * speed_q * dist_q


# v3.43 (2026-05-29 사용자 명령): bt_vs_bt lufbery 회피 — 적극 closure-in 강제
FORCE_ENGAGE_WEIGHT = 4.0


def cost_force_engage_bt(f: dict) -> float:
    """bt_vs_bt scenario 의 lufbery 회피 — head-on 후 dist 벌어지면 강하게 closure-in.

    조건: dist > 3000ft + |aa-180|<30 (head-on 통과 후) + closure < 50 (separating)
    → OffensivePursuit/CutoffPursuit cost 강화 (reward 더 큼)
    """
    dist = f.get("dist", 0)
    aa = f.get("aa", 90)
    closure = f.get("closure_kts", 0)
    head_on_q = _gauss(abs(aa - 180), 30.0)  # head-on 통과 직후
    dist_q = _sigmoid((dist - 3500) / 1000.0)
    separating_q = _sigmoid(-closure / 50.0)  # closure 작거나 음수
    intensity = head_on_q * dist_q * separating_q
    return -FORCE_ENGAGE_WEIGHT * intensity


def action_initial_pursuit_accel(f: dict) -> tuple[int, int, int]:
    """직진 (rel_b 약하게 추적) + max vel."""
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    hdg = 4 + int(round(np.clip(rel_b / 40.0, -1, 1)))
    return _bin_clip(2, hdg, 4)


def cost_break_turn(f: dict) -> float:
    """방어 — AA<30 + closing (v3.8.3: 약화 — 덜 활성, 공격 시간 확보).

    진단: defensive vs draw — 우리가 BreakTurn 너무 일찍 → 공격 swing 못 만듦.
    """
    aa = f["aa"]
    closure = f["closure_kts"]
    dist = f["dist"]
    if aa > 50.0:                    # v3.7 60 → 50 (더 좁은 위협 정의)
        return 4.0
    threat_score = _gauss(aa, 20.0) * max(0.1, min(1.0, closure / 100.0 + 0.5))
    threat_score *= _gauss(dist - 1500.0, 1800.0)
    if threat_score < 0.15:          # v3.7 0.1 → 0.15 (더 큰 위협만)
        return 3.0
    return -4.47 * threat_score       # v3.7 -5.0 → -3.5 (약화)


def cost_defensive_spiral(f: dict) -> float:
    """심각한 defensive — break_turn 보다 위협 클 때 (down-spiral, energy preserve)."""
    aa = f["aa"]
    if aa > 40.0:
        return 6.0
    dist = f["dist"]
    closure = f["closure_kts"]
    if dist > 3500.0 or closure < 50.0:
        return 4.5
    # 매우 위험 — AA<40 + 가까이 + 빠른 접근
    aa_q = _gauss(aa, 15.0)
    return -7.0 * aa_q * _gauss(dist - 1500.0, 1500.0)


def cost_lost_pursuit(f: dict) -> float:
    """적이 우리 6시 잡았고 closure 음수 (멀어짐) — 회피 reverse 시도.

    components:
      A. ata 큼 (>140°, 우리 후방 적)
      B. closure 음 (적이 멀어짐 — 도주 가능)
      C. dist 적당히 (>2000ft, 즉시 사격 위험 X)
    """
    ata = f["ata"]
    if ata < 130.0:
        return 4.0
    closure = f["closure_kts"]
    dist = f["dist"]
    if dist < 2000.0 or closure > -30.0:
        return 3.5
    ata_q = _gauss(ata - 170.0, 25.0)
    return -2.5 * ata_q * min(1.0, (-closure) / 100.0)


def cost_tail_chase_vertical(f: dict) -> float:
    """v3.11 NEW: 적 6시 잡았는데 catch up 안 됨 → vertical advantage.

    진단 trace (defensive/aggressive vs v3.10.1): pos_adv +157°, ata 11°,
    dist 11000~16000ft, closure ≈ 0 → catch up loop. 같은 F-16 max accel →
    closure 0 영원. vertical separation 으로 alt 우위 + dive 시 V advantage.

    조건: pos_adv > 100° (적 6시) + ata < 30° (정렬) + dist > 5000ft (멀음) +
          |closure| < 50 (catch up 정체) + alt 여유 (< 28000ft)
    """
    pos_adv = f["pos_adv"]
    ata = f["ata"]
    dist = f["dist"]
    closure = f["closure_kts"]
    ego_alt = f["ego_alt"]
    if not (pos_adv > 100.0 and ata < 30.0
            and dist > 5000.0 and abs(closure) < 50.0
            and ego_alt < 28000.0):
        return 3.0   # 부적합
    # 강한 reward — Extension 대신 vertical 우선
    closing_penalty = 1.0 if closure < 0 else (0.6 if closure < 20 else 0.3)
    dist_q = min(1.0, (dist - 5000.0) / 8000.0)   # 5000~13000ft 사이 ramp
    alt_room = (28000.0 - ego_alt) / 13000.0       # alt 여유 (15000~28000)
    return -5.52 * closing_penalty * dist_q * alt_room


def action_tail_chase_vertical(f: dict) -> tuple[int, int, int]:
    """climb max + 적 방향 hdg + vel 3 (alt 우위 축적, 향후 dive)."""
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    if abs(rel_b) < 8.0:
        hdg = 4
    else:
        hdg = 4 + int(round(np.clip(rel_b / 22.5, -4, 4)))
    return _bin_clip(4, hdg, 3)   # max climb + 가속


def cost_dive_attack(f: dict) -> float:
    """v3.12 NEW: 우리 alt 우위 (적 아래) → dive max → PE→KE 변환 → V advantage.

    TailChaseVertical 후속 — climb 으로 alt 우위 만든 후 dive attack.
    조건: alt_gap < -1000 (우리가 적보다 1000ft+ 위) + ata < 40° (정렬) +
          dist∈[2000, 8000ft] (적당히 가까이) + pos_adv > 50°
    """
    alt_gap = float(obs_current.get("alt_gap_ft", 0.0))
    pos_adv = f["pos_adv"]
    ata = f["ata"]
    dist = f["dist"]
    ego_alt = f["ego_alt"]
    # 적 아래 (alt_gap < 0 negative = 적이 우리 아래)
    # ego_alt 충분 (dive 여유)
    # v3.12.1 (2026-05-27): dist 조건 8000 → 14000 (trace 평균 13604 cover)
    # 근거: vs aggressive trace mean alt_gap=-1198 + dist=13604 → 조건 만족해야 활성 가능
    if not (alt_gap < -1000.0 and ata < 40.0 and pos_adv > 50.0
            and 2000.0 < dist < 14000.0 and ego_alt > HARD_DECK_FT + 3000.0):
        return 3.0
    alt_adv_q = min(1.0, -alt_gap / 3000.0)
    ata_q = _gauss(ata, 25.0)
    dist_q = _gauss(dist - 6000.0, 5000.0)   # peak 6000ft 그러나 wide
    return -5.66 * alt_adv_q * ata_q * dist_q


_da_phase = 0
_da_tick = 0


def action_dive_attack(f: dict) -> tuple[int, int, int]:
    """v3.42 (2026-05-29): v6h4 SmartLowYoYo 관측 기반 phase transition (fixed timer 종식).

    DIVE → RECOVER phase 전환 = 관측 기반 (closure, alt, ata).
    """
    global _da_phase, _da_tick
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    ata = f.get("ata", 0)
    closure = f.get("closure_kts", 0)
    ego_alt = f.get("ego_alt", 15000)
    base_hdg = 4 + int(round(np.clip(rel_b / 22.5, -4, 4)))
    if _da_phase == 0:  # DIVE
        _da_tick += 1
        # DIVE 종료 조건 (관측 기반): WEZ 근접 OR alt 너무 낮음 OR closure 정상화
        if (ata < 15 and 500 < f.get("dist", 9999) < 3000) or ego_alt < HARD_DECK_FT + 3000 or abs(closure) < 50:
            _da_phase = 1
            _da_tick = 0
        elif _da_tick >= 15:  # 안전 cap
            _da_phase = 1
            _da_tick = 0
    else:  # RECOVER
        _da_tick += 1
        # RECOVER 종료 조건: closure 다시 정상 + alt 회복
        if closure < 50 and ego_alt > HARD_DECK_FT + 2000:
            _da_phase = 0
            _da_tick = 0
        elif _da_tick >= 8:
            _da_phase = 0
            _da_tick = 0
    if _da_phase == 0:
        return _bin_clip(0, base_hdg, 4)  # max dive + max accel
    else:
        alt_idx = 3 if ego_alt < HARD_DECK_FT + 3000 else 2
        return _bin_clip(alt_idx, base_hdg, 3)  # recover


def cost_cross_over_turn(f: dict) -> float:
    """v3.12 NEW: 평행 비행 detect → cross-over turn 으로 angle break.

    조건: pos_adv > 100° (우리 적 6시) + ata < 30° (정렬) +
          dist > 8000ft (멀음) + d_dist > 30 (멀어지는 추세)
    → catch up 불가능 — 우리 ±90° lateral turn 으로 적 trajectory 와 angle 차이 만들기
    """
    pos_adv = f["pos_adv"]
    ata = f["ata"]
    dist = f["dist"]
    d_dist = f["d_dist"]
    # v3.12.3: cost weight -2.8 → -1.5 (simple 회귀 fix, 적정 활성).
    # 근거: v3.12.2 trace 에서 def 37.7%, aggr 20.9% 활성 — 너무 dominate → simple 회귀.
    if not (pos_adv > 100.0 and ata < 30.0 and dist > 8000.0 and d_dist > 10.0):
        return 3.0
    stuck_q = min(1.0, d_dist / 100.0)
    dist_q = min(1.0, (dist - 8000.0) / 10000.0)
    return -1.5 * stuck_q * dist_q


def action_cross_over_turn(f: dict) -> tuple[int, int, int]:
    """±90° lateral turn — rel_b 무관, 임의 강 turn (왼/오 번갈아 가능)."""
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    # rel_b 부호 *반대로* 강 turn → 적 trajectory cross-over 시도
    # rel_b > 0 (적 우측) → 우리 좌선회 (hdg 1)
    if rel_b >= 0:
        hdg = 1   # 강 좌선회
    else:
        hdg = 7   # 강 우선회
    ego_alt = f["ego_alt"]
    alt = 2 if ego_alt > HARD_DECK_FT + 2500 else 3
    return _bin_clip(alt, hdg, 3)   # vel 유지 (energy 보존)


def cost_extension(f: dict) -> float:
    """원거리 closure 만들기 (v3.10.1: weight 강화 -1.0 → -2.5).

    진단: defensive/aggressive 매치에서 dist 24000ft 도주 상태일 때
    Extension 활성 가능했지만 weight -0.33 만 → HighYoYo (-1.5) 가 dominate.
    Extension 강화 → closure 만들기 우선.
    """
    dist = f["dist"]
    ata = f["ata"]
    if dist < 5000.0:
        return 3.0
    dist_q = min(1.0, (dist - 5000.0) / 10000.0)
    ata_q = _gauss(ata - 70.0, 60.0)
    return -4.28 * dist_q * ata_q     # v3.10 -1.0 → -2.5


def cost_stale_chase(f: dict) -> float:
    """장기 stalemate (d_dist 작음 + d_pos 작음 + dist 멀음) → vertical 분리."""
    if len(obs_history_global) < 4:
        return 3.0
    if f["dist"] < 4000.0 or abs(f["closure_kts"]) > 30.0:
        return 3.0
    if abs(f["d_pos"]) > 5.0:  # pos 변화 있으면 stale 아님
        return 3.0
    return -1.0  # stalemate detected — HighYoYo 같은 vertical 시도


def cost_lead_pursuit(f: dict) -> float:
    """default fallback — 항상 0."""
    return 0.0


# global obs_history reference for stale-chase (set by selector)
obs_history_global: deque = deque(maxlen=HISTORY_LEN)


# ────────────────────────────────────────────────────────────────
# Branch action functions — bin 산출 (engine action 매핑)
# adaptive_bin_modulation 호환 — 후처리 통합
# ────────────────────────────────────────────────────────────────


def _bin_clip(alt: int, hdg: int, vel: int) -> tuple[int, int, int]:
    return (int(np.clip(alt, 0, 4)),
            int(np.clip(hdg, 0, 8)),
            int(np.clip(vel, 0, 4)))


def action_hard_deck(f: dict) -> tuple[int, int, int]:
    return _bin_clip(4, 4, 3)


# ─── v3.20: tactical_lookup.json 통합 ──────────────────────────────
# 과거 mine_tactical_patterns.py → counter_table → tactical_lookup.json
# 112 state cells (ata × dist × closure × e_diff) × {aggressive, defensive}
# 각 cell 의 recommended node + tick_wr.

_TACTICAL_LOOKUP_CACHE = None
_LOOKUP_NODE_TO_BRANCH = {
    "Accelerate":      "Extension",
    "ExtensionBreak":  "Extension",
    "HeadOnBreak":     "BreakTurn",
    "LeadPursuit":     "LeadPursuit",
    "SmartHighYoYo":   "HighYoYo",
    "SmartLagPursuit": "CutoffPursuit",
    "SmartLowYoYo":    "DiveAttack",
}


def _load_tactical_lookup():
    global _TACTICAL_LOOKUP_CACHE
    if _TACTICAL_LOOKUP_CACHE is not None:
        return _TACTICAL_LOOKUP_CACHE
    try:
        from pathlib import Path as _P
        root = _P(__file__).resolve().parents[3]
        path = root / "logs/knowledge/tactical_lookup.json"
        if not path.exists():
            _TACTICAL_LOOKUP_CACHE = {}
            return {}
        import json as _json
        _TACTICAL_LOOKUP_CACHE = _json.load(open(path, "r", encoding="utf-8"))
        return _TACTICAL_LOOKUP_CACHE
    except Exception:
        _TACTICAL_LOOKUP_CACHE = {}
        return {}


def _state_key(ata: float, dist: float, closure: float, e_diff: float) -> str:
    """mine_tactical_patterns.py 의 bin functions 와 일치."""
    a_bin = min(int(max(ata, 0) // 30), 5)            # 0~5
    if dist < 1000: d_bin = 0
    elif dist < 3000: d_bin = 1
    elif dist < 6000: d_bin = 2
    elif dist < 10000: d_bin = 3
    else: d_bin = 4
    if closure < -100: c_bin = 0
    elif closure < 0: c_bin = 1
    elif closure < 100: c_bin = 2
    else: c_bin = 3
    if e_diff < -3000: e_bin = 0
    elif e_diff < 0: e_bin = 1
    elif e_diff < 3000: e_bin = 2
    else: e_bin = 3
    return f"{a_bin}_{d_bin}_{c_bin}_{e_bin}"


def _tactical_lookup_bias(f: dict, opp_name: str) -> dict:
    """현 state 의 recommended node → 우리 branch cost bias.

    high-quality cells (wr>=0.9 + n>=30) 만 활용.
    """
    if not opp_name or opp_name not in ("aggressive", "defensive"):
        return {}
    lookup = _load_tactical_lookup()
    if not lookup:
        return {}
    key = _state_key(f["ata"], f["dist"], f["closure_kts"], f["energy_diff_ft"])
    cell = lookup.get("states", {}).get(key, {})
    rec = cell.get(opp_name)
    if rec is None:
        return {}
    # quality gate
    wr = float(rec.get("tick_wr", 0))
    n = int(rec.get("n", 0))
    if wr < 0.85 or n < 20:
        return {}
    branch = _LOOKUP_NODE_TO_BRANCH.get(rec["node"])
    if branch is None:
        return {}
    # v3.20.1: STRONG bias — lookup 이 검증된 cell 추천이면 *강제 선택*
    # wr 0.85→4.0, 1.0→6.0 (모든 다른 branch 보다 음수 큼 → argmin 선택)
    bias_mag = -4.0 - (wr - 0.85) * 13.3
    return {branch: bias_mag}


# ─── v3.30: WEZ-dwell quality (사용자 통찰 2026-05-28): "적에게 대미지 주는
# 기간 길게 = 속도+헤딩+거리 복합 상대값으로 cost". overshoot 방지 = 적절한
# 속도/거리 match → WEZ 안에서 오래 머무름.

# Tunable (GA-fuzzable)
WEZ_DWELL_CLOSURE_OPT_KTS = 50.0   # ideal closure (느린 추격, overshoot 방지)
WEZ_DWELL_CLOSURE_SIGMA = 80.0     # tolerance 폭
WEZ_DWELL_DIST_OPT_FT = 1750.0     # WEZ center
WEZ_DWELL_DIST_SIGMA = 700.0
WEZ_DWELL_DROT_SIGMA = 12.0        # |d_ata| 작을수록 lock 안정
WEZ_DWELL_WEIGHT = 2.0             # 이 quality 전체 cost magnitude


def cost_wez_dwell_quality(f: dict) -> float:
    """WEZ 진입/유지 시 적과의 *상대 closure+heading+dist* 조합으로 dwell 길이 예측.

    closure 적절 + dist WEZ center + ata 변화율 작음 → 오래 머무름 → dmg 누적.
    overshoot (closure 큼 + dist 줄어듦 매우 빠름) 시 quality 낮음.

    pursuit 계열 cost 에 *공통 multiplier* 로 추가 적용.
    """
    closure = f.get("closure_kts", 0.0)
    dist = f.get("dist", 0.0)
    d_ata = abs(f.get("d_ata", 0.0))
    # closure quality: opt 근처 가우시안 (overshoot 시 closure 큼 → 낮음)
    closure_q = _gauss(closure - WEZ_DWELL_CLOSURE_OPT_KTS, WEZ_DWELL_CLOSURE_SIGMA)
    # dist quality: WEZ center 근처
    dist_q = _gauss(dist - WEZ_DWELL_DIST_OPT_FT, WEZ_DWELL_DIST_SIGMA)
    # angular stability: lock 흔들림 작을수록 좋음
    drot_q = _gauss(d_ata, WEZ_DWELL_DROT_SIGMA)
    return closure_q * dist_q * drot_q  # 0~1 (높을수록 dwell 좋음)


# ─── v3.28: Situation detector (사용자 명확화 2026-05-28) ──────────────
# dogfight = 상황의 조합. on_to_on vs chase 를 spawn 직후 obs 로 *분류* 후
# situation-conditional 처리. NOT global head-on 강화.

def _detect_situation(f: dict, spawn_obs_history: list) -> str:
    """spawn 직후 첫 obs (또는 history first) 로 on_to_on / chase 분류.

    on_to_on (bt_vs_bt scenario): dist > 2500ft + AA > 150° (head-on)
    chase (tail_chase scenario): dist < 3500ft + ATA < 90° (chase setup)
    """
    if not spawn_obs_history:
        # fallback: use current
        dist = f.get("dist", 0)
        aa = abs(f.get("aa_deg", 0))
        ata = f.get("ata", 0)
    else:
        first = spawn_obs_history[0] if isinstance(spawn_obs_history, (list, tuple)) else spawn_obs_history
        dist = float(first.get("distance_ft", first.get("dist", 0)))
        aa = abs(float(first.get("aa_deg", 0)))
        ata = float(first.get("ata_deg", first.get("ata", 0)))
    if dist > 2500 and aa > 150:
        return "on_to_on"
    if dist < 3500 and ata < 90:
        return "chase"
    return "unknown"


# ─── v3.27: situation_state_lookup.json (aggregated, opp-independent) ────
# 2026-05-28 사용자 요청 self-learning loop 산물. tactical_lookup + ga_hypotheses
# 결합. 모든 opp 에 작동 (aggressive/defensive 외).
_SITUATION_LOOKUP_CACHE = None


def _load_situation_lookup():
    global _SITUATION_LOOKUP_CACHE
    if _SITUATION_LOOKUP_CACHE is not None:
        return _SITUATION_LOOKUP_CACHE
    try:
        from pathlib import Path as _P
        root = _P(__file__).resolve().parents[3]
        path = root / "logs/knowledge/situation_state_lookup.json"
        if not path.exists():
            _SITUATION_LOOKUP_CACHE = {}
            return {}
        import json as _json
        _SITUATION_LOOKUP_CACHE = _json.load(open(path, "r", encoding="utf-8"))
        return _SITUATION_LOOKUP_CACHE
    except Exception:
        _SITUATION_LOOKUP_CACHE = {}
        return {}


def _situation_lookup_bias(f: dict, min_confidence: float = 0.7) -> dict:
    """opp-independent state-conditional branch bias. aggressive/defensive 외 모든 opp 대응.

    confidence >= 0.7 이면 mid-bias (-3), >=0.9 면 strong (-5).
    """
    lookup = _load_situation_lookup()
    if not lookup:
        return {}
    state_rec = lookup.get("state_recommendation", {})
    key = _state_key(f["ata"], f["dist"], f["closure_kts"], f["energy_diff_ft"])
    rec = state_rec.get(key)
    if rec is None:
        return {}
    conf = float(rec.get("confidence", 0))
    if conf < min_confidence:
        return {}
    branch = _LOOKUP_NODE_TO_BRANCH.get(rec.get("node"))
    if branch is None:
        return {}
    # v3.27: opp-independent bias — 약한 (-3 ~ -5). _tactical_lookup_bias (-4~-6) 와 보완.
    bias_mag = -3.0 - (conf - 0.7) * 6.67  # conf 0.7→-3.0, 1.0→-5.0
    return {branch: bias_mag}


# ─── v3.14 NEW: engine 표준 BFM action 직접 호출 ────────────────────
# 사용자 통찰 (2026-05-27): 평행 비행 깰 수단 = engine 표준 BFM (HighYoYo phase
# state machine, ImmelmannTurn, SplitS, OneCircleFight, LagPursuit, …) 활용.
# 우리 단순 1-tick action 보다 정교한 sequence policy.

import uuid as _uuid
_engine_bfm_cache: dict = {}


def _get_engine_bfm(name: str):
    """engine 의 BFM action instance lazy load + 격리 blackboard namespace."""
    global _engine_bfm_cache
    if name in _engine_bfm_cache:
        return _engine_bfm_cache[name]
    try:
        # lazy import — 패키지 컨텍스트 보장
        import sys as _sys
        from pathlib import Path as _P
        _proj_root = _P(__file__).resolve().parents[3]
        if str(_proj_root) not in _sys.path:
            _sys.path.insert(0, str(_proj_root))
        from src.behavior_tree.nodes import actions as _eng_act
        cls = getattr(_eng_act, name, None)
        if cls is None:
            return None
        inst = cls()
        # 격리 blackboard
        inst.blackboard = py_trees.blackboard.Client(
            name=f"engbfm_{name}_{_uuid.uuid4().hex[:6]}")
        inst.blackboard.register_key(
            key="observation", access=py_trees.common.Access.WRITE)
        inst.blackboard.register_key(
            key="action", access=py_trees.common.Access.WRITE)
        if hasattr(inst, 'initialise'):
            try:
                inst.initialise()
            except Exception:
                pass
        _engine_bfm_cache[name] = inst
        return inst
    except Exception as _e:
        logger.warning(f"_get_engine_bfm({name}) load fail: {_e}")
        return None


def _call_engine_bfm(name: str, obs: dict, fallback: tuple = (2, 4, 2)) -> tuple[int, int, int]:
    """engine BFM 호출 → bin 추출."""
    inst = _get_engine_bfm(name)
    if inst is None:
        return _bin_clip(*fallback)
    try:
        inst.blackboard.set("observation", obs)
        inst.blackboard.set("action", None)
        inst.update()
        action = inst.blackboard.get("action")
        if action is None:
            return _bin_clip(*fallback)
        return _bin_clip(int(action[0]), int(action[1]), int(action[2]))
    except Exception:
        return _bin_clip(*fallback)


def action_engine_high_yoyo(f: dict) -> tuple[int, int, int]:
    return _call_engine_bfm("HighYoYo", obs_current, fallback=(3, 4, 1))


def action_engine_one_circle(f: dict) -> tuple[int, int, int]:
    return _call_engine_bfm("OneCircleFight", obs_current, fallback=(2, 4, 2))


def action_engine_two_circle(f: dict) -> tuple[int, int, int]:
    return _call_engine_bfm("TwoCircleFight", obs_current, fallback=(2, 4, 3))


def action_engine_immelmann(f: dict) -> tuple[int, int, int]:
    return _call_engine_bfm("ImmelmannTurn", obs_current, fallback=(4, 4, 1))


def action_engine_split_s(f: dict) -> tuple[int, int, int]:
    return _call_engine_bfm("SplitS", obs_current, fallback=(0, 4, 4))


def action_engine_lag_pursuit(f: dict) -> tuple[int, int, int]:
    return _call_engine_bfm("LagPursuit", obs_current, fallback=(2, 4, 2))


def action_engine_overshoot_avoid(f: dict) -> tuple[int, int, int]:
    return _call_engine_bfm("OvershootAvoidance", obs_current, fallback=(2, 4, 1))


def action_engine_energy_fight(f: dict) -> tuple[int, int, int]:
    return _call_engine_bfm("EnergyFight", obs_current, fallback=(3, 4, 3))


def action_engine_tc_fight(f: dict) -> tuple[int, int, int]:
    return _call_engine_bfm("TCFight", obs_current, fallback=(2, 4, 3))


# ─── v3.15 NEW: Velocity Oscillation + Vertical Scissors ─────────
# 사용자 진단 (2026-05-27): vel 90% = 3/4 (accel), alt 변동 거의 없음 (def 만 Δ9837).
# 평행 비행 깨기 = vel/alt 진동 (closure 변동 + 적 catch up 패턴 방해).

# global tick counter (oscillation phase)
_vosc_tick = 0


def cost_velocity_oscillation(f: dict) -> float:
    """평행 비행 stuck → vel 5-tick oscillation (brake↔accel) 으로 closure 변동.

    근거: trace v3.14.2 vel 분포 vs aggressive: 1=brake 1ticks(!), 3=247, 4=510 — 가속만.
    적과 같은 vel → closure 0 영원. 우리만 brake/accel 변동 → 적이 따라 못함 (BT 반응 느림).
    조건: 평행 비행 (pos_adv>100 + ata<30 + dist∈[5000,15000] + |closure|<50).
    """
    pos_adv = f["pos_adv"]
    ata = f["ata"]
    dist = f["dist"]
    closure = f["closure_kts"]
    if not (pos_adv > 100.0 and ata < 30.0
            and 5000.0 < dist < 15000.0 and abs(closure) < 50.0):
        return 3.0
    # 약한 우선 — CrossOver/TCV 와 비슷
    return -1.6


def action_velocity_oscillation(f: dict) -> tuple[int, int, int]:
    """5-tick brake / 5-tick accel 교차. 적 향한 hdg 유지."""
    global _vosc_tick
    _vosc_tick += 1
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    if abs(rel_b) < 8.0:
        hdg = 4
    else:
        hdg = 4 + int(round(np.clip(rel_b / 22.5, -4, 4)))
    # 5-tick oscillation
    phase = (_vosc_tick // 5) % 2
    vel = 1 if phase == 0 else 4   # brake / max accel
    return _bin_clip(2, hdg, vel)


def cost_vertical_scissors(f: dict) -> float:
    """평행 비행 + Es 충분 → alt 5-tick climb/dive 교차.

    근거: aggressive 매치 alt 거의 hold (2=703 ticks). vertical 진동으로 적 trajectory
    cross 시도 + alt advantage 만들기. ace 매치 dynamics 안 깨도록 조건 엄격.
    """
    pos_adv = f["pos_adv"]
    ata = f["ata"]
    dist = f["dist"]
    closure = f["closure_kts"]
    ego_alt = f["ego_alt"]
    if not (pos_adv > 100.0 and ata < 30.0
            and 6000.0 < dist < 13000.0 and abs(closure) < 50.0
            and HARD_DECK_FT + 4000 < ego_alt < 25000):
        return 3.0
    return -1.7


def action_vertical_scissors(f: dict) -> tuple[int, int, int]:
    """5-tick climb / 5-tick dive 교차 — vertical S 패턴."""
    global _vosc_tick
    _vosc_tick += 1
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    if abs(rel_b) < 8.0:
        hdg = 4
    else:
        hdg = 4 + int(round(np.clip(rel_b / 30.0, -3, 3)))
    phase = (_vosc_tick // 5) % 2
    ego_alt = f["ego_alt"]
    if phase == 0:
        alt = 4   # max climb
    else:
        alt = 0 if ego_alt > HARD_DECK_FT + 3000 else 2
    return _bin_clip(alt, hdg, 3)


def cost_barrel_roll(f: dict) -> float:
    """평행 + 적당히 가까이 → hdg ±90° oscillation (적 lead 추정 흩뜨림).

    조건: ata<40 + dist∈[3000,9000] + |closure|<80 + pos_adv>50.
    """
    pos_adv = f["pos_adv"]
    ata = f["ata"]
    dist = f["dist"]
    closure = f["closure_kts"]
    if not (pos_adv > 50.0 and ata < 40.0
            and 3000.0 < dist < 9000.0 and abs(closure) < 80.0):
        return 3.0
    return -1.5


def action_barrel_roll(f: dict) -> tuple[int, int, int]:
    """3-tick left turn / 3-tick right turn — hdg oscillation."""
    global _vosc_tick
    _vosc_tick += 1
    phase = (_vosc_tick // 3) % 2
    hdg = 1 if phase == 0 else 7   # 강 좌 / 강 우
    return _bin_clip(2, hdg, 3)


_prev_tau_gun = 0.0
_prev_ata_gun = None


def action_gun_engagement(f: dict) -> tuple[int, int, int]:
    """v3.40 (2026-05-29 사용자 원칙): PD-controlled gun tracking (v6h4 SmartGunAttack 스타일).

    cmd = kp*tau + kd*tau_rate (closed-loop PD). 매 tick 관측 → 적응형.
    vel: WEZ 외 vel=3 (approach), WEZ 진입 vel=1 (dwell 극대화).
    """
    global _prev_tau_gun
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    tau_rate = rel_b - _prev_tau_gun
    _prev_tau_gun = rel_b
    cmd = PD_GUN_KP * rel_b + PD_GUN_KD * tau_rate
    hdg = max(0, min(8, int(round(cmd / 22.5)) + 4))
    dist = f.get("dist", 9999)
    # R15-A2 fix: WEZ 안에서도 *closure*를 봐야 함 (사용자 원칙: 관측값 기반 적응형).
    # 단순 감속은 tail-chase 시 추격 포기 — closure +30 에 vel=1 주면 적이 도주.
    closure = float(obs_current.get("closure_rate_kts", 0.0))
    in_wez = WEZ_MIN_FT <= dist <= WEZ_MAX_FT
    if in_wez:
        if closure > 150:        # 곧 overshoot
            vel = 1
        elif closure > 50:        # 적절히 접근 — 중립
            vel = 2
        elif closure > -20:       # 약하게 접근 또는 정체 — 추격 가속
            vel = 3
        else:                     # 분리 중 — 풀 추격
            vel = PD_GUN_VEL_APPROACH
    else:
        vel = PD_GUN_VEL_APPROACH
    alt_gap = float(obs_current.get("alt_gap_ft", 0.0))
    alt = 2 + (1 if alt_gap > 200 else (-1 if alt_gap < -200 else 0))
    return _bin_clip(alt, hdg, vel)


def action_gun_engagement_oto(f: dict) -> tuple[int, int, int]:
    """on_to_on 상황 전용 gun engagement (v3.28). hdg ±2 + 더 정밀 매핑."""
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    hdg = 4 + int(round(np.clip(rel_b / 22.5, -2, 2)))
    alt_gap = float(obs_current.get("alt_gap_ft", 0.0))
    alt = 2 + (1 if alt_gap > 200 else (-1 if alt_gap < -200 else 0))
    return _bin_clip(alt, hdg, 3)


_prev_dist_offp = None
_prev_ata_offp = None
_prev_omega_opp_sign = 0


def _detect_circle_fight(f: dict) -> str:
    """v3.41 (사용자 자료 § 4): 우리 omega 부호 vs 적 omega 부호.

    rate fight (two-circle): 우리·적 같은 방향 (둘 다 좌선회 or 둘 다 우선회) → 큰 원
    radius fight (one-circle): 다른 방향 (서로 마주보는 선회) → 작은 원, vel↓
    """
    global _prev_omega_opp_sign
    omega_opp = f.get("omega_opp_degs", 0)
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    # 우리 turn 의도 = rel_b 부호 (적이 우측 = 우리 우선회)
    our_sign = 1 if rel_b > 0 else (-1 if rel_b < 0 else 0)
    # 적 omega 부호 — 단순 magnitude 만 있어서 sign 추정 필요. d_aa 사용 가능.
    d_aa = f.get("d_aa", 0)
    opp_sign = 1 if d_aa > 0 else (-1 if d_aa < 0 else 0)
    # opp reversal 감지 (이전 부호와 반대)
    opp_reversed = (_prev_omega_opp_sign != 0 and opp_sign != 0
                     and opp_sign * _prev_omega_opp_sign < 0)
    if opp_sign != 0:
        _prev_omega_opp_sign = opp_sign
    if our_sign == 0 or opp_sign == 0:
        return "neutral"
    if our_sign == opp_sign:
        return "two_circle"  # 같은 방향 = rate fight
    return "one_circle"      # 반대 방향 = radius fight


def action_offensive_pursuit(f: dict) -> tuple[int, int, int]:
    """v3.41 (2026-05-29): 5-rule adaptive + one-circle/two-circle 결정 (사용자 자료 § 4).

    매 tick 관측 → BFM rule + circle type 분기.
    """
    global _prev_dist_offp, _prev_ata_offp
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    alt_gap = float(obs_current.get("alt_gap_ft", 0.0))
    closure = f.get("closure_kts", 0)
    dist = f.get("dist", 9999)
    ata = f.get("ata", 0)
    e_diff = f.get("energy_diff_ft", 0)
    dist_widening = (_prev_dist_offp is not None
                     and dist > _prev_dist_offp + OFFP_DIST_WIDEN_THRESH)
    ata_worsening = (_prev_ata_offp is not None
                     and ata > _prev_ata_offp + OFFP_ATA_WORSEN_THRESH)
    _prev_dist_offp = dist
    _prev_ata_offp = ata
    circle_type = _detect_circle_fight(f)
    base_hdg = 4 + int(round(np.clip(rel_b / 22.5, -4, 4)))
    alt_idx = 2 if abs(alt_gap) < 500 else (3 if alt_gap > 0 else 1)
    # Priority 1: one-circle (radius fight) — 적이 우리쪽 turn, 우리도 tight + vel↓
    if circle_type == "one_circle" and dist < 6000:
        sign = 1 if rel_b > 0 else -1
        hdg = max(0, min(8, 4 + sign * ONE_CIRCLE_TURN_INTENSITY))
        vel = ONE_CIRCLE_VEL  # vel=1 (작은 반경)
        return _bin_clip(alt_idx, hdg, vel)
    # Priority 2: two-circle (rate fight) — 우리도 같은 방향 큰 원
    if circle_type == "two_circle" and dist < 8000:
        sign = 1 if rel_b > 0 else -1
        hdg = max(0, min(8, 4 + sign * TWO_CIRCLE_TURN_INTENSITY))
        vel = TWO_CIRCLE_VEL  # vel=4 (큰 회전율, 속도 유지)
        return _bin_clip(alt_idx, hdg, vel)
    # Priority 3-7: 5-rule BFM (v6h4 SmartLeadPursuit)
    if dist_widening and closure < 0:
        hdg = max(0, base_hdg - 2) if base_hdg <= 4 else min(8, base_hdg + 2)
        vel = 2
    elif ata_worsening:
        hdg = max(0, base_hdg - 1) if base_hdg <= 4 else min(8, base_hdg + 1)
        vel = 2
    elif dist < 2500 and closure > OFFP_OVERSHOOT_CLOSURE:
        hdg = base_hdg
        vel = 1
    elif dist > OFFP_FAR_DIST and ata < OFFP_SPRINT_ATA_MAX:
        hdg = base_hdg
        vel = 4
    elif e_diff > OFFP_ENERGY_DIVE_THRESH and alt_gap < -500:
        hdg = base_hdg
        vel = 4
        alt_idx = 1
    else:
        hdg = base_hdg
        vel = 3
    return _bin_clip(alt_idx, hdg, vel)


_prev_ata_cutoff = None
_prev_dist_cutoff = None


def action_cutoff_pursuit(f: dict) -> tuple[int, int, int]:
    """v3.42 (2026-05-29): v6h4 SmartPurePursuit 4-rule 적응형.

    (1) ATA>60° or 커지는 중 → max-G turn + corner vel (2)
    (2) ATA<20° + 거리 벌어짐 → sprint vel 4
    (3) overshoot (dist<2500 + closure>OVERSHOOT) → vel 1
    (4) 기본 pure pursuit
    """
    global _prev_ata_cutoff, _prev_dist_cutoff
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    ata = f.get("ata", 0)
    dist = f.get("dist", 5000)
    closure = f.get("closure_kts", 0)
    dist_widening = (_prev_dist_cutoff is not None
                     and dist > _prev_dist_cutoff + OFFP_DIST_WIDEN_THRESH)
    ata_worsening = (_prev_ata_cutoff is not None
                     and ata > _prev_ata_cutoff + OFFP_ATA_WORSEN_THRESH)
    _prev_dist_cutoff = dist
    _prev_ata_cutoff = ata
    sign = 1 if rel_b > 0 else (-1 if rel_b < 0 else 0)
    if ata > 60 or ata_worsening:
        hdg = max(0, min(8, 4 + sign * 4))  # max-G
        vel = 2
    elif ata < 20 and dist_widening:
        hdg = max(0, min(8, 4 + sign * 1))
        vel = 4
    elif dist < 2500 and closure > OFFP_OVERSHOOT_CLOSURE:
        hdg = 4 + sign * 2
        vel = 1
    else:
        hdg = max(0, min(8, 4 + sign * 2))
        vel = 3
    alt_gap = float(obs_current.get("alt_gap_ft", 0.0))
    alt = 2 if abs(alt_gap) < 500 else (3 if alt_gap > 0 else 1)
    return _bin_clip(alt, hdg, vel)


_hy_phase = 0
_hy_tick = 0
_hy_prev_dist = None


def action_high_yoyo(f: dict) -> tuple[int, int, int]:
    """v3.42 (2026-05-29): v6h4 SmartHighYoYo 관측 기반 phase transition (fixed timer 종식).

    CLIMB phase transitions (모두 관측 기반):
    - dist_widening → DIVE (yoyo 반경 과대)
    - |closure| < closure_normal → DIVE (역할 완료)
    - e_diff > energy_force_dive → DIVE (폭주 방지)
    DIVE phase transitions:
    - closure 다시 과다 → CLIMB (선회 부족)
    """
    global _hy_phase, _hy_tick, _hy_prev_dist
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    ata = f.get("ata", 0)
    closure = f.get("closure_kts", 0)
    e_diff = f.get("energy_diff_ft", 0)
    dist = f.get("dist", 5000)
    dist_widening = (_hy_prev_dist is not None and dist > _hy_prev_dist + 80)
    _hy_prev_dist = dist
    sign = 1 if rel_b > 0 else -1
    turn_mag = 3 if ata < 90 else 4
    turn = max(0, min(8, 4 + sign * turn_mag))
    if _hy_phase == 0:  # CLIMB
        _hy_tick += 1
        if dist_widening or abs(closure) < 100 or e_diff > 3000 or _hy_tick >= 8:
            _hy_phase = 1
            _hy_tick = 0
    else:  # DIVE
        _hy_tick += 1
        if closure > OFFP_OVERSHOOT_CLOSURE * 1.2:
            _hy_phase = 0
            _hy_tick = 0
        elif _hy_tick >= 10:
            _hy_phase = 0
            _hy_tick = 0
    if _hy_phase == 0:
        alt_idx, vel = 4, 3  # CLIMB + corner
    else:
        alt_idx, vel = 1, 4  # DIVE + accel
    return _bin_clip(alt_idx, turn, vel)


def cost_lag_pursuit(f: dict) -> float:
    """v3.14 NEW: 평행 비행 + 우리 ata 작음 → engine LagPursuit (적 후방 lag 유지).

    근거: 평행 비행 stuck (pos_adv>100 + ata<30 + dist 5000-12000ft + closure 거의 0)
    에서 우리가 *lead 가 아닌 lag* (적 trajectory 뒤쪽) 잡으면 angle 작아짐 + dist 유지.
    Engine LagPursuit (actions.py:661) 의 정통 BFM.
    """
    pos_adv = f["pos_adv"]
    ata = f["ata"]
    dist = f["dist"]
    closure = f["closure_kts"]
    if not (pos_adv > 80.0 and ata < 40.0 and 4000.0 < dist < 12000.0
            and abs(closure) < 80.0):
        return 3.0
    pos_q = min(1.0, pos_adv / 180.0)
    ata_q = _gauss(ata - 15.0, 25.0)
    return -1.8 * pos_q * ata_q


def action_lag_pursuit(f: dict) -> tuple[int, int, int]:
    return action_engine_lag_pursuit(f)


def cost_immelmann(f: dict) -> float:
    """v3.14 NEW: 평행 비행 + ata 작음 + Es 충분 → ImmelmannTurn (180° reverse + alt gain).

    근거: 평행 비행 stuck 에서 reverse 로 head-on merge 다시 시도. Es 충분해야 climb 가능.
    """
    pos_adv = f["pos_adv"]
    ata = f["ata"]
    dist = f["dist"]
    closure = f["closure_kts"]
    energy_diff = f["energy_diff_ft"]
    ego_alt = f["ego_alt"]
    # 평행 stuck + Es 거의 같음 + alt 여유
    if not (pos_adv > 100.0 and ata < 30.0 and dist > 9000.0
            and abs(closure) < 50.0 and energy_diff > -1000.0
            and ego_alt < 25000.0):
        return 3.0
    return -1.5     # 약한 우선 (engine sequence 가 진행)


def action_immelmann(f: dict) -> tuple[int, int, int]:
    return action_engine_immelmann(f)


def cost_split_s(f: dict) -> float:
    """v3.14 NEW: 우리 위 + ata 잡음 → SplitS (180° + dive)."""
    alt_gap = float(obs_current.get("alt_gap_ft", 0.0))
    ata = f["ata"]
    ego_alt = f["ego_alt"]
    pos_adv = f["pos_adv"]
    # 우리 alt 위 (alt_gap 음수) + ata 잡음 + alt 충분
    if not (alt_gap < -2000.0 and ata < 30.0 and pos_adv > 80.0
            and ego_alt > HARD_DECK_FT + 5000.0):
        return 3.0
    return -2.0


def action_split_s(f: dict) -> tuple[int, int, int]:
    return action_engine_split_s(f)


def action_inside_chase(f: dict) -> tuple[int, int, int]:
    """v3.9 NEW: inside turn — hdg 강 turn (적 inside 잡고 lock) + vel 유지."""
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    ata = f["ata"]
    # 강한 turn (ata 비례, max +/-4 추가)
    extra = min(3, int(ata / 20.0))
    if abs(rel_b) < 5.0:
        hdg = 4
    else:
        base = 4 + int(round(np.clip(rel_b / 18.0, -4, 4)))
        hdg = base + int(np.sign(rel_b)) * extra
    alt_gap = float(obs_current.get("alt_gap_ft", 0.0))
    alt = 2 if abs(alt_gap) < 500 else (3 if alt_gap > 0 else 1)
    return _bin_clip(alt, hdg, 2)   # vel 유지 (decel X — inside 유지)


_prev_ata_bt = None


def action_break_turn(f: dict) -> tuple[int, int, int]:
    """v3.42 (2026-05-29): v6h4 SmartBreakTurn 4-rule 적응형.

    (1) Last ditch (enm_in_wez) → max-G + 수직 회피
    (2) Panic (dist<panic_dist) → max-G break
    (3) 적 lead 성공 중 (ATA 감소) → max-G + 반대 방향
    (4) 원거리 (dist>extend_dist) → 에너지 보존 break
    else: 기본 break
    """
    global _prev_ata_bt
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    ego_alt = f.get("ego_alt", 10000)
    dist = f.get("dist", 5000)
    ata = f.get("ata", 0)
    overshoot = f.get("overshoot_risk", False)
    # 적 lead 성공 감지: ATA 시간에 따라 감소 (적이 우리 정확 겨냥)
    lead_detected = (_prev_ata_bt is not None and ata < _prev_ata_bt - 2.0)
    _prev_ata_bt = ata
    sign_back = -1 if rel_b >= 0 else 1  # 반대 방향
    panic_dist = 2000.0
    extend_dist = 4000.0
    alt_split = 8000.0
    if overshoot:
        # Last ditch
        hdg = max(0, min(8, 4 + sign_back * 4))
        vel = 2
        alt_idx = 4 if ego_alt < 5000 else 2
    elif dist < panic_dist:
        hdg = max(0, min(8, 4 + sign_back * 4))
        vel = 2
        alt_idx = 2 if ego_alt > alt_split else 3
    elif lead_detected:
        hdg = max(0, min(8, 4 + sign_back * 4))
        vel = 2
        alt_idx = 2
    elif dist > extend_dist:
        hdg = max(0, min(8, 4 + sign_back * 2))
        vel = 4
        alt_idx = 2
    else:
        hdg = max(0, min(8, 4 + sign_back * 3))
        vel = 3
        alt_idx = 1 if ego_alt > alt_split else 2
    return _bin_clip(alt_idx, hdg, vel)


def action_defensive_spiral(f: dict) -> tuple[int, int, int]:
    """극한 방어 — barrel + dive — energy preserve, 적 후방으로."""
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    ego_alt = f["ego_alt"]
    hdg = 0 if rel_b >= 0 else 8       # 반대 방향
    alt = 1 if ego_alt > HARD_DECK_FT + 1500 else 2  # dive (mild)
    return _bin_clip(alt, hdg, 4)      # max accel


def action_lost_pursuit(f: dict) -> tuple[int, int, int]:
    """우리 6시 적 — 직진+상승 (적 추격 끊기, 우리 가속/거리 벌리기)."""
    # rel_b 반대 방향 turn 으로 적 LOS 끊기
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    hdg = 4 + int(round(np.clip(-rel_b / 30.0, -2, 2)))
    ego_alt = f["ego_alt"]
    alt = 3 if ego_alt < 25000 else 2
    return _bin_clip(alt, hdg, 4)


def action_extension(f: dict) -> tuple[int, int, int]:
    """원거리 closure — 적 방향 + max accel (v3.13 vertical bias 회귀로 revert)."""
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    hdg = 4 if abs(rel_b) < 8 else 4 + int(round(np.clip(rel_b / 22.5, -4, 4)))
    return _bin_clip(2, hdg, 4)


def action_stale_chase(f: dict) -> tuple[int, int, int]:
    """stalemate 탈출 — vertical 강 (climb max + decel)."""
    return _bin_clip(4, 4, 1)


def action_defensive_escape(f: dict) -> tuple[int, int, int]:
    """v3.45 (2026-05-29 R15-E): T-45A 교리 + v6h4 SmartBreakTurn + Phase 5 split-S.

    매 tick *관측 기반 적응형* dispatch (사용자 원칙: 잠금 X, 매 tick 재평가).
    Phase 5 SPLIT-S (imminent kill): dist<2500 + ata>165 + closure>10 → 다이브+max-G+full
    Phase 4 LAST-DITCH (dist<1500 + ata>170): barrel roll
    Phase 3 BUGOUT GATE (AOT≥150 + energy adv + dist>2500): extension (0-g unload)
    Phase 1/2 SURVIVE/OVERSHOOT: action_break_turn (5-rule v6h4)
    """
    if not _is_defensive_state(f):
        return action_break_turn(f)
    dist = f["dist"]
    ata = f["ata"]
    aa = f["aa"]
    closure = f.get("closure_kts", 0)
    energy_diff = f.get("energy_diff_ft", 0.0)
    ego_alt = f.get("ego_alt", 10000)
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    sign_back = -1 if rel_b >= 0 else 1
    aot = 360.0 - aa if aa < 180 else aa

    # Phase 5 SPLIT-S: 적 nose 우리 6시 정확 lock + closure 양수 + alt 여유
    # → 수직 분리로 적 tracking 깨기 (v6h4 vertical defensive 교리)
    if (dist < DEFESC_SPLITS_DIST_FT and ata > DEFESC_SPLITS_ATA_DEG
            and closure > DEFESC_SPLITS_CLOSURE_KTS
            and ego_alt > HARD_DECK_FT + 2000):
        hdg = max(0, min(8, 4 + sign_back * 4))
        return _bin_clip(1, hdg, 4)

    if dist < DEFESC_LASTDITCH_DIST_FT and ata > 170:
        return action_barrel_roll(f)
    if aot >= DEFESC_BUGOUT_AOT_DEG and energy_diff > 0 and dist > 2500:
        return action_extension(f)
    return action_break_turn(f)


_prev_dist_lp = None
_prev_ata_lp = None


def action_lead_pursuit(f: dict) -> tuple[int, int, int]:
    """v3.42 (2026-05-29): v6h4 SmartLeadPursuit 5-rule + TOF lead 보정.

    적의 미래 위치 (R/V_bullet 만큼 propagate) 에 nose 두기.
    BFM 5-rule: 거리 벌어짐, ATA 커짐, overshoot, sprint, dive.
    """
    global _prev_dist_lp, _prev_ata_lp
    rel_b = float(obs_current.get("relative_bearing_deg", 0.0))
    closure = f.get("closure_kts", 0)
    alt_gap = float(obs_current.get("alt_gap_ft", 0.0))
    ata = f.get("ata", 0)
    dist = f.get("dist", 9999)
    e_diff = f.get("energy_diff_ft", 0)
    d_ata = f.get("d_ata", 0)
    dist_widening = (_prev_dist_lp is not None
                     and dist > _prev_dist_lp + OFFP_DIST_WIDEN_THRESH)
    ata_worsening = (_prev_ata_lp is not None
                     and ata > _prev_ata_lp + OFFP_ATA_WORSEN_THRESH)
    _prev_dist_lp = dist
    _prev_ata_lp = ata
    # TOF lead 보정 (자료 § B): pipper = ata - d_ata × (R/V_bullet)
    t_tof = dist / BULLET_VELOCITY_FPS
    lead_correction = d_ata * t_tof  # 적의 LOS rate 만큼 lead
    sign = 1.0 if rel_b >= 0 else -1.0
    target_b = rel_b + sign * lead_correction
    base_hdg = 4 + int(round(np.clip(target_b / 22.5, -4, 4)))
    alt_idx = 2 if abs(alt_gap) < 500 else (3 if alt_gap > 0 else 1)
    if dist_widening and closure < 0:
        hdg = max(0, base_hdg - 2) if base_hdg <= 4 else min(8, base_hdg + 2)
        vel = 2
    elif ata_worsening:
        hdg = max(0, base_hdg - 1) if base_hdg <= 4 else min(8, base_hdg + 1)
        vel = 2
    elif dist < 2500 and closure > OFFP_OVERSHOOT_CLOSURE:
        hdg = base_hdg
        vel = 1
    elif dist > OFFP_FAR_DIST and ata < OFFP_SPRINT_ATA_MAX:
        hdg = base_hdg
        vel = 4
    elif e_diff > OFFP_ENERGY_DIVE_THRESH and alt_gap < -500:
        hdg = base_hdg
        vel = 4
        alt_idx = 1
    else:
        hdg = base_hdg
        vel = 3
    return _bin_clip(alt_idx, hdg, vel)


# ─── v3.22 adaptive_eagle_v11_code Smart actions 직접 호출 ───────
# 사용자 통찰: SmartLeadPursuit/SmartLagPursuit/SmartHighYoYo/SmartBreakTurn/SmartLowYoYo
# 모두 검증된 BFM 법칙 (5 priority 우선순위 + 시계열 추적). 우리 cost-branch 가 호출.

_smart_cache: dict = {}


# v3.24 counter_v4 effective_params (mine_tactical_patterns 결과)
_SMART_BEST_PARAMS = {
    "SmartLowYoYo": dict(dive_alt=1, dive_ticks=6, dive_vel=4,
                          recover_alt=3, recover_vel=3),
    "SmartLagPursuit": dict(tau_gain=0.6, vel=3),
    "SmartHighYoYo": dict(closure_normal_kts=100, dist_widen_thresh_ft=80,
                           energy_force_dive_ft=3000,
                           max_climb_ticks=6, max_dive_ticks=8,
                           overshoot_closure_kts=280),
}


def _get_smart(name: str):
    """adaptive_eagle_v11_code 의 SmartX instance lazy load + counter_v4 best params."""
    if name in _smart_cache:
        return _smart_cache[name]
    try:
        import sys as _sys
        from pathlib import Path as _P
        import importlib.util as _iu
        _root = _P(__file__).resolve().parents[3]
        if str(_root) not in _sys.path:
            _sys.path.insert(0, str(_root))
        cust_path = _root / "examples/adaptive_eagle_v11_code/nodes/custom_actions.py"
        spec = _iu.spec_from_file_location("_eagle_v11_custom", cust_path)
        mod = _iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls = getattr(mod, name, None)
        if cls is None:
            return None
        # v3.24: counter_v4 effective_params 사용
        params = _SMART_BEST_PARAMS.get(name, {})
        try:
            inst = cls(**params)
        except TypeError:
            # constructor 가 다른 params 받음 — fallback to default
            inst = cls()
        inst.blackboard = py_trees.blackboard.Client(
            name=f"smart_{name}_{_uuid.uuid4().hex[:6]}")
        inst.blackboard.register_key(
            key="observation", access=py_trees.common.Access.WRITE)
        inst.blackboard.register_key(
            key="action", access=py_trees.common.Access.WRITE)
        if hasattr(inst, 'initialise'):
            try: inst.initialise()
            except Exception: pass
        _smart_cache[name] = inst
        return inst
    except Exception as _e:
        logger.warning(f"_get_smart({name}) fail: {_e}")
        return None


_NORM_ANGLE_KEYS = ("ata_deg", "aa_deg", "hca_deg", "tau_deg",
                    "ata_lead_deg", "tau_lead_deg", "relative_bearing_deg")


def _normalize_obs_for_smart(obs: dict) -> dict:
    """v3.22.2 fix — Smart 코드가 obs[key]*180 가정 + side_flag turn 방향 사용.

    1) angle keys 도 → 정규화 ([-1, 1] 또는 [0, 1])
    2) side_flag: Smart 가 우/좌 turn 결정. 우리 obs 에 0 → 항상 같은 방향.
       relative_bearing_deg 부호로 set.
    """
    norm = dict(obs)
    for k in _NORM_ANGLE_KEYS:
        if k in norm and isinstance(norm[k], (int, float)):
            norm[k] = norm[k] / 180.0
    # side_flag (Smart turn 방향): rel_bearing > 0 (적 우측) → +1, 좌측 → -1
    rb = obs.get("relative_bearing_deg", 0.0)
    if not isinstance(rb, (int, float)):
        rb = 0.0
    norm["side_flag"] = 1.0 if rb > 0 else (-1.0 if rb < 0 else 0.0)
    return norm


def _call_smart(name: str, obs: dict, fallback=(2, 4, 3)) -> tuple[int, int, int]:
    inst = _get_smart(name)
    if inst is None:
        return _bin_clip(*fallback)
    try:
        norm_obs = _normalize_obs_for_smart(obs)
        inst.blackboard.set("observation", norm_obs)
        inst.blackboard.set("action", None)
        inst.update()
        a = inst.blackboard.get("action")
        if a is None: return _bin_clip(*fallback)
        return _bin_clip(int(a[0]), int(a[1]), int(a[2]))
    except Exception:
        return _bin_clip(*fallback)


def action_smart_lead(f): return _call_smart("SmartLeadPursuit", obs_current, (2, 4, 3))
def action_smart_lag(f): return _call_smart("SmartLagPursuit", obs_current, (2, 4, 2))
def action_smart_highyoyo(f): return _call_smart("SmartHighYoYo", obs_current, (4, 4, 1))
def action_smart_lowyoyo(f): return _call_smart("SmartLowYoYo", obs_current, (1, 4, 4))
def action_smart_breakturn(f): return _call_smart("SmartBreakTurn", obs_current, (1, 0, 3))
def action_smart_purepursuit(f): return _call_smart("SmartPurePursuit", obs_current, (2, 4, 3))


# Smart cost wrappers — 기존 cost 함수 재사용, action 만 Smart 로 dispatch
def cost_smart_lead(f): return cost_lead_pursuit(f)
def cost_smart_lag(f): return cost_lag_pursuit(f)         # 이미 정의
def cost_smart_highyoyo(f): return cost_high_yoyo(f)
def cost_smart_lowyoyo(f): return cost_dive_attack(f)     # low yoyo = dive 비슷
def cost_smart_breakturn(f): return cost_break_turn(f)
def cost_smart_purepursuit(f): return cost_offensive_pursuit(f)


# Branch registry — v3.8.1: 8 branch (v3.7 baseline) + Layer 2 dynamics 만 보존.
# 신규 (DefensiveSpiral / LostPursuit / StaleChase) 제거 — 도주 선호 dominate.
BRANCHES = [
    ("HardDeck",            None,                       action_hard_deck),
    ("GunEngagement",       cost_gun_engagement,        action_gun_engagement),
    # v3.34 (2026-05-28): two-mode separation (사용자 자료)
    ("GunTracking",         cost_gun_tracking,          action_gun_engagement),
    ("GunSnapshot",         cost_gun_snapshot,          action_gun_engagement),
    # v3.37 (2026-05-29): all-aspect WEZ envelope + Lead TOF (사용자 자료)
    ("GunEnvelope",         cost_wez_envelope,          action_gun_engagement),
    ("GunLeadTOF",          cost_lead_tof,              action_gun_engagement),
    ("BreakTurn",           cost_break_turn,            action_break_turn),
    ("OffensivePursuit",    cost_offensive_pursuit,     action_offensive_pursuit),
    ("CutoffPursuit",       cost_cutoff_pursuit,        action_cutoff_pursuit),
    ("DiveAttack",          cost_dive_attack,           action_dive_attack),   # v3.23: SmartLowYoYo swap (fuzz: ace 12.3→35.9 일관, total +24.8)
    ("CrossOverTurn",       cost_cross_over_turn,       action_cross_over_turn),
    ("TailChaseVertical",   cost_tail_chase_vertical,   action_tail_chase_vertical),
    # v3.15 NEW: oscillation branches (closure/alt 변동으로 적 trajectory 깨기)
    ("VelOscillation",      cost_velocity_oscillation,  action_velocity_oscillation),
    ("VerticalScissors",    cost_vertical_scissors,     action_vertical_scissors),
    ("BarrelRoll",          cost_barrel_roll,           action_barrel_roll),    # v3.16
    ("HighYoYo",            cost_high_yoyo,             action_high_yoyo),
    ("Extension",           cost_extension,             action_extension),
    ("LeadPursuit",         cost_lead_pursuit,          action_lead_pursuit),
    # v3.31 (2026-05-28): doctrine-based defensive escape (T-45A ACMFP-03)
    ("DefensiveEscape",     cost_defensive_escape,      action_defensive_escape),
    # v3.33 (2026-05-28): 초기 가속 (사용자 명령) — chase 시 에너지 적립 first
    ("InitPursuitAccel",    cost_initial_pursuit_accel, action_initial_pursuit_accel),
    # v3.43 (2026-05-29): bt_vs_bt 강제 engage (lufbery 회피)
    ("ForceEngageBT",       cost_force_engage_bt,       action_extension),
]


# global obs_current reference (set by selector) — action 함수가 raw obs 키 접근용
obs_current: dict = {}


# ────────────────────────────────────────────────────────────────
# R15-J8 K1-K7 가설 state machines (격리 if-then, 누적 적용)
# 각 K 의 활성 상태 + tick counter 추적.
# ────────────────────────────────────────────────────────────────
class _KState:
    """모든 K state machine 의 instance 별 storage."""
    def __init__(self):
        # K1 vertical asym: "off" / "climb" / "dive"
        self.k1_phase = "off"
        self.k1_phase_tick = 0
        self.k1_cooldown = 0
        # K2 phase shift: "off" / "straight"
        self.k2_phase = "off"
        self.k2_phase_tick = 0
        self.k2_cooldown = 0
        # K4 vertical force: "off" / "climb" / "dive"
        self.k4_phase = "off"
        self.k4_phase_tick = 0
        self.k4_cooldown = 0
        # K5 fire dwell lock: "off" / "lock"
        self.k5_phase = "off"
        self.k5_phase_tick = 0
        self.k5_lock_action = None
        # K8 corner-bleed (P2, K_STALEMATE_DESIGN C-1): "off" / "bleed" / "convert"
        self.k8_phase = "off"
        self.k8_phase_tick = 0
        self.k8_cooldown = 0
        # K9 tracking lock + bin rate-limit (P3, C-2): "off" / "lock"
        self.k9_phase = "off"
        self.k9_phase_tick = 0
        self.k9_cooldown = 0
        self.k9_prev_hdg = 4
        # K10 머지 lead turn (R15-K reframe): "off" / "lock"
        # d_ata × 2.5s lookahead — 우리 90° corner turn time. gun TOF 0.9s 와 다른 *기체 turn lead*.
        self.k10_phase = "off"
        self.k10_phase_tick = 0
        self.k10_cooldown = 0
        # K11 spawn-phase lead turn (defensive/aggressive/ace 머지 phase 활성)
        # 사용자 데이터: 첫 30 ticks 모두 hdg=1 약한 좌회전 + 풀가속 → 측면 closing 못 따라감.
        # 해결: spawn 직후 max-G turn + 감속(corner) → 작은 R 즉시 형성.
        self.k11_phase = "off"
        self.k11_phase_tick = 0
        self.k11_triggered_once = False  # spawn 단 한번만
        # stalemate counter (any K1/K4 trigger)
        self.no_dmg_ticks = 0
        # last us hp (for stalemate detect)
        self.last_us_hp = 100.0
        self.last_opp_hp = 100.0
        # CAS / Es history (10 tick window)
        self.cas_window = []
        self.alt_window = []
        self.ata_window = []
        self.closure_window = []
        self.dist_window = []
        self.alt_gap_window = []
        self.hdg_diff_window = []  # not directly available, approximated


def _k_update_windows(state: _KState, obs: dict, f: dict):
    """매 tick window update."""
    state.cas_window.append(float(obs.get("ego_vc_kts", 400.0)))
    state.alt_window.append(float(f.get("ego_alt", 15000.0)))
    state.ata_window.append(float(f.get("ata", 999.0)))
    state.closure_window.append(float(f.get("closure_kts", 0.0)))
    state.dist_window.append(float(f.get("dist", 99999.0)))
    state.alt_gap_window.append(float(obs.get("alt_gap_ft", 0.0)))
    for arr in (state.cas_window, state.alt_window, state.ata_window,
                state.closure_window, state.dist_window, state.alt_gap_window):
        if len(arr) > 50:
            arr.pop(0)


def _k_apply_dispatch(state: _KState, f: dict, obs: dict, last_action,
                      enabled_ks: set):
    """K1-K7 우선순위 dispatch — 활성 시 (alt, hdg, vel) override 반환. None = no override.

    우선순위: K5 (catch lock) > K7 (dive attack) > K3 (cut-off) > K1 (climb/dive) > K4 (alt) > K2 (straight)
    """
    rel_b = float(obs.get("relative_bearing_deg", 0.0))
    cas = float(obs.get("ego_vc_kts", 400.0))
    ata = float(f.get("ata", 999.0))
    closure = float(f.get("closure_kts", 0.0))
    dist = float(f.get("dist", 99999.0))
    alt_gap = float(obs.get("alt_gap_ft", 0.0))
    ego_alt = float(f.get("ego_alt", 15000.0))

    # === K5 — fire dwell maximize (highest priority) ===
    # 조건: ATA<12 + WEZ dist + 직전 5 tick 모두 ATA<25 → 15 tick all action lock
    if "K5" in enabled_ks:
        if state.k5_phase == "lock":
            state.k5_phase_tick += 1
            if state.k5_phase_tick >= 15 or ata >= 25:
                state.k5_phase = "off"
                state.k5_phase_tick = 0
                state.k5_lock_action = None
            elif state.k5_lock_action is not None:
                return state.k5_lock_action, "K5_LOCK"
        else:
            # 활성화 조건
            recent = state.ata_window[-5:] if len(state.ata_window) >= 5 else []
            if (recent and all(a < 25 for a in recent) and ata < 12
                    and 500 < dist < 2500):
                state.k5_phase = "lock"
                state.k5_phase_tick = 0
                state.k5_lock_action = tuple(last_action) if last_action else None
                if state.k5_lock_action:
                    return state.k5_lock_action, "K5_LOCK"

    # === K11 — Spawn-phase merge lead turn (R15-K, 머지 0-2초) ===
    # 데이터: defensive/aggressive/ace 매치 모두 첫 30 ticks 우리 hdg=1 약한 좌회전 →
    #   적 측면 closing rate (~600 kts) > 우리 turn rate → 영원히 측면 통과.
    # 해결: spawn 직후 max-G turn (hdg=0 or 8) + vel=1 (감속) → 작은 turn radius 즉시.
    # 단 한번만 (spawn 단 한 머지 시점).
    if "K11" in enabled_ks:
        # 매 tick 의 sub_sit_g3 가 아니라 직접 조건 — spawn_tick 사용 위해 state.no_dmg_ticks 활용
        # state.no_dmg_ticks 가 self._spawn_tick 이므로 (cost_branch_selector update 에서 update)
        spawn_tick = state.no_dmg_ticks
        if state.k11_phase == "lock":
            state.k11_phase_tick += 1
            # 10 tick (= 1초) lock 또는 ATA 가 50° 아래로 떨어지면 종료 (정렬 진입)
            if state.k11_phase_tick >= 10 or ata < 50:
                state.k11_phase = "off"
                state.k11_phase_tick = 0
            else:
                # max-G turn toward 적 + 감속
                hdg = 0 if rel_b < 0 else 8
                return (2, hdg, 1), "K11_SPAWN_MERGE"
        elif (not state.k11_triggered_once
              and spawn_tick < 20
              and abs(ata - 90) < 30  # 측면 crossing 모먼트
              and dist < 4500
              and ego_alt > HARD_DECK_FT + 1500):
            state.k11_phase = "lock"
            state.k11_phase_tick = 0
            state.k11_triggered_once = True
            hdg = 0 if rel_b < 0 else 8
            return (2, hdg, 1), "K11_SPAWN_MERGE"

    # === K10 — 머지 lead turn (R15-K reframe, 사용자 BFM 교리 기반) ===
    # 가설: pure pursuit (hdg=rel_b) 의 본질적 lag → 머지에서 적 미래 위치로 *미리 회전*
    # 조건: closure > 30 + 2000 < dist < 5000 + |d_ata| > 3 (LOS rate 있어야 lead 의미)
    # action: d_ata × 2.5s (corner 기체 turn time) 만큼 lead, hdg commit 5 tick
    d_ata_now = float(f.get("d_ata", 0))
    K10_LOOKAHEAD_S = 2.5  # F-16 corner @9G 90° turn ~2s
    K10_AGGR = 1.5         # 1.5x bin scale (강한 commit)
    if "K10" in enabled_ks:
        if state.k10_phase == "lock":
            state.k10_phase_tick += 1
            if state.k10_phase_tick >= 5 or closure < -50 or dist > 6000:
                state.k10_phase = "off"
                state.k10_phase_tick = 0
                state.k10_cooldown = 30
            else:
                # lead corrected target bearing
                sign = 1.0 if rel_b >= 0 else -1.0
                lead_correction = d_ata_now * K10_LOOKAHEAD_S
                target_b = rel_b + sign * lead_correction
                hdg = max(0, min(8, 4 + int(round(np.clip(target_b / 22.5 * K10_AGGR, -4, 4)))))
                # vel=3 = corner 매칭 (turn rate 최대), alt=2 수평
                return (2, hdg, 3), "K10_MERGE_LEAD"
        else:
            if state.k10_cooldown > 0:
                state.k10_cooldown -= 1
            elif (closure > 30 and 2000 < dist < 5000 and abs(d_ata_now) > 3
                    and ata > 40
                    and ego_alt > HARD_DECK_FT + 1500):
                state.k10_phase = "lock"
                state.k10_phase_tick = 0
                sign = 1.0 if rel_b >= 0 else -1.0
                lead_correction = d_ata_now * K10_LOOKAHEAD_S
                target_b = rel_b + sign * lead_correction
                hdg = max(0, min(8, 4 + int(round(np.clip(target_b / 22.5 * K10_AGGR, -4, 4)))))
                return (2, hdg, 3), "K10_MERGE_LEAD"

    # === K9 — tracking lock + bin rate-limit (P3, K_STALEMATE_DESIGN C-2) ===
    # 조건: ATA<25 + 직전 5 tick ATA 하강 추세 + 500<dist<3000 (WEZ 진입 직전)
    # action: lead pursuit soft-lock — hdg=rel_b 추종 BUT ±1 bin/tick rate-limit
    #         + vel=2 (corner) 고정 + alt 유지 → jitter 차단 → fire-window 안정.
    # K_STALEMATE_DESIGN C-2: defensive 139ft 진입했으나 hdg 0↔8 jitter 로 추적 실패.
    # K9 가 K8 active 시 비활성 (충돌 방지)
    k8_active = state.k8_phase != "off"
    if "K9" in enabled_ks and not k8_active:
        if state.k9_phase == "lock":
            state.k9_phase_tick += 1
            # 종료: 10 tick 또는 ATA 정렬 깨짐
            if state.k9_phase_tick >= 10 or ata >= 30:
                state.k9_phase = "off"
                state.k9_phase_tick = 0
                state.k9_cooldown = 30
            else:
                # 목표 hdg = rel_b 기반 lead
                target_hdg = max(0, min(8, 4 + int(round(np.clip(rel_b / 22.5, -4, 4)))))
                # rate-limit: prev_hdg 와 ±1 bin 이내
                delta = max(-1, min(1, target_hdg - state.k9_prev_hdg))
                hdg = max(0, min(8, state.k9_prev_hdg + delta))
                state.k9_prev_hdg = hdg
                return (2, hdg, 2), "K9_TRACK_LOCK"
        else:
            if state.k9_cooldown > 0:
                state.k9_cooldown -= 1
            else:
                # ATA 하강 추세 감지
                recent_ata = state.ata_window[-5:] if len(state.ata_window) >= 5 else []
                ata_descending = (recent_ata and len(recent_ata) >= 5
                                   and recent_ata[-1] < recent_ata[0])
                # P3 v2: dist 조건 완화 100-3000 (defensive 139ft inner-WEZ 잡기)
                if (ata_descending and ata < 25 and 100 < dist < 3000):
                    state.k9_phase = "lock"
                    state.k9_phase_tick = 0
                    target_hdg = max(0, min(8, 4 + int(round(np.clip(rel_b / 22.5, -4, 4)))))
                    state.k9_prev_hdg = target_hdg
                    return (2, target_hdg, 2), "K9_TRACK_LOCK"

    # === K8 — corner-bleed lock (P2, K_STALEMATE_DESIGN C-1) ===
    # 조건: dist>6000 + |closure|<50 + CAS>500 + 40 tick no_dmg → high-speed neutral extension
    # 2-phase commit:
    #   bleed (20 tick lock): vel=0 + hdg=hard turn 적 방향 → corner speed 진입
    #   convert: CAS<400 후 종료 → 일반 dispatch 복귀
    if "K8" in enabled_ks:
        if state.k8_phase == "bleed":
            state.k8_phase_tick += 1
            # convert 전환: 20 tick 끝 OR CAS<400 도달
            if state.k8_phase_tick >= 20 or cas < 400:
                state.k8_phase = "off"
                state.k8_phase_tick = 0
                state.k8_cooldown = 80
            else:
                # 적 방향 hard turn + vel=0 (idle decel)
                hdg = 0 if rel_b < 0 else 8
                return (2, hdg, 0), "K8_BLEED"
        else:
            if state.k8_cooldown > 0:
                state.k8_cooldown -= 1
            elif (cas > 500 and dist > 6000 and abs(closure) < 50
                    and state.no_dmg_ticks >= 40):
                state.k8_phase = "bleed"
                state.k8_phase_tick = 0
                hdg = 0 if rel_b < 0 else 8
                return (2, hdg, 0), "K8_BLEED"

    # === K7 — dive attack (Es advantage 활용) ===
    # 조건: Es advantage > 500m AND opp_alt < our_alt - 300m
    # 우리는 opp_alt = ego_alt - alt_gap (alt_gap>0 일 때 우리가 더 높음)
    if "K7" in enabled_ks:
        if alt_gap > 1000 and ata < 60 and dist < 6000:
            # dive 직진 + vel max
            hdg = max(0, min(8, 4 + int(round(np.clip(rel_b / 22.5, -3, 3)))))
            return (0, hdg, 4), "K7_DIVE_ATTACK"

    # === K3 — cut-off linear (Pattern C, R15-K Stage1 완화) ===
    # v1: 15 tick 모두 |closure|<30 (너무 엄격, aggressive 활성화 X)
    # v2: 8 tick 평균 |closure|<50 + dist 증가 추세 + ata<30 (도주 적 catch)
    # K8 cooldown 중에는 K3 도 비활성 (K8 진행 완료 후 K3 시도)
    k8_cooldown_active = state.k8_phase != "off" or state.k8_cooldown > 0
    if "K3" in enabled_ks and not k8_cooldown_active:
        if len(state.closure_window) >= 8 and len(state.dist_window) >= 8:
            recent_cl = state.closure_window[-8:]
            recent_dist = state.dist_window[-8:]
            recent_alt_gap = state.alt_gap_window[-8:]
            slope_dist = (recent_dist[-1] - recent_dist[0]) / 7
            avg_abs_cl = sum(abs(c) for c in recent_cl) / 8
            if (avg_abs_cl < 50 and dist > 3000
                    and slope_dist > 20 and all(abs(ag) < 500 for ag in recent_alt_gap)
                    and ata < 30):
                # cut-off path: 적 lead 방향으로 hdg adjust + max throttle
                hdg = max(0, min(8, 4 + int(round(np.clip(rel_b / 22.5, -3, 3)))))
                return (2, hdg, 4), "K3_CUT_OFF_LINEAR"

    # === K1 — vertical asym break (Pattern A/A' stalemate) ===
    # 조건: |alt_gap| < 200ft + 50 tick stalemate (no dmg)
    if "K1" in enabled_ks:
        if state.k1_phase == "climb":
            state.k1_phase_tick += 1
            if state.k1_phase_tick >= 25:
                state.k1_phase = "dive"
                state.k1_phase_tick = 0
            return (4, 4 + int(round(np.clip(rel_b / 22.5, -2, 2))), 4), "K1_CLIMB"
        elif state.k1_phase == "dive":
            state.k1_phase_tick += 1
            if state.k1_phase_tick >= 25:
                state.k1_phase = "off"
                state.k1_phase_tick = 0
                state.k1_cooldown = 100
            return (0, 4 + int(round(np.clip(rel_b / 22.5, -2, 2))), 4), "K1_DIVE"
        else:
            if state.k1_cooldown > 0:
                state.k1_cooldown -= 1
            elif (abs(alt_gap) < 200 and state.no_dmg_ticks >= 50
                    and ego_alt > HARD_DECK_FT + 3000):
                state.k1_phase = "climb"
                state.k1_phase_tick = 0
                return (4, 4 + int(round(np.clip(rel_b / 22.5, -2, 2))), 4), "K1_CLIMB"

    # === K4 — vertical force open (Pattern B offset spiral) ===
    # 조건: 30 tick dist std 작음 + ATA mean > 60 (절대 정렬 안 됨)
    if "K4" in enabled_ks:
        if state.k4_phase == "climb":
            state.k4_phase_tick += 1
            if state.k4_phase_tick >= 40:
                state.k4_phase = "dive"
                state.k4_phase_tick = 0
            return (4, 4, 4), "K4_CLIMB"
        elif state.k4_phase == "dive":
            state.k4_phase_tick += 1
            if state.k4_phase_tick >= 15:
                state.k4_phase = "off"
                state.k4_phase_tick = 0
                state.k4_cooldown = 100
            hdg = max(0, min(8, 4 + int(round(np.clip(rel_b / 22.5, -4, 4)))))
            return (0, hdg, 4), "K4_DIVE_INTO"
        else:
            if state.k4_cooldown > 0:
                state.k4_cooldown -= 1
            elif (len(state.dist_window) >= 30 and len(state.ata_window) >= 30
                    and ego_alt > HARD_DECK_FT + 3000):
                d30 = state.dist_window[-30:]
                a30 = state.ata_window[-30:]
                dist_std = (sum((x - sum(d30)/30) ** 2 for x in d30) / 30) ** 0.5
                ata_mean = sum(a30) / 30
                if dist_std < 1500 and ata_mean > 60 and dist > 3000:
                    state.k4_phase = "climb"
                    state.k4_phase_tick = 0
                    return (4, 4, 4), "K4_CLIMB"

    # === K2 — phase shift (figure-8 mirror omega) ===
    # 조건: 40 tick stalemate + no_dmg + dist oscillation 큼
    if "K2" in enabled_ks:
        if state.k2_phase == "straight":
            state.k2_phase_tick += 1
            if state.k2_phase_tick >= 10:
                state.k2_phase = "off"
                state.k2_phase_tick = 0
                state.k2_cooldown = 80
            return (2, 4, 4), "K2_STRAIGHT"
        else:
            if state.k2_cooldown > 0:
                state.k2_cooldown -= 1
            elif (state.no_dmg_ticks >= 40 and len(state.dist_window) >= 30
                    and dist > 2000):
                d30 = state.dist_window[-30:]
                dist_amp = max(d30) - min(d30)
                if dist_amp > 4000:
                    state.k2_phase = "straight"
                    state.k2_phase_tick = 0
                    return (2, 4, 4), "K2_STRAIGHT"

    return None, None  # 아무 K도 활성 안 됨


# ────────────────────────────────────────────────────────────────
# Adaptive bin modulation — engine threshold-anchored 후처리
# (custom_actions.py 의 adaptive_bin_modulation 와 동일 원칙)
# ────────────────────────────────────────────────────────────────


def adaptive_post(alt: int, hdg: int, vel: int, f: dict) -> tuple[int, int, int]:
    """branch action 출력의 engine-threshold-anchored 미세 조정."""
    ata = f["ata"]
    dist = f["dist"]
    ego_alt = f["ego_alt"]
    closure = f["closure_kts"]
    overshoot = f["overshoot_risk"]

    # 1. Hard Deck buffer (절대 우선)
    if ego_alt < HARD_DECK_FT + 400.0:
        if alt < 3:
            alt = 3
        return _bin_clip(alt, hdg, vel)

    # 2. Overshoot 감지 시 강제 감속
    if overshoot or (closure > 100.0 and ata < 25.0 and dist < 2200.0):
        if vel > 1:
            vel = 1

    # 3. WEZ in + ata<12 → hdg lock + vel 보존
    if WEZ_MIN_FT <= dist <= WEZ_MAX_FT and ata < WEZ_ATA_MAX_DEG:
        if abs(hdg - 4) <= 1:
            hdg = 4
        if vel < 2:
            vel = 2

    # 4. ATA 작음 (<20) + in 39 line → jitter 제거
    elif ata < 20.0 and f["in_39"]:
        if abs(hdg - 4) == 1:
            hdg = 4

    return _bin_clip(alt, hdg, vel)


# ────────────────────────────────────────────────────────────────
# Custom Action — SPA pipeline
# ────────────────────────────────────────────────────────────────


class CostBasedBranchSelector(py_trees.behaviour.Behaviour):
    """v11_code 분기 + MPC cost components + SPA framework.

    매 tick:
      1. Sense — obs + obs_history 갱신
      2. Plan  — 11 branch cost 평가 (multi-component) + common_threat 추가 + argmin
      3. Act   — 선택 branch action → adaptive_bin_modulation → blackboard

    v3.10 (2026-05-27, 사용자 통찰): branch-level CSV trace (env: BRANCH_CSV).
    각 tick 의 (branch, cost, all sense, all branch costs) 기록 → 매치 후 분석.
    """
    def __init__(self, name: str = "CostBasedBranchSelector",
                 hard_deck_threshold_ft: float = 1500.0):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="action", access=py_trees.common.Access.WRITE)
        self.hard_deck_threshold_ft = float(hard_deck_threshold_ft)
        self._obs_history: deque = deque(maxlen=HISTORY_LEN)
        self._last_branch = "INIT"
        self._branch_tick = 0
        # v3.28: sticky situation (latched at spawn, no re-detect to avoid flicker)
        self._situation: str = "unknown"
        # v3.10 trace CSV
        self._csv_path = os.environ.get("BRANCH_CSV", "")
        self._csv_file = None
        self._csv_tick = 0
        # v3.26 spawn-tick counter (forced engagement 시 사용)
        self._spawn_tick = 0
        # R15-J8 K1-K7 state machine
        self._k_state = _KState()
        self._last_action_cached = [2, 4, 2]

    def _maybe_log_sub_dispatch(self, f: dict, sub_sit: str,
                                  alt_d: int, hdg_d: int, vel_d: int):
        """R15-G3: sub-situation dispatch 가 활성화될 때 BRANCH_CSV 에 기록."""
        if not self._csv_path:
            return
        # 첫 호출 시 헤더 init 위해 placeholder row 작성 (실제 row 는 cost-path 와 동일 포맷)
        if self._csv_file is None:
            from pathlib import Path as _P
            _P(self._csv_path).parent.mkdir(parents=True, exist_ok=True)
            self._csv_file = open(self._csv_path, "w", encoding="utf-8")
            branch_names = [b[0] for b in BRANCHES if b[0] != "HardDeck"]
            cols = (["tick", "chosen", "min_cost",
                     "ata", "aa", "dist", "closure", "ed", "alt_gap",
                     "pos_adv", "R_us", "R_opp", "R_adv", "om_us", "om_opp",
                     "d_ata", "d_aa", "d_pos", "d_es", "ego_alt",
                     "alt_b", "hdg_b", "vel_b"]
                    + [f"c_{n}" for n in branch_names])
            self._csv_file.write(",".join(cols) + "\n")
            self._csv_tick = 0
        row = [self._csv_tick, f"SUB_{sub_sit}", "0.000",
               f"{f['ata']:.1f}", f"{f['aa']:.1f}", f"{f['dist']:.0f}",
               f"{f['closure_kts']:.0f}", f"{f['energy_diff_ft']:.0f}",
               f"{f.get('alt_gap_ft', 0):.0f}",
               f"{f['pos_adv']:.1f}", f"{f['R_us_ft']:.0f}",
               f"{f.get('R_opp_ft', 0):.0f}", f"{f.get('R_advantage_ft', 0):.0f}",
               f"{f['turn_rate']:.2f}", f"{f.get('omega_opp_degs', 0):.2f}",
               f"{f['d_ata']:.2f}", f"{f.get('d_aa', 0):.2f}",
               f"{f.get('d_pos', 0):.2f}", f"{f.get('d_es', 0):.2f}",
               f"{f['ego_alt']:.0f}", alt_d, hdg_d, vel_d]
        # 나머지 branch cost 칸은 빈 값 (dispatch 가 cost 계산 안 함)
        branch_names = [b[0] for b in BRANCHES if b[0] != "HardDeck"]
        row.extend(["" for _ in branch_names])
        self._csv_file.write(",".join(str(v) for v in row) + "\n")
        self._csv_file.flush()
        self._csv_tick += 1

    def update(self) -> py_trees.common.Status:
        global obs_current, obs_history_global

        obs = self.blackboard.observation
        if obs is None:
            self.blackboard.action = [2, 4, 2]
            return py_trees.common.Status.SUCCESS

        # === Sense ===
        self._obs_history.append(dict(obs))
        obs_current = obs
        obs_history_global = self._obs_history
        f = compute_features(obs, self._obs_history)
        self._spawn_tick += 1

        # v3.26 spawn forced — env var 통해 활성 (default OFF, 회귀 인지).
        if (os.environ.get("SPAWN_FORCED_ENGAGE", "0") == "1"
                and self._spawn_tick <= 20
                and f["ego_alt"] > self.hard_deck_threshold_ft):
            rel_b = float(obs.get("relative_bearing_deg", 0.0))
            hdg = 4 if abs(rel_b) < 8.0 else 4 + int(round(np.clip(rel_b / 22.5, -4, 4)))
            alt_gap = float(obs.get("alt_gap_ft", 0.0))
            alt = 2 if abs(alt_gap) < 500 else (3 if alt_gap > 0 else 1)
            self.blackboard.action = [int(np.clip(alt, 0, 4)),
                                       int(np.clip(hdg, 0, 8)), 4]
            self._last_branch = "SPAWN_FORCE"
            self._branch_tick = self._spawn_tick
            return py_trees.common.Status.SUCCESS

        # === R15-J8 K1-K7 STATE MACHINE DISPATCH (action override, highest priority) ===
        # K 가설 누적 적용 — 시각화 진단 기반.
        _k_update_windows(self._k_state, obs, f)
        # no_dmg stalemate 카운트 (간단히 spawn_tick 으로 근사 — 실제 HP는 없음)
        # 더 정확히는 inject_match_state 의 ego_damage_dealt 활용 가능
        self._k_state.no_dmg_ticks = self._spawn_tick
        # 사용 K env 변수 — default K2 only (R15-J12 noise 분석 결과 best net +75.9)
        # ablation (R15-J10): K4 역효과, K5 high-variance, K1 catch 많지만 taken 큼
        # noise (R15-J12): K2 통계적 best, K3 mean +67.2 ≈ NONE
        _ks_env = os.environ.get("R15_J8_KS", "K2,K8,K10,K11")
        enabled_ks = set(s.strip() for s in _ks_env.split(",") if s.strip())

        if f["ego_alt"] > self.hard_deck_threshold_ft + 1500:
            k_override, k_tag = _k_apply_dispatch(
                self._k_state, f, obs, self._last_action_cached, enabled_ks
            )
            if k_override is not None:
                alt_d, hdg_d, vel_d = k_override
                action_out = [int(np.clip(alt_d, 0, 4)),
                              int(np.clip(hdg_d, 0, 8)),
                              int(np.clip(vel_d, 0, 4))]
                self.blackboard.action = action_out
                self._last_action_cached = action_out
                self._last_branch = k_tag
                self._branch_tick += 1
                if self._csv_path:
                    self._maybe_log_sub_dispatch(f, k_tag, *action_out)
                return py_trees.common.Status.SUCCESS

        # === R15-I HYPOTHESIS TESTS (각 격리 if-then, 대규모 cost bias) ===
        # 각 가정 별로 격리된 조건 분기. 활성화 시 sub-situation dispatch 우회 + cost loop 강제.
        hypothesis_bias = {}
        hypothesis_tag = None  # CSV/log 용
        sub_sit_now = _detect_sub_situation(f)
        cur_closure = float(f.get("closure_kts", 0.0))
        cur_dist = float(f.get("dist", 99999))

        # === K6 — corner speed lock-in (cost bias) ===
        # 조건: |CAS - 450| > 100 + Lufbery/NeutralMerge
        if os.environ.get("R15_J8_K6", "1") == "1":
            cur_cas = float(obs.get("ego_vc_kts", 400.0))
            if sub_sit_now in ("Lufbery", "NeutralMerge") and abs(cur_cas - 450) > 100:
                # cost bias for OffensivePursuit (uses vel naturally) + tail chase
                hypothesis_bias["TailChaseVertical"] = -50.0  # corner speed maintaining branch
                if hypothesis_tag is None:
                    hypothesis_tag = "K6_CORNER_SPEED"

        # --- H1: HOM + high closure (>400 kts) → GunEngagement 대규모 cost 감소 ---
        # 가정: HOM 빠른 closure window 에서 부드러운 lead-turn 부족. 격렬한 gun shot 필요.
        # 결과 (2026-05-29): 변화 없음. 비활성 (env var override 가능).
        if os.environ.get("R15_H1_ENABLED", "0") == "1":
            if sub_sit_now == "HOM" and cur_closure > 400:
                hypothesis_bias["GunEngagement"] = -100.0
                hypothesis_bias["GunTracking"] = -100.0
                hypothesis_bias["GunSnapshot"] = -50.0
                hypothesis_tag = "H1_HOM_FAST"

        # --- H2: MUTUAL_EXTEND (분리 중) → CutoffPursuit / ForceEngageBT 대규모 cost 감소 ---
        # 가정: head-on 후 양쪽 분리 시 cost framework 가 Extension 선호. 강제 추격 cost 로 catch.
        # 결과 (2026-05-29): 거의 변화 없음 (CutoffPursuit action 본질적 catch 한계). 비활성.
        if os.environ.get("R15_H2_ENABLED", "0") == "1" and len(self._obs_history) >= 30:
            recent_closures = [float(r.get("closure_rate_kts", 0.0))
                               for r in list(self._obs_history)[-30:]]
            avg_recent_cl = sum(recent_closures) / len(recent_closures)
            if avg_recent_cl < -80 and cur_dist > 2500:
                hypothesis_bias["CutoffPursuit"] = -100.0
                hypothesis_bias["ForceEngageBT"] = -100.0
                hypothesis_bias["InitPursuitAccel"] = -50.0
                hypothesis_tag = "H2_MUTUAL_EXTEND"

        # --- H3: 좋은 정렬 + WEZ 거리 → GunEngagement 대규모 cost ---
        # 가정: ata<20 + 700<dist<3000 (WEZ 안 좋은 정렬) 일 때 GunEngagement -200 강제.
        # 결과: simple +1.4 / ace -1.9. 매우 약한 영향. 비활성.
        cur_ata = abs(float(f.get("ata", 999)))
        if os.environ.get("R15_H3_ENABLED", "0") == "1":
            if cur_ata < 20 and 700 < cur_dist < 3000:
                hypothesis_bias["GunEngagement"] = -200.0
                hypothesis_bias["GunTracking"] = -200.0
                hypothesis_bias["GunEnvelope"] = -150.0
                hypothesis_tag = "H3_GOOD_ALIGN_FIRE"

        # --- H6: OffensivePursuit 항상 강제 (무조건 -500) ---
        # 가정: cost framework 의 branch 자주 교체 = catch 한계. 단일 branch 무조건 commit
        #       이면 catch 가능한가? (만약 결과 동일 → OffensivePursuit action 본질적 한계)
        # 결과: MUTUAL_EXTEND 그룹 5/8 +12.1 dmg ⭐ — catch 가능! 단 ace winning (+21) 회귀.
        if os.environ.get("R15_H6_ENABLED", "0") == "1":
            hypothesis_bias["OffensivePursuit"] = -500.0
            hypothesis_tag = "H6_FORCE_OP"

        # --- H7: H6 보존 + Off_Lag 보호 (ace pattern 살림) ---
        # 가정: H6 의 +12 catch 능력은 살리고, ace 의 Off_Lag dispatch (LeadPursuit) 는 보존.
        # 결과: 너무 좁힘 — MUTUAL_EXTEND catch 대부분 손실 (HOM/Off_TC 카테고리 in catch moment).
        if os.environ.get("R15_H7_ENABLED", "0") == "1":
            if sub_sit_now not in ("Off_TailChase", "Off_Lag", "Defensive",
                                    "DefSpiral", "HOM"):
                hypothesis_bias["OffensivePursuit"] = -500.0
                hypothesis_tag = "H7_FORCE_OP_PROTECT_OFFLAG"

        # --- H8: H6 force OP + Off_Lag 만 protect (ace pattern 살림) ---
        # 가정: HOM/Off_TC 모멘트는 catch source. Off_Lag (ace pattern) 만 제외.
        # 결과: +88.9 deal (baseline 23.8 의 3.7배). ace 는 여전 0.
        if os.environ.get("R15_H8_ENABLED", "0") == "1":
            if sub_sit_now != "Off_Lag":
                hypothesis_bias["OffensivePursuit"] = -500.0
                hypothesis_tag = "H8_FORCE_OP_EXCEPT_OFFLAG"

        # --- H9: H8 + close range (dist<2500) 시 OP 비활성 (ace gun pattern 보존) ---
        # 가정: ace winning 은 close-range gun pattern. close 시 OP 강제 안 하고
        #       cost framework 자유 → GunEngagement 자연 선택.
        # 결과: deal 108 / taken 45 / net +63. v10 처음 catch +9 ⭐, v6h5b +25 큼.
        if os.environ.get("R15_H9_ENABLED", "0") == "1":
            if sub_sit_now != "Off_Lag" and cur_dist > 2500:
                hypothesis_bias["OffensivePursuit"] = -500.0
                hypothesis_tag = "H9_FORCE_OP_FAR_PROTECT_CLOSE_AND_OFFLAG"

        # --- H10: H8 base + precise WEZ moment (ata<12, dist<1500) → GunEngagement -1000 ---
        # 가정: H8 의 +88.9 deal 유지 + WEZ catch moment 에서 Gun 우선 → ace catch 가능.
        # 결과: deal 85 / taken 0.9 / net +84.5. 14/20 catch. ace 여전 0. v6h5b 0.
        if os.environ.get("R15_H10_ENABLED", "0") == "1":
            if sub_sit_now != "Off_Lag":
                hypothesis_bias["OffensivePursuit"] = -500.0
                hypothesis_tag = "H10_H8+PRECISE_WEZ_GUN"
            if cur_ata < 12 and 500 < cur_dist < 1500:
                hypothesis_bias["GunEngagement"] = -1000.0
                hypothesis_bias["GunTracking"] = -1000.0

        # --- H11: H10 + Off_TailChase/Off_Lag 시 OP protect (ace LeadPursuit 살림) ---
        # 결과: deal ~76 taken 0 net +76 (H10 -8.5).
        if os.environ.get("R15_H11_ENABLED", "0") == "1":
            if sub_sit_now not in ("Off_Lag", "Off_TailChase"):
                hypothesis_bias["OffensivePursuit"] = -500.0
                hypothesis_tag = "H11_H10+PROTECT_OFFTC"
            if cur_ata < 12 and 500 < cur_dist < 1500:
                hypothesis_bias["GunEngagement"] = -1000.0
                hypothesis_bias["GunTracking"] = -1000.0

        # R15-J: H10 (best 가설) 다시 활성화 — 시각화 분석 위해
        if os.environ.get("R15_H10_J", "1") == "1":
            if sub_sit_now != "Off_Lag":
                hypothesis_bias["OffensivePursuit"] = -500.0
                hypothesis_tag = "H10_J_BEST"
            if cur_ata < 12 and 500 < cur_dist < 1500:
                hypothesis_bias["GunEngagement"] = -1000.0
                hypothesis_bias["GunTracking"] = -1000.0

        # 가정 활성화 시 sub-situation dispatch 우회 (cost loop 가 강제됨)
        bypass_sub_dispatch = bool(hypothesis_bias)

        # R15-G3 (2026-05-29): bt_vs_bt 통합 — sub-situation 기반 if-then dispatch override.
        # 사용자 vision: us_attack/us_defend/merge 서브 행동을 bt_vs_bt 통합 BT 에 명시적 분기.
        # 각 sub-situation 의 winning action 패턴을 cost framework 보다 우선 적용.
        if f["ego_alt"] > self.hard_deck_threshold_ft + 1500 and not bypass_sub_dispatch:
            sub_sit_g3 = _detect_sub_situation(f)
            dispatch_action = _sub_situation_dispatch(f, sub_sit_g3, self._spawn_tick, obs)
            if dispatch_action is not None:
                alt_d, hdg_d, vel_d = dispatch_action
                self.blackboard.action = [int(alt_d), int(hdg_d), int(vel_d)]
                if self._last_branch == f"SUB_{sub_sit_g3}":
                    self._branch_tick += 1
                else:
                    self._last_branch = f"SUB_{sub_sit_g3}"
                    self._branch_tick = 1
                # CSV trace for sub-situation dispatch
                if self._csv_path:
                    self._maybe_log_sub_dispatch(f, sub_sit_g3, alt_d, hdg_d, vel_d)
                return py_trees.common.Status.SUCCESS

        # === Plan ===
        # 1. HardDeck — hard override (cost 비교 bypass)
        all_costs = {}
        if f["ego_alt"] < self.hard_deck_threshold_ft:
            alt, hdg, vel = action_hard_deck(f)
            chosen, min_cost = "HardDeck", -1e6
        else:
            # 2. 다른 branch cost 비교 + common threat + stuck penalty
            threat = common_threat_cost(f)
            # v3.16 thr=60 stuck-penalty
            # R15-I H5 (2026-05-29): stuck_penalty 비활성 옵션 — 한 branch 오래 commit 시 catch.
            stuck_penalty = 0.0
            if os.environ.get("R15_H5_ENABLED", "1") != "1":
                if self._branch_tick > 35:
                    stuck_penalty = min(2.36, (self._branch_tick - 35) / 50.0)
            extra_stuck = 0.0
            opp_bias = {}
            # R15-I: hypothesis bias 주입 (sub-situation dispatch 우회 시)
            for bn, b in hypothesis_bias.items():
                opp_bias[bn] = opp_bias.get(bn, 0.0) + b

            # v3.20 NEW: tactical_lookup.json 활용 (사용자 통찰 2026-05-27)
            # 과거 mine_tactical_patterns → counter_table → tactical_lookup 의 data-driven
            # knowledge (112 state cells, 63 high-quality wr>=0.9). 우리 cost 에 통합.
            lookup_bias = _tactical_lookup_bias(f, os.environ.get("ADVERSARY", "").lower())
            for bn, b in lookup_bias.items():
                opp_bias[bn] = opp_bias.get(bn, 0.0) + b

            # v3.27 NEW (2026-05-28): situation_state_lookup.json — opp-independent.
            # GA hypotheses + tactical_lookup 통합. 모든 opp (aggressive/defensive 외) 대응.
            # v3.27 hook DISABLED 2026-05-28: verify 결과 (R2 245 → R2+hook 98)
            # base 4 에 강한 negative effect. tactical_lookup 이 adaptive_eagle BT 결정
            # 기반이라 우리 cost_branch 와 충돌. 데이터 fresh 후 재고려.
            # sit_bias = _situation_lookup_bias(f, min_confidence=0.7)
            # for bn, b in sit_bias.items():
            #     opp_bias[bn] = opp_bias.get(bn, 0.0) + b

            # v3.28-v3.29 (2026-05-28): on_to_on / chase 상황 분리 — 사용자 vision.
            # "글로벌 single 강화 trade-off 못 풀음 → 상황별 cost 함수 / if-then 분기"
            # Dynamic (flicker) detection: verify 240 vs sticky 207 — flicker 우세.
            # Multiplier 는 cost loop 안에서 branch_name 별 적용 (아래).
            sit_now = _detect_situation(f, list(self._obs_history))
            # legacy boost (gun) — situation multiplier 와 함께 작동 가능
            if sit_now == "on_to_on":
                opp_bias["GunEngagement"] = opp_bias.get("GunEngagement", 0.0) - 3.0

            # v3.25: state-based dynamic SmartX dispatch
            # 매 tick state_key + opp → counter_v4 high-quality (wr>=0.95, n>=50) 추천 시
            # *우리 branch 무시* + 추천 SmartX 직접 실행. high-confidence 자동 적용.
            dyn_smart_action = None
            opp_name_v25 = os.environ.get("ADVERSARY", "").lower()
            if opp_name_v25 in ("aggressive", "defensive"):
                try:
                    from examples.pursuit_chase_v1.nodes import _counter_v4_loader as _cv4
                    sk = _state_key(f["ata"], f["dist"], f["closure_kts"], f["energy_diff_ft"])
                    rec = _cv4.best_for(sk, opp_name_v25, min_wr=0.85, min_n=20)
                    if rec is not None:
                        node = rec["node"]
                        if node == "SmartLowYoYo":
                            dyn_smart_action = action_smart_lowyoyo(f)
                        elif node == "SmartLagPursuit":
                            dyn_smart_action = action_smart_lag(f)
                        elif node == "SmartHighYoYo":
                            dyn_smart_action = action_smart_highyoyo(f)
                        elif node == "HeadOnBreak":
                            dyn_smart_action = action_smart_breakturn(f)
                        elif node == "ExtensionBreak":
                            dyn_smart_action = action_extension(f)
                        elif node == "LeadPursuit":
                            dyn_smart_action = action_smart_lead(f)
                        elif node == "Accelerate":
                            dyn_smart_action = action_extension(f)
                except Exception:
                    pass
            for bname, cost_fn, _ in BRANCHES:
                if cost_fn is None:
                    continue
                try:
                    c_raw = cost_fn(f)
                    c_situ = _apply_situation_multiplier(bname, c_raw, sit_now)
                    # v3.38 sub-situation if-then dispatch (사용자 vision)
                    # 7 sub-situations × per-branch boost (HOM/Off_TailChase/Off_Lag/Lufbery/DefSpiral)
                    sub_boost = _apply_sub_situation_boost(f, bname)
                    c_sub = c_situ * sub_boost
                    c_pursuit = cost_pursuit_curve_select(f, bname)
                    c_counter = cost_counter_defense(f, bname)
                    c = c_sub + c_pursuit + c_counter + threat
                    if bname == self._last_branch:
                        c += stuck_penalty + extra_stuck
                    if bname in opp_bias:
                        c += opp_bias[bname]
                    all_costs[bname] = c
                except Exception:
                    all_costs[bname] = 999.0
            chosen = min(all_costs, key=lambda k: all_costs[k])
            min_cost = all_costs[chosen]
            action_fn = dict((n, fn) for n, _, fn in BRANCHES)[chosen]
            alt, hdg, vel = action_fn(f)
            # v3.25: dynamic SmartX override (high-confidence)
            if dyn_smart_action is not None:
                alt, hdg, vel = dyn_smart_action
                chosen = f"DYN_{chosen}"

        # === Act ===
        # v3.8.2 fix: adaptive_post 변경이 회귀 야기 → 최소 안전망만 (Hard Deck buffer)
        if f["ego_alt"] < HARD_DECK_FT + 400.0 and alt < 3:
            alt = 3

        # tracking + trace
        if chosen == self._last_branch:
            self._branch_tick += 1
        else:
            self._last_branch = chosen
            self._branch_tick = 1

        if os.environ.get("COST_BRANCH_LOG", "") and (self._branch_tick <= 3 or self._branch_tick % 30 == 0):
            logger.warning(
                f"[BRANCH={chosen} cost={min_cost:+.2f} t={self._branch_tick}] "
                f"ata={f['ata']:.0f} aa={f['aa']:.0f} dist={f['dist']:.0f} "
                f"cl={f['closure_kts']:+.0f} ed={f['energy_diff_ft']:+.0f} "
                f"d_ata={f['d_ata']:+.1f} d_pos={f['d_pos']:+.1f} bin=({alt},{hdg},{vel})")

        # v3.10 CSV trace (env: BRANCH_CSV=path/to/file.csv) — 분석용
        if self._csv_path:
            if self._csv_file is None:
                from pathlib import Path as _P
                _P(self._csv_path).parent.mkdir(parents=True, exist_ok=True)
                self._csv_file = open(self._csv_path, "w", encoding="utf-8")
                # header: tick, chosen, min_cost, sense values, per-branch costs
                branch_names = [b[0] for b in BRANCHES if b[0] != "HardDeck"]
                cols = (["tick", "chosen", "min_cost",
                         "ata", "aa", "dist", "closure", "ed", "alt_gap",
                         "pos_adv", "R_us", "R_opp", "R_adv", "om_us", "om_opp",
                         "d_ata", "d_aa", "d_pos", "d_es", "ego_alt", "alt_b", "hdg_b", "vel_b"]
                        + [f"c_{n}" for n in branch_names])
                self._csv_file.write(",".join(cols) + "\n")
                self._csv_tick = 0
            alt_gap_obs = float(obs.get("alt_gap_ft", 0.0))
            row = [self._csv_tick, chosen, f"{min_cost:.3f}",
                   f"{f['ata']:.1f}", f"{f['aa']:.1f}", f"{f['dist']:.0f}",
                   f"{f['closure_kts']:.0f}", f"{f['energy_diff_ft']:.0f}",
                   f"{alt_gap_obs:.0f}",
                   f"{f['pos_adv']:.1f}", f"{f['R_us_ft']:.0f}",
                   f"{f.get('R_opp_ft', 0):.0f}", f"{f.get('R_advantage_ft', 0):.0f}",
                   f"{f['turn_rate']:.2f}", f"{f.get('omega_opp_degs', 0):.2f}",
                   f"{f['d_ata']:.2f}", f"{f.get('d_aa', 0):.2f}",
                   f"{f['d_pos']:.2f}", f"{f['d_es']:.1f}",
                   f"{f['ego_alt']:.0f}", alt, hdg, vel]
            branch_names = [b[0] for b in BRANCHES if b[0] != "HardDeck"]
            for bn in branch_names:
                row.append(f"{all_costs.get(bn, 999):.3f}")
            self._csv_file.write(",".join(str(v) for v in row) + "\n")
            self._csv_file.flush()
            self._csv_tick += 1

        action_out = [int(alt), int(hdg), int(vel)]
        self.blackboard.action = action_out
        self._last_action_cached = action_out
        return py_trees.common.Status.SUCCESS
