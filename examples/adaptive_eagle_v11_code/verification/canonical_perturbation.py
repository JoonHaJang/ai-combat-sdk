"""
canonical_perturbation.py — Bounded perturbation operator P(x_0; δ).

모든 verification 방법론(metamorphic, SMC, STL falsification 등)이 공유하는
기반 sampler. canonical 초기 조건(scripts/run_match.py와 일치)에서 정의된
δ-bound 안의 시나리오만 생성.

수식:
    P(x_0; δ) = { x | ‖x − x_canonical‖_axis ≤ δ_axis  for each axis }

Reference: ../VERIFICATION_METHODOLOGY.md §4
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterator, Optional

import numpy as np


# ─── Canonical 초기 조건 (run_match.py 표준과 정확 일치) ──────────────────
# 출처: 사용자 지시 + JSBSim configs/1v1/NoWeapon/*.yaml 실측
CANONICAL_SPD_KTS  = 386.8     # ego, enemy 동일 초기 속도
CANONICAL_ALT_FT   = 15000.0   # 동일 초기 고도
CANONICAL_DIST_FT  = 3297.6    # ego(원점) → enemy(동쪽) 거리
CANONICAL_EGO_HDG  = 0.0       # 북향
CANONICAL_ENM_HDG  = 180.0     # 남향 → HCA=180°, AA=90°, ATA=90°, cl=0


@dataclass
class PerturbationBound:
    """δ_bound — canonical 주변 허용 변동 폭.

    기본값은 보수적 (실 매치 산포 측정 전 잠정값).
    δ_bound = 0 → 정확 canonical 단일점.
    """
    pos_ft:    float = 50.0    # x, y 위치 산포 (각 축 독립)
    alt_ft:    float = 100.0   # z(고도) 산포
    spd_kts:   float = 5.0     # 속도 산포
    hdg_deg:   float = 1.0     # 헤딩 산포

    # 적 정책 분포 (sampling 가중치)
    policy_weights: dict[str, float] = field(default_factory=lambda: {
        "passive":   0.20,
        "orbiting":  0.20,
        "defensive": 0.20,
        "offensive": 0.20,
        "evading":   0.20,
    })

    @classmethod
    def zero(cls) -> "PerturbationBound":
        """δ=0 — 정확 canonical 단일점 검증용."""
        return cls(pos_ft=0, alt_ft=0, spd_kts=0, hdg_deg=0)

    @classmethod
    def relaxed(cls) -> "PerturbationBound":
        """더 넓은 bound — sensitivity 분석용 (정식 P 밖)."""
        return cls(pos_ft=200, alt_ft=500, spd_kts=15, hdg_deg=3)


DEFAULT_BOUND = PerturbationBound()


# ─── 정확 canonical 초기 조건 ─────────────────────────────────────────────

def canonical_init() -> dict:
    """sim_dogfight_verify.run_scenario 가 받는 init dict, δ=0 정확 canonical."""
    return {
        "own":   (0.0, 0.0, CANONICAL_ALT_FT,
                  CANONICAL_EGO_HDG, 0.0, CANONICAL_SPD_KTS),
        "enemy": (CANONICAL_DIST_FT, 0.0, CANONICAL_ALT_FT,
                  CANONICAL_ENM_HDG, 0.0, CANONICAL_SPD_KTS),
        "e_diff": 0.0,
        "desc":  "canonical (exact, δ=0)",
    }


# ─── Sampling ──────────────────────────────────────────────────────────────

def sample_init(bound: PerturbationBound = DEFAULT_BOUND,
                rng: Optional[np.random.Generator] = None) -> dict:
    """P(x_0; bound)에서 1개 init 추출 (균등 분포)."""
    if rng is None:
        rng = np.random.default_rng()

    def u(b: float) -> float:
        return float(rng.uniform(-b, b)) if b > 0 else 0.0

    own = (
        u(bound.pos_ft),                                 # x
        u(bound.pos_ft),                                 # y
        CANONICAL_ALT_FT  + u(bound.alt_ft),             # z
        (CANONICAL_EGO_HDG + u(bound.hdg_deg)) % 360.0,  # hdg
        0.0,                                             # gamma
        CANONICAL_SPD_KTS + u(bound.spd_kts),            # spd
    )
    enemy = (
        CANONICAL_DIST_FT + u(bound.pos_ft),
        u(bound.pos_ft),
        CANONICAL_ALT_FT  + u(bound.alt_ft),
        (CANONICAL_ENM_HDG + u(bound.hdg_deg)) % 360.0,
        0.0,
        CANONICAL_SPD_KTS + u(bound.spd_kts),
    )
    return {"own": own, "enemy": enemy, "e_diff": 0.0, "desc": "canonical_perturbed"}


def sample_policy(bound: PerturbationBound = DEFAULT_BOUND,
                  rng: Optional[np.random.Generator] = None) -> str:
    """policy_weights 분포에서 적 정책 1개 추출."""
    if rng is None:
        rng = np.random.default_rng()
    keys = list(bound.policy_weights.keys())
    weights = np.array([bound.policy_weights[k] for k in keys], dtype=float)
    weights = weights / weights.sum()
    idx = rng.choice(len(keys), p=weights)
    return keys[idx]


def iter_samples(n: int,
                 bound: PerturbationBound = DEFAULT_BOUND,
                 seed: int = 0) -> Iterator[tuple[dict, str]]:
    """N개 (init, policy) 쌍 generator. 재현성 위해 seed 고정."""
    rng = np.random.default_rng(seed)
    for _ in range(n):
        yield sample_init(bound, rng), sample_policy(bound, rng)


# ─── Grid sampling (deterministic) ────────────────────────────────────────

def grid_init(n_per_axis: int = 3,
              bound: PerturbationBound = DEFAULT_BOUND) -> Iterator[dict]:
    """Bound 안 grid sampling — deterministic 커버리지용.

    n_per_axis=3 ⇒ 각 perturbed 축 3 grid points (-bound, 0, +bound).
    축이 6개(ego_x,y,z,spd, enemy_x,y,z,spd 등) 변동 시 3⁶ = 729 cases.
    """
    def axis(b: float):
        return [-b, 0.0, b] if b > 0 else [0.0]

    for ego_x in axis(bound.pos_ft):
     for ego_y in axis(bound.pos_ft):
      for ego_z_d in axis(bound.alt_ft):
       for ego_spd_d in axis(bound.spd_kts):
        for enm_x_d in axis(bound.pos_ft):
         for enm_y in axis(bound.pos_ft):
          for enm_z_d in axis(bound.alt_ft):
           for enm_spd_d in axis(bound.spd_kts):
            yield {
                "own": (ego_x, ego_y, CANONICAL_ALT_FT + ego_z_d,
                        CANONICAL_EGO_HDG, 0.0, CANONICAL_SPD_KTS + ego_spd_d),
                "enemy": (CANONICAL_DIST_FT + enm_x_d, enm_y, CANONICAL_ALT_FT + enm_z_d,
                          CANONICAL_ENM_HDG, 0.0, CANONICAL_SPD_KTS + enm_spd_d),
                "e_diff": 0.0,
                "desc": "canonical_grid",
            }


# ─── Sanity check ──────────────────────────────────────────────────────────

def verify_init_in_bound(init: dict, bound: PerturbationBound) -> tuple[bool, list[str]]:
    """init 이 P(x_0; bound) 안에 있는지 검증.

    Returns:
        (passed, violation_list).
    """
    ox, oy, oz, ohdg, _, ospd = init["own"]
    ex, ey, ez, ehdg, _, espd = init["enemy"]
    violations = []

    eps = 1e-3  # 부동소수점 여유
    for name, val, ref, b in [
        ("ego.x",   ox, 0.0,                b.pos_ft if (b:=bound) else 0),
        ("ego.y",   oy, 0.0,                bound.pos_ft),
        ("ego.z",   oz, CANONICAL_ALT_FT,   bound.alt_ft),
        ("ego.spd", ospd, CANONICAL_SPD_KTS,bound.spd_kts),
        ("enm.x",   ex, CANONICAL_DIST_FT,  bound.pos_ft),
        ("enm.y",   ey, 0.0,                bound.pos_ft),
        ("enm.z",   ez, CANONICAL_ALT_FT,   bound.alt_ft),
        ("enm.spd", espd, CANONICAL_SPD_KTS,bound.spd_kts),
    ]:
        if abs(val - ref) > b + eps:
            violations.append(f"{name}={val:.2f} (ref={ref}, |Δ|={abs(val-ref):.2f} > bound {b})")

    # hdg는 modular
    def hdg_dist(a, b):
        d = abs((a - b) % 360.0)
        return min(d, 360.0 - d)
    if hdg_dist(ohdg, CANONICAL_EGO_HDG) > bound.hdg_deg + eps:
        violations.append(f"ego.hdg={ohdg} (ref={CANONICAL_EGO_HDG})")
    if hdg_dist(ehdg, CANONICAL_ENM_HDG) > bound.hdg_deg + eps:
        violations.append(f"enm.hdg={ehdg} (ref={CANONICAL_ENM_HDG})")

    return len(violations) == 0, violations


if __name__ == "__main__":
    # 빠른 자가 검증
    print("=== canonical_init ===")
    print(canonical_init())
    print()
    print("=== 5개 perturbation samples (default bound) ===")
    rng = np.random.default_rng(42)
    for i in range(5):
        init = sample_init(DEFAULT_BOUND, rng)
        ok, viol = verify_init_in_bound(init, DEFAULT_BOUND)
        print(f"  [{i}] in_bound={ok}  own={init['own']}")
        if not ok:
            print(f"      violations: {viol}")
    print()
    print("=== Grid: %d cells (n_per_axis=3, default bound) ==="
          % sum(1 for _ in grid_init(3, DEFAULT_BOUND)))
