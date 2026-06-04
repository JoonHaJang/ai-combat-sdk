"""프로젝트 bt_zoo 를 새 엔진 native 적으로 포팅 (simple/aggressive/defensive/ace).

★ 출처: ai-combat-sdk/examples/{simple,aggressive,defensive,ace}.yaml (구엔진 BT).
  구엔진 action/condition → 우리 Tactic/obs 충실 매핑:
    Pursue→PURE_PURSUIT, LeadPursuit→LEAD_PURSUIT, LagPursuit→LAG_PURSUIT,
    GunAttack→GUN_TRACK, BreakTurn→BREAK_TURN, DefensiveManeuver→BREAK_TURN,
    OneCircleFight→ONE_CIRCLE, HighYoYo→HIGH_YOYO, AltitudeAdvantage/ClimbingTurn/
    ClimbTo→HIGH_YOYO(상승), Accelerate→(Pursue 가 이미 sprint).
  조건: DistanceBelow/Above→distance_ft, ATABelow/Above→ata_deg,
    UnderThreat(aa_thr)→aa_deg, IsOffensive/Defensive/Neutral→advantage.

각 적 함수: opp 자신의 obs (o21=compute_obs(opp,us)) → Tactic. Match 가 tactic_fn2 로 호출.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

from tactic import Tactic, HARD_DECK_FT, WEZ_MIN_FT, WEZ_MAX_FT

# 상황 임계 (구엔진 BFMSituation 근사 — advantage 기반)
ADV_OFF = 0.25    # advantage > → IsOffensiveSituation
ADV_DEF = -0.25   # advantage < → IsDefensiveSituation


def _below_hard_deck(o):
    return o.ego_alt_ft < HARD_DECK_FT + 200.0   # 약간 마진


# ── simple: HardDeck 회피 + Pursue ────────────────────────────────────────
def simple(o) -> Tactic:
    if _below_hard_deck(o):
        return Tactic.CLIMB              # ★ ClimbTo (wings-level 최대 상승)
    return Tactic.PURE_PURSUIT           # Pursue


# ── aggressive: 거리 불문 적극 추적 (가속) ────────────────────────────────
def aggressive(o) -> Tactic:
    if _below_hard_deck(o):
        return Tactic.CLIMB              # ★ EmergencyClimb (ClimbTo)
    # 근/중/원거리 모두 Pursue(+Accelerate). PURE_PURSUIT 가 chase PID 로 이미 sprint.
    return Tactic.PURE_PURSUIT


# ── defensive: 위협 시 방어기동 → 안전하면 추적 ───────────────────────────
def defensive(o) -> Tactic:
    if o.aa_deg > 120.0:                 # UnderThreat (적이 우리 뒤 정면노출)
        return Tactic.BREAK_TURN         # DefensiveManeuver
    if _below_hard_deck(o):
        return Tactic.CLIMB              # ★ ClimbTo
    if o.ego_alt_ft < 984.0:
        return Tactic.CLIMB              # AltitudeAdvantage (고도 회복)
    if o.distance_ft < 6562.0:
        return Tactic.LEAD_PURSUIT       # 안전+근거리 → 공격 전환
    return Tactic.PURE_PURSUIT           # 기본 추적


# ── ace: BFM 상황인식 + Gun WEZ + 에너지 (최강) ──────────────────────────
def ace(o) -> Tactic:
    # 1. Hard Deck
    if _below_hard_deck(o):
        return Tactic.CLIMB              # ★ ClimbTo (wings-level 상승)
    # 2. Gun WEZ (dist 500~3000, ata<15) → 정밀 공격
    if WEZ_MIN_FT <= o.distance_ft <= WEZ_MAX_FT and o.ata_deg < 15.0:
        return Tactic.GUN_TRACK
    # 3. DBFM (방어) — advantage 열세
    if o.advantage < ADV_DEF:
        if o.aa_deg > 130.0:
            return Tactic.BREAK_TURN            # 심각 위협 급선회
        if o.aa_deg > 100.0:
            return Tactic.BREAK_TURN            # DefensiveManeuver
        if o.ego_alt_ft < 16404.0:
            return Tactic.HIGH_YOYO             # 고도 열세 에너지 확보
        return Tactic.HIGH_YOYO                 # AltitudeAdvantage
    # 4. OBFM (공격) — advantage 우세
    if o.advantage > ADV_OFF:
        if o.distance_ft < 4921.0:
            return Tactic.LEAD_PURSUIT
        if o.distance_ft < 9843.0 and o.ata_deg > 30.0:
            return Tactic.ONE_CIRCLE
        if o.distance_ft < 13123.0:
            return Tactic.LAG_PURSUIT
        return Tactic.PURE_PURSUIT              # 원거리 추적(+고도)
    # 5. HABFM (중립/정면)
    if o.ego_alt_ft < 11483.0:
        return Tactic.HIGH_YOYO                 # ClimbingTurn
    if o.ata_deg > 60.0:
        return Tactic.HIGH_YOYO                 # Lufbery 탈출
    if o.distance_ft < 8202.0:
        return Tactic.ONE_CIRCLE
    return Tactic.LEAD_PURSUIT


# 레지스트리 (situation_matrix·rollout 검증용)
OPPONENT_BTS = {
    "simple":     simple,
    "aggressive": aggressive,
    "defensive":  defensive,
    "ace":        ace,
}


if __name__ == "__main__":
    # 각 적이 상황별로 무엇을 내는지 sanity check
    from scenarios import SITUATIONS
    from obs import compute_obs
    print("적 BT sanity — 상황별 선택 tactic (opp 관점):")
    print(f"{'opponent':<12}" + "".join(f"{s:>14}" for s in SITUATIONS))
    for name, fn in OPPONENT_BTS.items():
        cells = []
        for s, sp in SITUATIONS.items():
            p1, p2 = sp()
            o21 = compute_obs(p2, p1)   # opp 관점
            cells.append(fn(o21).name)
        print(f"{name:<12}" + "".join(f"{c:>14}" for c in cells))
