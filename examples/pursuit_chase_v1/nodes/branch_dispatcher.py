"""Branch Dispatcher — Hybrid Differential Game 의 mode 선택기 (RT-1).

PURSUIT_CHASE_PLAN.md §2.6 의 형식적 정의를 실 BT 코드로 매핑:
  mode set M = {Bernoulli, PN, OneCircle, TwoCircle, LDT, HighYoYo, HJIFallback, HardDeck}
  τ_m(x) = mode m 의 entry score (R2 의 tau_functions.py)
  V_m^*(x) — closed-form per mode (R1 의 gradient_approximators.py)
  HJI fallback — R7 의 v3 LUT

본 dispatcher 의 역할:
  obs → (active_mode, blended ∇V) → continuous_policy 가 u* 산출

설계 (v11 BT 분기 구조 + 우리 ∇V_i + LUT 통합):
  1. Hard predicate 우선순위 (안전·게임 종단):
     HardDeck → GunEngagement → OffensivePursuit
  2. TheoremAdaptive — soft τ-blend (기본):
     τ_corner_1c / τ_corner_2c / τ_yoyo / τ_ldt / τ_pn 가중 평균
  3. HJI fallback — τ 합이 ε 이하인 영역만:
     V_LUT 의 ∇V 사용
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

import numpy as np


# ─── Mode 정의 (PLAN §2.6.2) ────────────────────────────────────

MODES = [
    "HardDeck",        # 안전: alt < 1200ft
    "GunEngagement",   # 사격: ATA<12° + WEZ 내 + alignment
    "OffensivePursuit",# 공격: ATA<45° + AA>100° + dist<4000
    "TheoremAdaptive", # τ-blend: corner/yoyo/ldt/pn
]


def _denorm_deg(obs: dict, key: str, default: float = 0.0) -> float:
    v = obs.get(key, default)
    return v * 180.0 if abs(v) <= 1.5 else v


def select_branch(obs: dict, alt_ft: float) -> dict:
    """Branch 선택 (PLAN §2.6 의 hard predicate 우선순위).

    v11 의 select_bt_branch 동일 로직 + AA-aware WEZ 확장.

    Returns:
        {"branch": str, "reason": str, "params": dict}
    """
    ata = _denorm_deg(obs, "ata_deg")
    aa = _denorm_deg(obs, "aa_deg")
    hca = _denorm_deg(obs, "hca_deg")
    dist = float(obs.get("distance_ft", 0.0))
    closure = float(obs.get("closure_rate_kts", 0.0))

    # 1. HardDeck — alt < 1200ft (game-terminal 회피)
    if alt_ft < 1200.0:
        return {"branch": "HardDeck", "reason": f"alt={alt_ft:.0f}<1200",
                "params": {}}

    # 2. GunEngagement — ATA<12° + WEZ + alignment ok
    # AA>45° 꼬리 추격 시 dist_gun_max=4000 (v11 확장)
    dist_gun_max = 4000.0 if aa > 45.0 else 3000.0
    aligned = (hca < 30.0) or (hca > 150.0) or (aa > 45.0)
    if ata < 12.0 and 500 < dist < dist_gun_max and aligned:
        return {"branch": "GunEngagement",
                "reason": f"ATA={ata:.1f}<12, dist={dist:.0f}∈[500,{dist_gun_max:.0f}], aligned={aligned}",
                "params": {"hca": hca, "aa": aa, "dist": dist}}

    # 3. OffensivePursuit — ATA<45° + AA>100° (적 등돌림) + dist<4000
    if ata < 45.0 and aa > 100.0 and dist < 4000.0:
        return {"branch": "OffensivePursuit",
                "reason": f"ATA={ata:.1f}<45, AA={aa:.1f}>100, dist={dist:.0f}<4000",
                "params": {"ata": ata, "aa": aa, "dist": dist, "closure": closure}}

    # 4. Default — TheoremAdaptive (τ-blend)
    return {"branch": "TheoremAdaptive",
            "reason": "soft τ-blend (PN + corner/yoyo/ldt)",
            "params": {"ata": ata, "aa": aa, "hca": hca, "dist": dist, "closure": closure}}


# ─── Branch-specific 명령 산출 ─────────────────────────────────

def cmd_HardDeck(obs: dict) -> Tuple[float, float, float]:
    """alt < 1200ft → 강제 상승, 수평 유지."""
    # γ̇ = max climb (alt_bin=4), ω = 0 (straight), a = +max (가속)
    return (0.0, math.radians(15.0), 15.0)


def cmd_GunEngagement(obs: dict, V_p: float, alt_ft: float) -> Tuple[float, float, float]:
    """ATA<12 + WEZ 내 — sustained PN + 코너속도 유지.

    PN 명령: rb_deg 따라 hdg 조정. closure>0 면 정렬 우선, closure<0 면 가속.
    """
    rb = _denorm_deg(obs, "relative_bearing_deg")
    closure = float(obs.get("closure_rate_kts", 0.0))
    # PN-3 (Bryson-Ho): ω = K · rb · (-1) — rb>0 (적 좌) → ω<0 (우회전... 아 B_d convention 좌회전)
    K_pn = 0.05   # gain (rb deg → rad/s)
    omega = -math.radians(K_pn * rb)
    # 수직: 적 고도 추종
    alt_gap = float(obs.get("alt_gap_ft", 0.0))
    gamma_dot = math.radians(0.5 * np.clip(alt_gap / 500.0, -1.0, 1.0) * 10.0)
    # 속도: closure<0 면 sprint
    if closure < 0:
        accel = 15.0
    elif V_p > 420 - 10:
        accel = -5.0
    else:
        accel = 5.0
    return (omega, gamma_dot, accel)


def cmd_OffensivePursuit(obs: dict, V_p: float, alt_ft: float) -> Tuple[float, float, float]:
    """ATA<45 + AA>100 (적 등돌림) — 적극 추격 + WEZ 진입 시도."""
    rb = _denorm_deg(obs, "relative_bearing_deg")
    closure = float(obs.get("closure_rate_kts", 0.0))
    dist = float(obs.get("distance_ft", 2000.0))
    # 강한 PN-5 (적 등돌림 → 우리만 정렬 추격)
    K_pn = 0.08
    omega = -math.radians(K_pn * rb)
    # 수직: 적 고도 추종 강함
    alt_gap = float(obs.get("alt_gap_ft", 0.0))
    gamma_dot = math.radians(0.5 * np.clip(alt_gap / 300.0, -1.0, 1.0) * 12.0)
    # 속도: closure 부족 시 sprint
    accel = 15.0 if (closure < 100 or dist > 2000) else 5.0
    return (omega, gamma_dot, accel)
