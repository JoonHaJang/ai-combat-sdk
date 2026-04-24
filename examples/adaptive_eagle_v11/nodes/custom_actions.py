"""
Adaptive Eagle 전체 BFM 커스텀 액션 노드

모든 노드에 TUNABLE_PARAMS를 선언하여 optimizer가 전체 공간을 자동 탐색.
빌트인 고정값이 default에 포함되므로 결과 >= 빌트인 보장.

카테고리:
  1. 추적/공격 (OBFM): SmartLeadPursuit, SmartPurePursuit, SmartLagPursuit, SmartGunAttack, SnapshotAttack
  2. 에너지 기동: SmartHighYoYo, SmartLowYoYo, SmartClimbingTurn, SmartDescendingTurn, VerticalFight
  3. 방어 (DBFM): SmartBreakTurn, SmartDefensiveSpiral, ExtensionBreak, Jink, GunsDefense, LastDitch
  4. 교전/선회전 (HABFM): SmartOneCircle, SmartTwoCircle, FlatScissors, RollingScissors
  5. 공전 탈출: HeadOnBreak
  6. 유틸: UnloadedExtension, Chandelle
"""

import random
import logging
import py_trees

logger = logging.getLogger(__name__)


# ─── Base ─────────────────────────────────────────────────────

class BaseAction(py_trees.behaviour.Behaviour):
    def __init__(self, name: str):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="action", access=py_trees.common.Access.WRITE)

    def set_action(self, alt: int, hdg: int, vel: int):
        self.blackboard.action = [alt, hdg, vel]

    def _obs(self):
        return self.blackboard.observation

    def _hdg_from_bearing(self, bearing_deg, gain=1.0):
        cmd = bearing_deg * gain
        return max(0, min(8, int(round(cmd / 22.5)) + 4))

    def _hdg_from_tau(self, tau_deg, gain=1.0):
        cmd = tau_deg * gain
        return max(0, min(8, int(round(cmd / 22.5)) + 4))

    def _safe_alt(self, desired, obs):
        """Hard Deck 보호: 저고도에서 하강 명령 차단."""
        alt = obs.get("ego_altitude_ft", 10000)
        if alt < 2000 and desired < 2:
            return 3  # 강제 상승
        return desired


# ═══════════════════════════════════════════════════════════════
# 1. 추적/공격 (OBFM)
# ═══════════════════════════════════════════════════════════════

class SmartLeadPursuit(BaseAction):
    """Purpose-driven Lead Pursuit.

    목적: 적의 미래 위치 앞에 기수를 두어 gun solution을 확보.
         총탄 비행시간을 보상하는 리드각을 유지하며 코너 속도에서 선회.

    BFM 불변 법칙 (관측 기반 피드백):
    ─────────────────────────────────────────────────────────
    (1) 추격 실패 감지: 거리 증가 + closure 음수 → 반경 좁히기 (max G)
    (2) 포인팅 실패  : ATA 증가 중 → 타이트 턴 + 감속
    (3) 원거리 가속  : 거리 원거리 + 포인팅 OK → 코너속도 이상으로 가속
    (4) 오버슈트 임박: 근접 + closure 과다 → 감속 브레이크
    (5) 에너지 과다  : e_diff 높음 + 고도 우위 → 하강 공격으로 변환
    """
    TUNABLE_PARAMS = {
        # BFM 불변 임계값 (작은 튜닝 범위만 허용)
        "dist_widen_thresh_ft":  {"type": "cont", "range": (10, 100), "default": 30},
        "ata_worsen_thresh_deg": {"type": "cont", "range": (1, 8), "default": 3},
        "overshoot_closure_kts": {"type": "cont", "range": (200, 400), "default": 280},
        "far_dist_ft":           {"type": "cont", "range": (5000, 12000), "default": 7000},
        "sprint_ata_max_deg":    {"type": "cont", "range": (20, 45), "default": 30},
        "dive_dist_ft":          {"type": "cont", "range": (2000, 6000), "default": 4000},
        "energy_dive_thresh_ft": {"type": "cont", "range": (1500, 5000), "default": 2500},
        "heading_gain":          {"type": "cont", "range": (0.8, 1.5), "default": 1.0},
    }

    def __init__(self, name="SmartLeadPursuit",
                 dist_widen_thresh_ft=30, ata_worsen_thresh_deg=3,
                 overshoot_closure_kts=280, far_dist_ft=7000,
                 sprint_ata_max_deg=30, dive_dist_ft=4000,
                 energy_dive_thresh_ft=2500, heading_gain=1.0,
                 **kwargs):
        super().__init__(name)
        self.dist_widen_thresh = dist_widen_thresh_ft
        self.ata_worsen_thresh = ata_worsen_thresh_deg
        self.overshoot_closure = overshoot_closure_kts
        self.far_dist = far_dist_ft
        self.sprint_ata_max = sprint_ata_max_deg
        self.dive_dist = dive_dist_ft
        self.energy_dive_thresh = energy_dive_thresh_ft
        self.heading_gain = heading_gain
        # 시계열 상태
        self._prev_dist = None
        self._prev_ata = None

    def update(self):
        try:
            obs = self._obs()
            rel_b = obs.get("relative_bearing_deg", 0) * 180
            ata = obs.get("ata_deg", 0.5) * 180
            dist = obs.get("distance_ft", 10000)
            closure = obs.get("closure_rate_kts", 0)
            e_diff = obs.get("energy_diff_ft", 0)
            alt_adv = obs.get("alt_advantage", False)

            # 시계열 델타
            dist_widening = (self._prev_dist is not None
                             and dist > self._prev_dist + self.dist_widen_thresh)
            ata_worsening = (self._prev_ata is not None
                             and ata > self._prev_ata + self.ata_worsen_thresh)
            self._prev_dist = dist
            self._prev_ata = ata

            # 기본 heading (bearing → hdg_idx)
            base_hdg = self._hdg_from_bearing(rel_b, self.heading_gain)

            # ─── BFM 법칙 (우선순위 순) ─────────────────
            # (1) 추격 실패: 거리 벌어짐 + closure 음수
            if dist_widening and closure < 0:
                # 반경 극소화: hdg 최대 편향, 속도 감속
                hdg = max(0, base_hdg - 2) if base_hdg <= 4 else min(8, base_hdg + 2)
                vel = 2  # 코너 속도 아래로 감속 → 선회율 최대
                alt_idx = self._safe_alt(2, obs)

            # (2) 포인팅 실패: ATA 커지는 중
            elif ata_worsening:
                hdg = max(0, base_hdg - 1) if base_hdg <= 4 else min(8, base_hdg + 1)
                vel = 2
                alt_idx = self._safe_alt(2, obs)

            # (3) 오버슈트 임박: 근접 + closure 과다
            elif dist < 2500 and closure > self.overshoot_closure:
                hdg = base_hdg  # 그대로
                vel = 1  # 감속
                alt_idx = self._safe_alt(2, obs)

            # (4) 원거리 sprint: 거리 멀고 포인팅 OK → 가속
            elif dist > self.far_dist and ata < self.sprint_ata_max:
                hdg = base_hdg
                vel = 4
                alt_idx = self._safe_alt(2, obs)

            # (5) 에너지 과다 + 고도 우위 + 근접: 하강 공격
            elif e_diff > self.energy_dive_thresh and alt_adv and dist < self.dive_dist:
                hdg = base_hdg
                vel = 4
                alt_idx = self._safe_alt(1, obs)  # 하강

            # 기본: 코너 속도 lead pursuit
            else:
                hdg = base_hdg
                vel = 3  # 코너 속도
                alt_idx = self._safe_alt(2, obs)

            self.set_action(alt_idx, hdg, vel)
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"SmartLeadPursuit: {e}")
            self.set_action(2, 4, 3)
            return py_trees.common.Status.SUCCESS


class SmartPurePursuit(BaseAction):
    """Purpose-driven Pure Pursuit.

    목적: 기수를 적에게 직접 지향하여 각도 회수. 근거리 또는 높은 ATA 상황.
         각도 확보 최우선 → 에너지 희생 OK (단 코너속도 아래로는 금지).

    BFM 불변 법칙:
    (1) ATA > 60°: 최대 G 턴, 속도 감속 (선회율 극대화)
    (2) ATA 증가 중: 현재 턴이 부족 → 강도 증가
    (3) ATA 작고 거리 증가: 포인팅 실패 아님, 가속 필요
    (4) 근접 + ATA 작음: 리드 전환 단계 → 현재 유지
    """
    TUNABLE_PARAMS = {
        "max_g_ata_thresh":      {"type": "cont", "range": (40, 80), "default": 60},
        "dist_widen_thresh_ft":  {"type": "cont", "range": (10, 100), "default": 30},
        "ata_worsen_thresh_deg": {"type": "cont", "range": (1, 8), "default": 3},
        "corner_vel_idx":        {"type": "disc", "choices": [2, 3], "default": 2},
        "sprint_vel_idx":        {"type": "disc", "choices": [3, 4], "default": 4},
    }

    def __init__(self, name="SmartPurePursuit",
                 max_g_ata_thresh=60, dist_widen_thresh_ft=30,
                 ata_worsen_thresh_deg=3, corner_vel_idx=2, sprint_vel_idx=4,
                 # backward compat
                 turn_intensity=None, vel=None, **kwargs):
        super().__init__(name)
        self.max_g_ata_thresh = max_g_ata_thresh
        self.dist_widen_thresh = dist_widen_thresh_ft
        self.ata_worsen_thresh = ata_worsen_thresh_deg
        self.corner_vel_idx = corner_vel_idx
        self.sprint_vel_idx = sprint_vel_idx
        self._prev_dist = None
        self._prev_ata = None

    def update(self):
        try:
            obs = self._obs()
            side = obs.get("side_flag", 0)
            ata = obs.get("ata_deg", 0.5) * 180
            dist = obs.get("distance_ft", 5000)

            dist_widening = (self._prev_dist is not None
                             and dist > self._prev_dist + self.dist_widen_thresh)
            ata_worsening = (self._prev_ata is not None
                             and ata > self._prev_ata + self.ata_worsen_thresh)
            self._prev_dist = dist
            self._prev_ata = ata

            # side_flag 기반 방향
            sign = 1 if side > 0 else -1

            # (1) 최대 G 턴 구간
            if ata > self.max_g_ata_thresh or ata_worsening:
                intensity = 4  # max
                vel = self.corner_vel_idx  # 코너 속도
            # (2) ATA 낮은데 거리 벌어짐 → sprint
            elif ata < 20 and dist_widening:
                intensity = 1
                vel = self.sprint_vel_idx
            # (3) 일반 pure pursuit
            else:
                intensity = 2
                vel = 3  # 코너 속도 근처

            hdg = 4 + sign * intensity
            self.set_action(2, max(0, min(8, hdg)), vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self.set_action(2, 4, 3)
            return py_trees.common.Status.SUCCESS


class SmartLagPursuit(BaseAction):
    """Purpose-driven Lag Pursuit.

    목적: 적의 후방(tail) lag 각도 유지로 오버슈트 회피하며 position keep.
         적이 턴하면 turn-circle 안쪽으로 cut, 적이 직진이면 sprint 접근.

    BFM 불변 법칙 (관측 기반 피드백):
    ─────────────────────────────────────────────────────────
    (1) 오버슈트 임박: closure 과다 + 근접 → 감속 vel=1, lag 더 강하게
    (2) 추격 실패  : 거리 벌어짐 + closure 음수 → tighter turn, 감속
    (3) ATA 증가  : 적이 빠른 선회 중 → tau_gain 증폭 (lag 유지)
    (4) 원거리 sprint: 거리 멀고 ATA 작음 → vel=4 가속
    (5) 에너지 열세: e_diff 낮음 → vel 보수 (에너지 회복)
    """
    TUNABLE_PARAMS = {
        "tau_gain":              {"type": "cont", "range": (0.3, 1.5), "default": 0.6},
        "vel":                   {"type": "disc", "choices": [2, 3, 4], "default": 3},
        "overshoot_closure_kts": {"type": "cont", "range": (200, 400), "default": 280},
        "overshoot_dist_ft":     {"type": "cont", "range": (1500, 4000), "default": 2500},
        "dist_widen_thresh_ft":  {"type": "cont", "range": (10, 100), "default": 30},
        "ata_worsen_thresh_deg": {"type": "cont", "range": (1, 8), "default": 3},
        "far_dist_ft":           {"type": "cont", "range": (5000, 12000), "default": 8000},
        "sprint_ata_max_deg":    {"type": "cont", "range": (20, 60), "default": 40},
        "low_energy_thresh_ft":  {"type": "cont", "range": (-5000, 0), "default": -2000},
    }

    def __init__(self, name="SmartLagPursuit", tau_gain=0.6, vel=3,
                 overshoot_closure_kts=280, overshoot_dist_ft=2500,
                 dist_widen_thresh_ft=30, ata_worsen_thresh_deg=3,
                 far_dist_ft=8000, sprint_ata_max_deg=40,
                 low_energy_thresh_ft=-2000, **kwargs):
        super().__init__(name)
        self.tau_gain = tau_gain
        self.vel = vel
        self.overshoot_closure = overshoot_closure_kts
        self.overshoot_dist = overshoot_dist_ft
        self.dist_widen_thresh = dist_widen_thresh_ft
        self.ata_worsen_thresh = ata_worsen_thresh_deg
        self.far_dist = far_dist_ft
        self.sprint_ata_max = sprint_ata_max_deg
        self.low_energy_thresh = low_energy_thresh_ft
        self._prev_dist = None
        self._prev_ata = None

    def update(self):
        try:
            obs = self._obs()
            tau = obs.get("tau_deg", 0) * 180
            ata = obs.get("ata_deg", 0.5) * 180
            dist = obs.get("distance_ft", 10000)
            closure = obs.get("closure_rate_kts", 0)
            e_diff = obs.get("energy_diff_ft", 0)

            dist_widening = (self._prev_dist is not None
                             and dist > self._prev_dist + self.dist_widen_thresh)
            ata_worsening = (self._prev_ata is not None
                             and ata > self._prev_ata + self.ata_worsen_thresh)
            self._prev_dist = dist
            self._prev_ata = ata

            # base heading: tau + gain
            base_hdg = self._hdg_from_tau(tau, self.tau_gain)

            # ─── BFM 법칙 (우선순위 순) ─────────────────
            # (1) 오버슈트 임박: closure 과다 + 근접
            if dist < self.overshoot_dist and closure > self.overshoot_closure:
                # lag 더 강하게 (tau_gain 1.3× 효과), 대폭 감속
                hdg = self._hdg_from_tau(tau, self.tau_gain * 1.3)
                vel = 1

            # (2) 추격 실패: 거리 벌어짐 + closure 음수
            elif dist_widening and closure < 0:
                # tighter turn (기동 방향 강조) + 감속
                hdg = max(0, base_hdg - 1) if base_hdg <= 4 else min(8, base_hdg + 1)
                vel = 2

            # (3) ATA 증가 중 (적 빠른 선회): lag 증폭
            elif ata_worsening and ata > 45:
                hdg = self._hdg_from_tau(tau, self.tau_gain * 1.2)
                vel = 2

            # (4) 원거리 + ATA 작음: sprint
            elif dist > self.far_dist and ata < self.sprint_ata_max:
                hdg = base_hdg
                vel = 4

            # (5) 에너지 열세: vel 보수 (자체 default보다 낮게)
            elif e_diff < self.low_energy_thresh:
                hdg = base_hdg
                vel = max(2, self.vel - 1)

            # 기본 lag pursuit
            else:
                hdg = base_hdg
                vel = self.vel

            alt_idx = self._safe_alt(2, obs)
            self.set_action(alt_idx, hdg, vel)
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"SmartLagPursuit: {e}")
            self.set_action(2, 4, 3)
            return py_trees.common.Status.SUCCESS


class SmartGunAttack(BaseAction):
    """PD 제어 정밀 사격 — Golden BT 패턴."""
    TUNABLE_PARAMS = {
        "kp":          {"type": "cont", "range": (0.5, 2.5), "default": 1.2},
        "kd":          {"type": "cont", "range": (0.1, 1.0), "default": 0.5},
        "vel_approach": {"type": "disc", "choices": [2, 3], "default": 3},
        "vel_wez":      {"type": "disc", "choices": [0, 1, 2], "default": 1},
    }

    def __init__(self, name="SmartGunAttack", kp=1.2, kd=0.5,
                 vel_approach=3, vel_wez=1):
        super().__init__(name)
        self.kp = kp
        self.kd = kd
        self.vel_approach = vel_approach
        self.vel_wez = vel_wez
        self._prev_tau = 0.0

    def update(self):
        try:
            obs = self._obs()
            tau = obs.get("tau_deg", 0) * 180
            dist = obs.get("distance_ft", 1000)
            tau_rate = tau - self._prev_tau
            self._prev_tau = tau
            cmd = self.kp * tau + self.kd * tau_rate
            hdg = max(0, min(8, int(round(cmd / 22.5)) + 4))
            vel = self.vel_approach if dist > 914 else self.vel_wez
            self.set_action(2, hdg, vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self.set_action(2, 4, 2)
            return py_trees.common.Status.SUCCESS


class SnapshotAttack(BaseAction):
    """순간 교차 사격 — WEZ 진입 감지 시 1-2틱 사격 후 이탈."""
    TUNABLE_PARAMS = {
        "fire_ticks":   {"type": "disc", "choices": [1, 2, 3], "default": 2},
        "break_hdg":    {"type": "disc", "choices": [0, 1, 2, 6, 7, 8], "default": 0},
    }

    def __init__(self, name="SnapshotAttack", fire_ticks=2, break_hdg=0):
        super().__init__(name)
        self.fire_ticks = fire_ticks
        self.break_hdg = break_hdg
        self._tick = 0

    def update(self):
        try:
            obs = self._obs()
            tau = obs.get("tau_deg", 0) * 180
            if self._tick < self.fire_ticks:
                hdg = self._hdg_from_tau(tau, 1.2)
                self.set_action(2, hdg, 1)  # 감속+조준
                self._tick += 1
            else:
                self.set_action(2, self.break_hdg, 4)  # 이탈
                self._tick = 0
                return py_trees.common.Status.SUCCESS
            return py_trees.common.Status.SUCCESS
        except Exception:
            self._tick = 0
            self.set_action(2, 4, 4)
            return py_trees.common.Status.SUCCESS


# ═══════════════════════════════════════════════════════════════
# 2. 에너지 기동
# ═══════════════════════════════════════════════════════════════

class SmartHighYoYo(BaseAction):
    """Purpose-driven High Yo-Yo.

    목적: 적의 turn circle 안쪽에 들어갔을 때(오버슈트 임박) 초과 closure를
         **수직 에너지로 변환**해 위치를 유지. 그 후 하강 공격.

    BFM 불변 법칙:
    (1) CLIMB 중 거리 증가 → yoyo 반경이 너무 큼 → 즉시 DIVE 전환
    (2) CLIMB 중 closure 정상화(|closure| < 100) → 역할 완료 → DIVE
    (3) CLIMB 중 에너지 과다(e_diff > 3000) → 강제 DIVE (폭주 방지)
    (4) DIVE 중 WEZ 조건 근접(ATA<15, dist<2000) → 완료 → 부모 BT가 LeadPursuit 선택
    (5) DIVE 중 closure 다시 과다 → 부족한 선회, 재 CLIMB

    기존 버전의 문제: climb_ticks 고정 → golden전 에너지 +18144ft 폭주.
    """
    TUNABLE_PARAMS = {
        "energy_force_dive_ft":   {"type": "cont", "range": (2000, 5000), "default": 3000},
        "closure_normal_kts":     {"type": "cont", "range": (50, 150), "default": 100},
        "dist_widen_thresh_ft":   {"type": "cont", "range": (20, 200), "default": 80},
        "overshoot_closure_kts":  {"type": "cont", "range": (200, 400), "default": 280},
        "max_climb_ticks":        {"type": "disc", "choices": [4, 6, 8], "default": 6},
        "max_dive_ticks":         {"type": "disc", "choices": [6, 8, 12], "default": 8},
    }

    def __init__(self, name="SmartHighYoYo",
                 energy_force_dive_ft=3000, closure_normal_kts=100,
                 dist_widen_thresh_ft=80, overshoot_closure_kts=280,
                 max_climb_ticks=6, max_dive_ticks=8,
                 # backward compat
                 climb_ticks=None, turn_intensity=None, climb_alt=None,
                 climb_vel=None, dive_vel=None, **kwargs):
        super().__init__(name)
        self.energy_force_dive = energy_force_dive_ft
        self.closure_normal = closure_normal_kts
        self.dist_widen_thresh = dist_widen_thresh_ft
        self.overshoot_closure = overshoot_closure_kts
        self.max_climb_ticks = max_climb_ticks
        self.max_dive_ticks = max_dive_ticks
        self._phase = 0  # 0=CLIMB, 1=DIVE
        self._tick = 0
        self._prev_dist = None

    def update(self):
        try:
            obs = self._obs()
            side = obs.get("side_flag", 0)
            ata = obs.get("ata_deg", 0.5) * 180
            closure = obs.get("closure_rate_kts", 0)
            e_diff = obs.get("energy_diff_ft", 0)
            dist = obs.get("distance_ft", 5000)

            dist_widening = (self._prev_dist is not None
                             and dist > self._prev_dist + self.dist_widen_thresh)
            self._prev_dist = dist

            sign = 1 if side >= 0 else -1
            # 턴은 기본 max-G during yoyo
            turn_magnitude = 3
            # ATA 매우 클 때만 추가
            if ata > 90:
                turn_magnitude = 4
            turn = max(0, min(8, 4 + sign * turn_magnitude))

            # ─── Phase 전환 규칙 (BFM invariant) ──────────
            if self._phase == 0:  # CLIMB
                self._tick += 1
                # (1) 거리 벌어짐 → yoyo 반경 과대 → 즉시 DIVE
                if dist_widening:
                    self._phase = 1
                    self._tick = 0
                # (2) closure 정상화
                elif abs(closure) < self.closure_normal:
                    self._phase = 1
                    self._tick = 0
                # (3) 에너지 과다 → 폭주 방지
                elif e_diff > self.energy_force_dive:
                    self._phase = 1
                    self._tick = 0
                # 최대 tick 제한
                elif self._tick >= self.max_climb_ticks:
                    self._phase = 1
                    self._tick = 0
            else:  # DIVE
                self._tick += 1
                # (5) closure 다시 과다 → 재 climb
                if closure > self.overshoot_closure * 1.2:
                    self._phase = 0
                    self._tick = 0
                elif self._tick >= self.max_dive_ticks:
                    # 완전 리셋 — 다음 호출 시 CLIMB 재시작
                    self._phase = 0
                    self._tick = 0

            # Action 생성
            if self._phase == 0:  # CLIMB
                vel = 3  # 코너속도 유지 (최대 선회율)
                alt_idx = 4  # 상승
            else:  # DIVE
                vel = 4  # 하강 가속
                alt_idx = self._safe_alt(1, obs)

            self.set_action(alt_idx, turn, vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self._phase = 0
            self._tick = 0
            self.set_action(2, 4, 3)
            return py_trees.common.Status.SUCCESS


class SmartLowYoYo(BaseAction):
    """2-phase: 하강+가속 → 상승+위치. 속도 확보.

    Conservative adaptation: overshoot prevention only.
    Full 5-rule adaptive variant was refuted in earlier experiment
    (AGG WR regression via TL dispatch timing shift).
    """
    TUNABLE_PARAMS = {
        "dive_ticks":           {"type": "disc", "choices": [4, 6, 8, 10], "default": 6},
        "dive_alt":             {"type": "disc", "choices": [0, 1], "default": 1},
        "dive_vel":             {"type": "disc", "choices": [3, 4], "default": 4},
        "recover_alt":          {"type": "disc", "choices": [3, 4], "default": 3},
        "recover_vel":          {"type": "disc", "choices": [2, 3], "default": 3},
        "overshoot_dist_ft":    {"type": "cont", "range": (1500, 4000), "default": 2000},
        "overshoot_closure_kts":{"type": "cont", "range": (200, 400), "default": 300},
    }

    def __init__(self, name="SmartLowYoYo", dive_ticks=6, dive_alt=1,
                 dive_vel=4, recover_alt=3, recover_vel=3,
                 overshoot_dist_ft=2000, overshoot_closure_kts=300, **kwargs):
        super().__init__(name)
        self.dive_ticks = dive_ticks
        self.dive_alt = dive_alt
        self.dive_vel = dive_vel
        self.recover_alt = recover_alt
        self.recover_vel = recover_vel
        self.overshoot_dist = overshoot_dist_ft
        self.overshoot_closure = overshoot_closure_kts
        self._phase = 0
        self._tick = 0

    def update(self):
        try:
            obs = self._obs()
            rel_b = obs.get("relative_bearing_deg", 0) * 180
            dist = obs.get("distance_ft", 10000)
            closure = obs.get("closure_rate_kts", 0)
            hdg = self._hdg_from_bearing(rel_b, 1.0)

            # Overshoot prevention: dive phase에서도 근접+고속 접근이면 recover 조기 전환
            if self._phase == 0 and dist < self.overshoot_dist and closure > self.overshoot_closure:
                self._phase = 1
                self._tick = 0

            if self._phase == 0:  # DIVE
                self.set_action(self._safe_alt(self.dive_alt, obs), hdg, self.dive_vel)
                self._tick += 1
                if self._tick >= self.dive_ticks:
                    self._phase = 1
                    self._tick = 0
            else:  # RECOVER
                self.set_action(self.recover_alt, hdg, self.recover_vel)
                self._tick += 1
                if self._tick >= self.dive_ticks:
                    self._phase = 0
                    self._tick = 0
            return py_trees.common.Status.SUCCESS
        except Exception:
            self._phase = 0
            self._tick = 0
            self.set_action(2, 4, 3)
            return py_trees.common.Status.SUCCESS


class SmartClimbingTurn(BaseAction):
    """상승 선회 — 에너지 저장."""
    TUNABLE_PARAMS = {
        "climb_rate":     {"type": "disc", "choices": [3, 4], "default": 3},
        "turn_intensity": {"type": "disc", "choices": [1, 2, 3], "default": 2},
        "vel":            {"type": "disc", "choices": [2, 3, 4], "default": 3},
    }

    def __init__(self, name="SmartClimbingTurn", climb_rate=3, turn_intensity=2, vel=3):
        super().__init__(name)
        self.climb_rate = climb_rate
        self.turn_intensity = turn_intensity
        self.vel = vel

    def update(self):
        try:
            obs = self._obs()
            side = obs.get("side_flag", 0)
            hdg = 4 + self.turn_intensity if side >= 0 else 4 - self.turn_intensity
            self.set_action(self.climb_rate, max(0, min(8, hdg)), self.vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self.set_action(3, 4, 3)
            return py_trees.common.Status.SUCCESS


class SmartDescendingTurn(BaseAction):
    """하강 선회 — 속도 획득."""
    TUNABLE_PARAMS = {
        "descent_rate":   {"type": "disc", "choices": [0, 1], "default": 1},
        "turn_intensity": {"type": "disc", "choices": [1, 2, 3], "default": 2},
        "vel":            {"type": "disc", "choices": [3, 4], "default": 4},
    }

    def __init__(self, name="SmartDescendingTurn", descent_rate=1, turn_intensity=2, vel=4):
        super().__init__(name)
        self.descent_rate = descent_rate
        self.turn_intensity = turn_intensity
        self.vel = vel

    def update(self):
        try:
            obs = self._obs()
            side = obs.get("side_flag", 0)
            hdg = 4 + self.turn_intensity if side >= 0 else 4 - self.turn_intensity
            self.set_action(self._safe_alt(self.descent_rate, obs), max(0, min(8, hdg)), self.vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self.set_action(2, 4, 4)
            return py_trees.common.Status.SUCCESS


class VerticalFight(BaseAction):
    """수직면 기동 — 에너지 우위 활용 급상승+급선회."""
    TUNABLE_PARAMS = {
        "turn_intensity": {"type": "disc", "choices": [2, 3, 4], "default": 3},
        "vel":            {"type": "disc", "choices": [3, 4], "default": 4},
    }

    def __init__(self, name="VerticalFight", turn_intensity=3, vel=4):
        super().__init__(name)
        self.turn_intensity = turn_intensity
        self.vel = vel

    def update(self):
        try:
            obs = self._obs()
            side = obs.get("side_flag", 0)
            hdg = 4 + self.turn_intensity if side >= 0 else 4 - self.turn_intensity
            self.set_action(4, max(0, min(8, hdg)), self.vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self.set_action(4, 4, 4)
            return py_trees.common.Status.SUCCESS


# ═══════════════════════════════════════════════════════════════
# 3. 방어 (DBFM)
# ═══════════════════════════════════════════════════════════════

class SmartBreakTurn(BaseAction):
    """Purpose-driven Break Turn.

    목적: 방어. 적의 lead/pure pursuit 기수를 스치게 만들어 사격 기회 박탈.
         즉시 최대 G, 방향은 적 LOS에서 벗어나는 쪽, 코너 속도 유지.

    BFM 불변 법칙:
    (1) 적 내 WEZ 내 (사격당하는 중) → Last ditch max-G
    (2) 거리 매우 가까움 (dist<2000) → Max-G break
    (3) 거리 중간 + 적이 우리 lead 성공 중 (우리 ATA 감소) → Max-G + 방향 반대
    (4) 거리 멂 (dist>4000) → 에너지 보존 break (속도 유지)
    """
    TUNABLE_PARAMS = {
        "panic_dist_ft":       {"type": "cont", "range": (1000, 3000), "default": 2000},
        "extend_dist_ft":      {"type": "cont", "range": (3000, 6000), "default": 4000},
        "ata_worsen_thresh":   {"type": "cont", "range": (1, 5), "default": 2},
        "alt_split_ft":        {"type": "cont", "range": (6000, 12000), "default": 8000},
    }

    def __init__(self, name="SmartBreakTurn",
                 panic_dist_ft=2000, extend_dist_ft=4000,
                 ata_worsen_thresh=2, alt_split_ft=8000,
                 # backward compat
                 vel=None, alt_high=None, alt_mid=None, **kwargs):
        super().__init__(name)
        self.panic_dist = panic_dist_ft
        self.extend_dist = extend_dist_ft
        self.ata_worsen_thresh = ata_worsen_thresh
        self.alt_split = alt_split_ft
        self._prev_ata = None

    def update(self):
        try:
            obs = self._obs()
            side = obs.get("side_flag", 0)
            alt_ft = obs.get("ego_altitude_ft", 10000)
            dist = obs.get("distance_ft", 5000)
            ata = obs.get("ata_deg", 0.5) * 180
            enm_in_wez = obs.get("enm_in_wez", False)

            # 적 lead pursuit 성공 감지: 우리 ATA가 시간에 따라 감소
            # (적이 우리를 점점 정확히 겨냥)
            lead_detected = (self._prev_ata is not None
                             and ata < self._prev_ata - self.ata_worsen_thresh)
            self._prev_ata = ata

            # side 반대 방향 break
            break_dir = -1 if side >= 0 else 1

            # ─── BFM 법칙 ────────────────────────────
            # (1) Last ditch: 사격당하는 중
            if enm_in_wez:
                turn = max(0, min(8, 4 + break_dir * 4))  # max
                vel = 2  # 최대 선회율 (코너속도 근처)
                alt_idx = 4 if alt_ft < 5000 else self._safe_alt(2, obs)  # 수직 회피

            # (2) 근접 panic
            elif dist < self.panic_dist:
                turn = max(0, min(8, 4 + break_dir * 4))
                vel = 2
                alt_idx = self._safe_alt(2 if alt_ft > self.alt_split else 3, obs)

            # (3) 적 lead 성공 중 → 반대로 강하게
            elif lead_detected:
                turn = max(0, min(8, 4 + break_dir * 4))
                vel = 2
                alt_idx = self._safe_alt(2, obs)

            # (4) 거리 멂 → 에너지 보존 extension
            elif dist > self.extend_dist:
                turn = max(0, min(8, 4 + break_dir * 2))
                vel = 4  # 속도 유지, 확장
                alt_idx = self._safe_alt(2, obs)

            # 기본 break
            else:
                turn = max(0, min(8, 4 + break_dir * 3))
                vel = 3  # 코너 속도
                alt_idx = self._safe_alt(
                    1 if alt_ft > self.alt_split else 2, obs)

            self.set_action(alt_idx, turn, vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self.set_action(2, 0, 3)
            return py_trees.common.Status.SUCCESS


class SmartDefensiveSpiral(BaseAction):
    """나선형 회피 — 고도 적응 + 선회 강도."""
    TUNABLE_PARAMS = {
        "turn_intensity": {"type": "disc", "choices": [2, 3, 4], "default": 3},
        "alt_threshold_ft": {"type": "cont", "range": (3000, 8000), "default": 5000},
        "vel":            {"type": "disc", "choices": [3, 4], "default": 4},
    }

    def __init__(self, name="SmartDefensiveSpiral", turn_intensity=3,
                 alt_threshold_ft=5000, vel=4):
        super().__init__(name)
        self.turn_intensity = turn_intensity
        self.alt_threshold = alt_threshold_ft
        self.vel = vel

    def update(self):
        try:
            obs = self._obs()
            side = obs.get("side_flag", 0)
            alt_ft = obs.get("ego_altitude_ft", 10000)
            hdg = 4 + self.turn_intensity if side >= 0 else 4 - self.turn_intensity
            alt_idx = 3 if alt_ft < self.alt_threshold else 1
            alt_idx = self._safe_alt(alt_idx, obs)
            self.set_action(alt_idx, max(0, min(8, hdg)), self.vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self.set_action(2, 0, 4)
            return py_trees.common.Status.SUCCESS


class ExtensionBreak(BaseAction):
    """반방향 이탈 — relative_bearing 부호로 결정론적 이탈."""
    TUNABLE_PARAMS = {
        "vel": {"type": "disc", "choices": [3, 4], "default": 4},
    }

    def __init__(self, name="ExtensionBreak", vel=4):
        super().__init__(name)
        self.vel = vel

    def update(self):
        try:
            obs = self._obs()
            rel_b = obs.get("relative_bearing_deg", 0)
            rel_b_deg = float(rel_b) * 180 if isinstance(rel_b, (int, float)) else 0
            hdg = 6 if rel_b_deg <= 0 else 2
            self.set_action(self._safe_alt(2, obs), hdg, self.vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self.set_action(2, 6, 4)
            return py_trees.common.Status.SUCCESS


class Jink(BaseAction):
    """불규칙 방향전환 — 추적 교란."""
    TUNABLE_PARAMS = {
        "alt_range":  {"type": "disc", "choices": [1, 2, 3], "default": 2},
        "vel":        {"type": "disc", "choices": [3, 4], "default": 4},
    }

    def __init__(self, name="Jink", alt_range=2, vel=4):
        super().__init__(name)
        self.alt_range = alt_range
        self.vel = vel

    def update(self):
        try:
            obs = self._obs()
            hdg = random.randint(0, 8)
            center = 2
            alt_idx = random.randint(max(0, center - self.alt_range), min(4, center + self.alt_range))
            alt_idx = self._safe_alt(alt_idx, obs)
            self.set_action(alt_idx, hdg, self.vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self.set_action(2, random.randint(0, 8), 4)
            return py_trees.common.Status.SUCCESS


class GunsDefense(BaseAction):
    """적 WEZ 내 감지 시 급선회 회피."""
    TUNABLE_PARAMS = {
        "turn_intensity": {"type": "disc", "choices": [3, 4], "default": 4},
        "alt_idx":        {"type": "disc", "choices": [0, 1, 2], "default": 1},
        "vel":            {"type": "disc", "choices": [3, 4], "default": 4},
    }

    def __init__(self, name="GunsDefense", turn_intensity=4, alt_idx=1, vel=4):
        super().__init__(name)
        self.turn_intensity = turn_intensity
        self.alt_idx_cmd = alt_idx
        self.vel = vel

    def update(self):
        try:
            obs = self._obs()
            side = obs.get("side_flag", 0)
            hdg = 4 - self.turn_intensity if side >= 0 else 4 + self.turn_intensity
            alt = self._safe_alt(self.alt_idx_cmd, obs)
            self.set_action(alt, max(0, min(8, hdg)), self.vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self.set_action(2, 0, 4)
            return py_trees.common.Status.SUCCESS


class LastDitch(BaseAction):
    """최후방어 — 급선회 + 최대감속."""
    TUNABLE_PARAMS = {
        "vel": {"type": "disc", "choices": [0, 1], "default": 0},
    }

    def __init__(self, name="LastDitch", vel=0):
        super().__init__(name)
        self.vel = vel

    def update(self):
        try:
            obs = self._obs()
            side = obs.get("side_flag", 0)
            hdg = 0 if side >= 0 else 8
            self.set_action(self._safe_alt(1, obs), hdg, self.vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self.set_action(2, 0, 0)
            return py_trees.common.Status.SUCCESS


# ═══════════════════════════════════════════════════════════════
# 4. 교전/선회전 (HABFM)
# ═══════════════════════════════════════════════════════════════

class SmartOneCircle(BaseAction):
    """동방향 급선회 (radius fight) — 반경 축소."""
    TUNABLE_PARAMS = {
        "turn_intensity": {"type": "disc", "choices": [3, 4], "default": 4},
        "vel":            {"type": "disc", "choices": [0, 1, 2], "default": 1},
    }

    def __init__(self, name="SmartOneCircle", turn_intensity=4, vel=1):
        super().__init__(name)
        self.turn_intensity = turn_intensity
        self.vel = vel

    def update(self):
        try:
            obs = self._obs()
            side = obs.get("side_flag", 0)
            hdg = 4 + self.turn_intensity if side >= 0 else 4 - self.turn_intensity
            self.set_action(2, max(0, min(8, hdg)), self.vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self.set_action(2, 0, 1)
            return py_trees.common.Status.SUCCESS


class SmartTwoCircle(BaseAction):
    """역방향 선회 (rate fight) — 에너지 전투."""
    TUNABLE_PARAMS = {
        "turn_intensity": {"type": "disc", "choices": [1, 2, 3], "default": 2},
        "vel":            {"type": "disc", "choices": [3, 4], "default": 4},
    }

    def __init__(self, name="SmartTwoCircle", turn_intensity=2, vel=4):
        super().__init__(name)
        self.turn_intensity = turn_intensity
        self.vel = vel

    def update(self):
        try:
            obs = self._obs()
            side = obs.get("side_flag", 0)
            # 역방향: 적이 오른쪽이면 왼쪽으로
            hdg = 4 - self.turn_intensity if side >= 0 else 4 + self.turn_intensity
            self.set_action(2, max(0, min(8, hdg)), self.vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self.set_action(2, 4, 4)
            return py_trees.common.Status.SUCCESS


class FlatScissors(BaseAction):
    """수평 교차 감속 — 오버슈트 유도. 매 N틱 방향 반전."""
    TUNABLE_PARAMS = {
        "reverse_ticks":  {"type": "disc", "choices": [2, 3, 4, 5, 6], "default": 3},
        "turn_intensity": {"type": "disc", "choices": [2, 3, 4], "default": 3},
        "vel":            {"type": "disc", "choices": [0, 1, 2], "default": 1},
    }

    def __init__(self, name="FlatScissors", reverse_ticks=3, turn_intensity=3, vel=1):
        super().__init__(name)
        self.reverse_ticks = reverse_ticks
        self.turn_intensity = turn_intensity
        self.vel = vel
        self._tick = 0
        self._dir = 1  # 1=right, -1=left

    def update(self):
        try:
            self._tick += 1
            if self._tick >= self.reverse_ticks:
                self._dir *= -1
                self._tick = 0
            hdg = 4 + self._dir * self.turn_intensity
            self.set_action(2, max(0, min(8, hdg)), self.vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self.set_action(2, 4, 1)
            return py_trees.common.Status.SUCCESS


class RollingScissors(BaseAction):
    """수직 교차 — alt 교대 + hdg 교대."""
    TUNABLE_PARAMS = {
        "reverse_ticks":  {"type": "disc", "choices": [3, 4, 5, 6], "default": 4},
        "turn_intensity": {"type": "disc", "choices": [2, 3, 4], "default": 3},
        "vel":            {"type": "disc", "choices": [1, 2, 3], "default": 2},
    }

    def __init__(self, name="RollingScissors", reverse_ticks=4, turn_intensity=3, vel=2):
        super().__init__(name)
        self.reverse_ticks = reverse_ticks
        self.turn_intensity = turn_intensity
        self.vel = vel
        self._tick = 0
        self._phase = 0  # 0=climb+left, 1=dive+right

    def update(self):
        try:
            obs = self._obs()
            self._tick += 1
            if self._tick >= self.reverse_ticks:
                self._phase = 1 - self._phase
                self._tick = 0

            if self._phase == 0:
                alt = 3
                hdg = 4 - self.turn_intensity
            else:
                alt = self._safe_alt(1, obs)
                hdg = 4 + self.turn_intensity

            self.set_action(alt, max(0, min(8, hdg)), self.vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self._phase = 0
            self._tick = 0
            self.set_action(2, 4, 2)
            return py_trees.common.Status.SUCCESS


# ═══════════════════════════════════════════════════════════════
# 5. 공전 탈출 + 유틸
# ═══════════════════════════════════════════════════════════════

class HeadOnBreak(BaseAction):
    """Purpose-driven Head-on Break — 공전/정면교전 탈출.

    목적: Head-on 또는 neutral 상황에서 수직 분리로 오버슈트/오버킬 회피,
         에너지 상태에 따라 dive (속도 확보) 또는 climb (각도 유지) 선택.

    BFM 불변 법칙 (관측 기반 피드백):
    ─────────────────────────────────────────────────────────
    (1) 에너지 우위: e_diff > high_e → 정면 유지 (dive 포기, vel 가속)
    (2) 에너지 열세 + 고도 열세: climb 회피 (recover_alt 상향)
    (3) 근접 + closure 고속: 급강하 break (dive_alt 최저)
    (4) 기본: off-nose dive break
    """
    TUNABLE_PARAMS = {
        "heading_gain":    {"type": "cont", "range": (0.3, 1.5), "default": 0.8},
        "dive_alt":        {"type": "disc", "choices": [0, 1], "default": 1},
        "vel":             {"type": "disc", "choices": [3, 4], "default": 4},
        "high_energy_ft":  {"type": "cont", "range": (2000, 6000), "default": 3000},
        "close_dist_ft":   {"type": "cont", "range": (1500, 4000), "default": 2500},
        "fast_closure_kts":{"type": "cont", "range": (150, 350), "default": 250},
    }

    def __init__(self, name="HeadOnBreak", heading_gain=0.8, dive_alt=1, vel=4,
                 high_energy_ft=3000, close_dist_ft=2500, fast_closure_kts=250,
                 **kwargs):
        super().__init__(name)
        self.heading_gain = heading_gain
        self.dive_alt = dive_alt
        self.vel = vel
        self.high_energy = high_energy_ft
        self.close_dist = close_dist_ft
        self.fast_closure = fast_closure_kts

    def update(self):
        try:
            obs = self._obs()
            tau = obs.get("tau_deg", 0) * 180
            dist = obs.get("distance_ft", 10000)
            closure = obs.get("closure_rate_kts", 0)
            e_diff = obs.get("energy_diff_ft", 0)
            alt_gap = obs.get("alt_gap_ft", 0)

            base_hdg = self._hdg_from_tau(tau, self.heading_gain)

            # (3) 급강하 break: 근접 + 고속 closure → dive_alt=0
            if dist < self.close_dist and closure > self.fast_closure:
                alt_idx = self._safe_alt(0, obs)
                vel = self.vel
                hdg = base_hdg
            # (1) 에너지 우위: dive 포기, 가속 유지
            elif e_diff > self.high_energy:
                alt_idx = self._safe_alt(2, obs)  # level
                vel = 4
                hdg = base_hdg
            # (2) 에너지 열세 + 고도 열세: climb
            elif e_diff < -self.high_energy and alt_gap < -1000:
                alt_idx = 3  # climb
                vel = self.vel
                hdg = base_hdg
            # (4) 기본 dive break
            else:
                alt_idx = self._safe_alt(self.dive_alt, obs)
                vel = self.vel
                hdg = base_hdg

            self.set_action(alt_idx, hdg, vel)
            return py_trees.common.Status.SUCCESS
        except Exception as ex:
            logger.warning(f"HeadOnBreak: {ex}")
            self.set_action(1, 4, 4)
            return py_trees.common.Status.SUCCESS


class UnloadedExtension(BaseAction):
    """0G 직선 가속 이탈."""
    TUNABLE_PARAMS = {
        "vel": {"type": "disc", "choices": [3, 4], "default": 4},
    }

    def __init__(self, name="UnloadedExtension", vel=4):
        super().__init__(name)
        self.vel = vel

    def update(self):
        self.set_action(2, 4, self.vel)
        return py_trees.common.Status.SUCCESS


class Chandelle(BaseAction):
    """경사 상승 선회 — 에너지 보존형 180° 방향전환. 2-phase."""
    TUNABLE_PARAMS = {
        "climb_ticks":    {"type": "disc", "choices": [4, 6, 8, 10], "default": 6},
        "turn_intensity": {"type": "disc", "choices": [2, 3, 4], "default": 3},
        "vel":            {"type": "disc", "choices": [2, 3, 4], "default": 3},
    }

    def __init__(self, name="Chandelle", climb_ticks=6, turn_intensity=3, vel=3):
        super().__init__(name)
        self.climb_ticks = climb_ticks
        self.turn_intensity = turn_intensity
        self.vel = vel
        self._phase = 0
        self._tick = 0

    def update(self):
        try:
            obs = self._obs()
            side = obs.get("side_flag", 0)
            turn_dir = self.turn_intensity if side >= 0 else -self.turn_intensity
            hdg = max(0, min(8, 4 + turn_dir))

            if self._phase == 0:  # CLIMB+TURN
                self.set_action(3, hdg, self.vel)
                self._tick += 1
                if self._tick >= self.climb_ticks:
                    self._phase = 1
                    self._tick = 0
            else:  # LEVEL OUT
                self.set_action(2, hdg, self.vel)
                self._tick += 1
                if self._tick >= self.climb_ticks // 2:
                    self._phase = 0
                    self._tick = 0
            return py_trees.common.Status.SUCCESS
        except Exception:
            self._phase = 0
            self._tick = 0
            self.set_action(2, 4, 3)
            return py_trees.common.Status.SUCCESS


# ═══════════════════════════════════════════════════════════════
# 6b. PN Guidance (L3 최적화 프로토타입, §10.1)
# ═══════════════════════════════════════════════════════════════

class PNLeadPursuit(BaseAction):
    """Proportional Navigation 기반 Lead Pursuit — L3 최적화 프로토타입.

    §10.1 BFM Guidance Law 적용:
    ─────────────────────────────────────────────────────────
    기존 SmartLeadPursuit의 규칙 기반 heading 계산을 PN 유도 법칙으로 교체.

    핵심 차이점:
    - 기존: bearing × gain (P 제어) + 5개 rule-based 분기
    - PN:   bearing × Kp + λ_dot × N × Δt (PD 제어) + ∫(bearing) × Ki

    Navigation Constant N이 Lead/Pure/Lag를 연속적으로 조절 (§10.1.1):
    - N > 3: Lead Pursuit (적극적 추적)
    - N ≈ 3: 표준 PN (collision course 수렴)
    - N < 3: Lag Pursuit (보수적, 오버슈트 방지)
    - N = 0: Pure Pursuit (기수를 적에게 직접 지향)

    오버슈트 예측 (§10.1.6):
    - t_impact < t_turn × margin → N 자동 감소 (Lead → Lag 전환)

    WEZ 유지 (§10.1.7):
    - λ_dot ≈ 0 목표 → Ki 적분항으로 정상상태 오차 보상
    """

    TUNABLE_PARAMS = {
        # PN 핵심 파라미터 — N(dist) 구간별
        "n_close":          {"type": "cont", "range": (0.0, 3.0), "default": 1.5},
        "n_mid":            {"type": "cont", "range": (2.0, 5.0), "default": 3.5},
        "n_far":            {"type": "cont", "range": (3.0, 6.0), "default": 4.5},
        # 거리 구간 경계
        "close_dist_ft":    {"type": "cont", "range": (1000, 3000), "default": 2000},
        "far_dist_ft":      {"type": "cont", "range": (4000, 10000), "default": 6000},
        # 에너지 보너스: e_diff > thresh → N += bonus (§10.1.8)
        "energy_n_bonus":   {"type": "cont", "range": (0.0, 2.0), "default": 0.5},
        "energy_thresh_ft": {"type": "cont", "range": (500, 3000), "default": 1000},
        # PID 게인
        "kp":               {"type": "cont", "range": (0.5, 2.0), "default": 1.0},
        "ki":               {"type": "cont", "range": (0.0, 0.3), "default": 0.05},
        # λ_dot EMA smoothing (노이즈 완화)
        "ema_alpha":        {"type": "cont", "range": (0.1, 0.8), "default": 0.3},
        # 오버슈트 안전 계수 (§10.1.6)
        "overshoot_margin": {"type": "cont", "range": (1.0, 5.0), "default": 2.0},
        "overshoot_n_cap":  {"type": "cont", "range": (0.0, 2.0), "default": 0.5},
        # 속도 전략
        "corner_vel":       {"type": "disc", "choices": [2, 3], "default": 3},
        "sprint_vel":       {"type": "disc", "choices": [3, 4], "default": 4},
        "brake_vel":        {"type": "disc", "choices": [0, 1, 2], "default": 1},
        "tight_turn_vel":   {"type": "disc", "choices": [1, 2], "default": 2},
        # 선회전 감속 조건 (SAE 데이터: HABFM에서 vel=3이 SAE=-0.44)
        "turn_fight_ata":   {"type": "cont", "range": (60, 120), "default": 80},
        "turn_fight_dist":  {"type": "cont", "range": (2000, 6000), "default": 4000},
        # ATA 악화 감지 임계 (°/tick)
        "ata_worsen_rate":  {"type": "cont", "range": (1.0, 10.0), "default": 3.0},
        # 거리 확대 추적 임계
        "dist_widen_rate":  {"type": "cont", "range": (50, 500), "default": 200},
        # 하강 공격 조건
        "dive_e_thresh_ft": {"type": "cont", "range": (1500, 5000), "default": 2500},
        "dive_dist_ft":     {"type": "cont", "range": (2000, 6000), "default": 4000},
    }

    DT = 0.2       # tick interval (seconds)
    G = 32.174      # ft/s²
    KTS_TO_FPS = 1.6878

    def __init__(self, name="PNLeadPursuit",
                 n_close=1.5, n_mid=3.5, n_far=4.5,
                 close_dist_ft=2000, far_dist_ft=6000,
                 energy_n_bonus=0.5, energy_thresh_ft=1000,
                 kp=1.0, ki=0.05, ema_alpha=0.3,
                 overshoot_margin=2.0, overshoot_n_cap=0.5,
                 corner_vel=3, sprint_vel=4, brake_vel=1,
                 tight_turn_vel=2,
                 turn_fight_ata=80, turn_fight_dist=4000,
                 ata_worsen_rate=3.0, dist_widen_rate=200,
                 dive_e_thresh_ft=2500, dive_dist_ft=4000,
                 **kwargs):
        super().__init__(name)
        self.n_close = n_close
        self.n_mid = n_mid
        self.n_far = n_far
        self.close_dist = close_dist_ft
        self.far_dist = far_dist_ft
        self.energy_n_bonus = energy_n_bonus
        self.energy_thresh = energy_thresh_ft
        self.kp = kp
        self.ki = ki
        self.ema_alpha = ema_alpha
        self.overshoot_margin = overshoot_margin
        self.overshoot_n_cap = overshoot_n_cap
        self.corner_vel = corner_vel
        self.sprint_vel = sprint_vel
        self.brake_vel = brake_vel
        self.tight_turn_vel = tight_turn_vel
        self.turn_fight_ata = turn_fight_ata
        self.turn_fight_dist = turn_fight_dist
        self.ata_worsen_rate = ata_worsen_rate
        self.dist_widen_rate = dist_widen_rate
        self.dive_e_thresh = dive_e_thresh_ft
        self.dive_dist = dive_dist_ft
        # 시계열 상태
        self._prev_ata = None
        self._prev_dist = None
        self._lambda_dot_ema = 0.0
        self._integral_err = 0.0

    def _adaptive_N(self, dist, e_diff, overshoot):
        """관측값 기반 Navigation Constant 결정 (§10.1.1, §10.1.8).

        dist 구간별 N 선형 보간:
          [0, close_dist)      → n_close (보수적, 오버슈트 방지)
          [close_dist, far_dist] → n_close → n_far 선형 보간
          (far_dist, ∞)        → n_far (적극적 Lead, 거리 좁힘)
        """
        if dist < self.close_dist:
            N = self.n_close
        elif dist > self.far_dist:
            N = self.n_far
        else:
            t = (dist - self.close_dist) / max(1, self.far_dist - self.close_dist)
            N = self.n_close + t * (self.n_far - self.n_close)

        # 에너지 우세 보너스: 적극적 Lead 허용 (§10.1.8)
        if e_diff > self.energy_thresh:
            N += self.energy_n_bonus

        # 오버슈트 위험 시 N 강제 감소 (§10.1.6)
        if overshoot:
            N = min(N, self.overshoot_n_cap)

        return max(0.0, min(6.0, N))

    def _compute_lambda_dot(self, ata):
        """LOS 회전율 근사 (§10.1.2): λ_dot ≈ ΔATA / Δt.

        EMA 스무딩으로 tick-to-tick 노이즈 완화.
        """
        if self._prev_ata is None:
            return 0.0
        raw = (ata - self._prev_ata) / self.DT
        # EMA 스무딩
        self._lambda_dot_ema = (self.ema_alpha * raw
                                + (1 - self.ema_alpha) * self._lambda_dot_ema)
        return self._lambda_dot_ema

    def _predict_overshoot(self, dist, closure_fps, ata, turn_rate_dps):
        """오버슈트 예측 (§10.1.6).

        t_impact = dist / V_c
        t_turn   = |ATA| / ω_max
        t_impact < t_turn × margin → OVERSHOOT
        """
        if closure_fps <= 0 or dist <= 0:
            return False
        t_impact = dist / closure_fps
        omega = max(abs(turn_rate_dps), 5.0)
        t_turn = abs(ata) / omega if omega > 0 else 999.0
        return t_impact < t_turn * self.overshoot_margin

    def update(self):
        try:
            obs = self._obs()

            # ── 관측값 추출 ──
            rel_b = obs.get("relative_bearing_deg", 0) * 180
            ata = obs.get("ata_deg", 0.5) * 180
            dist = obs.get("distance_ft", 10000)
            closure = obs.get("closure_rate_kts", 0)
            e_diff = obs.get("energy_diff_ft", 0)
            turn_rate = obs.get("turn_rate_degs", 0)
            overshoot_flag = obs.get("overshoot_risk", False)
            alt_adv = obs.get("alt_advantage", False)

            closure_fps = closure * self.KTS_TO_FPS

            # ── 시계열 변화 감지 ──
            ata_worsening = False
            dist_widening = False
            if self._prev_ata is not None:
                ata_delta = ata - self._prev_ata
                if ata_delta > self.ata_worsen_rate:
                    ata_worsening = True
            if self._prev_dist is not None:
                dist_delta = dist - self._prev_dist
                if dist_delta > self.dist_widen_rate and closure < 0:
                    dist_widening = True

            # §10.1.2: LOS 회전율 (스무딩된 λ_dot)
            lambda_dot = self._compute_lambda_dot(ata)

            # §10.1.6: 오버슈트 예측
            overshoot = (self._predict_overshoot(dist, closure_fps, ata, turn_rate)
                         or overshoot_flag)

            # §10.1.1: Adaptive N
            N = self._adaptive_N(dist, e_diff, overshoot)

            # ── PN 기반 heading 계산 (PID) ──
            p_term = rel_b * self.kp
            d_term = N * lambda_dot * self.DT
            self._integral_err += rel_b * self.DT
            self._integral_err = max(-90.0, min(90.0, self._integral_err))
            i_term = self.ki * self._integral_err
            cmd_deg = p_term + d_term + i_term
            hdg = max(0, min(8, int(round(cmd_deg / 22.5)) + 4))

            # ── 속도 전략 (SAE/TIR 데이터 기반 개선) ──
            # 우선순위: 오버슈트 > 선회전 감속 > ATA 악화 > 거리 확대 추적 > 원거리 스프린트 > 기본
            in_turn_fight = (ata > self.turn_fight_ata
                             and dist < self.turn_fight_dist
                             and abs(turn_rate) > 5)

            if overshoot:
                # 임박한 오버슈트 → 급감속 + lag 전환
                vel = self.brake_vel
            elif in_turn_fight:
                # 선회 교전: 속도 줄여 선회 반경 축소 → inside cut
                # (SAE 데이터: HABFM+vel3 = -0.44, tight turn이 필요)
                vel = self.tight_turn_vel
                # heading 보강: 선회전에서 더 공격적으로 안쪽으로 cut
                if hdg < 4:
                    hdg = max(0, hdg - 1)
                elif hdg > 4:
                    hdg = min(8, hdg + 1)
            elif ata_worsening:
                # ATA가 빠르게 악화 → 상대가 더 빨리 돌고 있음 → 감속으로 대응
                vel = self.tight_turn_vel
            elif dist_widening:
                # 거리가 벌어지고 closure 음수 → 가속 추적
                vel = self.sprint_vel
            elif dist > self.far_dist:
                # 원거리 → 스프린트
                vel = self.sprint_vel
            else:
                vel = self.corner_vel

            # ── 고도 전략 ──
            alt_idx = self._safe_alt(2, obs)
            if e_diff > self.dive_e_thresh and alt_adv and dist < self.dive_dist:
                alt_idx = self._safe_alt(1, obs)

            # ── 상태 업데이트 ──
            self._prev_ata = ata
            self._prev_dist = dist

            self.set_action(alt_idx, hdg, vel)
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"PNLeadPursuit: {e}")
            self.set_action(2, 4, 3)
            return py_trees.common.Status.SUCCESS


# ═══════════════════════════════════════════════════════════════
# 7. TacticalLookup — data-driven state-conditional dispatch
# ═══════════════════════════════════════════════════════════════

class TacticalLookup(BaseAction):
    """State-bin → recommended-node dispatcher.

    Sidesteps EIM's 6-class bottleneck (ADAPTIVE_BT_EXPLAINED §5.5
    ORBITING trash bin problem) by looking up actions directly from
    4D observation state bin (ata × dist × closure × e_diff).

    Lookup table: logs/knowledge/tactical_lookup.json — generated from
    aggregated match data (150 matches across 15 adaptive_eagle versions
    vs aggressive/defensive). Each state cell has a validated best-WR node.

    Per tick:
      1. Compute state bin from observation
      2. Pick aggressive/defensive recommendation bucket (by EIM intent if
         available, else by WR × n)
      3. Delegate to sub-node's update() (or emit built-in action for
         LeadPursuit/Accelerate)
      4. FAILURE if state not covered → Selector falls through to fallback
    """

    # LeadPursuit and Accelerate are both dispatched via observation-based logic
    # in update() (previously hardcoded tuples — hdg=0 caused max-left, Accelerate
    # straight-sprint caused high-closure WEZ overshoot with single-tick shots).
    _BUILTIN_ACTIONS = {}

    # Custom node delegation targets (class name -> class ref is resolved lazily)
    _DELEGATE_CLASSES = (
        "SmartLowYoYo", "SmartLagPursuit", "HeadOnBreak",
        "SmartHighYoYo", "ExtensionBreak", "SmartBreakTurn",
        "SmartGunAttack",
    )

    def __init__(self, name="TacticalLookup",
                 lookup_path="logs/knowledge/tactical_lookup.json",
                 min_tick_wr_agg=0.85, min_support_n_agg=50,
                 min_tick_wr_def=0.9, min_support_n_def=100,
                 closure_agg_threshold=50.0):
        super().__init__(name)
        self.lookup_path = lookup_path
        self.min_tick_wr_agg = min_tick_wr_agg
        self.min_support_n_agg = min_support_n_agg
        self.min_tick_wr_def = min_tick_wr_def
        self.min_support_n_def = min_support_n_def
        self.closure_agg_threshold = closure_agg_threshold
        self._lookup = None
        self._delegates = {}
        self._loaded = False

    def _lazy_load(self):
        import json
        from pathlib import Path
        if self._loaded:
            return
        self._loaded = True
        try:
            self._lookup = json.load(open(self.lookup_path, encoding="utf-8"))
        except Exception as e:
            logger.warning("[TacticalLookup] lookup load failed: %s", e)
            self._lookup = None
            return
        import sys
        mod = sys.modules[self.__class__.__module__]
        for cname in self._DELEGATE_CLASSES:
            cls = getattr(mod, cname, None)
            if cls is None:
                continue
            try:
                self._delegates[cname] = cls(name=f"TL_{cname}")
            except Exception as e:
                logger.warning("[TacticalLookup] delegate init failed (%s): %s", cname, e)

    @staticmethod
    def _bin_index(val, edges):
        for i in range(len(edges) - 1):
            if val < edges[i + 1]:
                return i
        return len(edges) - 2

    # Node-based EIM intent → strategic bucket mapping.
    # runtime INTENT_CLASSES = GUN_ATTACK, PURSUIT, DEFENSIVE, ENERGY,
    #                         NEUTRAL_CIRCLE, NEUTRAL_SCISSORS
    _AGG_INTENTS = {"GUN_ATTACK", "PURSUIT", "ENERGY"}
    _DEF_INTENTS = {"DEFENSIVE", "NEUTRAL_CIRCLE", "NEUTRAL_SCISSORS"}

    def _query_eim_intent(self, obs):
        """Read live EIM prediction from src.intent.shared_state.

        Returns (intent_str, confidence_float) or (None, 0.0) on failure.
        The submission-safe EnemyIntentIs stub returns FAILURE, but the
        runner still populates shared_state via OnlineIntentTracker.
        """
        try:
            from src.intent import shared_state
            ego_id = str(obs.get("agent_id", ""))
            intent, conf = shared_state.get_enemy_intent(ego_id)
            if isinstance(conf, dict):
                conf_val = conf.get(intent, 0.0)
            else:
                conf_val = float(conf) if conf else 0.0
            return intent, conf_val
        except Exception:
            return None, 0.0

    def _pick_bucket(self, cell, obs, closure):
        """Select aggressive/defensive bucket using live EIM intent when
        available; fall back to closure heuristic.

        Bucket routing (strategic interpretation of tactical intent):
          - Aggressive opponent → opponent intent ∈ {GUN_ATTACK, PURSUIT, ENERGY}
          - Defensive opponent  → opponent intent ∈ {DEFENSIVE, NEUTRAL_*}
        Per-bucket confidence gates preserved.
        """
        agg = cell.get("aggressive")
        defn = cell.get("defensive")

        intent, conf = self._query_eim_intent(obs)
        if intent in self._AGG_INTENTS and conf >= 0.3:
            primary, secondary = agg, defn
        elif intent in self._DEF_INTENTS and conf >= 0.3:
            primary, secondary = defn, agg
        else:
            # EIM unknown/low-confidence → closure fallback
            if closure > self.closure_agg_threshold:
                primary, secondary = agg, defn
            else:
                primary, secondary = defn, agg

        pri_wr = self.min_tick_wr_agg if primary is agg else self.min_tick_wr_def
        pri_n = self.min_support_n_agg if primary is agg else self.min_support_n_def
        sec_wr = self.min_tick_wr_def if primary is agg else self.min_tick_wr_agg
        sec_n = self.min_support_n_def if primary is agg else self.min_support_n_agg

        if primary and primary["tick_wr"] >= pri_wr and primary["n"] >= pri_n:
            return primary
        if secondary and secondary["tick_wr"] >= sec_wr and secondary["n"] >= sec_n:
            return secondary
        return None

    def update(self):
        self._lazy_load()
        if not self._lookup:
            return py_trees.common.Status.FAILURE
        try:
            obs = self._obs()
            ata_raw = obs.get("ata_deg", 0.5)
            ata = ata_raw * 180 if ata_raw < 2 else ata_raw
            dist = obs.get("distance_ft", 10000)
            clos = obs.get("closure_rate_kts", 0)
            ediff = obs.get("energy_diff_ft", 0)
            edges = self._lookup["bin_edges"]
            a = self._bin_index(ata, edges["ata"])
            d = self._bin_index(dist, edges["dist"])
            c = self._bin_index(clos, edges["closure"])
            e = self._bin_index(ediff, edges["e_diff"])
            key = f"{a}_{d}_{c}_{e}"
            cell = self._lookup["states"].get(key)
            if not cell:
                return py_trees.common.Status.FAILURE
            bucket = self._pick_bucket(cell, obs, clos)
            if not bucket:
                return py_trees.common.Status.FAILURE

            node_name = bucket["node"]

            # LeadPursuit: compute hdg from bearing (was hardcoded (2,0,3) — bug caused
            # max-left turn regardless of enemy position). alt=level, vel=corner speed.
            if node_name == "LeadPursuit":
                rel_b = obs.get("relative_bearing_deg", 0) * 180
                hdg = self._hdg_from_bearing(rel_b, gain=1.0)
                self.set_action(2, hdg, 3)
                return py_trees.common.Status.SUCCESS

            # Accelerate: observation-aware chase + shot-setup. Previously hardcoded
            # (2,4,4) — straight sprint caused high-closure WEZ overshoot (1-tick shots).
            # Distinguish "chasing a runner" (low closure + far or wide ATA → sprint)
            # from "advantageous tail chase" (low closure + near + narrow ATA → sustain
            # corner speed for turn rate, don't blow past the shot).
            if node_name == "Accelerate":
                rel_b = obs.get("relative_bearing_deg", 0) * 180
                e_diff = obs.get("energy_diff_ft", 0)
                hdg = self._hdg_from_bearing(rel_b, gain=1.0)
                if dist < 2500 and clos > 400:
                    vel = 1                   # imminent overshoot
                elif dist < 3500 and clos > 300:
                    vel = 2                   # near-merge decel
                elif dist < 4000 and ata < 25:
                    vel = 3                   # on their 6 + pointing good — sustain
                elif clos < 150 or dist > 5000:
                    vel = 4                   # runner or far — sprint to close
                else:
                    vel = 3
                if e_diff > 2500:
                    alt_cmd = 1
                elif e_diff < -1500:
                    alt_cmd = 3
                else:
                    alt_cmd = 2
                self.set_action(self._safe_alt(alt_cmd, obs), hdg, vel)
                return py_trees.common.Status.SUCCESS

            builtin = self._BUILTIN_ACTIONS.get(node_name)
            if builtin:
                self.set_action(*builtin)
                return py_trees.common.Status.SUCCESS

            delegate = self._delegates.get(node_name)
            if delegate is None:
                return py_trees.common.Status.FAILURE
            return delegate.update()
        except Exception as ex:
            logger.warning("[TacticalLookup] update failed: %s", ex)
            return py_trees.common.Status.FAILURE
