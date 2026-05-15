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


# ─── 분기 진입 임계 (튜닝 가능, 의미는 분기 정의 자체) ──────────
# Cumulative curriculum 의 회귀 표면 — 변경 시 모든 stage 재검증 필요.
ALT_HARD_DECK_FT      = 1200.0   # HardDeck 진입
ATA_THREAT_DEG        = 100.0    # DefensiveBreak: 적 후방반구
DIST_THREAT_FT        = 3000.0   # DefensiveBreak: 근접 위협
ATA_TURNAROUND_DEG    = 90.0     # TurnAround: 적 후방반구
AA_RUNNING_DEG        = 90.0     # TurnAround: README 컨벤션 AA<90 = 적 등돌림(도망)
DIST_MERGE_FT         = 2000.0   # TurnAround/OrbitBreak: merge 구간 배제
ATA_GUN_DEG           = 12.0     # GunEngagement: WEZ 조준각
WEZ_INNER_FT          = 500.0    # GunEngagement: WEZ 내 경계
V_P_RECOVERY_ENTER    = 360.0    # EnergyRecovery 진입 (≈0.82·V_corner(15000ft))
V_P_RECOVERY_EXIT     = 400.0    # EnergyRecovery 탈출 (히스테리시스 deadband)
CLOSURE_OVERSHOOT_KTS = 150.0    # LagPursuit: 빠른 접근
DIST_LAG_FT           = 2500.0   # LagPursuit: overshoot 가능 거리
ATA_OFFENSE_DEG       = 45.0     # OffensivePursuit
AA_TARGET_BACK_DEG    = 100.0    # OffensivePursuit: 적이 등돌림
DIST_OFFENSE_FT       = 4000.0   # OffensivePursuit
ATA_ORBIT_LO_DEG      = 30.0     # OrbitBreak: 락 영역 lower
ATA_ORBIT_HI_DEG      = 110.0    # OrbitBreak: 락 영역 upper
CLOSURE_ORBIT_KTS     = 200.0    # OrbitBreak: 매치드-턴-레이트 락 식별
# ZoomClimb (option C — defensive 도망 시 PE 축적, 후속 dive 로 closing 우위)
ATA_ZOOM_DEG          = 60.0     # ZoomClimb: 적 향함 (pointed)
CLOSURE_RUNNING_KTS   = -50.0    # ZoomClimb: 적이 도망 중 (opening)
DIST_ZOOM_FT          = 5000.0   # ZoomClimb: 장거리 (PE banking 가치)
ALT_ZOOM_CEILING_FT   = 18000.0  # ZoomClimb: alt 여유 (climb room)


# ─── Mode 정의 (PLAN §2.6.2) ────────────────────────────────────

MODES = [
    "HardDeck",        # 안전: alt < 1200ft
    "DefensiveBreak",  # 위협 회피: enm_in_wez/후방반구 → break (v11 이식, safety)
    "TurnAround",      # 적 후방+멀어짐 → 강제 hard-turn (FP-robust, τ-blend 우회)
    "GunEngagement",   # 사격: ATA<12° + WEZ 내 + alignment        → m_2 PN
    "EnergyRecovery",  # 에너지 고갈: V_p<0.82·V_corner → 가속 회복  → m_4 corner (Boyd EM)
    "LagPursuit",      # overshoot 변위: Shaw LDT (m_5)            → m_5 LDT
    "OffensivePursuit",# 공격: ATA<45° + AA>100° + dist<4000        → m_2 PN
    "OrbitBreak",      # orbit-lock 탈출: V_corner 가속 (v11 이식)  → m_3/m_4 corner+pn
    "ZoomClimb",       # 도망적 장거리 추격: PE 축적 (climb), defensive 의 후속 turn 대비
    "TheoremAdaptive", # τ-blend: corner/yoyo/ldt/pn
]


def _denorm_deg(obs: dict, key: str, default: float = 0.0) -> float:
    v = obs.get(key, default)
    return v * 180.0 if abs(v) <= 1.5 else v


def select_branch(obs: dict, alt_ft: float, prev_branch: str = "") -> dict:
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
    overshoot = bool(obs.get("overshoot_risk", False))
    V_p = float(obs.get("ego_vc_kts", 386.8))

    # 1. HardDeck — alt < 1200ft (game-terminal 회피)
    if alt_ft < 1200.0:
        return {"branch": "HardDeck", "reason": f"alt={alt_ft:.0f}<1200",
                "params": {}}

    # 1.5 DefensiveBreak — 위협 회피. HJI 외부 safety branch (PLAN §8 허용).
    #   reactive : enm_in_wez (이미 피격) — 너무 늦음
    #   predictive: ATA>100° (적이 우리 후방반구) ∧ dist<3000ft (근접) — v11 IsLostPursuit 이식.
    #               적이 우리 6시를 잡기 *전에* break.
    threat_reactive = bool(obs.get("enm_in_wez", False))
    threat_predictive = (ata > 100.0 and dist < 3000.0)
    if threat_reactive or threat_predictive:
        return {"branch": "DefensiveBreak",
                "reason": (f"enm_in_wez={threat_reactive} ∨ "
                           f"(ATA={ata:.0f}>100 ∧ dist={dist:.0f}<3000)={threat_predictive}"),
                "params": {"ata": ata, "dist": dist}}

    # 1.7 TurnAround — A0~A4 + A2 모두 시험됨. simple 회귀 OR defensive 무효 — 단일-tick
    #   branch 로는 simple/defensive 분리 못 함 결론. 비활성 (dead weight 제거).
    #   미래 stage: EIM (적 의도 분류, multi-tick) 도입 시 재고려.
    if False and ata > 90.0 and aa > 90.0 and closure < 0.0 and dist > 2000.0:
        return {"branch": "TurnAround",
                "reason": f"ATA={ata:.0f}>90 ∧ AA={aa:.0f}>90 (적 등돌림) ∧ closure={closure:.0f}<0 ∧ dist={dist:.0f}>2000",
                "params": {"ata": ata, "aa": aa, "dist": dist, "closure": closure}}

    # 2. GunEngagement — ATA<12° + WEZ + alignment ok
    # AA>45° 꼬리 추격 시 dist_gun_max=4000 (v11 확장)
    dist_gun_max = 4000.0 if aa > 45.0 else 3000.0
    aligned = (hca < 30.0) or (hca > 150.0) or (aa > 45.0)
    if ata < 12.0 and 500 < dist < dist_gun_max and aligned:
        return {"branch": "GunEngagement",
                "reason": f"ATA={ata:.1f}<12, dist={dist:.0f}∈[500,{dist_gun_max:.0f}], aligned={aligned}",
                "params": {"hca": hca, "aa": aa, "dist": dist}}

    # 2.3 EnergyRecovery — 에너지 고갈 (Boyd EM). 히스테리시스: 진입 360, 탈출 400.
    #   에너지 없이는 기동 제어 불가 → 오버슈트·나쁜 각도. 회복이 추격보다 우선.
    #   진입 360 / 탈출 400 deadband — 한 번 회복 들어가면 버퍼 쌓고 나옴 (chatter 방지).
    #   threshold ≈ 0.82·V_corner(15000ft≈438). GunEngagement 다음 — 쏠 수 있으면 쏘되,
    #   못 쏘면 추격 전에 에너지부터.
    #   주의: EnergyRecovery 진입을 ata/closure 로 게이트하려는 시도는 모두 simple 을
    #   회귀시킴 (simple 은 V_p<360 시 무조건 EnergyRecovery 필요 — load-bearing).
    #   히스테리시스: 진입 360, 탈출 400 (chatter 방지).
    e_enter, e_exit = 360.0, 400.0
    low_energy = V_p < e_enter or (prev_branch == "EnergyRecovery" and V_p < e_exit)
    if low_energy:
        return {"branch": "EnergyRecovery",
                "reason": f"V_p={V_p:.0f} (recovery: enter<{e_enter:.0f} exit>{e_exit:.0f}, prev={prev_branch})",
                "params": {"V_p": V_p, "ata": ata, "dist": dist}}

    # 2.5 LagPursuit — overshoot 위험 (m_5 Shaw Lag Displacement Turn)
    #   bore-in 하면 WEZ 통과/overshoot → lag 으로 변위 누적 후 재진입 (v11 overshoot 분기 이식).
    #   GunEngagement 이 먼저 평가되므로 여기 도달 = 사격 불가 상태.
    if overshoot or (closure > 150.0 and dist < 2500.0):
        return {"branch": "LagPursuit",
                "reason": f"overshoot={overshoot} ∨ (cl={closure:.0f}>150 ∧ dist={dist:.0f}<2500)",
                "params": {"ata": ata, "dist": dist, "closure": closure}}

    # 3. OffensivePursuit — ATA<45° + AA>100° (적 등돌림) + dist<4000
    if ata < 45.0 and aa > 100.0 and dist < 4000.0:
        return {"branch": "OffensivePursuit",
                "reason": f"ATA={ata:.1f}<45, AA={aa:.1f}>100, dist={dist:.0f}<4000",
                "params": {"ata": ata, "aa": aa, "dist": dist, "closure": closure}}

    # 4. OrbitBreak — circular orbit-lock 감지 (v11 CircularOrbitBreak / CustomOrbitDetector 이식)
    #    abeam ATA + 낮은 |closure| + 먼 거리 = matched-turn-rate 락
    #    (PROJECT_OVERVIEW/03 + PLAN §2.5.7 의 핵심 미해결 상태). default τ-blend 보다
    #    먼저 평가 — V_adv 가 락을 못 깬다는 §2.5.7 결론을 구조적으로 우회.
    if 30.0 < ata < 110.0 and abs(closure) < 200.0 and dist > 2000.0:
        return {"branch": "OrbitBreak",
                "reason": f"orbit-lock: ATA={ata:.1f}∈(30,110), |cl|={abs(closure):.0f}<200, dist={dist:.0f}>2000",
                "params": {"ata": ata, "aa": aa, "dist": dist, "closure": closure}}

    # 4.5 ZoomClimb (Option C) — 도망적 장거리 추격 시 PE 축적.
    #   적 향함(ata<60) ∧ 적 도망(closure<-50) ∧ 장거리(dist>5000) ∧ alt 여유(<18000).
    #   defensive 류는 결국 defensive maneuver(turn) 함 — 그때까지 PE 비축, turn 시 dive.
    #   vs simple: simple 은 pursuit (closure>0 다수) → 거의 발동 안 함.
    ego_alt = float(obs.get("ego_altitude_ft", 15000.0))
    if (ata < ATA_ZOOM_DEG and closure < CLOSURE_RUNNING_KTS and
            dist > DIST_ZOOM_FT and ego_alt < ALT_ZOOM_CEILING_FT):
        return {"branch": "ZoomClimb",
                "reason": (f"ATA={ata:.0f}<60 ∧ closure={closure:.0f}<-50 ∧ "
                           f"dist={dist:.0f}>5000 ∧ alt={ego_alt:.0f}<18000"),
                "params": {"ata": ata, "dist": dist, "closure": closure, "alt": ego_alt}}

    # 5. Default — TheoremAdaptive (τ-blend)
    return {"branch": "TheoremAdaptive",
            "reason": "soft τ-blend (PN + corner/yoyo/ldt)",
            "params": {"ata": ata, "aa": aa, "hca": hca, "dist": dist, "closure": closure}}


# ─── Branch-specific 명령 산출 ─────────────────────────────────

def cmd_HardDeck(obs: dict) -> Tuple[float, float, float]:
    """alt < 1200ft → 강제 상승, 수평 유지."""
    # γ̇ = max climb (alt_bin=4), ω = 0 (straight), a = +max (가속)
    return (0.0, math.radians(15.0), 15.0)


def cmd_TurnAround(obs: dict) -> Tuple[float, float, float]:
    """적 후방+도망 → 강제 max-turn 으로 적 향함 (FP-robust 결정적 분기).

    τ-blend 의 약한 PN 명령은 ata~127° 같은 큰 mis-point 에서 FP-민감 — seed 따라
    turn-around 완료 못 함 → defensive draw basin. 여기선 max omega 로 결정적 선회.
      - omega = -copysign(omega_max, rb) → 적 방향으로 max 선회 (RT-1.3 부호 규약)
      - gamma 약하게 적 고도 추종
      - accel = +max (turn 중 가능한 에너지 유지)
    """
    rb = _denorm_deg(obs, "relative_bearing_deg")
    rb_sign = rb if rb != 0.0 else 1.0
    omega = -math.copysign(math.radians(19.0), rb_sign)
    alt_gap = float(obs.get("alt_gap_ft", 0.0))
    gamma_dot = math.radians(0.3 * np.clip(alt_gap / 500.0, -1.0, 1.0) * 8.0)
    accel = 15.0
    return (omega, gamma_dot, accel)


def cmd_DefensiveBreak(obs: dict) -> Tuple[float, float, float]:
    """enm_in_wez → break-turn: 적 반대로 강선회 + 에너지 확보 (v11 SmartBreakTurn 이식).

    위협 회피는 capture(∇V_i)의 반대 — escape. 별도 offensive ∇V 없음 → HardDeck 과
    동일하게 heuristic safety maneuver (PLAN §8: HJI 외부 safety branch 허용).

    적 반대 방향 max 선회: rb>0 (적 우측) → 좌선회 (omega>0, RT-1.3 부호 규약).
    동시에 nose-low + 가속 → 선회 중 에너지 유지.
    """
    rb = _denorm_deg(obs, "relative_bearing_deg")
    # 적 반대로 hard turn: rb>0 (적 우) → omega>0 (좌); rb<0 (적 좌) → omega<0 (우)
    omega = math.copysign(math.radians(19.0), rb if rb != 0.0 else 1.0)
    gamma_dot = math.radians(-3.0)   # 약간 nose-low — 선회 중 속도 유지
    accel = 15.0                     # 가속 — 에너지 확보 (extension)
    return (omega, gamma_dot, accel)


def cmd_GunEngagement(obs: dict, V_p: float, alt_ft: float) -> Tuple[float, float, float]:
    """[DEPRECATED] superseded by `_MODE_TAU["GunEngagement"]={"pn":1.0}` in
    continuous_policy.py (PLAN §2.6.5 — ∇V-derived 명령). 참조 구현으로 유지.

    ATA<12 + WEZ 내 — sustained PN + 코너속도 유지.
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
    """[DEPRECATED] superseded by `_MODE_TAU["OffensivePursuit"]={"pn":1.0}`.
    ATA<45 + AA>100 (적 등돌림) — 적극 추격 + WEZ 진입 시도."""
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


def cmd_ZoomClimb(obs: dict) -> Tuple[float, float, float]:
    """Option C: 도망적 장거리 추격 시 PE 축적 — 적 향해 moderate-turn + climb + accel.

    defensive 류는 결국 defensive maneuver(turn) 함 — 그 순간을 위해 PE 비축.
    적이 turn 하면 우리 dive 로 closing speed advantage 획득 (E-fight 정석).
      - moderate PN heading (적 추적 유지, over-turn 으로 bleed 방지)
      - 강한 climb (gamma_dot+) — PE banking
      - 최대 accel — KE 와 PE 동시 축적
    """
    rb = _denorm_deg(obs, "relative_bearing_deg")
    omega = -math.radians(0.03 * rb)              # moderate pursuit (bleed 최소)
    gamma_dot = math.radians(15.0)                # 강한 상승 (PE 축적)
    accel = 15.0
    return (omega, gamma_dot, accel)


def cmd_OrbitBreak(obs: dict, V_p: float, V_c: float) -> Tuple[float, float, float]:
    """[DEPRECATED] superseded by `_MODE_TAU["OrbitBreak"]={"pn":0.5,"corner":0.5}`.
    Circular orbit-lock 탈출 — 에너지 비대칭 생성 (v11 CircularOrbitBreak 이식).

    matched-turn-rate 락 (양쪽 동일 ω 로 선회) 의 탈출 메커니즘:
      - V_corner 로 가속 → 순간 선회율 최대화 (RT-2 grad_V_corner 의 V_c 추적과 동일 목표).
        적이 sub-optimal (V_corner 추적 안 함) 이면 선회 우위 비대칭 발생 → 락 깨짐.
        (PLAN §2.6.6: 적이 minimax 안 하면 그만큼 우리 advantage)
      - 동시에 적 방향 PN 선회 유지 → 락 탈출 중 각도 손실 방지.
    """
    rb = _denorm_deg(obs, "relative_bearing_deg")
    # 적 방향 강선회 (PN). rb>0=적 우측 → 우선회(omega<0) — RT-1.3 부호 규약.
    K_pn = 0.06
    omega = -math.radians(K_pn * rb)
    # 수직: 적 고도 약하게 추종
    alt_gap = float(obs.get("alt_gap_ft", 0.0))
    gamma_dot = math.radians(0.3 * np.clip(alt_gap / 500.0, -1.0, 1.0) * 10.0)
    # 핵심: V_corner 로 가속해 선회 우위 확보 (V_p < V_c 면 +max, 초과 시 약감속)
    if V_p < V_c - 5.0:
        accel = 15.0
    elif V_p > V_c + 10.0:
        accel = -5.0
    else:
        accel = 0.0
    return (omega, gamma_dot, accel)
