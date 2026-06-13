"""Guidance 계층 — Tactic enum → (psi_star_deg, h_star_ft, v_star_kts).

각 tactic마다 현재 obs geometry를 읽어 연속 setpoint를 산출한다.
BT는 tactic만 선택하고, 구체 수치는 이 계층이 매 tick 자동 계산.

참조:
  - NAVAIR 00-80T-105 (pursuit curves, yoyo, scissors, lag displacement roll)
  - AFTTP 3-3.F-16 (one-circle / two-circle / gun employment)
  - liuqh16/LAG get_AO_TA_R: AO/TA geometry 계산 패턴 참조
    (https://github.com/liuqh16/LAG/blob/master/envs/JSBSim/utils/utils.py)
  - Wikipedia "Basic fighter maneuvers": scissors, lag displacement roll 분류

단위: 모든 입출력은 도(°)/ft/kts (TACTIC_SPEC.md §0 기준).
      heading wrap: % 360.0 (항공 관례 0~360°).
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from tactic import (
    Tactic,
    # 엔진 상수
    HARD_DECK_FT, WEZ_MIN_FT, WEZ_MAX_FT, WEZ_ATA_DEG,
    # F-16 성능
    V_CORNER_KTS, V_RADIUS_KTS, V_MAX_KTS, V_TRIM_KTS, V_MIN_KTS,
    # Guidance 파라미터
    YOYO_CLIMB_FT, YOYO_DESCENT_FT, YOYO_DV_KTS, CLIMB_TARGET_FT,
    SCISSORS_TURN_DEG, SCISSORS_VERT_FT, SCISSORS_H_MARGIN_FT,
    LDR_TURN_DEG, LDR_CLIMB_FT,
    LEAD_ANGLE_FACTOR, LEAD_DV_KTS,
    BREAK_TURN_DEG, EXT_HEADING_DEG,
    GUN_ENTRY_ATA_DEG, GUN_LEAD_TAU_FACTOR, GUN_DV_KTS,
    H_MAX_FT, H_MIN_FT, PURSUIT_CLOSE_KTS,
)
from constants import KNOT_TO_FT_S, EPS_DENOM  # 단위 변환 (kts→fps), 0나눗셈 guard
import os


WEZ_MID_FT = 0.5 * (WEZ_MIN_FT + WEZ_MAX_FT)   # ~1750ft, chase 안착 목표

# ★ 에너지 바닥 (외측 유도, U.6 nose-chaser 하강나선 방지): VERTICAL_PURSUIT 가 적을 따라
#   하드덱으로 내려가지 않도록 고도 setpoint 하한. 적이 더 내려가면 우리는 에너지 유지 →
#   적이 바닥서 climb 강요당할 때 비대칭(에너지 우위) 생성(V.6). env 로 sweep.
ENERGY_FLOOR_FT = float(os.environ.get("NME_ENERGY_FLOOR_FT", str(HARD_DECK_FT + 4000.0)))


@dataclass
class ChaseConfig:
    """Chase 3-phase 속도 프로파일 (파라미터화 — 하드코딩 금지, 최적화 연동).

    ★ 사용자 BFM 교리: ①진행방향 다르면 낮은속도 좁은반경 즉시선회 →
      ②정렬되면 속도 burst 추격 → ③가까워지면 overshoot 전 감속.
    """
    turn_in_deg:   float = 35.0    # |rel_b|>이값 = 진행방향 크게 다름 → 선회 phase
    turn_in_kts:   float = 220.0   # phase1 선회 속도 (낮음 → 반경 ∝V² 절반↓, tight).
                                   #   ★ 실험: 310(코너)는 simple WIN→DRAW 회귀 → 220 유지(merge 전환 필수).
    kp_closure:    float = 0.020   # kts(desired closure) per ft(range error)
    kv_closure:    float = 1.2     # 속도 명령 = ego_vc + kv·(desired−current closure)
    max_closure_kts: float = 120.0 # phase2 burst 최대 접근속도
    min_closure_kts: float = -25.0 # phase3 WEZ 진입 시 후퇴(감속) → overshoot 방지


@dataclass
class Obs:
    """guidance 내부 obs 래퍼. engine/obs.py Observation 을 소비.

    단위·부호 규약 ([[new-match-engine-math-units]] 메모리 준수):
      heading_deg      : ° 0~360, 절대 (= obs.ego_psi_deg)
      ego_altitude_ft  : ft MSL  (= obs.ego_alt_ft)
      ego_vc_kts       : kts     (= obs.ego_vc_kts)
      ata_deg, aa_deg  : ° [0,180] 절대값
      rel_b            : ° ±180, 우+/좌− (= obs.rel_b_deg)
      closure_kts      : kts ±, +접근 (= obs.closure_kts)
      distance_ft      : ft
      roll_deg         : ° ±180, 우+/좌− (= obs.ego_phi_deg, 우리 선회방향)
      omega_opp_signed : °/s ±, 우+/좌− (= obs.enm_r_dps, 적 선회율 직접 100%)
      enm_altitude_ft  : ft MSL (= obs.enm_alt_ft)
      advantage        : [−1,+1] 무차원 (= obs.advantage, +공격/−방어)
      tau_s            : s, time-to-merge = dist/closure (파생)
    """
    heading_deg:        float   # ° 0~360 절대
    ego_altitude_ft:    float   # ft MSL
    ego_vc_kts:         float   # kts
    ata_deg:            float   # ° [0,180] 절대값
    aa_deg:             float   # ° [0,180] 절대값
    rel_b:              float   # ° ±180, 우+/좌−
    closure_kts:        float   # kts ±, +접근
    distance_ft:        float   # ft
    roll_deg:           float   # ° ±180, 우+/좌− (우리 선회방향)
    omega_opp_signed:   float   # °/s ±, 우+/좌− (적 선회율, enm_r_dps 직접)
    enm_altitude_ft:    float   # ft MSL
    advantage:          float   # [−1,+1] 무차원, +공격/−방어
    tau_s:              float   # s, time-to-merge
    enm_psi_deg:        float = 0.0   # ° 0~360 절대 (적 진행방향) — cutoff 요격용
    enm_vc_kts:         float = 0.0   # kts (적 속도) — lead-collision 속도비용

    @classmethod
    def from_observation(cls, o) -> "Obs":
        """engine/obs.py Observation (또는 그 dict) → guidance Obs.

        ★ 단위/부호 변환 지점 — 메모리 규약과 일치하게 매핑.
        """
        d = o.as_dict() if hasattr(o, "as_dict") else dict(o)
        dist  = float(d["distance_ft"])
        clos  = float(d["closure_kts"])
        # tau_s: time-to-merge = 거리(ft) / closure(fps). 접근(+)일 때만 유의미.
        #   closure ≤ 0 (이격) → tau 매우 큼(충돌 안 함). guard: max(EPS, |closure_fps|)
        clos_fps = clos * KNOT_TO_FT_S
        tau_s = dist / max(EPS_DENOM, abs(clos_fps)) if clos > 0 else 999.0
        return cls(
            heading_deg      = float(d["ego_psi_deg"]) % 360.0,
            ego_altitude_ft  = float(d["ego_alt_ft"]),
            ego_vc_kts       = float(d["ego_vc_kts"]),
            ata_deg          = float(d["ata_deg"]),
            aa_deg           = float(d["aa_deg"]),
            rel_b            = float(d["rel_b_deg"]),
            closure_kts      = clos,
            distance_ft      = dist,
            roll_deg         = float(d["ego_phi_deg"]),   # 우리 선회방향(bank)
            omega_opp_signed = float(d["enm_r_dps"]),      # 적 선회율 직접(°/s, 부호)
            enm_altitude_ft  = float(d["enm_alt_ft"]),
            advantage        = float(d["advantage"]),
            tau_s            = tau_s,
            enm_psi_deg      = float(d.get("enm_psi_deg", 0.0)) % 360.0,
            enm_vc_kts       = float(d.get("enm_vc_kts", 0.0)),
        )

    # 하위호환: dict 직접 (테스트용, obs.Observation 키 기준)
    from_dict = from_observation


@dataclass
class Setpoint:
    """Guidance 출력. 단위: °/ft/kts (절대값, TACTIC_SPEC.md §5)."""
    psi_star_deg: float   # 목표 heading 0~360°
    h_star_ft:    float   # 목표 고도 ft MSL
    v_star_kts:   float   # 목표 속도 kts

    def clamped(self) -> "Setpoint":
        return Setpoint(
            psi_star_deg = self.psi_star_deg % 360.0,
            h_star_ft    = max(H_MIN_FT, min(H_MAX_FT, self.h_star_ft)),
            v_star_kts   = max(V_MIN_KTS, min(V_MAX_KTS, self.v_star_kts)),
        )


def _normalize_0_360(deg: float) -> float:
    """heading 정규화 → [0, 360°). setpoint 출력 전용.

    ★ autopilot.py 의 _wrap(rad) → [−π, +π] 와 다른 함수.
      이 함수: degrees, [0, 360°) — 절대 heading setpoint 용.
      autopilot: radians, [−π, +π]  — 오차 계산 용.
    음수 입력 처리: −10° % 360 = 350° (Python % 동작 이용, 올바름).
    """
    return deg % 360.0


# 하위 호환 alias (기존 코드 참조)
_wrap = _normalize_0_360


def _sign(x: float) -> float:
    """부호 반환. x==0 → +1."""
    return 1.0 if x >= 0.0 else -1.0


def _sig(x: float) -> float:
    """sigmoid [0,1] — τ 게이트용 (BFM 조건 hard→soft). overflow guard."""
    if x < -30.0:
        return 0.0
    if x > 30.0:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


class GuidanceLayer:
    """Tactic enum → Setpoint.

    상태 유지가 필요한 tactic(SCISSORS의 reversal_sign)은 내부 state로 관리.
    외부에서 매 tick compute(tactic, obs_dict) 를 호출한다.
    """

    def __init__(self, chase: "ChaseConfig | None" = None):
        # SCISSORS 상태
        self._scissors_sign: float = 1.0   # 현재 선회 방향 (+1=우, −1=좌)
        self._scissors_prev_overshoot: bool = False
        # chase 속도 제어 게인 (파라미터화 — Optuna/scipy 최적화 대상)
        self.chase = chase or ChaseConfig()

    def _chase_speed(self, o: Obs, target_ft: float) -> float:
        """Chase 3-phase 속도 (★ 사용자 BFM 교리).

        ① 진행방향 크게 다름(|rel_b|>turn_in_deg) → 낮은속도(turn_in_kts) 좁은반경 즉시선회.
           반경 ∝ V² 이므로 저속이 tight → excursion(넓은 호) 최소화.
        ② 정렬 후 → 거리 PID 로 속도 burst (멀수록 빠른 접근).
        ③ 가까워짐(dist→target) → desired_closure→0 → 감속 → overshoot 전 안착.
        target_ft: 안착 목표거리 (WEZ 중심 부근).
        """
        c = self.chase
        # ① 선회 phase — 진행방향 다르면 저속 tight turn
        if abs(o.rel_b) > c.turn_in_deg:
            return c.turn_in_kts
        # ②③ 거리 PID — far burst / near 감속
        err = o.distance_ft - target_ft
        desired_closure = max(c.min_closure_kts, min(c.max_closure_kts, c.kp_closure * err))
        v = o.ego_vc_kts + c.kv_closure * (desired_closure - o.closure_kts)
        return max(c.turn_in_kts, min(V_MAX_KTS, v))

    def compute(self, tactic: Tactic, obs) -> Setpoint:
        """메인 진입점. obs: engine.obs.Observation (또는 그 dict)."""
        o = obs if isinstance(obs, Obs) else Obs.from_observation(obs)
        sp = self._dispatch(tactic, o)
        return sp.clamped()

    def _dispatch(self, tactic: Tactic, o: Obs) -> Setpoint:
        match tactic:
            case Tactic.ADAPTIVE:
                return self._adaptive(o)
            case Tactic.VERTICAL_PURSUIT:
                return self._vertical_pursuit(o)
            case Tactic.LEAD_PURSUIT:
                return self._lead_pursuit(o)
            case Tactic.PURE_PURSUIT:
                return self._pure_pursuit(o)
            case Tactic.LAG_PURSUIT:
                return self._lag_pursuit(o)
            case Tactic.LAG_DISPLACEMENT_ROLL:
                return self._lag_displacement_roll(o)
            case Tactic.GUN_TRACK:
                return self._gun_track(o)
            case Tactic.ONE_CIRCLE:
                return self._one_circle(o)
            case Tactic.TWO_CIRCLE:
                return self._two_circle(o)
            case Tactic.TIGHT_TURN:
                return self._tight_turn(o)
            case Tactic.LEAD_TURN | Tactic.HEADON:
                return self._lead_turn(o)
            case Tactic.SCISSORS:
                return self._scissors(o)
            case Tactic.HIGH_YOYO:
                return self._high_yoyo(o)
            case Tactic.LOW_YOYO:
                return self._low_yoyo(o)
            case Tactic.BREAK_TURN:
                return self._break_turn(o)
            case Tactic.EXTENSION:
                return self._extension(o)
            case Tactic.CLIMB:
                return self._climb(o)
            case _:  # LEVEL_FLIGHT
                return self._level_flight(o)

    # ── 공격 계열 ──────────────────────────────────────────────────────

    def _lead_pursuit(self, o: Obs) -> Setpoint:
        """★ Lead-collision 요격 — 적 미래위치로 직진 cutoff (extender 닫으며 각 유지).

        기존 'ata 비례 lead' = over-turn pure (계측: extender vs 각·거리 동시 실패).
        교체: 2차방정식 요격 — "τ초 뒤 적 위치"를 향해 비행. 부호/분기 버그 없는 정공법.

          상대위치 p = R·(sinλ, cosλ)   (λ=LOS방위=heading+rel_b, 컴퍼스 (E,N))
          적속도   v = V_t·(sinψ_t, cosψ_t)
          요격조건 |p + τ·v| = τ·V_us  →  (|v|²−V_us²)τ² + 2(p·v)τ + |p|² = 0
          τ>0 해 → 조준점 = p + τ·v → ψ* = atan2(E, N)

        τ 실근 없음(적 더 빠르고 도주) → pure pursuit fallback (가능한 최선 추격).
        ref: 표준 미사일/요격 lead-collision (Zarchan, *Tactical & Strategic Missile Guidance* §2).
        """
        lam = math.radians(o.heading_deg + o.rel_b)
        R = o.distance_ft
        pE, pN = R * math.sin(lam), R * math.cos(lam)               # 적 상대위치(ft)
        psit = math.radians(o.enm_psi_deg)
        vt = max(50.0, o.enm_vc_kts) * KNOT_TO_FT_S                 # fps
        vus = max(50.0, o.ego_vc_kts) * KNOT_TO_FT_S
        vE, vN = vt * math.sin(psit), vt * math.cos(psit)          # 적 속도(fps)
        a = vE*vE + vN*vN - vus*vus
        b = 2.0 * (pE*vE + pN*vN)
        c = pE*pE + pN*pN
        disc = b*b - 4.0*a*c
        tau = -1.0
        if abs(a) < 1e-6:                       # 동속 → 선형해 τ = -c/b
            if abs(b) > 1e-6: tau = -c / b
        elif disc >= 0.0:
            sq = math.sqrt(disc)
            r1, r2 = (-b - sq) / (2.0*a), (-b + sq) / (2.0*a)
            cand = [r for r in (r1, r2) if r > 1e-3]
            if cand: tau = min(cand)            # 가장 빠른 요격
        if tau > 0.0:
            aimE, aimN = pE + tau*vE, pN + tau*vN
            psi = _wrap(math.degrees(math.atan2(aimE, aimN)))
        else:                                   # 요격불가(적 더 빠름) → pure
            psi = _wrap(o.heading_deg + o.rel_b)
        v = self._chase_speed(o, WEZ_MID_FT)    # closure
        return Setpoint(psi, o.ego_altitude_ft, v)

    def _vertical_pursuit(self, o: Obs) -> Setpoint:
        """★ evasive extender 전용 — pure 추격 + 적 고도 추종 (zoom-extend 따라붙음).

        계측: 적이 zoom climb 으로 extend 시 수평유지 pursuit 는 수직으로 놓침(altgap -6618ft, WEZ 0).
        적 고도(h=enm) 추종하면 따라붙어 WEZ 44~48%·격추. defensive 회귀 때문에 글로벌 대신
        evasive 상황 디스패치 전용 (상황 독립).
        """
        psi = _wrap(o.heading_deg + o.rel_b)
        v = self._chase_speed(o, WEZ_MID_FT)
        # ★ 에너지 바닥: 적이 하드덱으로 끌고 내려가도 안 따라감(하강 나선 방지, U.6).
        #   적 고도가 바닥 위면 추종, 아래로 다이브하면 바닥 유지 → 에너지 보존.
        h = max(o.enm_altitude_ft, ENERGY_FLOOR_FT)
        return Setpoint(psi, h, v)   # ★ 적 고도 추종(에너지 바닥 적용)

    def _aim_cutoff(self, o: Obs) -> float:
        """lead-collision 요격 heading (적 미래위치 cutoff). 요격불가면 pure. (관측-차 함수, 하드코딩 0)"""
        lam = math.radians(o.heading_deg + o.rel_b); R = o.distance_ft
        pE, pN = R * math.sin(lam), R * math.cos(lam)
        psit = math.radians(o.enm_psi_deg)
        vt = max(50.0, o.enm_vc_kts) * KNOT_TO_FT_S
        vus = max(50.0, o.ego_vc_kts) * KNOT_TO_FT_S
        vE, vN = vt * math.sin(psit), vt * math.cos(psit)
        a = vE*vE + vN*vN - vus*vus; b = 2.0*(pE*vE + pN*vN); c = pE*pE + pN*pN
        disc = b*b - 4.0*a*c; tau = -1.0
        if abs(a) < 1e-6:
            if abs(b) > 1e-6: tau = -c / b
        elif disc >= 0.0:
            sq = math.sqrt(disc); cand = [r for r in ((-b-sq)/(2*a), (-b+sq)/(2*a)) if r > 1e-3]
            if cand: tau = min(cand)
        if tau > 0.0:
            return _wrap(math.degrees(math.atan2(pE + tau*vE, pN + tau*vN)))
        return _wrap(o.heading_deg + o.rel_b)

    def _adaptive(self, o: Obs) -> Setpoint:
        """★ 관측-차 반응형 ADAPTIVE (2026-06-13) — 5상황 soft 멤버십 × virtual-point 블렌딩.

        설계: MPC의 *relational cost*는 살리고 *rollout*은 버림([[mpc-failure-analysis]]).
        모든 게이트=아군–적군 관측 *차이*(ata, aa, HCA, closure, Δvc) sigmoid — **절대값(dist/alt) 금지**
        (틱-의존·비불변). 5상황: DEFENSIVE/OFFENSIVE/CIRCLE/EXTEND/MERGE. 하드스위치 없음(연속 blend).
        per-situation heading=virtual-point(cutoff/pursuit/break), 속도=상대(enm_vc 기준)+E-M 물리상수.
        """
        ata, aa = o.ata_deg, o.aa_deg
        hca = abs(((o.heading_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)
        clos = o.closure_kts
        # ── 상황 soft 멤버십 (전부 상대량 sigmoid) ──
        w_def  = _sig((aa - 110.0) / 20.0)                              # 적이 우리 뒤(방어, 최우선)
        w_off  = _sig((35.0 - ata) / 15.0) * _sig((90.0 - aa) / 30.0)   # 우리가 적 뒤·정렬(공격)
        w_ext  = _sig((-clos - 25.0) / 30.0) * _sig((ata - 30.0) / 20.0)# 이탈(opening)+미정렬
        w_circ = _sig((hca - 90.0) / 30.0) * _sig((ata - 35.0) / 20.0)  # 교차(rate)+미정렬
        w_mrg  = _sig((ata - 35.0) / 15.0) * _sig((90.0 - aa) / 30.0) * _sig((hca - 45.0) / 30.0)  # 전환국면
        ws = [w_def, w_off, w_ext, w_circ, w_mrg]
        tot = sum(ws) + 1e-6
        wd, wo, we, wc, wm = (x / tot for x in ws)
        # ── per-situation heading (virtual-point) ──
        psi_pur = _wrap(o.heading_deg + o.rel_b)                        # 적 직격 (offensive/circle)
        psi_brk = _wrap(o.heading_deg - _sign(o.rel_b) * 100.0)         # break away (defensive)
        psi_cut = self._aim_cutoff(o)                                  # lead-collision (merge/extend)
        # circular 블렌딩 (각도 평균)
        sr = (wd*math.sin(math.radians(psi_brk)) + (wo+wc)*math.sin(math.radians(psi_pur))
              + (we+wm)*math.sin(math.radians(psi_cut)))
        cr = (wd*math.cos(math.radians(psi_brk)) + (wo+wc)*math.cos(math.radians(psi_pur))
              + (we+wm)*math.cos(math.radians(psi_cut)))
        psi = _wrap(math.degrees(math.atan2(sr, cr)))
        # ── 속도: 상대(enm_vc 기준) + 물리상수(코너/반경) 블렌딩 ──
        v_off = self._chase_speed(o, WEZ_MID_FT)                       # 닫기 PID(상대거리)
        v_ext = min(V_MAX_KTS, max(50.0, o.enm_vc_kts) + 60.0)         # 적보다 빠르게(이탈 추격)
        v_mrg = max(V_MIN_KTS, max(50.0, o.enm_vc_kts) - 40.0)         # 적보다 느리게→반경 tight
        v = (wd*V_CORNER_KTS + wo*v_off + wc*V_RADIUS_KTS + we*v_ext + wm*v_mrg)
        # 고도: 적 고도 추종(에너지 바닥), 수직 yoyo 제거(단순화)
        tau_y = 0.0
        # ── 고도: yoyo 게이트 높으면 상승 perch, 아니면 적 고도 추종 ──
        h = (1.0 - tau_y) * o.enm_altitude_ft + tau_y * (o.ego_altitude_ft + YOYO_CLIMB_FT)
        return Setpoint(psi, h, v)

    def _pure_pursuit(self, o: Obs) -> Setpoint:
        """NAVAIR 00-80T-105 §4-2 Pure Pursuit.
        nose → 현재 적 위치 (rel_b 방향으로 직접 선회).
        ★ 추격 가속: closure≤PURSUIT_CLOSE_KTS(안 좁혀짐) → v*=최대 sprint.
          (계측: 동속 적을 못 잡던 근본 — co-speed pure pursuit=거리 일정.)
        """
        psi = _wrap(o.heading_deg + o.rel_b)
        # ★ 3-phase chase: 진행방향 다르면 저속 tight 선회 → 정렬 후 burst → 근접 감속.
        v = self._chase_speed(o, WEZ_MID_FT)
        # 고도: 수평 유지(h=ego). ★ 고도추종(h=enm) 글로벌 적용은 defensive 4/4→0/4 회귀 →
        #   evasive 전용 VERTICAL_PURSUIT tactic 으로 분리 (상황 독립).
        return Setpoint(psi, o.ego_altitude_ft, v)

    def _lag_pursuit(self, o: Obs) -> Setpoint:
        """NAVAIR 00-80T-105 §4-4 Lag Pursuit.
        nose를 적 뒤쪽으로 — 선회전 유지·에너지 보존.
        lag = rel_b * 0.5 (반만 선회 → 적 뒤쪽 유지).
        """
        lag_angle = o.rel_b * 0.5
        psi = _wrap(o.heading_deg + lag_angle)
        h   = o.enm_altitude_ft - 500.0   # 약간 낮게 — 에너지 이득
        return Setpoint(psi, h, o.ego_vc_kts)

    def _lag_displacement_roll(self, o: Obs) -> Setpoint:
        """Wikipedia BFM "Lag Displacement Roll" / NAVAIR §5 Offensive BFM.
        overshoot 직전 lift-vector를 적 후방으로 이탈 — 포지션 유지·에너지 최소 손실.
        고도: 적보다 높으면 유지, 낮으면 LDR_CLIMB_FT 상승.
        ref: Wikipedia "Displacement rolls are out-of-plane maneuvers used to
             shift aircraft laterally from projected flight path."
        """
        psi = _wrap(o.heading_deg + _sign(o.rel_b) * LDR_TURN_DEG)
        # 수직 이탈: 현재 고도와 적 고도 비교
        dh = LDR_CLIMB_FT if o.ego_altitude_ft <= o.enm_altitude_ft else 0.0
        h  = o.ego_altitude_ft + dh
        return Setpoint(psi, h, o.ego_vc_kts)

    def _gun_track(self, o: Obs) -> Setpoint:
        """AFTTP 3-3.F-16 §9 Gun Employment.
        매 tick 연속 정밀 lead angle — 5×9×5 분해능 한계를 구조적으로 제거.
        ata_signed = ata_deg * sign(rel_b): 부호 있는 ATA (rel_b로 방향 복원).
        lead_correction = omega_opp_signed * tau_s * factor: 적 선회 예측.
        ref: WEZ 조건 ATA<12°, 500~3000ft (wez_engine.py, TACTIC_SPEC §7).
        """
        ata_signed = o.ata_deg * _sign(o.rel_b)
        lead_correction = o.omega_opp_signed * o.tau_s * GUN_LEAD_TAU_FACTOR
        psi = _wrap(o.heading_deg + ata_signed + lead_correction)
        # ★ chase PID로 WEZ 거리 안착 (gun 은 WEZ 중심에 단단히 머물러야)
        v   = self._chase_speed(o, WEZ_MID_FT)
        return Setpoint(psi, o.enm_altitude_ft, v)

    # ── 중립 선회 계열 ─────────────────────────────────────────────────

    def _one_circle(self, o: Obs) -> Setpoint:
        """AFTTP 3-3 §6 One-Circle / Angles Fight.

        ★ blind ±90 폐기 (계측: dist 483→29613 분리). 적 위치(rel_b) 기반으로.
        psi* = heading + rel_b (적 향해 선회) + lead(각도 쌓이면 nose 앞당김).
          merge 후 적이 뒤(rel_b≈±180) → 자동 반전 → 분리 방지.
          one-circle = 최소반경(corner speed), 적 정조준 우선.
        진영 무관: rel_b(상대방위)만 씀.
        """
        # ★ merge lead-turn: head-on 접근(|rel_b|작음+고속접근)이면 직진 통과 말고
        #   적 있는 쪽으로 hard turn → 적 6시로 curve (계측: 직진통과→23000ft 분리).
        if abs(o.rel_b) < 45.0 and o.closure_kts > 100.0 and o.distance_ft < 6000.0:
            turn = _sign(o.rel_b) * 100.0        # 적 쪽으로 hard lead turn
            psi  = _wrap(o.heading_deg + turn)
        else:
            # 적이 옆/뒤 → 적 향해 선회 + 각도쌓이면 lead
            w = max(0.0, min(1.0, o.advantage))
            lead = w * 15.0 * _sign(o.rel_b)
            psi  = _wrap(o.heading_deg + o.rel_b + lead)
        return Setpoint(psi, o.ego_altitude_ft, V_CORNER_KTS)

    def _two_circle(self, o: Obs) -> Setpoint:
        """AFTTP 3-3 §7 Two-Circle / Radius Fight.

        ★ blind ±90 폐기. 적 위치(rel_b) 기반 + rate→lead 전환.
        psi* = heading + rel_b (적 향해) + lead(각도 쌓이면 더 앞당김).
          two-circle = rate fight: corner speed 유지하며 적 추적.
          승리 궤적([[winning-trajectory-figure8]]): rate 이득 → sustained WEZ 전환.
        two-circle 정석상 고도 하강 허용 (에너지→선회율).
        진영 무관: rel_b·omega 둘 다 상대값.
        """
        w = max(0.0, min(1.0, o.advantage))      # rate 이득 → lead 전환
        # rate fight는 적 선회방향으로 더 강하게 lead (out-rate)
        lead = w * 25.0 * _sign(o.omega_opp_signed if abs(o.omega_opp_signed) > 1.0
                                else o.rel_b)
        psi  = _wrap(o.heading_deg + o.rel_b + lead)
        return Setpoint(psi, o.ego_altitude_ft, V_CORNER_KTS)

    def _tight_turn(self, o: Obs) -> Setpoint:
        """★ 최소반경 angles turn (one-circle radius fight).

        ONE_CIRCLE 는 V_CORNER(max-rate=큰 반경)로 돌아 머지가 벌어짐(실험 C′: 30km).
        반경 R ∝ V² 이므로, 코너보다 *느린* V_RADIUS 로 돌면 반경이 ~34% 작아져 적 곁에서 tight 하게 각을 딴다.
        heading 은 적 향해 선회(+각 쌓이면 lead) = one_circle 와 동일, 속도만 min-radius.
        ref: Shaw §one-circle radius fight (작은 반경 우위). corner=rate / radius=느린속도 구분.
        """
        w = max(0.0, min(1.0, o.advantage))
        lead = w * 15.0 * _sign(o.rel_b)
        psi = _wrap(o.heading_deg + o.rel_b + lead)
        return Setpoint(psi, o.ego_altitude_ft, V_RADIUS_KTS)

    def _lead_turn(self, o: Obs) -> Setpoint:
        """★ 머지 전환 Lead Turn (Shaw BFM 핵심) — 직진 통과(거리확장) 방지.

        중립/정면 머지에서 적 *미래위치*(lead-collision)로 *미리* tight 선회 → 교차 시 nose-on,
        넓게 안 지나감. _lead_pursuit 와 조준은 같으나(요격점), 속도를 chase-sprint 가 아니라
        min-radius(V_RADIUS)로 둬 반경을 줄여 머지를 닫는다(실험 C′: 코너 선회는 30km로 벌어짐).
        요격 불가(적 더 빠름)면 적 현재위치로 hard turn(pure) — 그래도 tight 속도 유지.
        ref: Shaw, *Fighter Combat* — Lead Turn / Nose-to-Nose merge conversion.
        """
        lam = math.radians(o.heading_deg + o.rel_b)
        R = o.distance_ft
        pE, pN = R * math.sin(lam), R * math.cos(lam)
        psit = math.radians(o.enm_psi_deg)
        vt = max(50.0, o.enm_vc_kts) * KNOT_TO_FT_S
        vus = max(50.0, o.ego_vc_kts) * KNOT_TO_FT_S
        vE, vN = vt * math.sin(psit), vt * math.cos(psit)
        a = vE*vE + vN*vN - vus*vus
        b = 2.0 * (pE*vE + pN*vN)
        c = pE*pE + pN*pN
        disc = b*b - 4.0*a*c
        tau = -1.0
        if abs(a) < 1e-6:
            if abs(b) > 1e-6: tau = -c / b
        elif disc >= 0.0:
            sq = math.sqrt(disc)
            cand = [r for r in ((-b - sq) / (2.0*a), (-b + sq) / (2.0*a)) if r > 1e-3]
            if cand: tau = min(cand)
        if tau > 0.0:
            aimE, aimN = pE + tau*vE, pN + tau*vN
            psi = _wrap(math.degrees(math.atan2(aimE, aimN)))
        else:
            psi = _wrap(o.heading_deg + o.rel_b)
        # ★ 조건부 속도 (E23 교훈): 근접 머지 선회(각 큼)면 min-radius tight,
        #   적이 멀거나 정렬돼 닫아야 하면 chase sprint (고정 저속은 이탈형이 달아남 → 53~58km 폭발).
        if o.distance_ft < 4500.0 and o.ata_deg > 25.0:
            v = V_RADIUS_KTS                          # tight merge turn
        else:
            v = self._chase_speed(o, WEZ_MID_FT)      # close the extender/aligned
        return Setpoint(psi, o.ego_altitude_ft, v)

    def _scissors(self, o: Obs) -> Setpoint:
        """NAVAIR 00-80T-105 §5-6 Scissors.
        overshoot 교착 → 반전 반복. 방향전환 속도 승부.
        overshoot 감지(aa < ata): reversal_sign 뒤집기.
        수직 scissors: 고도 여유 있으면 ±SCISSORS_VERT_FT 교대.
        ref: Wikipedia "Scissors — series of turn reversals."
        """
        overshoot = o.aa_deg < o.ata_deg
        if overshoot and not self._scissors_prev_overshoot:
            self._scissors_sign *= -1.0
        self._scissors_prev_overshoot = overshoot

        psi = _wrap(o.heading_deg + self._scissors_sign * SCISSORS_TURN_DEG)

        # 고도: 수직 scissors 가능 여부
        h_margin = o.ego_altitude_ft - HARD_DECK_FT
        if h_margin > SCISSORS_H_MARGIN_FT:
            dh = self._scissors_sign * SCISSORS_VERT_FT
            h  = o.ego_altitude_ft + dh
        else:
            h  = o.ego_altitude_ft

        return Setpoint(psi, h, V_CORNER_KTS)

    # ── 수직 계열 ──────────────────────────────────────────────────────

    def _high_yoyo(self, o: Obs) -> Setpoint:
        """NAVAIR 00-80T-105 §5-2 High Yo-Yo.
        에너지 과잉·overshoot 위험 → 상승+감속, 선회전 유지.
        heading: 현재 유지 (상승 중 heading 변화 최소화).
        """
        h = o.ego_altitude_ft + YOYO_CLIMB_FT
        v = o.ego_vc_kts - YOYO_DV_KTS
        return Setpoint(o.heading_deg, h, v)

    def _low_yoyo(self, o: Obs) -> Setpoint:
        """NAVAIR 00-80T-105 §5-3 Low Yo-Yo.
        closure 부족·에너지 저하 → 강하+가속.
        heading: 현재 유지.
        """
        h = o.ego_altitude_ft - YOYO_DESCENT_FT
        v = o.ego_vc_kts + YOYO_DV_KTS
        return Setpoint(o.heading_deg, h, v)

    # ── 방어 계열 ──────────────────────────────────────────────────────

    def _break_turn(self, o: Obs) -> Setpoint:
        """AFTTP 3-3 §8 Defensive Break Turn.
        max-G break — 적 반대 방향으로 90° 전환.
        sign: −sign(rel_b) → 적이 오른쪽에 있으면 왼쪽으로 break.
        """
        sign_break = -_sign(o.rel_b)
        psi = _wrap(o.heading_deg + sign_break * BREAK_TURN_DEG)
        return Setpoint(psi, o.ego_altitude_ft, V_CORNER_KTS)

    def _extension(self, o: Obs) -> Setpoint:
        """AFTTP 3-3 §10 Extension / Separation.
        적 반대 방향 직진 → 에너지 회복.
        heading: 현재 heading + 180° (직접 이탈).
        """
        psi = _wrap(o.heading_deg + EXT_HEADING_DEG)
        return Setpoint(psi, o.ego_altitude_ft, V_MAX_KTS)

    # ── 기본 ───────────────────────────────────────────────────────────

    def _level_flight(self, o: Obs) -> Setpoint:
        """전환·초기화·기본값 — 현재 상태 유지."""
        return Setpoint(o.heading_deg, o.ego_altitude_ft, V_TRIM_KTS)

    def _climb(self, o: Obs) -> Setpoint:
        """ClimbTo 포팅 — wings-level 최대 상승 (HardDeck 회피, 선회 아님).
        원본: heading 유지 + 급상승 + 속도 유지. → psi*=현재heading(레벨), h*=목표고도.
        """
        return Setpoint(o.heading_deg, CLIMB_TARGET_FT, V_CORNER_KTS)


# ── 진입 조건 헬퍼 (BT에서 tactic 선택 시 참조) ───────────────────────

def suggest_tactic(o: Obs, scissors_state: bool = False) -> Tactic:
    """obs geometry → 권장 Tactic.

    BT가 직접 결정하는 경우 사용 안 해도 됨.
    rule-based fallback / 테스트용.
    TACTIC_SPEC.md §4 진입 조건 기준.
    """
    # 방어 우선 (적이 WEZ 진입 임박)
    if o.aa_deg < 30.0 and o.distance_ft < WEZ_MAX_FT and o.closure_kts > 100.0:
        return Tactic.BREAK_TURN

    # GUN_TRACK: WEZ 내 정밀 조준
    if o.ata_deg < GUN_ENTRY_ATA_DEG and o.distance_ft < WEZ_MAX_FT:
        return Tactic.GUN_TRACK

    # 에너지 고갈 or 불리(advantage<−0.3) → EXTENSION
    # advantage: [−1,+1] 무차원. −0.3 ≈ 명확히 방어적 상황.
    if o.ego_vc_kts < 250.0 or (o.advantage < -0.3):
        return Tactic.EXTENSION

    # overshoot → LAG_DISPLACEMENT_ROLL
    if o.aa_deg < o.ata_deg and o.closure_kts > 50.0:
        return Tactic.LAG_DISPLACEMENT_ROLL

    # HIGH_YOYO: 에너지 과잉 or overshoot 위험
    if o.ego_vc_kts > 420.0 or (o.aa_deg < 30.0 and o.ata_deg > 30.0):
        return Tactic.HIGH_YOYO

    # LOW_YOYO: closure 부족 + 에너지 부족
    if o.closure_kts < 0.0 and o.ego_vc_kts < 280.0:
        return Tactic.LOW_YOYO

    # SCISSORS: overshoot 교착 감지 시
    if scissors_state:
        return Tactic.SCISSORS

    # 공격 포지션 (advantage>0.2 = 공격 우위, dist 근접, nose 정렬)
    if o.advantage > 0.2 and o.distance_ft < 6000.0 and o.ata_deg < 45.0:
        return Tactic.LEAD_PURSUIT

    # 강한 공격 우위(advantage>0.5) → 선회전 유지 LAG
    if o.advantage > 0.5:
        return Tactic.LAG_PURSUIT

    # 중립 선회
    ego_turn_sign = _sign(o.roll_deg) if abs(o.roll_deg) > 5.0 else 0.0
    opp_turn_sign = _sign(o.omega_opp_signed) if abs(o.omega_opp_signed) > 2.0 else 0.0
    if ego_turn_sign != 0.0 and opp_turn_sign != 0.0:
        if ego_turn_sign != opp_turn_sign:
            return Tactic.ONE_CIRCLE
        else:
            return Tactic.TWO_CIRCLE

    return Tactic.PURE_PURSUIT


if __name__ == "__main__":
    # 단위 검증 — 대표 상황 5개
    gl = GuidanceLayer()

    # 테스트 dict: engine/obs.py Observation 키 사용 (단위 §0 준수)
    # advantage = 1 − (ata+aa)/180 로 계산해 일관성 유지.
    def _adv(ata, aa): return 1.0 - (ata + aa) / 180.0
    cases = [
        ("head-on merge (ONE_CIRCLE)", Tactic.ONE_CIRCLE, {
            "ego_psi_deg": 90.0, "ego_alt_ft": 15000.0, "ego_vc_kts": 350.0,
            "ata_deg": 170.0, "aa_deg": 170.0, "rel_b_deg": 5.0,
            "closure_kts": 600.0, "distance_ft": 8000.0, "ego_phi_deg": -15.0,
            "enm_r_dps": 10.0, "enm_alt_ft": 15000.0, "advantage": _adv(170,170),
        }),
        ("WEZ 진입 (GUN_TRACK)", Tactic.GUN_TRACK, {
            "ego_psi_deg": 0.0, "ego_alt_ft": 15000.0, "ego_vc_kts": 380.0,
            "ata_deg": 10.0, "aa_deg": 160.0, "rel_b_deg": -8.0,
            "closure_kts": 50.0, "distance_ft": 2000.0, "ego_phi_deg": -5.0,
            "enm_r_dps": -8.0, "enm_alt_ft": 15200.0, "advantage": _adv(10,160),
        }),
        ("에너지 고갈 (EXTENSION)", Tactic.EXTENSION, {
            "ego_psi_deg": 180.0, "ego_alt_ft": 12000.0, "ego_vc_kts": 240.0,
            "ata_deg": 60.0, "aa_deg": 30.0, "rel_b_deg": 90.0,
            "closure_kts": -20.0, "distance_ft": 5000.0, "ego_phi_deg": 0.0,
            "enm_r_dps": 5.0, "enm_alt_ft": 12000.0, "advantage": _adv(60,30),
        }),
        ("overshoot (LAG_DISPLACEMENT_ROLL)", Tactic.LAG_DISPLACEMENT_ROLL, {
            "ego_psi_deg": 270.0, "ego_alt_ft": 14000.0, "ego_vc_kts": 400.0,
            "ata_deg": 50.0, "aa_deg": 30.0, "rel_b_deg": -30.0,
            "closure_kts": 80.0, "distance_ft": 3500.0, "ego_phi_deg": -30.0,
            "enm_r_dps": -12.0, "enm_alt_ft": 15000.0, "advantage": _adv(50,30),
        }),
        ("scissors 교착 반전", Tactic.SCISSORS, {
            "ego_psi_deg": 45.0, "ego_alt_ft": 16000.0, "ego_vc_kts": 320.0,
            "ata_deg": 25.0, "aa_deg": 20.0, "rel_b_deg": 20.0,
            "closure_kts": 10.0, "distance_ft": 2500.0, "ego_phi_deg": 20.0,
            "enm_r_dps": 8.0, "enm_alt_ft": 16000.0, "advantage": _adv(25,20),
        }),
    ]

    print(f"{'상황':<35} {'psi*':>8} {'h*':>9} {'v*':>8}")
    print("-" * 65)
    for label, tactic, obs_d in cases:
        sp = gl.compute(tactic, obs_d)
        print(f"{label:<35} {sp.psi_star_deg:>7.1f}° {sp.h_star_ft:>8.0f}ft {sp.v_star_kts:>7.1f}kts")
