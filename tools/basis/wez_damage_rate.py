"""WEZ damage rate D(x) — Model B' (PLAN §0.8 / §11.7) 의 기본 함수.

본 모듈은 *순수 함수* — 정책 변경 없음. logging / 분석용 score function.

수식 (PLAN §0.8):
    D(x) = 25.0 · w_ATA(x) · w_dist(x)  HP/s   (x ∈ WEZ)
         = 0                              (x ∉ WEZ)

    w_ATA(x) = max(0, 1 - ATA / 12°)             linear decay
    w_dist(x) = bell on [500, 3000] ft, peak at 1500 ft

    WEZ 조건: ATA < 12° AND 500 < dist < 3000 ft AND (closure > 0 — optional)

Use cases:
    - D_us(x) = D(ATA=our_ATA, dist=dist)        — 우리가 적에게 가하는 damage rate
    - D_them(x) = D(ATA=enemy_ATA_at_us = AA-derived, dist=dist)  — 적이 우리에게
    - Running cost L(t) = D_them(t) - D_us(t)   — 적분 시 우리에게 불리한 누적
    - Total payoff J = ∫ -L dt = ∫ (D_us - D_them) dt
"""

from __future__ import annotations

import math


# core 정확 매개변수 (src/control/health_manager.py + src/utils/units.py 기준, 2026-05-17 정정)
BASE_DPS = 25.0          # HP/s, 최적 조건 시 max damage (core MAX_DPS 와 동일)
ATA_LIMIT_DEG = 12.0     # WEZ cone half-angle (core WEZ_MAX_ANGLE_DEG)
DIST_MIN_FT = 500.0      # WEZ inner (core WEZ_MIN_RANGE_M = 152.4m)
DIST_MAX_FT = 3000.0     # WEZ outer (core WEZ_MAX_RANGE_M = 914.4m)

# [REMOVED] DIST_SWEET_FT — *core 에는 sweet spot 없음*. damage 는 500ft 가 최대 (선형 감소).
# 이전 doc 의 1500ft sweet spot 가정은 *우리 BT 의 잘못된 가정*. 정정됨.


def w_ata(ata_deg: float) -> float:
    """Linear decay angle weight ∈ [0, 1] — core 와 정확 일치.

    core: angle_factor = 1.0 - (ata / 12°). ATA=0 → 1.0, ATA=12° → 0.0.
    """
    return max(0.0, 1.0 - abs(ata_deg) / ATA_LIMIT_DEG)


def w_dist(dist_ft: float) -> float:
    """Linear decay distance weight ∈ [0, 1] — core 와 정확 일치.

    core: distance_factor = (MAX_RANGE - dist) / (MAX_RANGE - MIN_RANGE).
          500ft → 1.0 (max damage), 3000ft → 0.0 (no damage). *sweet spot 없음, 가까울수록 좋음*.
    """
    if dist_ft < DIST_MIN_FT or dist_ft > DIST_MAX_FT:
        return 0.0
    return (DIST_MAX_FT - dist_ft) / (DIST_MAX_FT - DIST_MIN_FT)


def damage_rate(ata_deg: float, dist_ft: float, closure_kts: float = 1.0) -> float:
    """D(x) — damage rate HP/s. core 게임 룰과 정확 일치.

    core 룰 (src/control/health_manager.py:25-76):
        is_in_wez = (ata < 12°) AND (500ft ≤ dist ≤ 3000ft)
        D = 25.0 · w_ata · w_dist    if in_wez else 0

    NOTE: closure 조건은 *core 게임 룰에 없음*. closure_kts 인자는 backward-compat 만 유지.
          (이전 default closure>0 조건 제거 — *모든 closure 에서 동일 damage*).
    """
    if not (0.0 <= abs(ata_deg) < ATA_LIMIT_DEG):
        return 0.0
    if not (DIST_MIN_FT <= dist_ft <= DIST_MAX_FT):
        return 0.0
    # closure 조건 제거 (core 와 일치)
    return BASE_DPS * w_ata(ata_deg) * w_dist(dist_ft)


def damage_diff(ata_us_deg: float, ata_them_deg: float,
                dist_ft: float, closure_kts: float = 1.0) -> float:
    """D_us - D_them — 우리에게 유리한 양수, 불리한 음수.

    closure 부호는 sign(closure) 로 양쪽 동일하게 적용 (대칭 가정).
    실제는 D_them 의 closure 는 -closure (적 시점) 이지만, 본 함수는 simplification.
    """
    d_us = damage_rate(ata_us_deg, dist_ft, closure_kts=max(closure_kts, 0.01))
    d_them = damage_rate(ata_them_deg, dist_ft, closure_kts=max(-closure_kts, 0.01))
    return d_us - d_them


# ─── self-test ─────────────────────────────────────────────────────

def _self_test():
    """Sanity — core (src/control/health_manager.py) 와 일치 검증."""
    # Peak: D(ATA=0°, dist=500ft) = 25.0 HP/s (가까울수록 max, sweet spot 없음)
    assert damage_rate(0.0, 500.0) == 25.0, f"D(0°, 500ft) ≠ 25.0"
    print(f"  Peak: D(0°, 500ft) = 25.0 PASS (core: max damage at min range)")

    # core 공식: D = 25 × (3000-dist)/2500 × (1 - ata/12)
    # ATA=3°, dist=1500 → 25 × (3000-1500)/2500 × (1 - 3/12) = 25 × 0.6 × 0.75 = 11.25
    val = damage_rate(3.0, 1500.0)
    expected = 25.0 * (3000.0 - 1500.0) / 2500.0 * (1.0 - 3.0/12.0)
    assert abs(val - expected) < 1e-6, f"D(3°, 1500) = {val} != {expected}"
    print(f"  D(ATA=3°, dist=1500ft) = {val:.4f} HP/s (core 공식 일치) PASS")

    # 경계
    assert damage_rate(12.0, 1500.0) == 0.0
    assert damage_rate(0.0, 3000.0) == 0.0
    print(f"  Boundary: D(12°, *) = 0, D(*, 3000ft) = 0 PASS")

    # w_dist 형태 (선형 감소)
    assert abs(w_dist(500.0) - 1.0) < 1e-9
    assert abs(w_dist(1750.0) - 0.5) < 1e-9
    assert abs(w_dist(3000.0) - 0.0) < 1e-9
    print(f"  w_dist linear: 500→1.0, 1750→0.5, 3000→0.0 PASS")
    print("\n[wez_damage_rate] ALL PASS — core 와 정확 일치")


if __name__ == "__main__":
    _self_test()
