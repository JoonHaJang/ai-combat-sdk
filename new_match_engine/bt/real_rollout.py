"""Real-engine Rollout Selector — 실제 JSBSim 으로 후보 tactic rollout (P4 제거).

kinematic surrogate 가 6000~12000ft/114° 오차로 불신뢰(P4 실증) → **실제 엔진**으로 rollout.
state capture/restore(0.1ms) + scratch plant 재사용으로 속도 확보(~144000 step/s).

설계 (프로젝트 PHASE1_MPC Stage A 비전):
  - dynamics = 실제 JSBSim (대리모델 아님 → P4 제로)
  - OppModel = constant_action (적 마지막 입력 H초 유지 = Phase 1 default, mode-persistence)
  - 후보 tactic 각각 H초 미니매치 → 실제 geometry → shaped cost → 최고 선택
  - cost 기반 적응형 (적 거동 바뀌면 rollout 결과 바뀜 → tactic 자동 변경). 하드코딩 아님.

cadence: 매 BT tick 아닌 ~1s 마다 rollout (tactic dwell). 후보 prune 으로 추가 가속.
"""
from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

import numpy as np
from plant import F16Plant
from autopilot import AutopilotConfig
from pilot import Pilot
from obs import compute_obs
from tactic import Tactic, WEZ_ATA_DEG, WEZ_MIN_FT, WEZ_MAX_FT
from situation import classify as classify_situation   # 상황 분류 (후보 pruning 용)
from judge import wez_damage                            # ★ 실제 게임 데미지 규칙

WEZ_MID_FT = 0.5 * (WEZ_MIN_FT + WEZ_MAX_FT)
_G = 32.174; _KT = 1.68781


def _es(alt_ft, vc_kts):
    v = vc_kts * _KT
    return alt_ft + v * v / (2.0 * _G)


def _es_diff(o12):
    return _es(o12.ego_alt_ft, o12.ego_vc_kts) - _es(o12.enm_alt_ft, o12.enm_vc_kts)


# ── ★ Universal 게임 목적 (적 무관 — 게임 규칙 grounding, 손튜닝 가중 금지) ──
#   적에 맞춘 가중 = overfit → 모르는 적서 깨짐. 대신 "실제 게임 점수"를 직접 시뮬.
#   에너지·위치는 창발 (에너지 까먹으면 미래 위치↓ → 점수↓, rollout 이 자동 포착).
def _wez_margin(o):
    """gun solution 근접도 [0,1] — 관측 기반, 적 무관. (WEZ 도달 gradient)
    ata 낮고(겨냥) WEZ 거리일수록 ↑. = 게임 승리(WEZ 데미지) 직전 상태.
    """
    ata_term = max(0.0, 1.0 - o.ata_deg / 90.0)        # 90°까지 gradient (정렬 유도)
    d = o.distance_ft
    if d < WEZ_MIN_FT:
        rng = d / WEZ_MIN_FT
    elif d <= WEZ_MAX_FT:
        rng = 1.0
    else:
        rng = max(0.0, 1.0 - (d - WEZ_MAX_FT) / 22000.0)  # 먼 거리도 gradient(닫기 유도)
    return ata_term * rng


def universal_score(o12, o21, dt):
    """★ 실제 게임 목적 = (우리가 가하는 WEZ dmg − 받는 dmg) + 위치마진차(우리−적).

    적 행동에 무관 (게임 judge 규칙 그대로). dmg 가 실제 점수, margin 은 멀 때 gradient.
    에너지/각도/거리 모두 이 목적의 창발적 means (별도 손가중 不要).
    """
    dmg = (wez_damage(o12.ata_deg, o12.distance_ft, dt)
           - wez_damage(o21.ata_deg, o21.distance_ft, dt))
    margin = _wez_margin(o12) - _wez_margin(o21)        # 우리 vs 적 (대칭, 상대적)
    return dmg * 20.0 + margin                          # 실제 dmg 강조 + 위치 gradient

# ── 물리 기반 상황별 admissible 후보 (★ 교전유형 = 지배 물리량 → 적합 tactic) ──
#   CHASE(속도 지배): sprint 추격 tactic (chase PID → max speed).
#   CIRCLE(선회율 지배): corner speed 선회 tactic (V_CORNER → 최대 ω).
#   DEFENSIVE(거부): 방어·회피 tactic.
CANDIDATES_CHASE = [
    Tactic.PURE_PURSUIT, Tactic.LEAD_PURSUIT, Tactic.GUN_TRACK,
]
CANDIDATES_CIRCLE = [
    Tactic.ONE_CIRCLE, Tactic.TWO_CIRCLE, Tactic.LEAD_PURSUIT,
    Tactic.LAG_PURSUIT, Tactic.HIGH_YOYO,
]
CANDIDATES_DEFENSIVE = [
    Tactic.BREAK_TURN, Tactic.EXTENSION, Tactic.LOW_YOYO, Tactic.TWO_CIRCLE,
]


# ── 상황 분류 (★ 단일 cost 금지 — 상황별 별도 cost) ───────────────────
#   메모리 [[situation-conditional-vision]] [[r11-sub-situation-framework]]:
#   dogfight=상황 조합. 글로벌 cost 자기모순. 상황이 목표(cost)를 정함.
from situation import DEFENSIVE, CHASE, CIRCLE   # 물리 기반 상황 상수


# ── HRL 하위 전문가 정책 = 물리 기반 상황별 cost (★ 지배 물리량 + 상호 비충돌) ──
#   출처: "Hierarchical RL for Air-to-Air Combat" + 측정(E-M 곡선).
#   규율: ① 상황 상호배타(HCA 물리 판별), ② 각 cost 는 그 상황 지배 물리량,
#   ③ 내부 term 같은 방향(충돌 X). 모두 relational(WEZ 규칙, 적 무관).

def _energy_norm(o12):
    """Es차 → [-1,+1] 부드럽게 (tanh). 적 무관 상대 에너지. 보조 term 용."""
    return math.tanh(_es_diff(o12) / 6000.0)


def _cost_chase(o12, o21):
    """CHASE 전문가 (속도 지배): dominant = 우리 WEZ 안착(거리 closing + nose-on).
    속도(max)는 chase tactic 의 chase PID 가 처리. 에너지 term 無(추격은 속도 우선)."""
    wez = 5.0 if (o12.ata_deg < WEZ_ATA_DEG and WEZ_MIN_FT <= o12.distance_ft <= WEZ_MAX_FT) else 0.0
    return 3.0 * _wez_margin(o12) + wez                 # dominant: 우리 위치 품질(거리·각도)


def _cost_circle(o12, o21):
    """CIRCLE 전문가 (선회율 지배): dominant = out-rate(우리 nose 가 적보다 앞서기).
    상대 margin 차 = 선회율 우위의 결과. 에너지(corner speed 유지) 보조 — 같은 방향."""
    out_rate = _wez_margin(o12) - _wez_margin(o21)      # dominant: 상대 각도우위(out-rate 결과)
    energy = _energy_norm(o12)                          # corner 에너지 유지(우위 밑천)
    return 2.0 * out_rate + energy


def _cost_defensive(o12, o21):
    """DEFENSIVE 전문가: dominant = 적 gun solution 거부. 보조 = 에너지보존·반격기회.
    deny↑·energy보존·reversal 모두 '생존→반격' 같은 방향 (비충돌)."""
    deny = 1.0 - _wez_margin(o21)                       # dominant: 적 마진 낮출수록↑
    reversal = _wez_margin(o12)                         # 반격(우리 뒤잡기) 기회
    energy = 0.5 * (_energy_norm(o12) + 1.0)            # 에너지 보존 [0,1] (생존 밑천)
    return 3.0 * deny + reversal + energy


_COST = {CHASE: _cost_chase, CIRCLE: _cost_circle, DEFENSIVE: _cost_defensive}
_CANDS = {CHASE: CANDIDATES_CHASE, CIRCLE: CANDIDATES_CIRCLE,
          DEFENSIVE: CANDIDATES_DEFENSIVE}


class RealRollout:
    """실엔진 rollout selector. scratch plant/pilot 재사용 → 1회 생성."""

    def __init__(self, lqr, cfg: AutopilotConfig | None = None,
                 horizon_s: float = 8.0, control_hz: float = 20.0,
                 safe_deck_ft: float = 2500.0, recompute_every: int = 10):
        self.lqr = lqr
        self.cfg = cfg or AutopilotConfig(KP_PSI=0.10)
        self.H = horizon_s
        self.control_hz = control_hz
        self.safe_deck_ft = safe_deck_ft       # Safety: 이 고도 미만 → 비상 상승
        # ★ rollout 캐싱 — 적은 10Hz tick(legacy 동일) but 우리 rollout 은 N tick 마다.
        #   recompute_every=10 @ bt 10Hz → 1s 마다 재계산. 그사이 캐시 tactic.
        self.recompute_every = recompute_every
        self._call_n = 0
        self._cached: Tactic = Tactic.LEVEL_FLIGHT
        # scratch plants/pilots (재사용 — 매 rollout restore 로 상태 주입)
        self._us = F16Plant(); self._us.set_ic(15000.0, 350.0); self._us.trim(); self._us.step(2)
        self._op = F16Plant(); self._op.set_ic(15000.0, 350.0); self._op.trim(); self._op.step(2)
        self._pilot_us = Pilot(self._us, lqr, self.cfg, 1.0 / control_hz)

    def select(self, live_us: F16Plant, live_op: F16Plant) -> Tactic:
        """live 플랜트 상태 capture → 후보별 실엔진 미니매치 → 최고 score tactic.

        ★ recompute_every tick 마다만 rollout 재계산(비용↓), 그 외 캐시 반환.
          단 Safety(hard deck)는 매 tick 즉시 — 안전은 지연 불가.
        """
        # Safety 는 캐시 무시, 매 tick 체크 (지연 시 자멸)
        o_safe = compute_obs(live_us, live_op)
        if o_safe.ego_alt_ft < self.safe_deck_ft:
            self.last_situation = "SAFETY"
            self._cached = Tactic.CLIMB
            return Tactic.CLIMB
        # rollout 캐싱: 주기 아니면 이전 결정 유지
        self._call_n += 1
        if (self._call_n - 1) % self.recompute_every != 0:
            return self._cached
        self._cached = self._rollout(live_us, live_op)
        return self._cached

    def _rollout(self, live_us: F16Plant, live_op: F16Plant) -> Tactic:
        snap_us = live_us.capture_state()
        snap_op = live_op.capture_state()
        u_op_const = snap_op["_u"]                 # OppModel = constant_action
        cdt = 1.0 / self.control_hz
        dt_phys = self._us.dt
        n_ctrl = max(1, int(round(cdt / dt_phys)))
        n_ticks = int(round(self.H / cdt))

        # ★ HRL: manager(classifier) → 상황별 전문가(cost+후보). 상호배타·비충돌.
        o_now = compute_obs(live_us, live_op)
        sit = classify_situation(o_now)
        cost_fn = _COST[sit]                            # 그 상황 dominant cost
        cands = _CANDS[sit]
        self.last_situation = sit

        best_t, best_score = cands[0], -1e18
        for tac in cands:
            self._us.restore_state(snap_us)
            self._op.restore_state(snap_op)
            self._op.set_input(u_op_const)
            score = 0.0
            for k in range(n_ticks):
                u = self._pilot_us.step(self._op, tactic=tac)
                self._us.set_input(u)
                self._op.set_input(u_op_const)   # 적 입력 고정 (constant_action)
                for _ in range(n_ctrl):
                    self._us.step(1); self._op.step(1)
                o12 = compute_obs(self._us, self._op)   # 우리→적
                o21 = compute_obs(self._op, self._us)   # 적→우리
                w = 1.0 + 2.0 * (k / n_ticks)    # terminal 가중
                score += w * cost_fn(o12, o21)          # 상황 전문가 cost
            if score > best_score:
                best_score, best_t = score, tac
        return best_t


if __name__ == "__main__":
    from run_nme import run_match
    from lqr import GainScheduledLQR

    print("=" * 64)
    print("  Real-engine Rollout 검증 (P4 제거) — vs 직진/TWO_CIRCLE 적")
    print("=" * 64)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    rr = RealRollout(gs, horizon_s=8.0)

    # selector 가 live 플랜트 접근 필요 → run_match 는 obs 만 줌. 직접 매치 구성.
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
    from match import Match
    from scenarios import spawn_adt_neutral

    for label, t2 in (("realroll_vs_straight", lambda o: Tactic.LEVEL_FLIGHT),
                      ("realroll_vs_twocircle", lambda o: Tactic.TWO_CIRCLE)):
        p1, p2 = spawn_adt_neutral()
        m = Match(p1, p2, gs, cfg1=AutopilotConfig(KP_PSI=0.10), cfg2=AutopilotConfig(KP_PSI=0.10),
                  control_hz=20, bt_hz=1, log_hz=0)   # bt_hz=1 → rollout 1초마다
        # tactic_fn1 이 rollout (live 플랜트 클로저)
        res = m.run(tactic_fn1=lambda o: rr.select(p1, p2), tactic_fn2=t2, duration_s=120.0)
        print(f"\n  {label}: winner={res.winner} t={res.time_s:.0f}s "
              f"H1={res.health1:.0f} H2={res.health2:.0f} dmg={res.damage_dealt1:.0f}")
