"""F-16 Flight Envelope — Doghouse Plot from First Principles.

본 모듈은 PURSUIT_CHASE_PLAN.md §2.2 의 식 E1, E2 를 직접 구현한다.
모든 magic number 금지 — 모든 상수는 출처 명시.

식:
  E1: ω(V, n) = g · √(n² - 1) / V                    [Anderson, Aircraft Perf. Ch.6]
  E2: n_max(V, alt, W) = min(n_struct, n_aero(V, alt, W))
      n_aero(V, alt, W) = ½·ρ(alt)·V²·S·C_L_max / W

사용:
  from tools.basis.envelope_f16 import omega_max_dps, V_corner_kts

  # 우리 매치 환경 (15000ft, combat config)
  omega_at_350kts = omega_max_dps(V_kts=350, alt_ft=15000)
  Vc = V_corner_kts(alt_ft=15000)   # ≈ 438 kts

검증 게이트 (PLAN §2.2.8 G0):
  G0_a: 모든 파라미터 출처 명시 ✓ (아래 PARAMS dict)
  G0_b: 식 E1, E2 가 첫 절 원리 derive ✓ (docstring)
  G0_c: JSBSim 직접 시뮬레이션과 ≤1% 정합 — tools/verify_envelope.py 로 검증
  G0_d: V_c(15000ft) ≈ 438kts — published F-16 ref 정합
  G0_e: v11 9-point (alt=8000ft) 도 같은 식으로 재현
"""

from __future__ import annotations

import math
from typing import Tuple


# ═══════════════════════════════════════════════════════════════════
# 파라미터 — 출처 명시 (PLAN §2.2.5 표)
# ═══════════════════════════════════════════════════════════════════

PARAMS = {
    # ─ Aerodynamic ─
    "S_wing_ft2":  300.0,   # JSBSim f16.xml:<wingarea> (line 41)
    "CL_max":      1.83,    # JSBSim CLDh table at α=40°(0.698 rad), elev=0  [NASA TP-1538]
    # CL_max=1.83 은 LEF 미반영 보수치. 실 F-16 (LEF auto-deploy) 은 ~2.0 가능.

    # ─ Structural ─
    "n_struct_g":  9.0,     # F-16 Flight Manual TO-1F-16C-1, fly-by-wire +9g limit

    # ─ Weight (combat config) ─
    "W_empty_lb":  17400.0, # JSBSim f16.xml:<emptywt>
    "W_combat_lb": 25000.0, # empty + 50% fuel (3400) + 2×AIM-9 (388) + pilot+misc (~1200)

    # ─ Physical constants ─
    "g_ft_s2":     32.174,  # standard gravity
    "kts_to_fps":  1.6878,  # knots to ft/s conversion
}


# ═══════════════════════════════════════════════════════════════════
# US Standard Atmosphere 1976 (Troposphere, ≤ 36,000 ft)
# ═══════════════════════════════════════════════════════════════════

def air_density_slug_ft3(alt_ft: float) -> float:
    """대기 밀도 ρ(alt) — US Std Atmosphere 1976 troposphere (≤ 36,000 ft).

    Form (조회 가능 standard form, ft 단위):
      ρ(h) = ρ₀ · (1 - β·h)^4.2561
    where:
      ρ₀ = 0.002377 slug/ft³                (sea level)
      β  = L/T₀ = 6.876 × 10⁻⁶ /ft         (T₀ = 518.67°R, L = 0.00357°R/ft)
      4.2561 = g/(R_air · L) - 1            (g=32.174 ft/s², R=1716.49 ft·lbf/slug/°R)

    수치 검증 (NASA TM-X-74335 / US Std Atm 1976 부록):
      0    ft: 0.002377  slug/ft³ ✓
      8000 ft: 0.001869  ✓
      15000 ft: 0.001496  ✓
      25000 ft: 0.001065  ✓
      36000 ft: 0.000706  ✓ (tropopause 한계)
    """
    if alt_ft < 0:
        alt_ft = 0.0
    if alt_ft > 36000:
        alt_ft = 36000.0
    rho_0 = 0.002377
    beta = 6.876e-6   # /ft, = L/T₀
    return rho_0 * (1.0 - beta * alt_ft) ** 4.2561


# ═══════════════════════════════════════════════════════════════════
# E1, E2 — 핵심 식
# ═══════════════════════════════════════════════════════════════════

def n_aero(V_fps: float, alt_ft: float,
           W_lb: float = None, S_ft2: float = None, CL_max: float = None) -> float:
    """E2 (a): 공력 한계 하중배수.

    n_aero = ½·ρ·V²·S·CL_max / W
    """
    W = W_lb or PARAMS["W_combat_lb"]
    S = S_ft2 or PARAMS["S_wing_ft2"]
    CL = CL_max or PARAMS["CL_max"]
    rho = air_density_slug_ft3(alt_ft)
    q = 0.5 * rho * V_fps * V_fps   # dynamic pressure (lb/ft²)
    return q * S * CL / W


def n_max(V_fps: float, alt_ft: float,
          W_lb: float = None, S_ft2: float = None, CL_max: float = None,
          n_struct: float = None) -> Tuple[float, str]:
    """E2: n_max(V, alt) = min(n_struct, n_aero).

    Returns (n_max, regime) where regime ∈ {"aero", "struct", "transition"}.
    """
    n_str = n_struct or PARAMS["n_struct_g"]
    na = n_aero(V_fps, alt_ft, W_lb, S_ft2, CL_max)
    if na < n_str - 1e-3:
        return na, "aero"
    elif na > n_str + 1e-3:
        return n_str, "struct"
    else:
        return n_str, "transition"


def omega_max_rad_s(V_kts: float, alt_ft: float, **kw) -> float:
    """E1+E2: 순간 최대 선회율 (rad/s).

    ω = g · √(n_max² - 1) / V_fps

    V=0 처리: n_max → 0 이고 √(n²-1) 가 허수 — 물리적으로 V=0 선회 불가.
    convention: V < V_min (실속 직전) 에선 0 반환.
    """
    V_fps = V_kts * PARAMS["kts_to_fps"]
    if V_fps < 1.0:
        return 0.0
    n, _ = n_max(V_fps, alt_ft, **kw)
    if n < 1.001:
        return 0.0   # 직선 비행 한계 (n=1 = level)
    g = PARAMS["g_ft_s2"]
    return g * math.sqrt(n * n - 1.0) / V_fps


def omega_max_dps(V_kts: float, alt_ft: float, **kw) -> float:
    """순간 최대 선회율 (°/s) — BT 와 envelope clamp 의 표준 단위."""
    return math.degrees(omega_max_rad_s(V_kts, alt_ft, **kw))


def turn_radius_ft(V_kts: float, alt_ft: float, **kw) -> float:
    """R = V / ω — 순간 최소 선회반경 (ft).

    V=0 또는 ω=0 처리: 무한대 → 1e9 sentinel.
    """
    omega = omega_max_rad_s(V_kts, alt_ft, **kw)
    if omega < 1e-6:
        return 1e9
    V_fps = V_kts * PARAMS["kts_to_fps"]
    return V_fps / omega


def V_corner_kts(alt_ft: float,
                 W_lb: float = None, S_ft2: float = None,
                 CL_max: float = None, n_struct: float = None) -> float:
    """코너속도 — n_aero(V_c) = n_struct 의 해.

    V_c = √(2 · n_struct · W / (ρ · S · CL_max))   [ft/s]
    """
    W = W_lb or PARAMS["W_combat_lb"]
    S = S_ft2 or PARAMS["S_wing_ft2"]
    CL = CL_max or PARAMS["CL_max"]
    n_str = n_struct or PARAMS["n_struct_g"]
    rho = air_density_slug_ft3(alt_ft)
    V_c_fps = math.sqrt(2.0 * n_str * W / (rho * S * CL))
    return V_c_fps / PARAMS["kts_to_fps"]


def gamma_rate_max_rad_s(V_kts: float, alt_ft: float, **kw) -> float:
    """수직 평면 최대 피치율.

    수직 평면 협조 선회 (loop) 에서도 식 E1 형식 동일 — n_max 가 그대로 적용.
    단 vertical loop 에서 n_eff = n - cos(γ) (중력 분배 다름). 단순화:
    horizontal envelope 의 ~70% 사용 (v11 측정치 일치).
    """
    return 0.7 * omega_max_rad_s(V_kts, alt_ft, **kw)


def gamma_rate_max_dps(V_kts: float, alt_ft: float, **kw) -> float:
    return math.degrees(gamma_rate_max_rad_s(V_kts, alt_ft, **kw))


# ═══════════════════════════════════════════════════════════════════
# Diagnostic — doghouse plot 출력
# ═══════════════════════════════════════════════════════════════════

def doghouse_table(alt_ft: float, V_range_kts: list = None) -> list:
    """Doghouse plot 표 산출 — 검증 / 시각화 용."""
    if V_range_kts is None:
        V_range_kts = [160, 200, 250, 300, 350, 400, 438, 500, 600]
    Vc = V_corner_kts(alt_ft)
    rows = []
    for V in V_range_kts:
        V_fps = V * PARAMS["kts_to_fps"]
        na = n_aero(V_fps, alt_ft)
        n, regime = n_max(V_fps, alt_ft)
        omega = omega_max_dps(V, alt_ft)
        R = turn_radius_ft(V, alt_ft)
        rows.append({
            "V_kts":  V,
            "V_fps":  round(V_fps, 1),
            "n_aero": round(na, 2),
            "n_max":  round(n, 2),
            "regime": regime,
            "omega_max_dps": round(omega, 2),
            "R_ft":   round(R, 0),
        })
    return rows, Vc


if __name__ == "__main__":
    import sys, os
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("F-16 Flight Envelope — Doghouse Plot (PURSUIT_CHASE_PLAN §2.2)")
    print("=" * 80)
    print(f"파라미터: W={PARAMS['W_combat_lb']}lb, S={PARAMS['S_wing_ft2']}ft², "
          f"CL_max={PARAMS['CL_max']}, n_struct={PARAMS['n_struct_g']}g")
    print()

    for alt in [8000, 15000, 25000]:
        rows, Vc = doghouse_table(alt)
        print(f"고도 {alt} ft   |   ρ={air_density_slug_ft3(alt):.5f} slug/ft³   |   "
              f"V_corner={Vc:.1f} kts")
        print(f"  {'V_kts':>6} {'n_aero':>8} {'n_max':>7} {'regime':>11} "
              f"{'ω_max[°/s]':>12} {'R[ft]':>8}")
        for r in rows:
            print(f"  {r['V_kts']:>6} {r['n_aero']:>8.2f} {r['n_max']:>7.2f} "
                  f"{r['regime']:>11} {r['omega_max_dps']:>12.2f} {r['R_ft']:>8.0f}")
        print()
