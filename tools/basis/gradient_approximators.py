"""BFM 정리별 ∇V_i Closed-Form Gradient Approximators.

본 모듈은 PURSUIT_CHASE_PLAN.md §2.3 의 식들을 직접 구현한다.
각 함수는 6D state x = (Δx, Δy, Δh, Δψ, V_p, V_e) 입력 → (V_i, ∇V_i) 출력.

정책 합성:
  ∇V_approx(x) = Σ τ_i(x) · ∇V_i(x) + τ_0(x) · ∇V_PN(x)

u_p* = -sign(B_d(x)^T · ∇V_approx(x)) · u_max(V_p, alt)

검증 (R5 정적 분석):
  G1_a (PN):     canonical IC 에서 u_ω* 가 적 방향
  G1_b (Corner): V_p > V_c → 감속, V_p < V_c → 가속
  G1_c (Yo-yo):  Δh > -1500 → climb, Δh < -1500 → dive
  G1_d (LDT):    Phase 1 에서 lag target 으로
  G1_e (조합):    모든 ∇V_i 가 numerical FD 와 ≤ 1% 정합
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np

# envelope (V_corner 등) 의존
from . import envelope_f16 as env


# ═══════════════════════════════════════════════════════════════════
# 상수 (PLAN §2.3 의 d_WEZ_star 등)
#
# [2026-05-17 정정] core 검증:
#   core (src/control/health_manager.py) 의 damage 공식 = 25 × (3000-d)/2500 × (1-ata/12).
#   즉 *damage 는 dist=500ft 에서 최대* (선형 감소, sweet spot 없음).
#   이전 가정 "WEZ 중심 1750ft" 는 *우리 BT 의 *policy choice*** 였음 (game rule 아님).
#   현재 1750ft 유지 이유: (a) collision 안전 margin, (b) overshoot 회피, (c) policy 변경 시
#   R7 회귀 위험 — 변경하려면 R5 검증 필요. 이 값은 *config*, *core 룰 아님*.
# ═══════════════════════════════════════════════════════════════════

WEZ_CENTER_FT = 1750.0     # *policy* target distance (core damage 최대는 500ft, 우리는 safety margin)
WEZ_HALF_WIDTH_FT = 1250.0  # WEZ 절반 폭 (V_dist 정규화 scale)
LAMBDA_DIST = 1.0 / (WEZ_HALF_WIDTH_FT ** 2)  # ≈ 6.4e-7. dist err=1250ft → V_dist=0.5
ALT_GAP_TARGET_FT = 1500.0  # yo-yo Phase 1 climb 목표 (적 대비 -1500ft = 우리 위)
LDT_LAG_OFFSET_DEG = 90.0   # Lag pursuit target offset

# Smooth saturation reference scales (R3 fix — bang-bang 회피)
# 각 BtG 채널의 "전형적 크기" — 이 값에서 u_max 도달. 작으면 비례 감소.
ALT_GAP_REF_FT = 1500.0           # yo-yo target alt_gap 과 동일 scale
V_CORNER_DELTA_REF_KTS = 50.0     # V_p 와 V_c 차이의 typical scale (envelope §2.2)

# Stage-2 model fix: speed objective 의 dist-regime 분기 (도망자 추격 vs WEZ station-keep)
WEZ_OUTER_FT = 3000.0          # 이 안 → V_e 매칭 (station-keep, Stage-1)
SPRINT_DIST_SCALE = 5000.0     # 이만큼 더 멀어지면 full sprint
V_SPRINT_KTS = 420.0           # envelope V_max. 480 시도시 도달불가 속도 추구로 양 상대 regress.

# 1-circle / 2-circle regime (정리 6, Shaw 1985) — RT-2
SIGMA_REGIME_WIDTH_RAD = math.radians(20.0)   # σ_1c/σ_2c transition 폭 (PLAN §2.6.3)
HCA_1C_CENTER_RAD = math.radians(90.0)        # σ_1c = sigmoid((90° - HCA)/20°)
HCA_2C_CENTER_RAD = math.radians(120.0)       # σ_2c = sigmoid((HCA - 120°)/20°)
_R_MIN_CACHE: dict = {}                       # alt_ft → min_V turn_radius (RT-2)


def _sig(z: float) -> float:
    """numerical-safe sigmoid."""
    if z > 30.0:
        return 1.0
    if z < -30.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


# ═══════════════════════════════════════════════════════════════════
# 정리 2 — Proportional Navigation, V_advantage 통합형 (PLAN §2.5)
#   V_adv = ½·ATA² + ½·(π - AA)² + ½·λ_d·(dist - d_WEZ*)²
# ═══════════════════════════════════════════════════════════════════

def grad_V_PN(x: np.ndarray, V_c_kts: float = 438.6) -> Tuple[float, np.ndarray]:
    """V_advantage closed-form ∇V — 유분리 + 공격 + 코너속도 통합 (PLAN §2.5).

    V_adv = ½·ATA² + ½·(π - AA)² + ½·λ_d·(dist - d_WEZ*)² + ½·λ_V·(V_p - V_c)²

    여기서:
      ATA = atan2(Δx, Δy) — 우리 nose vs LOS 각
      cos(AA) = -(Δx sin(Δψ) + Δy cos(Δψ)) / dist — 적 nose vs (적→우리) LOS 각
      V_c = 코너속도 (alt 함수, §2.2 envelope)

    유리한 끝점: ATA=0 ∧ AA=π ∧ dist=d_WEZ ∧ V_p=V_c.

    R3.1 update: V_p 추격 항 통합 — Boyd 정리 5 가 baseline 에 흡수. vel_bin 의 quantize
    가 의미 있는 값 산출 (이전: BtG_a=0 → vel 항상 hold).

    Args:
        x = (Δx, Δy, Δh, Δψ, V_p, V_e)  [ft, ft, ft, rad, kts, kts]
        V_c_kts: 코너속도. caller 가 alt 따라 envelope 에서 계산해 전달.
    """
    dx, dy, dh, dpsi, V_p, V_e = x

    # 기본 양들
    r_xy_sq = dx*dx + dy*dy + 1e-9
    dist = math.sqrt(r_xy_sq + dh*dh) + 1e-9
    ata = math.atan2(dx, dy)   # 수평 aim 각 ∈ (-π, π]
    # Stage-1 model fix (abstraction gap): 3D ATA — 수직 aim 각 추가.
    # 기존 모델은 atan2(dx,dy) 수평각만 → 고도차 dh 있으면 "조준됨" 오판
    # (SDK ATA 는 3D). dh>0 = 적 위 → pitch up 필요. 이 항이 gamma 채널 구동.
    r_xy = math.sqrt(r_xy_sq)
    ata_vert = math.atan2(dh, r_xy)   # elevation 각 ∈ (-π/2, π/2)
    r3d_sq = r_xy_sq + dh * dh

    # AA — adversary nose alignment toward us
    s_psi = math.sin(dpsi)
    c_psi = math.cos(dpsi)
    N = dx * s_psi + dy * c_psi
    cos_AA = max(-1.0, min(1.0, -N / dist))
    AA = math.acos(cos_AA)
    # numerical-safe sin(AA) — AA boundary (0 or π) 에선 ∂AA/∂· 발산 → clip
    sin_AA = max(math.sin(AA), 1e-6)

    # V_adv components
    dist_err = dist - WEZ_CENTER_FT
    # Stage-1 model fix (abstraction gap): m_2 (PN gun-tracking) 의 speed objective 는
    # V_corner 가 아니라 V_e (적 속도) 매칭 — closure→0 으로 WEZ 안에 station-keep.
    # 기존 (V_p-V_c)² 는 corner-speed(선회속도)로 끌어 WEZ 를 통과(overshoot)시키는
    # 근본 결함. corner-speed 추적은 m_4 corner mode 가 담당. 이로써 그동안 모델이
    # 무시하던 V_e state 변수(x[5]) 가 value function 에 편입됨.
    # Stage-2 model fix: speed objective 는 dist-regime 의존.
    # 근거리(≤WEZ_OUTER) → V_e 매칭 (station-keep, Stage-1). 원거리 → V_sprint 추격.
    # (V_p-V_e)² 만으론 원거리에서 도망자 속도에 capped → 못 따라잡음 (vs defensive 진단).
    sprint_frac = min(1.0, max(0.0, (dist - WEZ_OUTER_FT) / SPRINT_DIST_SCALE))
    V_target = V_e + (V_SPRINT_KTS - V_e) * sprint_frac
    V_err = V_p - V_target
    # ∂V_target/∂dist (clip 선형 구간에서만 nonzero)
    if WEZ_OUTER_FT < dist < WEZ_OUTER_FT + SPRINT_DIST_SCALE:
        dVtarget_ddist = (V_SPRINT_KTS - V_e) / SPRINT_DIST_SCALE
    else:
        dVtarget_ddist = 0.0
    LAMBDA_V = 1.0 / (V_CORNER_DELTA_REF_KTS ** 2)   # 속도 오차 normalize

    # AA mask α — (iv) AA-self-gated 시도 (2026-05-15) REVERTED:
    #   진단: V_aa 의 ω 채널 신호는 sound 하나, simple/defensive/aggressive 매치 IC 가
    #   beam (AA=π/2) → α=σ(0)=0.5 → V_aa 가 V_ATA 의 LOS-aligning ω 와 충돌 →
    #   net turn-away (R5 결과: 3 상대 모두 DRAW 100/100, simple 6W→1D 회귀).
    #   Z3 L_AA1 (AA<π/8 보호) 는 *deep* head-on 만 — 매치 IC 의 *beam* 분포 보호 못 함.
    #   다음 후보: (B2) AA-gate ∧ ATA-aligned-gate 결합 (simple 시작의 ATA=π/2 도 차단).
    alpha_aa = 0.0
    d_alpha_dVp = 0.0; d_alpha_dVe = 0.0; d_alpha_dr = 0.0

    V_ata = 0.5 * ata * ata + 0.5 * ata_vert * ata_vert   # 수평 + 수직 aim (3D ATA)
    V_aa = alpha_aa * 0.5 * (math.pi - AA) * (math.pi - AA)
    V_dist = 0.5 * LAMBDA_DIST * dist_err * dist_err
    V_speed = 0.5 * LAMBDA_V * V_err * V_err

    # (C) V_T additive 시도 REVERTED — magnitude 함정:
    #   V_T 의 ω 기여 ~2400 (B·V_e·∂cos_AA/∂Δψ) vs V_ATA ~1.57 → V_T 가 1500× dominate.
    #   simple/defensive/aggressive 모두 DRAW 100/100 (Stage-1 6W → 1D 회귀, 직접 측정).
    # 다음 경로: V_T 를 V_PN 안이 아니라 *별도 mode m_T* 로 (τ_T 가중치 + closure gate).
    # grad_V_Tcap 함수는 유지 — optimal_control 의 m_T 호출에서 사용.
    V = V_ata + V_aa + V_dist + V_speed

    # ∂ATA_horiz/∂(Δx, Δy)
    dATA_dx = dy / r_xy_sq
    dATA_dy = -dx / r_xy_sq
    # ∂ATA_vert/∂(Δx, Δy, Δh) — 수직 aim 각 (Stage-1 3D ATA)
    dATAv_dx = -dh * dx / (r3d_sq * r_xy)
    dATAv_dy = -dh * dy / (r3d_sq * r_xy)
    dATAv_dh = r_xy / r3d_sq

    # ∂dist/∂(Δx, Δy, Δh)
    ddist_dx = dx / dist
    ddist_dy = dy / dist
    ddist_dh = dh / dist

    # ∂(cos AA)/∂· — chain rule
    # cos_AA = -N/dist where N = dx·s_ψ + dy·c_ψ
    d_cosAA_dx = -s_psi / dist + N * dx / (dist**3)
    d_cosAA_dy = -c_psi / dist + N * dy / (dist**3)
    d_cosAA_dh = N * dh / (dist**3)
    d_cosAA_dpsi = -(dx * c_psi - dy * s_psi) / dist

    # Chain rule: ∂(α·½(π-AA)²)/∂· = α·(π-AA)/sin_AA·∂cos_AA/∂· (α 가 AA-무관 시)
    factor_AA = alpha_aa * (math.pi - AA) / sin_AA
    half_aa_sq = 0.5 * (math.pi - AA) * (math.pi - AA)

    # V_speed 의 dist-coupling: ∂V_speed/∂dist = λ_V·V_err·(-dVtarget_ddist)
    speed_dist = -LAMBDA_V * V_err * dVtarget_ddist
    grad = np.array([
        ata * dATA_dx + ata_vert * dATAv_dx + factor_AA * d_cosAA_dx
            + (LAMBDA_DIST * dist_err + d_alpha_dr * half_aa_sq) * ddist_dx
            + speed_dist * ddist_dx,
        ata * dATA_dy + ata_vert * dATAv_dy + factor_AA * d_cosAA_dy
            + (LAMBDA_DIST * dist_err + d_alpha_dr * half_aa_sq) * ddist_dy
            + speed_dist * ddist_dy,
        ata_vert * dATAv_dh + factor_AA * d_cosAA_dh
            + (LAMBDA_DIST * dist_err + d_alpha_dr * half_aa_sq) * ddist_dh
            + speed_dist * ddist_dh,
        factor_AA * d_cosAA_dpsi,
        LAMBDA_V * V_err + d_alpha_dVp * half_aa_sq,         # ∂V/∂V_p
        -LAMBDA_V * V_err * (1.0 - sprint_frac) + d_alpha_dVe * half_aa_sq,  # ∂V/∂V_e
    ])

    return V, grad


# ═══════════════════════════════════════════════════════════════════
# 정리 5+6 — Boyd EM + Shaw Corner
#   V_56 = ½·(V_p - V_c(alt))²
# ═══════════════════════════════════════════════════════════════════

def grad_V_corner(x: np.ndarray, alt_ft: float = 15000.0) -> Tuple[float, np.ndarray]:
    """정리 5+6 (Boyd 1964 + Shaw 1985) 의 V_p 차원 closed-form.

    Args:
        x : 6D state
        alt_ft: 현재 고도 (V_c 가 고도 함수, §2.2)

    Returns:
        (V_56, ∇V_56) — ω/γ̇ 채널에는 영향 없음 (a 채널 전용)
    """
    _, _, _, _, V_p, _ = x
    V_c = env.V_corner_kts(alt_ft)
    err = V_p - V_c

    V = 0.5 * err * err
    grad = np.zeros(6)
    grad[4] = err   # ∂V/∂V_p = V_p - V_c
    return V, grad


# ═══════════════════════════════════════════════════════════════════
# 정리 6 (1-circle) — Shaw 1985 OneCircle mode (RT-2, PLAN §2.6.3)
#   V_3 = ½·λ_R·(R(V_p) - R_min)² + ½·σ_1c(HCA)·ATA²
# ═══════════════════════════════════════════════════════════════════

def _R_min_ft(alt_ft: float) -> float:
    """envelope 최소 선회반경 R_min = min_V R(V) at given alt — alt 별 cache.

    R(V) 는 코너속도 부근에서 최소 (aero regime 에선 ~const, struct regime 에선 ∝V²).
    """
    key = round(alt_ft, 1)
    cached = _R_MIN_CACHE.get(key)
    if cached is not None:
        return cached
    best = 1e9
    V = 160.0
    while V <= 600.0:
        R = env.turn_radius_ft(V, alt_ft)
        if R < best:
            best = R
        V += 2.0
    _R_MIN_CACHE[key] = best
    return best


def _dR_dVp(V_p: float, alt_ft: float, h: float = 0.01) -> float:
    """∂R/∂V_p — central finite difference (PLAN §2.6.3: 'numerical' 허용).

    R(V) 는 코너속도에서 kink (C1 불연속) — h 작게 (0.01 kts) 유지해 kink 회피.
    """
    R_plus = env.turn_radius_ft(V_p + h, alt_ft)
    R_minus = env.turn_radius_ft(V_p - h, alt_ft)
    return (R_plus - R_minus) / (2.0 * h)


def grad_V_1circle(x: np.ndarray, alt_ft: float = 15000.0) -> Tuple[float, np.ndarray]:
    """정리 6 (Shaw 1985 1-circle) closed-form V_3 와 ∇V_3 (PLAN §2.6.3 m_3).

    V_3 = ½·λ_R·(R(V_p) - R_min)² + ½·σ_1c(HCA)·ATA²

    1-circle 의 본질 (Shaw): 선회 반경 R 이 작은 자가 1 turn 후 적 6시 진입.
    → V_p 를 R 최소가 되는 속도로 끌고 + (HCA<90° 영역에서) ATA 정렬.

      R(V_p) = turn_radius_ft(V_p, alt)    — 현 속도 순간 선회반경 (§2.2 envelope)
      R_min  = min_V R(V)                  — envelope 최소 (≈ 코너속도)
      λ_R    = 1 / R_min²                  — R 정규화 (R_err=R_min → V_R=0.5)
      σ_1c   = sigmoid((90° - HCA) / 20°)  — HCA<90° 영역에서 활성
      HCA    = |x[3]| (dpsi, rad; obs_to_state 가 0..π unsigned 로 공급)
      ATA    = atan2(Δx, Δy)

    ∇V_3 는 ω/a 채널 모두에 영향: ATA 항 → ω (∂/∂Δx,Δy,Δψ), R 항 → a (∂/∂V_p).

    Args:
        x: 6D state (Δx, Δy, Δh, Δψ, V_p, V_e)
        alt_ft: 현재 고도 (R, R_min 이 alt 함수)

    Returns:
        (V_3, ∇V_3) — ∇V_3 shape (6,)
    """
    dx, dy, _, dpsi, V_p, _ = x
    r_xy_sq = dx * dx + dy * dy + 1e-9
    ata = math.atan2(dx, dy)

    # ─ R 항 (Shaw: 최소 선회반경 추구) ─
    R_now = env.turn_radius_ft(V_p, alt_ft)
    R_min = _R_min_ft(alt_ft)
    lambda_R = 1.0 / (R_min * R_min)
    R_err = R_now - R_min
    dR_dVp = _dR_dVp(V_p, alt_ft)

    # ─ σ_1c(HCA) — HCA<90° 활성 (PLAN §2.6.3) ─
    hca = abs(dpsi)                                  # obs_to_state: dpsi ∈ [0, π]
    sign_dpsi = 1.0 if dpsi >= 0.0 else -1.0
    sigma_1c = _sig((HCA_1C_CENTER_RAD - hca) / SIGMA_REGIME_WIDTH_RAD)
    # ∂σ_1c/∂Δψ = σ(1-σ) · ∂((90°-HCA)/δ)/∂Δψ = σ(1-σ) · (-1/δ) · ∂HCA/∂Δψ
    dsigma_ddpsi = (sigma_1c * (1.0 - sigma_1c)
                    * (-1.0 / SIGMA_REGIME_WIDTH_RAD) * sign_dpsi)

    # ─ V_3 ─
    V_R = 0.5 * lambda_R * R_err * R_err
    V_ata = 0.5 * sigma_1c * ata * ata
    V = V_R + V_ata

    # ─ ∇V_3 ─
    dATA_dx = dy / r_xy_sq
    dATA_dy = -dx / r_xy_sq

    grad = np.array([
        sigma_1c * ata * dATA_dx,             # ∂V/∂Δx  (ATA 항)
        sigma_1c * ata * dATA_dy,             # ∂V/∂Δy  (ATA 항)
        0.0,                                  # ∂V/∂Δh
        0.5 * ata * ata * dsigma_ddpsi,       # ∂V/∂Δψ  (σ_1c regime gate)
        lambda_R * R_err * dR_dVp,            # ∂V/∂V_p (R 항)
        0.0,                                  # ∂V/∂V_e
    ])
    return V, grad


# ═══════════════════════════════════════════════════════════════════
# Capture-time (Bryson-Ho ZEM) — H1 lemma 회피용 V_T (SUPERPLAN_v2 §3 후보 C)
#
#   V_T = ½·(dist − d_WEZ*)² / (closure² + C_REG²)
#   closure(x) = V_p·cos(ATA) + V_e·cos(AA)
#
# 동기: H1 lemma (verify_h1_omega_zero.py PROVED) — V_dist 의 ω·a 채널 영구 0.
# V_T 는 closure 가 V_p·V_e·Δψ 결합함수라 세 채널 모두 transmission ≠ 0.
# closure → 0 시 regularize (C_REG = 50kts) — 적이 우리만큼 빠르거나 더
# 빠르게 도망 시 V_T 가 bounded.
# ═══════════════════════════════════════════════════════════════════

D_REF_FT = 1000.0   # dist scale (typical mid-match dist 범위와 정합)
V_REF_KTS = 100.0   # closure scale (typical closing rate 분포 중심)


def grad_V_Tcap(x: np.ndarray) -> Tuple[float, np.ndarray]:
    """V_T = ½·((dist − d_WEZ*)/d_REF)² · exp(−closure / V_REF)
       — Lyapunov-type capture-time potential, sign-correct closure.

    이전 형태 V_T = (dist-d*)² / (closure² + C²) 는 *sign-blind*:
      ∂V_T/∂closure ∝ -closure → closure<0 영역에서 부호 flip → 적이 멀어지는
      중에 closure 더 음수로 만드는 *틀린 방향* 명령.

    본 형태는 항상 ∂V_T/∂closure = -V_T/V_REF < 0 → 그라디언트 반대 (정책의
    BtG_a) 항상 closure 키우는 방향. closure → +∞ 시 V_T → 0 (이미 닫힘),
    closure → -∞ 시 V_T → ∞ (강한 push). Lyapunov decay 형태.

    수학:
      s := (dist − d*) / d_REF       (dimensionless)
      c := V_p·cos_ATA + V_e·cos_AA  (kts)
      V_T = ½·s²·exp(−c/V_REF)

      ∂V_T/∂x_k = exp(−c/V_REF)·[s·∂s/∂x_k − ½·s²·∂c/∂x_k / V_REF]
                = (1/d_REF)·s·exp(−c/V_REF)·∂dist/∂x_k
                  − ½·s²/V_REF·exp(−c/V_REF)·∂c/∂x_k

    채널 transmission (H1 회피):
      ∂c/∂V_p = cos_ATA ≠ 0   ⇒ a 채널 nonzero
      ∂c/∂Δψ = V_e·∂cos_AA/∂Δψ ⇒ ω 채널 nonzero (Δψ entry)
    """
    dx, dy, dh, dpsi, V_p, V_e = x

    r_xy_sq = dx*dx + dy*dy + 1e-9
    r_xy = math.sqrt(r_xy_sq)
    dist = math.sqrt(r_xy_sq + dh*dh) + 1e-9

    # closure components (kts)
    cos_ATA = dy / r_xy
    s_psi = math.sin(dpsi)
    c_psi = math.cos(dpsi)
    N = dx*s_psi + dy*c_psi
    cos_AA = -N / dist
    closure = V_p * cos_ATA + V_e * cos_AA

    s_norm = (dist - WEZ_CENTER_FT) / D_REF_FT
    # exp(-c/V_REF) — clip 음수 closure 폭주 방지 (closure < -V_REF·30 → exp 너무 큼)
    exp_arg = -closure / V_REF_KTS
    if exp_arg > 30.0:
        exp_arg = 30.0
    exp_term = math.exp(exp_arg)
    V_T = 0.5 * s_norm * s_norm * exp_term

    # ∂dist/∂x  (∂dist/∂Δψ = ∂dist/∂V_p = ∂dist/∂V_e = 0)
    ddist_dx = dx / dist
    ddist_dy = dy / dist
    ddist_dh = dh / dist

    # ∂cos_ATA/∂(Δx,Δy)  (cos_ATA = Δy / r_xy, planar)
    inv_rxy = 1.0 / r_xy
    inv_rxy3 = inv_rxy / r_xy_sq
    dcos_ATA_dx = -dy * dx * inv_rxy3
    dcos_ATA_dy = inv_rxy - dy*dy*inv_rxy3

    # ∂cos_AA/∂x  (cos_AA = -N/dist)
    dist_cube = dist * dist * dist
    d_cosAA_dx = -s_psi/dist + N*dx/dist_cube
    d_cosAA_dy = -c_psi/dist + N*dy/dist_cube
    d_cosAA_dh = N*dh/dist_cube
    d_cosAA_dpsi = -(dx*c_psi - dy*s_psi)/dist

    # ∂closure/∂x
    dcl_dx = V_p * dcos_ATA_dx + V_e * d_cosAA_dx
    dcl_dy = V_p * dcos_ATA_dy + V_e * d_cosAA_dy
    dcl_dh = V_e * d_cosAA_dh
    dcl_dpsi = V_e * d_cosAA_dpsi
    dcl_dVp = cos_ATA
    dcl_dVe = cos_AA

    # ∂V_T/∂x = exp_term · [s/d_REF · ∂dist/∂x − s²/(2·V_REF) · ∂c/∂x]
    A = exp_term * s_norm / D_REF_FT
    B = exp_term * s_norm * s_norm * 0.5 / V_REF_KTS

    grad = np.array([
        A * ddist_dx - B * dcl_dx,
        A * ddist_dy - B * dcl_dy,
        A * ddist_dh - B * dcl_dh,
        - B * dcl_dpsi,
        - B * dcl_dVp,
        - B * dcl_dVe,
    ])
    return V_T, grad


# ═══════════════════════════════════════════════════════════════════
# 정리 7 — Lag Displacement Turn (Shaw Phase 1)
#   V_7,P1 = ½·(ATA - ATA_lag)²
#   ATA_lag = sign(Δx) · 90°
# ═══════════════════════════════════════════════════════════════════

V_LAG_MARGIN_KTS = 30.0   # LDT: V_p 가 V_e 보다 이만큼 느려야 lag 으로 떨어짐 (Shaw 정전)


def grad_V_LDT(x: np.ndarray) -> Tuple[float, np.ndarray]:
    """정리 7 (Shaw 1985 LDT) Phase 1 의 closed-form — 각도 + 속도 lag.

    Phase 1: lag pursuit 으로 displacement 누적. Shaw 원전: angle lag *+ speed lag*
    (느려져서 떨어짐). 기존 구현은 각도만 — 속도 항 누락으로 lag 분기가 감속 안 함
    → 사용자 관찰 "뒤를 잡고도 머무르려 하지 않음" 의 직접 원인.

    수정: V_p 목표를 V_e − V_LAG_MARGIN 으로 설정 (적보다 30kts 느려짐 = 능동 brake).
    """
    dx, dy, _, _, V_p, V_e = x
    r_xy_sq = dx*dx + dy*dy + 1e-9
    ata = math.atan2(dx, dy)

    # 각도 lag: 적 방향 +/- 90°
    ata_lag = math.copysign(math.pi / 2.0, dx)
    err_ata = ata - ata_lag

    # 속도 lag (Stage-2 추가): V_p → V_e − margin 으로 능동 감속
    LAMBDA_V_LDT = 1.0 / (V_CORNER_DELTA_REF_KTS ** 2)
    V_target_lag = V_e - V_LAG_MARGIN_KTS
    err_v = V_p - V_target_lag

    V = 0.5 * err_ata * err_ata + 0.5 * LAMBDA_V_LDT * err_v * err_v

    dATA_dx = dy / r_xy_sq
    dATA_dy = -dx / r_xy_sq

    grad = np.array([
        err_ata * dATA_dx,            # ∂V/∂Δx
        err_ata * dATA_dy,            # ∂V/∂Δy
        0.0,                          # ∂V/∂Δh
        0.0,                          # ∂V/∂Δψ
        LAMBDA_V_LDT * err_v,         # ∂V/∂V_p = λ_V·(V_p − V_target_lag)  → V_p>target 면 BtG_a>0 → 감속
        -LAMBDA_V_LDT * err_v,        # ∂V/∂V_e = −λ_V·err_v  (V_target_lag 가 V_e 의 함수)
    ])
    return V, grad


# ═══════════════════════════════════════════════════════════════════
# 정리 8 — Pontryagin High Yo-Yo (Phase 1 climb)
#   V_8,P1 = ½·(Δh + 1500)²   when Δh > -1500
#   Phase 2 (dive): V_8,P2 = ½·Δh²  (적 고도 추종)
# ═══════════════════════════════════════════════════════════════════

def grad_V_yoyo(x: np.ndarray) -> Tuple[float, np.ndarray]:
    """정리 8 (Pontryagin 수직 BFM) closed-form.

    Phase 1 (climb): Δh > -1500 (우리 alt 우위 부족) → climb
    Phase 2 (dive):  Δh ≤ -1500 (우위 확보) → invert dive

    Phase boundary 는 부드럽지 않음 — boundary 에서 V 와 ∇V 가 C0 연속 (값 일치),
    C1 불연속 (gradient 부호 flip). 이게 Pontryagin bang-bang 의 본질.
    """
    dx, dy, dh, dpsi, V_p, V_e = x

    if dh > -ALT_GAP_TARGET_FT:
        # Phase 1 — climb cost
        err = dh + ALT_GAP_TARGET_FT
        V = 0.5 * err * err
        grad = np.zeros(6)
        grad[2] = err   # ∂V/∂Δh = Δh + 1500 > 0 (climb wanted)
    else:
        # Phase 2 — dive to enemy alt
        V = 0.5 * dh * dh
        grad = np.zeros(6)
        grad[2] = dh    # ∂V/∂Δh = Δh < 0 (dive wanted)

    return V, grad


# ═══════════════════════════════════════════════════════════════════
# Disturbance Jacobian B_d(x) — dynamics_f16_6d.py 와 일치
# ═══════════════════════════════════════════════════════════════════

def B_d_matrix(x: np.ndarray) -> np.ndarray:
    """제어 jacobian B_d ∈ ℝ^(6×3). u_p = (ω, γ̇, a)."""
    dx, dy, _, _, V_p, _ = x
    V_p_fps = V_p * env.PARAMS["kts_to_fps"]
    return np.array([
        [ dy,        0.0,       0.0],   # ∂(Δx_dot)/∂u_p
        [-dx,        0.0,       0.0],   # ∂(Δy_dot)/∂u_p
        [ 0.0,    -V_p_fps,     0.0],   # ∂(Δh_dot)/∂u_p
        [-1.0,       0.0,       0.0],   # ∂(Δψ_dot)/∂u_p
        [ 0.0,       0.0,       1.0],   # ∂(V_p_dot)/∂u_p
        [ 0.0,       0.0,       0.0],   # ∂(V_e_dot)/∂u_p
    ])


# ═══════════════════════════════════════════════════════════════════
# 정책 합성 — τ-blended optimal control
# ═══════════════════════════════════════════════════════════════════

def optimal_control(x: np.ndarray,
                     taus: dict,
                     alt_ft: float = 15000.0,
                     bias_tau_T: float = 0.0,
                     ) -> Tuple[np.ndarray, dict]:
    """∇V_approx = Σ τ_i · ∇V_i  →  u* = -sign(B_d^T · ∇V) · u_max.

    Args:
        x: 6D state
        taus: {'pn': float, 'corner': float, 'ldt': float, 'yoyo': float, 'T': float}
              각 ∈ [0, 1], Σ ≤ 1 권장 (잔여 = baseline PN). 'T' 항은 정규화 분모 포함.
        alt_ft: 현재 고도 (envelope 와 V_c)
        bias_tau_T: V_T 의 *추가 bias* (정규화 분모에서 제외, C2 2026-05-16).
              기존 simple-load-bearing 비율을 보존하면서 τ_T·g_T_unit 를 추가 방향 신호로
              주입. caller (예: Theorem 분기) 가 H1 우회용으로 활성. default 0 (기존 동작).

    Returns:
        (u_star, info) — u_star = (ω, γ̇, a) 연속, info 는 진단 dict
    """
    V_c_kts = env.V_corner_kts(alt_ft)
    V_pn,    g_pn    = grad_V_PN(x, V_c_kts=V_c_kts)
    V_2c,    g_2c    = grad_V_corner(x, alt_ft)     # m_4 (2-circle): V_c tracking
    V_1c,    g_1c    = grad_V_1circle(x, alt_ft)    # m_3 (1-circle): R-min + ATA align (RT-2)
    V_ldt,   g_ldt   = grad_V_LDT(x)
    V_yoyo,  g_yoyo  = grad_V_yoyo(x)
    V_T,     g_T     = grad_V_Tcap(x)               # m_T (ZEM capture-time, SUPERPLAN_v2 §3 후보 C)

    # ─ Corner mode 의 1c/2c sub-mode 분기 (PLAN §2.6.2/2.6.4 switching surface S_34) ─
    #   HCA < 90°  → 1-circle (g_1c),  HCA > 120° → 2-circle (g_2c)
    #   사이는 σ blend — S_34 (HCA≈105°) 에서 50/50. v11 의 implicit 1c/2c 의 형식화.
    hca_rad = abs(x[3])
    sig_1c = _sig((HCA_1C_CENTER_RAD - hca_rad) / SIGMA_REGIME_WIDTH_RAD)
    sig_2c = _sig((hca_rad - HCA_2C_CENTER_RAD) / SIGMA_REGIME_WIDTH_RAD)
    w_sum = sig_1c + sig_2c + 1e-9
    g_corn = (sig_1c * g_1c + sig_2c * g_2c) / w_sum
    V_corn = (sig_1c * V_1c + sig_2c * V_2c) / w_sum

    # τ_i (caller 가 명시 전달; 누락은 0). PN baseline 도 명시 가중치 필요.
    tau_pn     = taus.get("pn", 0.0)
    tau_corner = taus.get("corner", 0.0)
    tau_ldt    = taus.get("ldt", 0.0)
    tau_yoyo   = taus.get("yoyo", 0.0)
    tau_T      = taus.get("T", 0.0)                 # m_T (ZEM capture-time)
    tau_total  = tau_pn + tau_corner + tau_ldt + tau_yoyo + tau_T

    if tau_total < 1e-6:
        # caller 가 모두 0 → safe fallback (PN 만)
        tau_pn = 1.0
        tau_total = 1.0

    # τ-blended gradient
    # m_T (V_T) 는 magnitude scale 이 V_PN 의 ~1500× — *grad-normalize* 후 blend 해야
    # tau_T blend 가 *방향 신호* 로만 작용 (magnitude 는 BTG_SCALE 단계에서 통일).
    # V_dist 가 ω+a 채널 영구 0 (H1 PROVED) 인 만큼 m_T 가 *그 빈자리* 채움.
    g_T_norm = float(np.linalg.norm(g_T)) + 1e-9
    g_T_unit = g_T / g_T_norm
    grad_approx = (tau_pn * g_pn + tau_corner * g_corn +
                   tau_ldt * g_ldt + tau_yoyo * g_yoyo +
                   tau_T * g_T_unit) / tau_total
    # C2 (2026-05-16): bias_tau_T 는 정규화에서 *분리* — yoyo·pn·corner·ldt 평형 보존
    # + V_T 방향 신호 *추가*. Theorem 분기 H1 우회용. caller 가 명시 활성.
    if bias_tau_T > 0.0:
        grad_approx = grad_approx + bias_tau_T * g_T_unit

    # B_d 와 inner product
    B_d = B_d_matrix(x)
    BtG = B_d.T @ grad_approx   # shape (3,)

    # Envelope bounds (V_p, alt 의존)
    V_p = x[4]
    omega_max = env.omega_max_rad_s(V_p, alt_ft)
    gamma_dot_max = env.gamma_rate_max_rad_s(V_p, alt_ft)
    accel_max = 15.0   # kts/s, F-16 typical thrust-drag balance approximation
    u_max = np.array([omega_max, gamma_dot_max, accel_max])

    # ─ Smooth saturation — magnitude-aware control (R3 fix + R3.1 정정) ─
    # 사용자 지적: bang-bang argmin → "선회 magnitude 차등" 부재 + V_p 손실.
    # u* = clip(-BtG · gain, -u_max, +u_max). BtG 가 typical magnitude 일 때 u_max 도달.
    #
    # 채널별 typical |BtG_i| (canonical IC + V_adv 의 각 항 차원분석):
    #   - ω: BtG_w = (B_d^T ∇V)_ω ≈ |ATA| at perpendicular ≈ π/2 ≈ 1.57
    #   - γ̇: BtG_γ̇ = -V_p_fps · ∂V/∂Δh.
    #         typical ∂V/∂Δh ≈ LAMBDA_DIST · ALT_GAP_REF ≈ 5e-4
    #         V_p_fps ≈ 650 → typical |BtG_γ̇| ≈ 0.3
    #   - a:  BtG_a = ∂V/∂V_p = LAMBDA_V · (V_p - V_c).
    #         V_err = V_CORNER_DELTA_REF=50 → typical ≈ 1/V_REF = 0.02
    V_p_fps = V_p * env.PARAMS["kts_to_fps"]
    BTG_SCALE = np.array([
        math.pi / 2,                                          # ω
        V_p_fps * LAMBDA_DIST * ALT_GAP_REF_FT,               # γ̇
        1.0 / V_CORNER_DELTA_REF_KTS,                         # a — 작은 임계 (~0.02)
    ])
    gain = u_max / (BTG_SCALE + 1e-9)
    u_raw = -BtG * gain
    u_star = np.clip(u_raw, -u_max, +u_max)

    # NOTE: turn-induced-drag accel cap (Boyd Ps coupling) 를 시도했으나 evidence 기각 —
    # post-hoc accel hard-cap 은 물리적으론 맞지만 agent 를 소극적으로 만듦 (vs simple
    # 4W2L → 1W5D). 유도항력 결합은 dynamics-level 또는 over-turn 억제로 재접근 필요.

    info = {
        "V_pn": V_pn, "V_corner": V_corn, "V_ldt": V_ldt, "V_yoyo": V_yoyo,
        "V_1circle": V_1c, "V_2circle": V_2c, "V_T": V_T,
        "grad_pn": g_pn, "grad_corner": g_corn, "grad_ldt": g_ldt, "grad_yoyo": g_yoyo,
        "grad_T": g_T,
        "grad_approx": grad_approx,
        "sig_1c": sig_1c, "sig_2c": sig_2c,
        "BtG": BtG, "BTG_SCALE": BTG_SCALE, "B_d": B_d,         # D1 (2026-05-16) — per-mode BtG 계산 노출
        "u_max": u_max,
        "u_star": u_star,
        "taus": {"pn": tau_pn, "corner": tau_corner, "ldt": tau_ldt, "yoyo": tau_yoyo, "T": tau_T},
    }
    return u_star, info


# ═══════════════════════════════════════════════════════════════════
# Numerical 검증 — finite-difference gradient 와 ≤ 1% 정합 확인
# ═══════════════════════════════════════════════════════════════════

def _finite_diff_grad(V_func, x: np.ndarray, h: float = 1e-3) -> np.ndarray:
    """central difference numerical gradient."""
    grad = np.zeros(6)
    for i in range(6):
        x_plus = x.copy();  x_plus[i] += h
        x_minus = x.copy(); x_minus[i] -= h
        V_plus, _ = V_func(x_plus)
        V_minus, _ = V_func(x_minus)
        grad[i] = (V_plus - V_minus) / (2.0 * h)
    return grad


def verify_gradients(verbose: bool = True) -> dict:
    """모든 ∇V_i 의 analytic vs finite-diff 일치 검증.

    Returns:
        dict {theorem_name: {"max_rel_err": float, "pass": bool}}
    """
    # canonical IC (ATA=90°, dist=3297.6ft, alt=15000ft 가정)
    x_canon = np.array([3297.6, 0.0, 0.0, math.pi, 386.8, 386.8])

    test_cases = {
        "PN":       (lambda xx: grad_V_PN(xx)),
        "Corner":   (lambda xx: grad_V_corner(xx, alt_ft=15000.0)),
        "OneCircle":(lambda xx: grad_V_1circle(xx, alt_ft=15000.0)),
        "LDT":      (lambda xx: grad_V_LDT(xx)),
        "YoYo":     (lambda xx: grad_V_yoyo(xx)),
        "Tcap":     (lambda xx: grad_V_Tcap(xx)),
    }

    results = {}
    for name, V_func in test_cases.items():
        _, g_analytic = V_func(x_canon)
        g_numeric = _finite_diff_grad(V_func, x_canon)
        # 0 인 차원은 상대오차 계산 안 함
        mask = np.abs(g_analytic) > 1e-8
        if mask.sum() > 0:
            rel_err = np.abs((g_analytic[mask] - g_numeric[mask]) / g_analytic[mask])
            max_rel = float(rel_err.max())
        else:
            max_rel = float(np.abs(g_numeric).max())
        passed = max_rel < 0.01
        results[name] = {"max_rel_err": max_rel, "pass": passed,
                         "analytic": g_analytic, "numeric": g_numeric}
        if verbose:
            print(f"  {name:8} max_rel_err = {max_rel:.4%}  {'PASS' if passed else 'FAIL'}")
            if not passed:
                print(f"    analytic = {g_analytic}")
                print(f"    numeric  = {g_numeric}")
    return results


if __name__ == "__main__":
    import sys, os
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("=" * 70)
    print("  ∇V_i Gradient Approximators — Sanity Check")
    print("=" * 70)
    print()
    print("[1] Analytic vs Finite-Difference gradient (canonical IC)")
    verify_gradients(verbose=True)
    print()

    print("[2] Sign check — canonical IC (Δx=3297, Δy=0, Δh=0, V_p=386.8)")
    x = np.array([3297.6, 0.0, 0.0, math.pi, 386.8, 386.8])

    # 각 정리 단독 실행
    for tau_name in ["pn", "corner", "ldt", "yoyo"]:
        taus = {tau_name: 1.0}
        u, info = optimal_control(x, taus, alt_ft=15000.0)
        print(f"  τ_{tau_name}=1.0  →  BtG=({info['BtG'][0]:+.3e}, "
              f"{info['BtG'][1]:+.3e}, {info['BtG'][2]:+.3e})")
        print(f"             u* = (ω={u[0]:+.4f} rad/s = {math.degrees(u[0]):+.2f}°/s, "
              f"γ̇={math.degrees(u[1]):+.2f}°/s, a={u[2]:+.2f} kts/s)")

    # 의미 해석
    print()
    print("[3] Interpretation (Δx>0 = 적 우측, dy=0 = 적이 우리 옆에)")
    print("   - PN:     u_ω 부호 → 적 방향 회전 (게이트 G1_a)")
    print("   - Corner: u_a 부호 → V_p=386.8 vs V_c(15000ft)=438.6, V_p<V_c → 가속 (게이트 G1_b)")
    print("   - LDT:    u_ω 부호 → lag target (Δx>0 → ATA_lag=+90°, 현재 ATA=π/2≈90° 이미 lag) (게이트 G1_d)")
    print("   - YoYo:   Δh=0 > -1500 → climb (게이트 G1_c)")
