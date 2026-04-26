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
# 6b. 2-Body Geometric PN Lead Pursuit (v11_code)
# ═══════════════════════════════════════════════════════════════

import math

def _sigmoid(x):
    """Numerically stable sigmoid."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    else:
        z = math.exp(x)
        return z / (1.0 + z)


class PNLeadPursuit(BaseAction):
    """2-Body Geometric PN Lead Pursuit — 연속 위협 함수 기반.

    v11 PNLeadPursuit와의 핵심 차이:
    ─────────────────────────────────────────────────────────
    v11: rule-based 분기 (if overshoot / elif turn_fight / elif ...)
         → 이산 경계에서 chattering, 전환 급격

    v11_code: 연속 위협 스칼라 τ ∈ [0,1] 기반 부드러운 제어
         → 모든 관측값의 연속 함수, 경계 없음

    2-Body 교전 기하학 변수 (매 tick EMA 계산):
    ─────────────────────────────────────────────────────────
    λ̇ (LOS rate)   = ΔATA/Δt          → 충돌 경로 수렴
    Ṙ (range rate)  = -closure         → 거리 변화율
    β̇ (AA rate)    = ΔAA/Δt           → 적의 추적 성공도
    Ė (energy rate) = Δe_diff/Δt       → 에너지 소비 추세

    위협 크기 τ = σ(w₁·Ṙ_n + w₂·(1-AA/180) + w₃·(-β̇_n) + w₄·(-Ė_n) + b)
    ─────────────────────────────────────────────────────────
    τ ≈ 1: 적 고속 접근 + 코 방향 + 적극 추적 → 위협 높음
    τ ≈ 0: 적 이탈/선회 + 꼬리 보임 → 위협 낮음

    제어 출력 = τ의 연속 함수:
    - N(τ, dist): τ↑→N↓ (보수적), τ↓→N↑ (적극 Lead)
    - vel(τ):     τ↑→vel 유지 (에너지전), τ↓→vel 감속 (inside cut)
    - alt(τ, e_diff): 기존 유지
    """

    TUNABLE_PARAMS = {
        # ── EMA smoothing ──
        "ema_alpha":        {"type": "cont", "range": (0.1, 0.6), "default": 0.3},
        # ── Threat τ sigmoid weights ──
        "w_rdot":           {"type": "cont", "range": (0.5, 4.0), "default": 2.0},
        "w_aa":             {"type": "cont", "range": (0.5, 4.0), "default": 1.5},
        "w_beta_dot":       {"type": "cont", "range": (0.0, 3.0), "default": 1.0},
        "w_edot":           {"type": "cont", "range": (0.0, 2.0), "default": 0.5},
        "tau_bias":         {"type": "cont", "range": (-2.0, 2.0), "default": 0.0},
        # ── N(τ, dist) 연속 제어 ──
        "n_passive":        {"type": "cont", "range": (3.0, 6.0), "default": 4.5},
        "n_active":         {"type": "cont", "range": (0.0, 3.0), "default": 1.0},
        "n_dist_scale":     {"type": "cont", "range": (0.0, 2.0), "default": 0.5},
        "far_dist_ft":      {"type": "cont", "range": (4000, 10000), "default": 6000},
        # ── PN heading (PID) ──
        "kp":               {"type": "cont", "range": (0.5, 2.0), "default": 1.0},
        "ki":               {"type": "cont", "range": (0.0, 0.3), "default": 0.05},
        # ── vel(τ, ga, dist, closure) 2-orbit 연속 제어 ──
        "vel_passive":      {"type": "cont", "range": (1.0, 3.0), "default": 2.0},
        "vel_active":       {"type": "cont", "range": (3.0, 4.0), "default": 3.5},
        "vel_chase_scale":  {"type": "cont", "range": (0.0, 4.0), "default": 2.5},
        "vel_sprint_scale": {"type": "cont", "range": (0.0, 4.0), "default": 2.5},
        # ── 2-orbit geometric advantage ──
        "ga_scale":         {"type": "cont", "range": (20, 90), "default": 45},
        "blend_dist_ft":    {"type": "cont", "range": (2000, 5000), "default": 3000},
        # ── 오버슈트 예측 ──
        "overshoot_margin": {"type": "cont", "range": (1.0, 5.0), "default": 2.0},
        "overshoot_n_cap":  {"type": "cont", "range": (0.0, 2.0), "default": 0.5},
        # ── 하강 공격 ──
        "dive_e_thresh_ft": {"type": "cont", "range": (1500, 5000), "default": 2500},
        "dive_dist_ft":     {"type": "cont", "range": (2000, 6000), "default": 4000},
        # ── Normalization scales (관측값 정규화) ──
        "rdot_scale":       {"type": "cont", "range": (100, 600), "default": 300},
        "beta_dot_scale":   {"type": "cont", "range": (5, 30), "default": 15},
        "edot_scale":       {"type": "cont", "range": (500, 3000), "default": 1000},
    }

    DT = 0.2       # tick interval (seconds)
    KTS_TO_FPS = 1.6878

    def __init__(self, name="PNLeadPursuit",
                 ema_alpha=0.3,
                 w_rdot=2.0, w_aa=1.5, w_beta_dot=1.0, w_edot=0.5,
                 tau_bias=0.0,
                 n_passive=4.5, n_active=1.0, n_dist_scale=0.5,
                 far_dist_ft=6000,
                 kp=1.0, ki=0.05,
                 vel_passive=2.0, vel_active=3.5,
                 vel_chase_scale=2.5, vel_sprint_scale=2.5,
                 ga_scale=45, blend_dist_ft=3000,
                 overshoot_margin=2.0, overshoot_n_cap=0.5,
                 dive_e_thresh_ft=2500, dive_dist_ft=4000,
                 rdot_scale=300, beta_dot_scale=15, edot_scale=1000,
                 **kwargs):
        super().__init__(name)
        self.ema_alpha = ema_alpha
        # τ weights
        self.w_rdot = w_rdot
        self.w_aa = w_aa
        self.w_beta_dot = w_beta_dot
        self.w_edot = w_edot
        self.tau_bias = tau_bias
        # N control
        self.n_passive = n_passive
        self.n_active = n_active
        self.n_dist_scale = n_dist_scale
        self.far_dist = far_dist_ft
        # PID
        self.kp = kp
        self.ki = ki
        # vel control
        self.vel_passive = vel_passive
        self.vel_active = vel_active
        self.vel_chase_scale = vel_chase_scale
        self.vel_sprint_scale = vel_sprint_scale
        self.ga_scale = ga_scale
        self.blend_dist = blend_dist_ft
        # overshoot
        self.overshoot_margin = overshoot_margin
        self.overshoot_n_cap = overshoot_n_cap
        # dive
        self.dive_e_thresh = dive_e_thresh_ft
        self.dive_dist = dive_dist_ft
        # normalization
        self.rdot_scale = rdot_scale
        self.beta_dot_scale = beta_dot_scale
        self.edot_scale = edot_scale
        # ── EMA 상태 ──
        self._prev_ata = None
        self._prev_aa = None
        self._prev_e_diff = None
        self._lambda_dot_ema = 0.0    # λ̇
        self._rdot_ema = 0.0          # Ṙ (= -closure, 양수=접근)
        self._beta_dot_ema = 0.0      # β̇
        self._edot_ema = 0.0          # Ė
        self._integral_err = 0.0

    def _ema(self, prev, raw):
        """EMA update: α × raw + (1-α) × prev."""
        return self.ema_alpha * raw + (1.0 - self.ema_alpha) * prev

    def _compute_threat_tau(self, rdot, aa, beta_dot, edot):
        """Continuous threat magnitude τ ∈ [0, 1].

        τ = σ(w₁·Ṙ_n + w₂·(1 - AA/180) + w₃·(-β̇_n) + w₄·(-Ė_n) + bias)

        높은 τ: 적이 빠르게 접근 + 코를 향함 + 적극 추적 + 에너지 소모 중
        낮은 τ: 적이 이탈 + 꼬리 보임 + 소극적
        """
        rdot_n = rdot / max(self.rdot_scale, 1.0)
        aa_factor = 1.0 - aa / 180.0  # AA 작을수록 적이 우리를 겨냥
        beta_dot_n = -beta_dot / max(self.beta_dot_scale, 1.0)  # β̇ 음수 = 적이 추적 성공
        edot_n = -edot / max(self.edot_scale, 1.0)  # Ė 음수 = 에너지 소모

        z = (self.w_rdot * rdot_n
             + self.w_aa * aa_factor
             + self.w_beta_dot * beta_dot_n
             + self.w_edot * edot_n
             + self.tau_bias)
        return _sigmoid(z)

    def _compute_N(self, tau, dist, overshoot):
        """Navigation Constant as continuous function of τ and dist.

        N = n_passive + τ × (n_active - n_passive)
        ≡ n_passive × (1-τ) + n_active × τ

        τ 높음(위협) → N ≈ n_active (낮은 N, 보수적, 오버슈트 방지)
        τ 낮음(기회) → N ≈ n_passive (높은 N, 적극적 Lead 추적)

        + dist_bonus: 원거리에서 N 추가 (적극 lead)
        오버슈트 임박 시: N 강제 cap.
        """
        N = self.n_passive + tau * (self.n_active - self.n_passive)

        # 원거리 보너스: 멀수록 적극적 Lead 허용
        dist_ratio = min(dist / max(self.far_dist, 1.0), 2.0)
        N += self.n_dist_scale * dist_ratio

        if overshoot:
            N = min(N, self.overshoot_n_cap)

        return max(0.0, min(6.0, N))

    def _compute_geo_advantage(self, ata, aa):
        """2-orbit geometric advantage ga in [0, 1].

        ga = sigmoid((AA - ATA) / ga_scale)

        ga ~ 1: 아군이 적 후방 (offensive tail chase) — 추격 유리
        ga ~ 0: 적이 아군 후방 (defensive) — 방어 필요
        ga ~ 0.5: 중립 (merge / turn fight)
        """
        return _sigmoid((aa - ata) / max(self.ga_scale, 1.0))

    def _compute_vel(self, tau, ga, dist, closure):
        """2-orbit velocity: f(tau, ga, dist, closure).

        2-orbit 핵심: 뒤를 잡으면(ga high) 스프린트, 선회전(ga mid+close)이면 감속.

        (1) vel_turn = vel_passive + tau * (vel_active - vel_passive)
            선회전 모드: tau 기반 (위협 높으면 에너지 보존, 낮으면 감속)

        (2) vel_chase = vel_active + ga * (4.0 - vel_active)
            추격 모드: ga 기반 (뒤잡으면 스프린트, 아니면 vel_active)

        (3) range_blend = sigmoid((dist - blend_dist) / 1500)
            근거리 → 선회전 모드, 원거리 → 추격 모드

        (4) chase_correction: 분리 중(closure<0) 스프린트 보정
        (5) dist_sprint: 초원거리(dist > far_dist) 추가 스프린트
        """
        # (1) Turn-fight component (tau-driven)
        vel_turn = self.vel_passive + tau * (self.vel_active - self.vel_passive)

        # (2) Chase component (ga-driven)
        vel_chase = self.vel_active + ga * (4.0 - self.vel_active)

        # (3) Range blend: close → turn fight, far → chase
        range_blend = _sigmoid((dist - self.blend_dist) / 1500.0)
        vel_base = vel_turn * (1.0 - range_blend) + vel_chase * range_blend

        # (4) Separation correction: closure<0 → sprint
        separation = max(0.0, -closure / max(self.rdot_scale, 1.0))
        dist_ratio = min(dist / max(self.far_dist, 1.0), 1.5)
        chase_c = self.vel_chase_scale * separation * dist_ratio * (1.0 - tau)

        # (5) Distance sprint: far → speed boost
        far_excess = max(0.0, (dist - self.far_dist) / max(self.far_dist, 1.0))
        dist_sprint = self.vel_sprint_scale * far_excess * (1.0 - tau)

        return vel_base + chase_c + dist_sprint

    def _predict_overshoot(self, dist, closure_fps, ata, turn_rate_dps):
        """오버슈트 예측: t_impact < t_turn × margin → True."""
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
            aa = obs.get("aa_deg", 0.5) * 180
            dist = obs.get("distance_ft", 10000)
            closure = obs.get("closure_rate_kts", 0)
            e_diff = obs.get("energy_diff_ft", 0)
            turn_rate = obs.get("turn_rate_degs", 0)
            overshoot_flag = obs.get("overshoot_risk", False)
            alt_adv = obs.get("alt_advantage", False)

            closure_fps = closure * self.KTS_TO_FPS

            # ── EMA rate 계산 ──
            # Ṙ (range rate): 양수 = 접근
            rdot_raw = closure  # closure 자체가 접근 속도
            self._rdot_ema = self._ema(self._rdot_ema, rdot_raw)

            # λ̇ (LOS rate)
            if self._prev_ata is not None:
                lambda_dot_raw = (ata - self._prev_ata) / self.DT
                self._lambda_dot_ema = self._ema(self._lambda_dot_ema, lambda_dot_raw)

            # β̇ (AA rate): 적의 추적 성공도
            if self._prev_aa is not None:
                beta_dot_raw = (aa - self._prev_aa) / self.DT
                self._beta_dot_ema = self._ema(self._beta_dot_ema, beta_dot_raw)

            # Ė (energy rate)
            if self._prev_e_diff is not None:
                edot_raw = (e_diff - self._prev_e_diff) / self.DT
                self._edot_ema = self._ema(self._edot_ema, edot_raw)

            # ── 위협 크기 τ ──
            tau = self._compute_threat_tau(
                self._rdot_ema, aa, self._beta_dot_ema, self._edot_ema)

            # ── 오버슈트 예측 ──
            overshoot = (self._predict_overshoot(dist, closure_fps, ata, turn_rate)
                         or overshoot_flag)

            # ── N(τ, dist) ──
            N = self._compute_N(tau, dist, overshoot)

            # ── PN heading (PID) ──
            p_term = rel_b * self.kp
            d_term = N * self._lambda_dot_ema * self.DT
            self._integral_err += rel_b * self.DT
            self._integral_err = max(-90.0, min(90.0, self._integral_err))
            i_term = self.ki * self._integral_err
            cmd_deg = p_term + d_term + i_term
            hdg = max(0, min(8, int(round(cmd_deg / 22.5)) + 4))

            # ── geometric advantage (2-orbit) ──
            ga = self._compute_geo_advantage(ata, aa)

            # ── vel(τ, ga, dist, closure) 연속 ──
            vel_cont = self._compute_vel(tau, ga, dist, closure)
            vel = max(0, min(4, int(round(vel_cont))))

            # ── alt(τ, e_diff) ──
            alt_idx = self._safe_alt(2, obs)
            if e_diff > self.dive_e_thresh and alt_adv and dist < self.dive_dist:
                alt_idx = self._safe_alt(1, obs)

            # ── 상태 업데이트 ──
            self._prev_ata = ata
            self._prev_aa = aa
            self._prev_e_diff = e_diff

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


# ═══════════════════════════════════════════════════════════════
# 8. ContinuousMasterController — HCCA v12
#    5-Layer Hierarchical Continuous Control Architecture
# ═══════════════════════════════════════════════════════════════

class ContinuousMasterController(BaseAction):
    """Hierarchical Continuous Control Architecture (HCCA) v12.

    5-Layer architecture replacing discrete BT routing with continuous control:
      Layer 0: State Estimation   — EMA smoothing + derivatives + physics
      Layer 1: Strategic Assessment — 4 continuous scores (threat/opp/energy/pursuit)
      Layer 2: Mode Selection      — Commitment Architecture (select, don't blend)
      Layer 3: Mode Controllers    — Selected mode outputs (hdg, vel, alt) continuously
      Layer 4: Output              — Discretize + safety clamp

    Key design: Commitment Architecture
      - Select ONE mode (no blend — blending opposing maneuvers is catastrophic)
      - Hysteresis: switch_margin (0.15) gap required for mode change
      - Min commitment: 5 ticks (1 second) before re-evaluation
      - Safety override: tau_threat > 0.85 → immediate DEFEND
    """

    # ── Mode constants ──
    MODE_ATTACK = 0
    MODE_DEFEND = 1
    MODE_ENERGY = 2
    MODE_PURSUE = 3
    MODE_NAMES = ["ATTACK", "DEFEND", "ENERGY", "PURSUE"]

    DT = 0.2       # tick interval (seconds)
    KTS_TO_FPS = 1.6878
    G_FT = 32.174  # gravity ft/s²

    TUNABLE_PARAMS = {
        # ── Layer 0: State Estimation ──
        "alpha_fast":       {"type": "cont", "range": (0.1, 0.5), "default": 0.3},
        "alpha_slow":       {"type": "cont", "range": (0.05, 0.2), "default": 0.1},
        "ga_scale":         {"type": "cont", "range": (20, 90), "default": 45},
        "overshoot_margin": {"type": "cont", "range": (1.0, 5.0), "default": 2.0},
        # ── Layer 1a: tau_threat ──
        "th_w1": {"type": "cont", "range": (0.5, 4.0), "default": 2.0},
        "th_w2": {"type": "cont", "range": (0.5, 4.0), "default": 1.5},
        "th_w3": {"type": "cont", "range": (0.0, 3.0), "default": 1.0},
        "th_w4": {"type": "cont", "range": (0.0, 2.0), "default": 0.5},
        "th_w5": {"type": "cont", "range": (1.0, 5.0), "default": 3.0},
        "th_w6": {"type": "cont", "range": (0.5, 3.0), "default": 1.5},
        "th_bias": {"type": "cont", "range": (-4.0, 2.0), "default": -1.5},
        "th_rdot_scale": {"type": "cont", "range": (100, 600), "default": 300},
        "th_aa_rate_scale": {"type": "cont", "range": (5, 30), "default": 15},
        "th_edot_scale": {"type": "cont", "range": (500, 3000), "default": 1000},
        # ── Layer 1b: tau_opportunity ──
        "op_w1": {"type": "cont", "range": (0.5, 4.0), "default": 2.0},
        "op_w2": {"type": "cont", "range": (0.5, 4.0), "default": 1.5},
        "op_w3": {"type": "cont", "range": (0.5, 3.0), "default": 1.5},
        "op_w4": {"type": "cont", "range": (1.0, 5.0), "default": 3.0},
        "op_w5": {"type": "cont", "range": (0.5, 3.0), "default": 1.5},
        "op_bias": {"type": "cont", "range": (-4.0, 2.0), "default": -1.5},
        "op_wez_max": {"type": "cont", "range": (500, 1500), "default": 914},
        # ── Layer 1c: tau_energy ──
        "en_w1": {"type": "cont", "range": (0.5, 4.0), "default": 2.0},
        "en_w2": {"type": "cont", "range": (0.5, 3.0), "default": 1.5},
        "en_w3": {"type": "cont", "range": (0.5, 3.0), "default": 1.0},
        "en_w4": {"type": "cont", "range": (0.5, 3.0), "default": 1.0},
        "en_w5": {"type": "cont", "range": (0.5, 3.0), "default": 1.0},
        "en_bias": {"type": "cont", "range": (-2.0, 2.0), "default": 0.0},
        "en_ediff_scale": {"type": "cont", "range": (1000, 10000), "default": 5000},
        "en_ps_scale": {"type": "cont", "range": (50, 500), "default": 200},
        "en_edot_scale": {"type": "cont", "range": (500, 3000), "default": 1000},
        # ── Layer 1d: tau_pursuit ──
        "pu_w1": {"type": "cont", "range": (0.5, 4.0), "default": 2.0},
        "pu_w2": {"type": "cont", "range": (0.5, 4.0), "default": 1.5},
        "pu_w3": {"type": "cont", "range": (0.5, 3.0), "default": 1.5},
        "pu_w4": {"type": "cont", "range": (0.5, 3.0), "default": 1.0},
        "pu_bias": {"type": "cont", "range": (-2.0, 2.0), "default": 0.0},
        "pu_closure_scale": {"type": "cont", "range": (50, 400), "default": 200},
        "pu_ata_scale": {"type": "cont", "range": (5, 30), "default": 10},
        "pu_range_scale": {"type": "cont", "range": (100, 600), "default": 300},
        # ── Layer 2: Mode Selection ──
        "temperature": {"type": "cont", "range": (0.1, 1.0), "default": 0.3},
        "switch_margin": {"type": "cont", "range": (0.05, 0.3), "default": 0.15},
        "min_commit_ticks": {"type": "disc", "choices": [3, 5, 8, 10], "default": 5},
        "critical_threat": {"type": "cont", "range": (0.7, 0.95), "default": 0.85},
        "patience_ticks": {"type": "disc", "choices": [30, 45, 60, 80], "default": 60},
        # ── Layer 3a: ATTACK mode ──
        "atk_kp": {"type": "cont", "range": (0.5, 2.0), "default": 1.0},
        "atk_ki": {"type": "cont", "range": (0.0, 0.3), "default": 0.05},
        "atk_n_base": {"type": "cont", "range": (2.0, 5.0), "default": 3.5},
        "atk_n_bonus": {"type": "cont", "range": (0.5, 3.0), "default": 1.5},
        "atk_n_cap": {"type": "cont", "range": (0.0, 2.0), "default": 0.5},
        "atk_blend_dist": {"type": "cont", "range": (2000, 5000), "default": 3000},
        "atk_vel_corner": {"type": "cont", "range": (1.0, 3.5), "default": 2.5},
        "atk_vel_max": {"type": "cont", "range": (3.5, 4.0), "default": 4.0},
        "atk_vel_brake": {"type": "cont", "range": (0.0, 2.0), "default": 1.0},
        "atk_dive_thresh": {"type": "cont", "range": (1500, 5000), "default": 2500},
        "atk_dive_dist": {"type": "cont", "range": (2000, 6000), "default": 4000},
        # ── Layer 3b: DEFEND mode ──
        "def_vel_desperate": {"type": "cont", "range": (1.0, 3.0), "default": 2.0},
        "def_vel_close": {"type": "cont", "range": (2.0, 4.0), "default": 3.0},
        "def_vel_medium": {"type": "cont", "range": (3.0, 4.0), "default": 3.5},
        "def_vel_extend": {"type": "cont", "range": (3.5, 4.0), "default": 4.0},
        "def_panic_dist": {"type": "cont", "range": (1000, 3000), "default": 1500},
        "def_alt_split_high": {"type": "cont", "range": (5000, 12000), "default": 8000},
        "def_alt_split_low": {"type": "cont", "range": (2000, 5000), "default": 3000},
        # ── Layer 3c: ENERGY mode ──
        "erg_kp": {"type": "cont", "range": (0.2, 1.0), "default": 0.5},
        "erg_deficit_thresh": {"type": "cont", "range": (-5000, -500), "default": -2000},
        "erg_surplus_thresh": {"type": "cont", "range": (1000, 5000), "default": 3000},
        "erg_vel_build": {"type": "cont", "range": (2.0, 3.5), "default": 3.0},
        "erg_vel_convert": {"type": "cont", "range": (3.0, 4.0), "default": 3.5},
        "erg_vel_cruise": {"type": "cont", "range": (2.5, 3.5), "default": 3.0},
        "erg_stall_thresh": {"type": "cont", "range": (150, 250), "default": 200},
        # ── Layer 3d: PURSUE mode ──
        "pur_kp": {"type": "cont", "range": (0.5, 2.0), "default": 1.0},
        "pur_n_base": {"type": "cont", "range": (2.0, 5.0), "default": 3.0},
        "pur_n_gain": {"type": "cont", "range": (0.5, 3.0), "default": 1.5},
        "pur_far_dist": {"type": "cont", "range": (4000, 10000), "default": 6000},
        "pur_ga_sprint": {"type": "cont", "range": (0.5, 0.9), "default": 0.7},
        "pur_stale_closure": {"type": "cont", "range": (20, 100), "default": 50},
        "pur_stale_pursuit": {"type": "cont", "range": (0.2, 0.75), "default": 0.65},
        "pur_vel_sprint": {"type": "cont", "range": (3.5, 4.0), "default": 4.0},
        "pur_vel_behind": {"type": "cont", "range": (2.5, 3.5), "default": 3.0},
        "pur_vel_corner": {"type": "cont", "range": (1.5, 3.5), "default": 3.0},
        "pur_orbit_break": {"type": "cont", "range": (3.0, 4.0), "default": 3.5},
        "pur_energy_floor": {"type": "cont", "range": (-5000, -1000), "default": -2000},
        "pur_energy_ceiling": {"type": "cont", "range": (2000, 6000), "default": 4000},
    }

    def __init__(self, name="ContinuousMasterController",
                 # Layer 0
                 alpha_fast=0.3, alpha_slow=0.1, ga_scale=45, overshoot_margin=2.0,
                 # Layer 1a: threat
                 th_w1=2.0, th_w2=1.5, th_w3=1.0, th_w4=0.5, th_w5=3.0, th_w6=1.5,
                 th_bias=-1.5, th_rdot_scale=300, th_aa_rate_scale=15, th_edot_scale=1000,
                 # Layer 1b: opportunity
                 op_w1=2.0, op_w2=1.5, op_w3=1.5, op_w4=3.0, op_w5=1.5,
                 op_bias=-1.5, op_wez_max=914,
                 # Layer 1c: energy
                 en_w1=2.0, en_w2=1.5, en_w3=1.0, en_w4=1.0, en_w5=1.0,
                 en_bias=0.0, en_ediff_scale=5000, en_ps_scale=200, en_edot_scale=1000,
                 # Layer 1d: pursuit
                 pu_w1=2.0, pu_w2=1.5, pu_w3=1.5, pu_w4=1.0,
                 pu_bias=0.0, pu_closure_scale=200, pu_ata_scale=10, pu_range_scale=300,
                 # Layer 2: mode selection
                 temperature=0.3, switch_margin=0.15, min_commit_ticks=5,
                 critical_threat=0.85, patience_ticks=60,
                 # Layer 3a: ATTACK
                 atk_kp=1.0, atk_ki=0.05, atk_n_base=3.5, atk_n_bonus=1.5,
                 atk_n_cap=0.5, atk_blend_dist=3000,
                 atk_vel_corner=2.5, atk_vel_max=4.0, atk_vel_brake=1.0,
                 atk_dive_thresh=2500, atk_dive_dist=4000,
                 # Layer 3b: DEFEND
                 def_vel_desperate=2.0, def_vel_close=3.0, def_vel_medium=3.5,
                 def_vel_extend=4.0, def_panic_dist=1500,
                 def_alt_split_high=8000, def_alt_split_low=3000,
                 # Layer 3c: ENERGY
                 erg_kp=0.5, erg_deficit_thresh=-2000, erg_surplus_thresh=3000,
                 erg_vel_build=3.0, erg_vel_convert=3.5, erg_vel_cruise=3.0,
                 erg_stall_thresh=200,
                 # Layer 3d: PURSUE
                 pur_kp=1.0, pur_n_base=3.0, pur_n_gain=1.5,
                 pur_far_dist=6000, pur_ga_sprint=0.7,
                 pur_stale_closure=50, pur_stale_pursuit=0.65,
                 pur_vel_sprint=4.0, pur_vel_behind=3.0, pur_vel_corner=3.0,
                 pur_orbit_break=3.5, pur_energy_floor=-2000, pur_energy_ceiling=4000,
                 **kwargs):
        super().__init__(name)

        # ── Layer 0 params ──
        self.alpha_fast = alpha_fast
        self.alpha_slow = alpha_slow
        self.ga_scale = ga_scale
        self.overshoot_margin = overshoot_margin

        # ── Layer 1a: threat ──
        self.th_w = [th_w1, th_w2, th_w3, th_w4, th_w5, th_w6]
        self.th_bias = th_bias
        self.th_rdot_scale = th_rdot_scale
        self.th_aa_rate_scale = th_aa_rate_scale
        self.th_edot_scale = th_edot_scale

        # ── Layer 1b: opportunity ──
        self.op_w = [op_w1, op_w2, op_w3, op_w4, op_w5]
        self.op_bias = op_bias
        self.op_wez_max = op_wez_max

        # ── Layer 1c: energy ──
        self.en_w = [en_w1, en_w2, en_w3, en_w4, en_w5]
        self.en_bias = en_bias
        self.en_ediff_scale = en_ediff_scale
        self.en_ps_scale = en_ps_scale
        self.en_edot_scale = en_edot_scale

        # ── Layer 1d: pursuit ──
        self.pu_w = [pu_w1, pu_w2, pu_w3, pu_w4]
        self.pu_bias = pu_bias
        self.pu_closure_scale = pu_closure_scale
        self.pu_ata_scale = pu_ata_scale
        self.pu_range_scale = pu_range_scale

        # ── Layer 2 params ──
        self.temperature = temperature
        self.switch_margin = switch_margin
        self.min_commit_ticks = min_commit_ticks
        self.critical_threat = critical_threat
        self.patience_ticks = patience_ticks

        # ── Layer 3a: ATTACK ──
        self.atk_kp = atk_kp
        self.atk_ki = atk_ki
        self.atk_n_base = atk_n_base
        self.atk_n_bonus = atk_n_bonus
        self.atk_n_cap = atk_n_cap
        self.atk_blend_dist = atk_blend_dist
        self.atk_vel_corner = atk_vel_corner
        self.atk_vel_max = atk_vel_max
        self.atk_vel_brake = atk_vel_brake
        self.atk_dive_thresh = atk_dive_thresh
        self.atk_dive_dist = atk_dive_dist

        # ── Layer 3b: DEFEND ──
        self.def_vel_desperate = def_vel_desperate
        self.def_vel_close = def_vel_close
        self.def_vel_medium = def_vel_medium
        self.def_vel_extend = def_vel_extend
        self.def_panic_dist = def_panic_dist
        self.def_alt_split_high = def_alt_split_high
        self.def_alt_split_low = def_alt_split_low

        # ── Layer 3c: ENERGY ──
        self.erg_kp = erg_kp
        self.erg_deficit_thresh = erg_deficit_thresh
        self.erg_surplus_thresh = erg_surplus_thresh
        self.erg_vel_build = erg_vel_build
        self.erg_vel_convert = erg_vel_convert
        self.erg_vel_cruise = erg_vel_cruise
        self.erg_stall_thresh = erg_stall_thresh

        # ── Layer 3d: PURSUE ──
        self.pur_kp = pur_kp
        self.pur_n_base = pur_n_base
        self.pur_n_gain = pur_n_gain
        self.pur_far_dist = pur_far_dist
        self.pur_ga_sprint = pur_ga_sprint
        self.pur_stale_closure = pur_stale_closure
        self.pur_stale_pursuit = pur_stale_pursuit
        self.pur_vel_sprint = pur_vel_sprint
        self.pur_vel_behind = pur_vel_behind
        self.pur_vel_corner = pur_vel_corner
        self.pur_orbit_break = pur_orbit_break
        self.pur_energy_floor = pur_energy_floor
        self.pur_energy_ceiling = pur_energy_ceiling

        # ══════════ Internal state ══════════
        # Layer 0: EMA state
        self._prev_ata = None
        self._prev_aa = None
        self._prev_e_diff = None
        self._prev_dist = None
        # Fast EMA derivatives
        self._ata_rate_fast = 0.0
        self._aa_rate_fast = 0.0
        self._range_rate_fast = 0.0
        self._energy_rate_fast = 0.0
        # Slow EMA trends
        self._closure_trend = 0.0
        self._ata_trend = 0.0
        self._energy_trend = 0.0

        # Layer 2: Commitment state
        self._current_mode = self.MODE_PURSUE  # default mode
        self._mode_ticks = 0
        self._mode_weights = [0.0, 0.0, 0.0, 1.0]
        self._attack_ticks = 0  # patience counter

        # Layer 3: Controller state
        self._integral_err = 0.0   # ATTACK PID integral
        self._side_flag = 1        # DEFEND break direction (1=right, -1=left)

    # ──────────────────────────────────────────────────────────
    # Layer 0: State Estimation
    # ──────────────────────────────────────────────────────────

    def _ema_fast(self, prev, raw):
        return self.alpha_fast * raw + (1.0 - self.alpha_fast) * prev

    def _ema_slow(self, prev, raw):
        return self.alpha_slow * raw + (1.0 - self.alpha_slow) * prev

    def _update_state(self, obs):
        """Layer 0: compute smoothed derivatives and physics from obs."""
        ata = obs.get("ata_deg", 0.5) * 180
        aa = obs.get("aa_deg", 0.5) * 180
        dist = obs.get("distance_ft", 10000)
        closure = obs.get("closure_rate_kts", 0)
        e_diff = obs.get("energy_diff_ft", 0)
        rel_b = obs.get("relative_bearing_deg", 0) * 180
        ego_alt = obs.get("ego_altitude_ft", 10000)
        ego_spd = obs.get("ego_vc_kts", 300)
        ps = obs.get("ps_fts", 0)
        turn_rate = obs.get("turn_rate_degs", 0)
        in_wez = obs.get("in_wez", False)
        enm_in_wez = obs.get("enm_in_wez", False)
        alt_adv = obs.get("alt_advantage", False)
        energy_adv = obs.get("energy_advantage", False)
        overshoot_flag = obs.get("overshoot_risk", False)

        tau_lead = obs.get("tau_deg", 0) * 180  # lead/intercept angle

        closure_fps = closure * self.KTS_TO_FPS

        # ── Fast EMA derivatives ──
        if self._prev_ata is not None:
            d_ata = (ata - self._prev_ata) / self.DT
            d_aa = (aa - self._prev_aa) / self.DT
            d_ediff = (e_diff - self._prev_e_diff) / self.DT
            self._ata_rate_fast = self._ema_fast(self._ata_rate_fast, d_ata)
            self._aa_rate_fast = self._ema_fast(self._aa_rate_fast, d_aa)
            self._range_rate_fast = self._ema_fast(self._range_rate_fast, closure_fps)
            self._energy_rate_fast = self._ema_fast(self._energy_rate_fast, d_ediff)
            # Slow trends
            self._closure_trend = self._ema_slow(self._closure_trend, closure)
            self._ata_trend = self._ema_slow(self._ata_trend, ata - self._prev_ata)
            self._energy_trend = self._ema_slow(self._energy_trend, e_diff - self._prev_e_diff)

        self._prev_ata = ata
        self._prev_aa = aa
        self._prev_e_diff = e_diff
        self._prev_dist = dist

        # ── Physics derivations ──
        ga = _sigmoid((aa - ata) / max(self.ga_scale, 1.0))

        # Overshoot prediction
        overshoot = overshoot_flag
        if closure_fps > 0 and dist > 0:
            t_impact = dist / closure_fps
            omega = max(abs(turn_rate), 5.0)
            t_turn = abs(ata) / omega if omega > 0 else 999.0
            if t_impact < t_turn * self.overshoot_margin:
                overshoot = True

        # Speed advantage (simple heuristic)
        spd_adv = 1.0 if ego_spd > 280 else 0.0

        return {
            "ata": ata, "aa": aa, "dist": dist, "closure": closure,
            "e_diff": e_diff, "rel_b": rel_b, "tau_lead": tau_lead,
            "ego_alt": ego_alt, "ego_spd": ego_spd, "ps": ps,
            "turn_rate": turn_rate, "in_wez": in_wez, "enm_in_wez": enm_in_wez,
            "alt_adv": alt_adv, "energy_adv": energy_adv,
            "closure_fps": closure_fps, "ga": ga, "overshoot": overshoot,
            "spd_adv": spd_adv,
        }

    # ──────────────────────────────────────────────────────────
    # Layer 1: Strategic Assessment — 4 continuous scores
    # ──────────────────────────────────────────────────────────

    def _compute_tau_threat(self, s):
        """Threat evaluation τ_threat ∈ [0,1]."""
        # closure term weighted by (1 - AA/180): threatening only when enemy faces us.
        # AA=0° (nose-on) → full weight; AA=180° (tail) → zero weight.
        aa_facing = 1.0 - s["aa"] / 180.0
        z = (self.th_w[0] * (s["closure"] / max(self.th_rdot_scale, 1)) * aa_facing
             + self.th_w[1] * aa_facing
             + self.th_w[2] * (-self._aa_rate_fast / max(self.th_aa_rate_scale, 1))
             + self.th_w[3] * (-self._energy_rate_fast / max(self.th_edot_scale, 1))
             + self.th_w[4] * (1.0 if s["in_wez"] else 0.0)
             + self.th_w[5] * max(0, s["closure"] / 300.0) * max(0, 1.0 - s["dist"] / 2000.0) * aa_facing
             + self.th_bias)
        return _sigmoid(z)

    def _compute_tau_opportunity(self, s):
        """Opportunity evaluation τ_opp ∈ [0,1]."""
        # Long-range penalty: beyond WEZ, opportunity decays with distance.
        # Prevents τ_opp from staying high at 7000+ft due to AA/ga terms alone.
        dist_decay = max(0.0, 1.0 - s["dist"] / 8000.0)
        z = (self.op_w[0] * (1.0 - s["ata"] / 180.0)
             + self.op_w[1] * (s["aa"] / 180.0)
             + self.op_w[2] * max(0, 1.0 - s["dist"] / max(self.op_wez_max, 1))
             + self.op_w[3] * (1.0 if s["enm_in_wez"] else 0.0)
             + self.op_w[4] * s["ga"]
             + self.op_bias
             - 1.5 * (1.0 - dist_decay))
        return _sigmoid(z)

    def _compute_tau_energy(self, s):
        """Energy state τ_energy ∈ [0,1]. High = energy-rich."""
        z = (self.en_w[0] * (s["e_diff"] / max(self.en_ediff_scale, 1))
             + self.en_w[1] * (1.5 if s["alt_adv"] else 0.0)
             + self.en_w[2] * s["spd_adv"]
             + self.en_w[3] * (s["ps"] / max(self.en_ps_scale, 1))
             + self.en_w[4] * (self._energy_trend / max(self.en_edot_scale, 1))
             + self.en_bias)
        return _sigmoid(z)

    def _compute_tau_pursuit(self, s):
        """Pursuit progress τ_pursuit ∈ [0,1]. High = making progress."""
        z = (self.pu_w[0] * (self._closure_trend / max(self.pu_closure_scale, 1))
             + self.pu_w[1] * (-self._ata_trend / max(self.pu_ata_scale, 1))
             + self.pu_w[2] * (self._range_rate_fast / max(self.pu_range_scale, 1))
             + self.pu_w[3] * s["ga"]
             + self.pu_bias)
        return _sigmoid(z)

    # ──────────────────────────────────────────────────────────
    # Layer 2: Mode Selection — Commitment Architecture
    # ──────────────────────────────────────────────────────────

    def _select_mode(self, tau_th, tau_op, tau_en, tau_pu):
        """Select mode using softmax + commitment architecture."""
        # Mode weight computation
        w_attack = tau_op * (1.0 - tau_th) * max(0.3, tau_en)
        w_defend = tau_th * (1.0 - tau_op * 0.5)
        # B1 fix: when energy is critically low (tau_en<0.3), τ_opp suppression
        # on w_energy is relaxed — energy crisis must take precedence over opportunity.
        op_suppress = 0.7 * min(1.0, max(0.0, tau_en / 0.3))
        w_energy = (1.0 - tau_en) * (1.0 - tau_th * 0.7) * (1.0 - tau_op * op_suppress)
        w_pursue = tau_pu * (1.0 - tau_th * 0.5) * (1.0 - tau_op * 0.3)

        # Patience modifier: ATTACK too long without progress → penalty
        if self._current_mode == self.MODE_ATTACK:
            self._attack_ticks += 1
            if self._attack_ticks > self.patience_ticks and tau_pu < 0.4:
                w_attack *= 0.5
                w_energy *= 1.5
        else:
            self._attack_ticks = 0

        # Softmax normalization
        raw = [w_attack, w_defend, w_energy, w_pursue]
        temp = max(self.temperature, 0.01)
        max_r = max(raw)
        exp_vals = [math.exp((r - max_r) / temp) for r in raw]
        sum_exp = sum(exp_vals)
        weights = [e / sum_exp for e in exp_vals]

        self._mode_weights = weights
        best_mode = weights.index(max(weights))

        # ── Safety override: critical threat → immediate DEFEND ──
        if tau_th > self.critical_threat:
            self._current_mode = self.MODE_DEFEND
            self._mode_ticks = 0
            return self._current_mode

        # ── Commitment check ──
        self._mode_ticks += 1
        if self._mode_ticks < self.min_commit_ticks:
            return self._current_mode  # stay committed

        # Switch only if margin exceeded
        current_weight = weights[self._current_mode]
        best_weight = weights[best_mode]
        if best_mode != self._current_mode and (best_weight - current_weight) > self.switch_margin:
            self._current_mode = best_mode
            self._mode_ticks = 0
            # Pick DEFEND break direction on switch
            if best_mode == self.MODE_DEFEND:
                self._side_flag = 1 if self._prev_ata is not None and (self._prev_ata or 0) > 0 else -1

        return self._current_mode

    # ──────────────────────────────────────────────────────────
    # Layer 3: Mode Controllers
    # ──────────────────────────────────────────────────────────

    def _mode_attack(self, s, tau_th):
        """ATTACK: PN heading + 2-orbit velocity + dive attack."""
        tau_lead = s["tau_lead"]
        dist = s["dist"]
        closure = s["closure"]
        ga = s["ga"]

        # ── PN Heading (tau_lead = lead/intercept angle) ──
        N = self.atk_n_base + (1.0 - tau_th) * self.atk_n_bonus
        if s["overshoot"]:
            N = min(N, self.atk_n_cap)
        N = max(0.0, min(6.0, N))

        p_term = tau_lead * self.atk_kp
        d_term = N * self._ata_rate_fast * self.DT
        self._integral_err += s["rel_b"] * self.DT
        self._integral_err = max(-90.0, min(90.0, self._integral_err))
        i_term = self.atk_ki * self._integral_err
        hdg_deg = p_term + d_term + i_term

        # ── 2-Orbit Velocity ──
        range_blend = _sigmoid((dist - self.atk_blend_dist) / 1500.0)
        vel_turn = self.atk_vel_corner
        vel_chase = self.atk_vel_max
        vel_cont = vel_turn * (1.0 - range_blend) + vel_chase * range_blend

        # Overshoot → brake
        if s["overshoot"]:
            vel_cont = self.atk_vel_brake

        # Separation correction
        if closure < 0:
            vel_cont = max(vel_cont, self.atk_vel_max)

        # ── Altitude ──
        alt_cont = 0.0  # level
        if s["e_diff"] > self.atk_dive_thresh and s["alt_adv"] and dist < self.atk_dive_dist:
            alt_cont = -1.0  # dive attack

        return hdg_deg, vel_cont, alt_cont

    def _mode_defend(self, s, tau_th):
        """DEFEND: break turn + corner speed + evasion altitude."""
        dist = s["dist"]
        ego_alt = s["ego_alt"]

        # ── Break heading: turn away from threat ──
        intensity = min(1.0, tau_th * 1.2)
        if s["in_wez"]:
            intensity = 1.0  # max break
        # Break in side_flag direction, scaled by intensity
        hdg_deg = self._side_flag * intensity * 90.0  # max ±90°

        # Extension if far enough
        if dist > 3000 and not s["in_wez"]:
            hdg_deg = self._side_flag * 45.0  # extension angle

        # ── Velocity ──
        if dist < self.def_panic_dist:
            vel_cont = self.def_vel_desperate  # corner speed for max turn rate
        elif dist < 2500:
            vel_cont = self.def_vel_close
        elif dist < 5000:
            vel_cont = self.def_vel_medium
        else:
            vel_cont = self.def_vel_extend  # extension speed

        # ── Altitude ──
        alt_cont = 0.0  # level default
        if ego_alt > self.def_alt_split_high:
            alt_cont = -1.0  # dive for speed
        elif ego_alt < self.def_alt_split_low:
            alt_cont = 1.0  # climb away from hard deck
        # Vertical evasion in WEZ at close range
        if s["in_wez"] and dist < 1500:
            alt_cont = 1.0 if ego_alt < 8000 else -1.0

        return hdg_deg, vel_cont, alt_cont

    def _mode_energy(self, s, tau_en, tau_pu):
        """ENERGY: loose tracking + energy management."""
        tau_lead = s["tau_lead"]
        e_diff = s["e_diff"]
        ga = s["ga"]

        # ── Loose heading tracking (tau_lead for lead pursuit) ──
        hdg_deg = tau_lead * self.erg_kp

        # ── Velocity & Altitude based on energy state ──
        if e_diff < self.erg_deficit_thresh:
            # Energy deficit → build energy
            vel_cont = self.erg_vel_build
            alt_cont = 0.5  # gentle climb (position energy)
        elif e_diff > self.erg_surplus_thresh:
            # Energy surplus → convert
            # Key insight: "energy surplus >5000ft often CAUSES loss"
            if ga > 0.6:
                # Behind enemy → dive attack setup
                vel_cont = self.erg_vel_convert
                alt_cont = -1.0  # dive
            else:
                # Not behind → yo-yo setup
                vel_cont = self.erg_vel_cruise
                alt_cont = 0.5  # gentle climb for yo-yo
        else:
            # Balanced → cruise
            vel_cont = self.erg_vel_cruise
            alt_cont = 0.0

        # Stall protection
        if s["ego_spd"] < self.erg_stall_thresh:
            vel_cont = max(vel_cont, 3.5)
            alt_cont = min(alt_cont, -0.5)  # nose down for speed

        return hdg_deg, vel_cont, alt_cont

    def _mode_pursue(self, s, tau_th, tau_pu):
        """PURSUE: 2-orbit pursuit — standard engagement mode."""
        tau_lead = s["tau_lead"]
        dist = s["dist"]
        closure = s["closure"]
        ga = s["ga"]
        e_diff = s["e_diff"]

        # ── PN heading with ga-adaptive N (tau_lead = lead angle) ──
        N = self.pur_n_base + (1.0 - ga) * self.pur_n_gain
        N = max(0.5, min(6.0, N))

        # Heading: lead pursuit (tau_lead aims at intercept point)
        hdg_deg = tau_lead * self.pur_kp + N * self._ata_rate_fast * self.DT

        # ── 2-Orbit Velocity ──
        if dist > self.pur_far_dist:
            vel_cont = self.pur_vel_sprint
        elif dist > 3000:
            # Mid-range: blend between corner and sprint based on distance
            range_ratio = (dist - 3000) / max(self.pur_far_dist - 3000, 1)
            vel_cont = self.pur_vel_corner + range_ratio * (self.pur_vel_sprint - self.pur_vel_corner)
        elif ga > self.pur_ga_sprint:
            vel_cont = self.pur_vel_behind
        elif abs(closure) < self.pur_stale_closure and tau_pu < self.pur_stale_pursuit and dist < 3000:
            # 갭#1+#3: scissors/orbit-lock 감지 — 근접+근-제로 closure+pursuit 부진
            # abs(closure)<50: 분리도 접근도 안 하는 교착 상태
            # dist<3000: 근거리에서만 (원거리 확산은 정상 sprint으로 처리)
            vel_cont = self.pur_orbit_break
            hdg_deg *= 0.7  # heading lock 완화로 orbit 탈출
        else:
            vel_cont = self.pur_vel_corner

        # Separation correction
        if closure < -50:
            vel_cont = max(vel_cont, self.pur_vel_sprint)

        # ── Altitude (energy management) ──
        alt_cont = 0.0
        if e_diff < self.pur_energy_floor:
            alt_cont = 0.5  # gentle climb for energy
        elif e_diff > self.pur_energy_ceiling:
            alt_cont = -0.5  # gentle dive to convert

        return hdg_deg, vel_cont, alt_cont

    # ──────────────────────────────────────────────────────────
    # Layer 4: Output — discretize + safety
    # ──────────────────────────────────────────────────────────

    def _discretize(self, hdg_deg, vel_cont, alt_cont, ego_alt):
        """Convert continuous outputs to discrete action indices."""
        # Heading: continuous degrees → [0,8] index
        hdg_idx = max(0, min(8, int(round(hdg_deg / 22.5)) + 4))

        # Velocity: continuous [0,4] → [0,4] index
        vel_idx = max(0, min(4, int(round(vel_cont))))

        # Altitude: continuous [-2,2] → [0,4] index
        alt_idx = max(0, min(4, int(round(alt_cont + 2))))

        # ── Safety clamp: hard deck protection ──
        if ego_alt < 2000 and alt_idx < 2:
            alt_idx = 3   # force climb
        if ego_alt < 1200:
            alt_idx = 4   # emergency climb

        return alt_idx, hdg_idx, vel_idx

    # ──────────────────────────────────────────────────────────
    # Main update
    # ──────────────────────────────────────────────────────────

    def update(self):
        try:
            obs = self._obs()

            # ── Layer 0: State Estimation ──
            s = self._update_state(obs)

            # ── Layer 1: Strategic Assessment ──
            tau_th = self._compute_tau_threat(s)
            tau_op = self._compute_tau_opportunity(s)
            tau_en = self._compute_tau_energy(s)
            tau_pu = self._compute_tau_pursuit(s)

            # ── Layer 2: Mode Selection ──
            mode = self._select_mode(tau_th, tau_op, tau_en, tau_pu)

            # ── Layer 3: Mode Controller ──
            if mode == self.MODE_ATTACK:
                hdg_deg, vel_cont, alt_cont = self._mode_attack(s, tau_th)
            elif mode == self.MODE_DEFEND:
                hdg_deg, vel_cont, alt_cont = self._mode_defend(s, tau_th)
            elif mode == self.MODE_ENERGY:
                hdg_deg, vel_cont, alt_cont = self._mode_energy(s, tau_en, tau_pu)
            else:  # PURSUE
                hdg_deg, vel_cont, alt_cont = self._mode_pursue(s, tau_th, tau_pu)

            # ── Layer 4: Discretize + Safety ──
            alt_idx, hdg_idx, vel_idx = self._discretize(
                hdg_deg, vel_cont, alt_cont, s["ego_alt"])

            self.set_action(alt_idx, hdg_idx, vel_idx)
            return py_trees.common.Status.SUCCESS

        except Exception as e:
            logger.warning(f"ContinuousMasterController: {e}")
            self.set_action(2, 4, 3)
            return py_trees.common.Status.SUCCESS
