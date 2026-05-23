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
ALT_HARD_DECK_FT      = 1200.0   # HardDeck 진입 (우리 safety margin; core 게임 룰은 1000ft 위반 시 즉시 LOSS, 200ft 여유)
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
    "AggressiveCloseMerge", # B-1 (2026-05-16): trend-based parallel-chase detector → V_T close-merge
    "TheoremAdaptive", # τ-blend: corner/yoyo/ldt/pn
]


def _parallel_chase_signal(obs_history) -> float:
    """B-1 (2026-05-16) — OODA Orient signal.

    *시간차분 기반* parallel-chase Nash 인식. obs_history (≥ 6 frames) 의 trend 로
    "두 행위자가 평행/평형 상태" 판단. Heron Systems 의 close-merge 진입점 동치.

    R2 정합: 분류기 아닌 finite-difference operator. obs_history 직접 사용.
    유도: parallel chase 의 정의 = (closure 평균 ~ 0) ∧ (closure 분산 작음) ∧
                                  (ATA 분산 작음) ∧ (dist 큼, Nash 영역).
    Returns:
        signal ∈ [0, 1]. > 0.7 면 parallel-chase locked.
    """
    # 1.2s window — 10Hz BT 에서 12 frames (upstream 2026-05 변경 후 시간 일관 유지)
    WINDOW_FRAMES = 12
    if obs_history is None or len(obs_history) < WINDOW_FRAMES:
        return 0.0
    win = obs_history[-WINDOW_FRAMES:]
    closures = [float(o.get("closure_rate_kts", 0.0)) for o in win]
    atas = [_denorm_deg(o, "ata_deg") for o in win]
    dists = [float(o.get("distance_ft", 0.0)) for o in win]
    cl_mean = sum(closures) / len(closures)
    cl_std = (sum((c - cl_mean) ** 2 for c in closures) / len(closures)) ** 0.5
    ata_mean = sum(atas) / len(atas)
    ata_std = (sum((a - ata_mean) ** 2 for a in atas) / len(atas)) ** 0.5
    dist_mean = sum(dists) / len(dists)
    # 4 sigmoid 곱 — 모든 4 조건 충족 시만 신호 ~1
    # [D-Obs-2b REVERTED]: closure_std 항 제거 + HISTORY_LEN 12 → ACM 발화율 폭증
    # (defensive 34%, aggressive 24%) 했으나 simple 5W→3W + defensive 3W→0W 평형 깸.
    # 학습: V_T routing 발화 빈도가 simple/defensive load-bearing 평형 깬다 (C1/C2 와 일관).
    # 4 sigmoid 유지 (높은 selectivity 가 simple 보호의 본질). HISTORY_LEN 10 면 항상 부족 →
    # B-1 parallel detector 사실상 비활성. 의도적 — Model A 한계 인정.
    def _sig(z): return 1.0 / (1.0 + math.exp(-z))
    s_cl_mean = _sig((50.0 - abs(cl_mean)) / 20.0)
    s_cl_std = _sig((40.0 - cl_std) / 15.0)
    s_ata_std = _sig((15.0 - ata_std) / 5.0)
    s_dist = _sig((dist_mean - 5000.0) / 1500.0)
    return s_cl_mean * s_cl_std * s_ata_std * s_dist


def _denorm_deg(obs: dict, key: str, default: float = 0.0) -> float:
    v = obs.get(key, default)
    return v * 180.0 if abs(v) <= 1.5 else v


def select_branch(obs: dict, alt_ft: float, prev_branch: str = "",
                   obs_history=None) -> dict:
    """Branch 선택 (PLAN §2.6 의 hard predicate 우선순위).

    v11 의 select_bt_branch 동일 로직 + AA-aware WEZ 확장 + B-1 OODA Orient.

    Args:
        obs_history: rolling obs buffer for trend-based detection (B-1).

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

    # 4.7 LongRangeClosing 시도 REVERTED — entry `dist>5000 ∧ closure>-50 ∧ ata<90`
    #   진단: simple 매치 dist>5000 비율 67.1% (가정 틀림) — 67회 진입 + V_T wrong
    #   direction → simple LOSS 99.45/100.

    # 4.8 LongRangeClosing (C1, 2026-05-16) REVERTED — entry `ata<20 ∧ dist>8000 ∧ closure>-100`.
    #   simple 5W/0L 보존, **defensive 3W → 0W/5D 회귀** (R7 위반). 학습:
    #   defensive 의 WIN 패턴이 Theorem 의 yoyo+pn 평형 기여하던 long-range ata-aligned
    #   영역을 새 분기로 흡수하면서 기존 WIN-yielding 평형 깨짐.
    #   상세: docs/diag/phase2_tau_T_routing_derivation.md §9.

    # 4.83 PatientApproach (2026-05-16, white-box 데이터 발견) — 적 NN throttle 진동 exploit.
    #   발견 (logs/bprime1/aggressive_n1 1s precision): 적 V_e 480↔160 진동 (NN actor instability).
    #     V_e=160 phase 에서 closure +189~+346 (우리 closing). V_e=480 phase 에서 closure 음수.
    #     평균적으로 closure mean ≈ -22 (slight diverge) but *진동 큼*.
    #   가설: 우리가 V_p 보존 (corner mode) + 작은 turn (PN 30%) 하면, 적 V_e 낮은 phase 에서
    #     지속적 closure + → 매치 시간 내 dist 닫음.
    #   이전 C1 (V_T dominant) 과 차이: corner dominant 로 V_p 보존이 핵심 (turn 손실 회피).
    #   entry: tick>50 (초기 phase 후), ata<30 (정렬), dist>8000 (long-range), |closure|<200 (parallel-ish).
    # PatientApproach v3 REVERTED 2026-05-16:
    #   aggressive 발화 50% but dist_min 3298 변화 없음 (corner-dominant turn 으로도 dist 못 줄임).
    #   defensive 발화 85% → baseline 3W→0W catastrophic.
    #   = *수평 macro 의 수학적 wall* — turn rate matching Nash 불가.
    #   진짜 path: ZoomDive (수직 BFM, v11 발견의 적 수직 4s lag exploit).

    # 4.84 BreakInduce (γ, 2026-05-16, 사용자 제안) — 적의 강한 closing 유도 break.
    #   데이터 (logs/bprime1 trajectory): aggressive t=110s 부근 closure=+121, ata≈1.8 (정렬).
    #     simple t=20s 부근 closure=+426, ata≈73 (정렬 안 됨). 이런 시점들이 *적 turn 유도* 후
    #     reverse pursuit 기회.
    #   entry: tick>100 (10s 이후) AND closure>+100 (적 closing 강함) AND ata>60 (우리 정렬 X)
    #          AND dist>5000 (close-merge 밖) AND prev_branch != "BreakInduce" (one-shot)
    #   mode: DefensiveBreak 와 동일 cmd (적 반대 hard-turn + 가속).
    #   목표: 적이 따라 turn → dpsi 발산 → 다음 tick reverse pursuit 으로 ATA 잡기.
    obs_hist_len = len(obs_history) if obs_history is not None else 0
    if (obs_hist_len > 100 and closure > 100.0 and ata > 60.0 and dist > 5000.0
            and prev_branch != "BreakInduce"):
        return {"branch": "BreakInduce",
                "reason": (f"강한 closing 유도 break: tick={obs_hist_len}, closure={closure:.0f}>100, "
                           f"ata={ata:.0f}>60, dist={dist:.0f}>5000"),
                "params": {"closure": closure, "ata": ata, "dist": dist}}

    # 4.85 InitialPhaseAccel (B'-2/B'-3 REVERTED 2026-05-16) — adaptive 형태도 simple 평형 깸.
    #   B'-2 (universal IPA): simple 5W→0W catastrophic, defensive n=4 HP 100/1 single 사격
    #     (BREAKTHROUGH 처럼 보였으나 B'-3 에서 재현 안 됨 → FP basin noise 였음).
    #   B'-3 (closure 분류 adaptive): simple 0W/5L — 우리가 사격당함 (97/100).
    #     1s closure 평균이 분류기로 너무 noisy (분포 overlap).
    #   결론: IPA 형태 (초기 turn 자제) 자체가 simple WIN 의 load-bearing turn 과 incompatible.
    #     16 사이클 누적 + Model B' running cost ≡ 0 (aggressive 매치 WEZ 미진입) =
    #     **aggressive 의 실증적 unsolvability 확정**.
    #   분기 비활성 유지. 추가 분기 코드는 history 학습 자산으로 보존.

    # 4.9 AggressiveCloseMerge (B-1+D-Obs-1, 2026-05-16) — trend-based parallel detector
    #   + Boyd EM physics guard (ps_fts / energy_advantage).
    #   B-1 (parallel_sig>0.7 only) 검증 결과: 15000 ticks 중 0회 발화 → no-op 무진전.
    #   원인: 4-sigmoid product 가 너무 엄격. parallel chase 가 실제로 더 자주 발생.
    #   D-Obs-1 변경:
    #     1) parallel_sig 임계값 0.7 → 0.5 (완화, 더 자주 발화)
    #     2) 안전 가드 추가: (ps_fts > -100 fps) ∨ (energy_advantage == True)
    #        — Boyd EM 정통: ps_fts > 0 이 sustained turn 가능 조건 (0Ps).
    #        — 가드: 우리 PE 충분히 있거나 (sustained 가능) 적보다 PE 우위 일 때만 close-merge.
    #        — 정당화: 가드 없이 진입하면 PE 소진 → 자살. 가드는 *물리적 안전 조건* 추가.
    # D-Obs-1 (ACCEPT) — defensive +1 WIN 효과. parallel_sig + ps/ea 가드 유지.
    parallel_sig = _parallel_chase_signal(obs_history)
    ps_fts = float(obs.get("ps_fts", 0.0))
    ea_bool = bool(obs.get("energy_advantage", False))
    em_ok = (ps_fts > -100.0) or ea_bool
    if parallel_sig > 0.7 and em_ok:
        return {"branch": "AggressiveCloseMerge",
                "reason": (f"parallel_sig={parallel_sig:.2f}>0.7, "
                           f"ps_fts={ps_fts:.0f}, energy_adv={ea_bool}"),
                "params": {"parallel_sig": parallel_sig, "ps_fts": ps_fts,
                           "energy_adv": ea_bool, "dist": dist}}

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
    """ZoomClimbDive (2026-05-16 갱신): alt_gap-aware *수직 BFM macro*.

    v11 sim 발견: 적의 수직 응답 시간상수 4초 (수평 0.4초 대비 10× lag).
    → 우리 *급격 수직 기동* 으로 alt_gap 벌리고 dive 로 V_p 우위 → close 시도.

    Phase (alt_gap 기반 자동):
      Z1 (alt_gap<2000):  강한 climb (γ=+15°) + accel — 적 4s lag 동안 alt_gap 벌림
      Z2 (2000≤alt_gap<4000): level (γ=0) + accel — V_p 회복 (climb 손실 보충)
      Z3 (alt_gap≥4000): dive (γ=-15°) + accel + PN turn — KE 변환 → V_p>V_e

    moderate PN heading 유지 (over-turn bleed 회피).
    """
    rb = _denorm_deg(obs, "relative_bearing_deg")
    alt_gap = float(obs.get("alt_gap_ft", 0.0))
    omega = -math.radians(0.03 * rb)              # moderate pursuit (bleed 최소)
    accel = 15.0                                  # 항상 max accel
    if alt_gap < 2000.0:
        gamma_dot = math.radians(15.0)            # Z1: 강한 climb
    elif alt_gap < 4000.0:
        gamma_dot = 0.0                           # Z2: level (V_p 회복)
    else:
        gamma_dot = math.radians(-15.0)           # Z3: dive (KE attack)
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
