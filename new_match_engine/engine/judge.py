"""Judge + WEZ — 심판 규칙 (원본 ai-combat-core 정확 복제).

★★★ 심판 규칙이므로 원본과 100% 일치해야 함. 단위·공식·우선순위 검증 필수.

원본 출처 (songhyonkim/ai-combat-core):
  - src/control/health_manager.py : WeaponEngagementZone (WEZ 데미지)
  - src/match/judge.py            : MatchJudge (승패 판정)
  - src/control/combat_geometry.py: ATA 계산
  - src/utils/units.py L162-166   : 상수

단위 변환 정합 (원본 내부=m, 우리=ft):
  WEZ 데미지 factor는 비율이라 m↔ft 무관:
    distance_factor = (MAX−d)/(MAX−MIN) — m이든 ft이든 동일값.
    증명: (914.4−d_m)/762 = (3000−d_ft)/2500  (d_m=d_ft·0.3048).
  → ft 기준으로 구현 (우리 obs 단위와 일치, 변환 0).

WEZ 데미지 공식 (원본 health_manager.py):
  is_in_wez = (ata < 12°) AND (500ft ≤ dist ≤ 3000ft)
  distance_factor = (3000 − dist_ft) / (3000 − 500)      # = /2500
  angle_factor    = 1 − ata_deg / 12
  damage_per_sec  = 25.0 × distance_factor × angle_factor   # HP/s
  damage          = damage_per_sec × dt                     # HP

★ ATA = 공격자 nose → 적 각도 (공격자 velocity 와 LOS=적−공격자 사이 각).
  ego가 enm 공격 → compute_obs(ego,enm).ata_deg (ego nose→enm).
  enm가 ego 공격 → compute_obs(enm,ego).ata_deg (enm nose→ego).
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
from dataclasses import dataclass, field
from enum import Enum

from tactic import (
    HARD_DECK_FT, WEZ_MIN_FT, WEZ_MAX_FT, WEZ_ATA_DEG,
    DAMAGE_RATE_HP_S, INITIAL_HEALTH, MATCH_DURATION_S,
)

_RANGE_SPAN_FT = WEZ_MAX_FT - WEZ_MIN_FT   # 2500 ft (원본 762m 와 비율동일)


# ── WEZ ────────────────────────────────────────────────────────────────────
def is_in_wez(ata_deg: float, dist_ft: float) -> bool:
    """원본 WeaponEngagementZone.is_in_wez — 3조건 AND.

    ata_deg : 공격자 nose→적 각도 (°)
    dist_ft : 공격자-적 거리 (ft)
    """
    return (ata_deg < WEZ_ATA_DEG
            and dist_ft >= WEZ_MIN_FT
            and dist_ft <= WEZ_MAX_FT)


def wez_damage(ata_deg: float, dist_ft: float, dt: float) -> float:
    """원본 WeaponEngagementZone.calculate_damage — HP 데미지.

    ata_deg : 공격자 nose→적 (°)
    dist_ft : 거리 (ft)
    dt      : 적분 시간 (s)
    반환    : 데미지 (HP), WEZ 밖이면 0.0
    """
    if not is_in_wez(ata_deg, dist_ft):
        return 0.0
    distance_factor = (WEZ_MAX_FT - dist_ft) / _RANGE_SPAN_FT   # 1.0@500ft → 0.0@3000ft
    angle_factor    = 1.0 - ata_deg / WEZ_ATA_DEG               # 1.0@0° → 0.0@12°
    return DAMAGE_RATE_HP_S * distance_factor * angle_factor * dt


# ── Health ──────────────────────────────────────────────────────────────────
@dataclass
class HealthGauge:
    """원본 HealthGauge — 체력 관리."""
    health: float = INITIAL_HEALTH
    damage_dealt: float = 0.0
    damage_taken: float = 0.0

    def take_damage(self, dmg: float):
        self.health = max(0.0, self.health - dmg)
        self.damage_taken += dmg

    def deal_damage(self, dmg: float):
        self.damage_dealt += dmg

    def is_alive(self) -> bool:
        return self.health > 0.0


# ── Judge ─────────────────────────────────────────────────────────────────
class Victory(Enum):
    HEALTH_ZERO         = "health_zero"       # 적 HP ≤ 0
    HEALTH_ADVANTAGE    = "health_adv"        # 시간초과 + HP 우위
    HARD_DECK_VIOLATION = "hard_deck"         # 적이 1000ft 미만
    TIMEOUT             = "timeout"           # 시간초과, 동일 HP
    SIMULTANEOUS_KO     = "simultaneous_ko"   # 양쪽 HP ≤ 0
    DRAW                = "draw"              # 양쪽 규칙위반
    NONE                = "none"             # 진행중


@dataclass
class JudgeResult:
    winner: str | None         # "agent1" / "agent2" / "draw" / None
    condition: Victory


def judge(alt1_ft: float, alt2_ft: float,
          health1: float, health2: float,
          step: int, max_steps: int) -> JudgeResult:
    """원본 MatchJudge.judge — 우선순위 순서대로 판정.

    우선순위: (1) Hard Deck → (2) Health=0 → (3) Timeout/HP우위.
    원본 judge.py L52-90 와 동일.
    """
    # 1. Hard Deck (최우선)
    a1_hd = alt1_ft < HARD_DECK_FT
    a2_hd = alt2_ft < HARD_DECK_FT
    if a1_hd and a2_hd:
        return JudgeResult("draw", Victory.DRAW)
    if a1_hd:
        return JudgeResult("agent2", Victory.HARD_DECK_VIOLATION)
    if a2_hd:
        return JudgeResult("agent1", Victory.HARD_DECK_VIOLATION)

    # 2. Health Zero
    a1_ko = health1 <= 0.0
    a2_ko = health2 <= 0.0
    if a1_ko and a2_ko:
        return JudgeResult("draw", Victory.SIMULTANEOUS_KO)
    if a1_ko:
        return JudgeResult("agent2", Victory.HEALTH_ZERO)
    if a2_ko:
        return JudgeResult("agent1", Victory.HEALTH_ZERO)

    # 3. Timeout / Health Advantage (최하위)
    if step >= max_steps:
        if health1 > health2:
            return JudgeResult("agent1", Victory.HEALTH_ADVANTAGE)
        if health2 > health1:
            return JudgeResult("agent2", Victory.HEALTH_ADVANTAGE)
        return JudgeResult("draw", Victory.TIMEOUT)

    # 4. 진행중
    return JudgeResult(None, Victory.NONE)


# ══════════════════════════════════════════════════════════════════════════
# 검증 — 원본 공식과 정확 일치 확인
# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  Judge/WEZ 심판규칙 검증 (원본 ai-combat-core 대조)")
    print("=" * 60)
    fails = 0

    def chk(cond, label, detail=""):
        global fails
        tag = "✅" if cond else "❌"
        if not cond: fails += 1
        print(f"  {tag}  {label}" + (f"  [{detail}]" if detail else ""))

    # ── WEZ 데미지 (원본 공식 정확값) ────────────────────────────────────
    print("\n[WEZ 데미지 — dt=0.2s]")
    # 최대: 500ft, 0° → 25*1*1*0.2 = 5.0 HP
    d = wez_damage(0.0, 500.0, 0.2)
    chk(abs(d - 5.0) < 1e-9, "최대 데미지 (500ft, 0°)", f"{d:.4f} HP (기대 5.0)")

    # 최대거리: 3000ft → 0 (경계 df=0)
    d = wez_damage(0.0, 3000.0, 0.2)
    chk(abs(d - 0.0) < 1e-9, "최대거리 3000ft → df=0", f"{d:.4f} HP")

    # WEZ 각도 경계: ata=12 → af=0 (is_in_wez 도 false: 12<12 false)
    d = wez_damage(12.0, 500.0, 0.2)
    chk(abs(d - 0.0) < 1e-9, "ata=12° (경계, WEZ 밖)", f"{d:.4f} HP")

    # 중간점: 1750ft, 6° → df=0.5, af=0.5, 25*0.25*0.2=1.25
    d = wez_damage(6.0, 1750.0, 0.2)
    chk(abs(d - 1.25) < 1e-9, "중간 (1750ft, 6°)", f"{d:.4f} HP (기대 1.25)")

    # 거리 밖: 499ft → WEZ 밖
    chk(wez_damage(0.0, 499.0, 0.2) == 0.0, "499ft (WEZ 밖, <500)")
    chk(wez_damage(0.0, 3001.0, 0.2) == 0.0, "3001ft (WEZ 밖, >3000)")

    # is_in_wez 3조건
    chk(is_in_wez(11.9, 500.0) is True,  "is_in_wez(11.9°, 500ft) True")
    chk(is_in_wez(12.0, 500.0) is False, "is_in_wez(12.0°, 500ft) False (ata 경계)")
    chk(is_in_wez(0.0, 152.0) is False,  "is_in_wez(0°, 152ft) False (거리 미만)")

    # dt 비례 확인 (적분 정합)
    d1 = wez_damage(0.0, 500.0, 0.1)
    d2 = wez_damage(0.0, 500.0, 0.2)
    chk(abs(d2 - 2*d1) < 1e-9, "dt 비례 (0.2 = 2×0.1)", f"{d1:.3f}, {d2:.3f}")

    # ── Judge 우선순위 ───────────────────────────────────────────────────
    print("\n[Judge 승패 판정]")
    MS = 1500
    # Hard deck 최우선 (HP 우위여도 hard deck 패배)
    r = judge(900.0, 15000.0, 100.0, 50.0, 100, MS)  # agent1 hard deck, but HP높음
    chk(r.winner == "agent2" and r.condition == Victory.HARD_DECK_VIOLATION,
        "Hard Deck 최우선 (HP 우위 무시)", f"{r.winner}/{r.condition.value}")

    # 양쪽 hard deck → draw
    r = judge(900.0, 800.0, 100.0, 100.0, 100, MS)
    chk(r.winner == "draw" and r.condition == Victory.DRAW, "양쪽 Hard Deck → draw")

    # Health zero
    r = judge(15000.0, 15000.0, 0.0, 50.0, 100, MS)
    chk(r.winner == "agent2" and r.condition == Victory.HEALTH_ZERO, "agent1 HP=0 → agent2 승")

    # 양쪽 KO
    r = judge(15000.0, 15000.0, 0.0, 0.0, 100, MS)
    chk(r.winner == "draw" and r.condition == Victory.SIMULTANEOUS_KO, "양쪽 KO → simultaneous")

    # Timeout HP 우위
    r = judge(15000.0, 15000.0, 80.0, 50.0, 1500, MS)
    chk(r.winner == "agent1" and r.condition == Victory.HEALTH_ADVANTAGE, "Timeout HP우위 → agent1")

    # Timeout 동일 HP → draw
    r = judge(15000.0, 15000.0, 60.0, 60.0, 1500, MS)
    chk(r.winner == "draw" and r.condition == Victory.TIMEOUT, "Timeout 동일HP → draw")

    # 진행중
    r = judge(15000.0, 15000.0, 100.0, 100.0, 100, MS)
    chk(r.winner is None and r.condition == Victory.NONE, "진행중 → None")

    print("\n" + "=" * 60)
    if fails == 0:
        print("  ✅ ALL PASS — 심판규칙 원본 일치 확인")
    else:
        print(f"  ❌ {fails} 실패")
    print("=" * 60)
    sys.exit(fails)
