"""Tactic enum + 상수 — 새 매치 엔진 단위 단일 진실(single source of truth).

참조:
  - NAVAIR 00-80T-105 (Naval Air Training Command BFM)
  - AFTTP 3-3.F-16 (USAF Tactical Employment)
  - liuqh16/LAG (JSBSim BFM env, get_AO_TA_R geometry)
  - Wikipedia: Basic fighter maneuvers

단위 규칙 (이 파일 및 guidance.py 전체):
  각도  → 도(°)          | JSBSim 내부는 rad, 경계에서 변환 (autopilot.py 전담)
  heading → 0~360°, 절대  | 항공 관례 시계방향 증가
  고도  → ft MSL, 절대    | AGL 아님
  속도  → kts (vc), 절대  | JSBSim 내부는 fps, autopilot.py 에서 변환
  거리  → ft              | 내부 계산 단일화
  선회율→ °/s, 우+=, 좌-= |
"""
from __future__ import annotations
from enum import IntEnum


class Tactic(IntEnum):
    # ── 공격 ──────────────────────────────────────────────────────────
    LEAD_PURSUIT          = 0   # nose 앞 — gun solution 준비
    PURE_PURSUIT          = 1   # nose → 현재 적 위치 — closure 유지
    LAG_PURSUIT           = 2   # nose 뒤 — 선회전 유지·에너지 보존
    LAG_DISPLACEMENT_ROLL = 3   # overshoot 직전 lift-vector 이탈 — 포지션 유지
    GUN_TRACK             = 4   # ATA<20°, WEZ 내 — 연속 정밀 lead angle
    # ── 중립 선회 ─────────────────────────────────────────────────────
    ONE_CIRCLE            = 5   # 양측 반대 방향 (angles fight)
    TWO_CIRCLE            = 6   # 양측 같은 방향 (radius fight)
    SCISSORS              = 7   # overshoot 교착 반전 반복 — 방향전환 속도 승부
    # ── 수직 ──────────────────────────────────────────────────────────
    HIGH_YOYO             = 8   # 에너지 과잉·overshoot → 상승+감속, 선회전 유지
    LOW_YOYO              = 9   # closure 부족·에너지 저하 → 강하+가속
    # ── 방어 ──────────────────────────────────────────────────────────
    BREAK_TURN            = 10  # max-G defensive break 90° — WEZ 이탈
    EXTENSION             = 11  # 이탈 직진 — 에너지 회복, 속도 최대
    # ── 기본 ──────────────────────────────────────────────────────────
    LEVEL_FLIGHT          = 12  # 전환·초기화·기본값
    CLIMB                 = 13  # ★ ClimbTo 포팅 — wings-level 최대 상승(HardDeck 회피)
    HEADON                = 14  # ★ 정면 merge 전용 — max-rate lead turn, gun 우선(에너지 무관)
    ADAPTIVE              = 15  # ★ τ-블렌딩(v11 이식) — lag↔pursuit↔yoyo 연속 합성, 적 기동 적응
    VERTICAL_PURSUIT      = 16  # ★ evasive extender 전용 — pure 추격 + 적 고도 추종(zoom 따라붙음)
    TIGHT_TURN            = 17  # ★ 최소반경 angles turn — 저속(V_RADIUS)으로 *반경* 최소화 (one-circle radius fight)
    LEAD_TURN             = 18  # ★ 머지 전환 — 적 미래위치로 tight cutoff (직진통과·거리확장 방지, Shaw BFM)


# ── 엔진 규칙 상수 (원본 judge.py/wez_engine.py/health_manager.py 일치 — 변경 금지) ─
# 원본 내부단위=m. 전부 ft 정확변환값(500ft=152.4m 등)이라 ft 기준 비율 동일.
# 출처: songhyonkim/ai-combat-core src/utils/units.py L162-166, health_manager.py
HARD_DECK_FT      = 1000.0   # ft MSL (=304.8m). 미만 = 즉시 패배
WEZ_MIN_FT        = 500.0    # ft (=152.4m). gun WEZ 최소거리
WEZ_MAX_FT        = 3000.0   # ft (=914.4m). gun WEZ 최대거리
WEZ_ATA_DEG       = 12.0     # ° gun WEZ 각도 (공격자 nose→적)
DAMAGE_RATE_HP_S  = 25.0     # HP/s 최대 데미지율 (152.4m·0° 기준)
INITIAL_HEALTH    = 100.0    # HP 초기 체력
MATCH_DURATION_S  = 300.0    # s 매치 기본 길이 (5분)

# ── F-16 성능 상수 (§10 실측 기반) ────────────────────────────────────
V_CORNER_KTS    = 320.0     # kts — max sustained turn RATE 속도 (max-rate corner; 큰 반경)
V_RADIUS_KTS    = 260.0     # ★ kts — 최소 선회반경 속도 (min-radius; 코너보다 느려야 반경↓). TIGHT_TURN/LEAD_TURN용
V_MAX_KTS       = 420.0     # kts — 최대 속도 (vel4 ≈ 398kt + 마진)
V_TRIM_KTS      = 350.0     # kts — 기본 trim 속도
V_MIN_KTS       = 150.0     # kts — 실속 마진

# ── Guidance 파라미터 (튜닝 가능) ─────────────────────────────────────
# HIGH/LOW YOYO
YOYO_CLIMB_FT       = 3000.0  # ft — 상승 목표 변화량
CLIMB_TARGET_FT     = 10000.0 # ft — CLIMB tactic 목표고도 (HardDeck 회피, 강한 상승)
YOYO_DESCENT_FT     = 2000.0  # ft — 강하 목표 변화량
YOYO_DV_KTS         = 40.0    # kts — 속도 변화량

# SCISSORS
SCISSORS_TURN_DEG   = 60.0    # ° — 반전 선회각 (각 방향)
SCISSORS_VERT_FT    = 1000.0  # ft — 수직 scissors 진동량
SCISSORS_H_MARGIN_FT= 3000.0  # ft — 수직 scissors 최소 고도 여유 (HARD_DECK 기준)

# LAG_DISPLACEMENT_ROLL
LDR_TURN_DEG        = 120.0   # ° — lift-vector 이탈 선회각
LDR_CLIMB_FT        = 1500.0  # ft — 수직 이탈량

# LEAD_PURSUIT
LEAD_ANGLE_FACTOR   = 0.3     # lead angle = ata_deg * factor (간략화)
LEAD_DV_KTS         = 20.0    # kts — 가속 마진

# 추격 가속 (closure 낮으면 sprint — 동속 적 run down)
PURSUIT_CLOSE_KTS   = 50.0    # kts — closure < 이값이면 v*=V_MAX sprint

# BREAK / EXTENSION
BREAK_TURN_DEG      = 90.0    # ° — break 전환각
EXT_HEADING_DEG     = 180.0   # ° — extension 반전각

# GUN_TRACK
GUN_ENTRY_ATA_DEG   = 20.0    # ° — GUN_TRACK 진입 ATA 임계
GUN_LEAD_TAU_FACTOR = 0.5     # 적 선회 예측: omega_opp * tau * factor
GUN_DV_KTS          = -10.0   # kts — 약간 감속 (overshoot 방지)

# ALTITUDE 제한
H_MAX_FT            = 50000.0 # ft — 최대 고도 제한
H_MIN_FT            = HARD_DECK_FT + 200.0  # ft — 최소 고도 (HARD_DECK + 마진)
