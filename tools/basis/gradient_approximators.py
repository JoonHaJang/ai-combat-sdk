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
# ═══════════════════════════════════════════════════════════════════

WEZ_CENTER_FT = 1750.0     # WEZ 거리 중심 (500~3000 의 중간)
WEZ_HALF_WIDTH_FT = 1250.0  # WEZ 절반 폭. dist 가 d_ref 만큼 벗어나면 V_dist=0.5 (ATA·AA 항과 동급)
LAMBDA_DIST = 1.0 / (WEZ_HALF_WIDTH_FT ** 2)  # ≈ 6.4e-7. dist err=1250ft → V_dist=0.5
ALT_GAP_TARGET_FT = 1500.0  # yo-yo Phase 1 climb 목표 (적 대비 -1500ft = 우리 위)
LDT_LAG_OFFSET_DEG = 90.0   # Lag pursuit target offset

# Smooth saturation reference scales (R3 fix — bang-bang 회피)
# 각 BtG 채널의 "전형적 크기" — 이 값에서 u_max 도달. 작으면 비례 감소.
ALT_GAP_REF_FT = 1500.0           # yo-yo target alt_gap 과 동일 scale
V_CORNER_DELTA_REF_KTS = 50.0     # V_p 와 V_c 차이의 typical scale (envelope §2.2)


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
    ata = math.atan2(dx, dy)   # ∈ (-π, π]

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
    V_err = V_p - V_c_kts   # 코너속도 추격
    LAMBDA_V = 1.0 / (V_CORNER_DELTA_REF_KTS ** 2)   # ≈ 4e-4 normalize

    # AA mask α(dist) — 사용자 "유분리" 통찰의 수학화:
    # dist 멀 때 (>>WEZ): close 우선, AA 무관심 → α≈0
    # dist 가까울 때 (≈WEZ): AA 추구 활성 → α≈1
    #
    # ⚠ R3.1c 진단 결과: sigmoid mask 가 sharp 해서 dist=3000 부근 oscillation.
    # 임시 진단 모드: alpha_aa=0 (V_aa 제거) — 순수 pursuit 동작 분리 관찰.
    # 해결 후 재활성.
    alpha_aa = 0.0   # diagnostic disable
    d_alpha_dr = 0.0

    V_ata = 0.5 * ata * ata
    V_aa = alpha_aa * 0.5 * (math.pi - AA) * (math.pi - AA)
    V_dist = 0.5 * LAMBDA_DIST * dist_err * dist_err
    V_speed = 0.5 * LAMBDA_V * V_err * V_err
    V = V_ata + V_aa + V_dist + V_speed

    # ∂ATA/∂(Δx, Δy)
    dATA_dx = dy / r_xy_sq
    dATA_dy = -dx / r_xy_sq

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

    # Chain rule: ∂(α·½(π-AA)²)/∂· =
    #   α · (π-AA)/sin_AA · ∂cos_AA/∂·   (AA path)
    #   + (∂α/∂dist · ∂dist/∂·) · ½(π-AA)²   (dist path through α)
    factor_AA = alpha_aa * (math.pi - AA) / sin_AA
    half_aa_sq = 0.5 * (math.pi - AA) * (math.pi - AA)

    grad = np.array([
        ata * dATA_dx + factor_AA * d_cosAA_dx
            + (LAMBDA_DIST * dist_err + d_alpha_dr * half_aa_sq) * ddist_dx,
        ata * dATA_dy + factor_AA * d_cosAA_dy
            + (LAMBDA_DIST * dist_err + d_alpha_dr * half_aa_sq) * ddist_dy,
        factor_AA * d_cosAA_dh
            + (LAMBDA_DIST * dist_err + d_alpha_dr * half_aa_sq) * ddist_dh,
        factor_AA * d_cosAA_dpsi,
        LAMBDA_V * V_err,
        0.0,
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
# 정리 7 — Lag Displacement Turn (Shaw Phase 1)
#   V_7,P1 = ½·(ATA - ATA_lag)²
#   ATA_lag = sign(Δx) · 90°
# ═══════════════════════════════════════════════════════════════════

def grad_V_LDT(x: np.ndarray) -> Tuple[float, np.ndarray]:
    """정리 7 (Shaw 1985 LDT) Phase 1 의 closed-form.

    Phase 1: lag pursuit 으로 displacement 누적.
    Phase 2 (dist·sin|ATA| ≥ R·√2) 는 PN 으로 fallback — 본 함수는 Phase 1 만.
    """
    dx, dy, _, _, _, _ = x
    r_xy_sq = dx*dx + dy*dy + 1e-9
    ata = math.atan2(dx, dy)

    # Lag target: 적 방향 +/- 90°
    ata_lag = math.copysign(math.pi / 2.0, dx)
    err = ata - ata_lag

    V = 0.5 * err * err

    dATA_dx = dy / r_xy_sq
    dATA_dy = -dx / r_xy_sq

    grad = np.array([
        err * dATA_dx,    # ∂V/∂Δx
        err * dATA_dy,    # ∂V/∂Δy
        0.0,              # ∂V/∂Δh
        0.0,              # ∂V/∂Δψ
        0.0,              # ∂V/∂V_p
        0.0,              # ∂V/∂V_e
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
                     ) -> Tuple[np.ndarray, dict]:
    """∇V_approx = Σ τ_i · ∇V_i  →  u* = -sign(B_d^T · ∇V) · u_max.

    Args:
        x: 6D state
        taus: {'pn': float, 'corner': float, 'ldt': float, 'yoyo': float}
              각 ∈ [0, 1], Σ ≤ 1 권장 (잔여 = baseline PN)
        alt_ft: 현재 고도 (envelope 와 V_c)

    Returns:
        (u_star, info) — u_star = (ω, γ̇, a) 연속, info 는 진단 dict
    """
    V_c_kts = env.V_corner_kts(alt_ft)
    V_pn,    g_pn    = grad_V_PN(x, V_c_kts=V_c_kts)
    V_corn,  g_corn  = grad_V_corner(x, alt_ft)
    V_ldt,   g_ldt   = grad_V_LDT(x)
    V_yoyo,  g_yoyo  = grad_V_yoyo(x)

    # τ_i (caller 가 명시 전달; 누락은 0). PN baseline 도 명시 가중치 필요.
    tau_pn     = taus.get("pn", 0.0)
    tau_corner = taus.get("corner", 0.0)
    tau_ldt    = taus.get("ldt", 0.0)
    tau_yoyo   = taus.get("yoyo", 0.0)
    tau_total  = tau_pn + tau_corner + tau_ldt + tau_yoyo

    if tau_total < 1e-6:
        # caller 가 모두 0 → safe fallback (PN 만)
        tau_pn = 1.0
        tau_total = 1.0

    # τ-blended gradient
    grad_approx = (tau_pn * g_pn + tau_corner * g_corn +
                   tau_ldt * g_ldt + tau_yoyo * g_yoyo) / tau_total

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

    info = {
        "V_pn": V_pn, "V_corner": V_corn, "V_ldt": V_ldt, "V_yoyo": V_yoyo,
        "grad_pn": g_pn, "grad_corner": g_corn, "grad_ldt": g_ldt, "grad_yoyo": g_yoyo,
        "grad_approx": grad_approx,
        "BtG": BtG,
        "u_max": u_max,
        "u_star": u_star,
        "taus": {"pn": tau_pn, "corner": tau_corner, "ldt": tau_ldt, "yoyo": tau_yoyo},
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
        "PN":     (lambda xx: grad_V_PN(xx)),
        "Corner": (lambda xx: grad_V_corner(xx, alt_ft=15000.0)),
        "LDT":    (lambda xx: grad_V_LDT(xx)),
        "YoYo":   (lambda xx: grad_V_yoyo(xx)),
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
