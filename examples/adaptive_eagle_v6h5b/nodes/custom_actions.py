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
    """빌트인 LagPursuit 커스텀화 — tau 기반 후방 추적."""
    TUNABLE_PARAMS = {
        "tau_gain":  {"type": "cont", "range": (0.3, 1.5), "default": 0.6},
        "vel":       {"type": "disc", "choices": [2, 3, 4], "default": 3},
    }

    def __init__(self, name="SmartLagPursuit", tau_gain=0.6, vel=3):
        super().__init__(name)
        self.tau_gain = tau_gain
        self.vel = vel

    def update(self):
        try:
            obs = self._obs()
            tau = obs.get("tau_deg", 0) * 180
            hdg = self._hdg_from_tau(tau, self.tau_gain)
            self.set_action(2, hdg, self.vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
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
    """2-phase: 하강+가속 → 상승+위치. 속도 확보."""
    TUNABLE_PARAMS = {
        "dive_ticks":     {"type": "disc", "choices": [4, 6, 8, 10], "default": 6},
        "dive_alt":       {"type": "disc", "choices": [0, 1], "default": 1},
        "dive_vel":       {"type": "disc", "choices": [3, 4], "default": 4},
        "recover_alt":    {"type": "disc", "choices": [3, 4], "default": 3},
        "recover_vel":    {"type": "disc", "choices": [2, 3], "default": 3},
    }

    def __init__(self, name="SmartLowYoYo", dive_ticks=6, dive_alt=1,
                 dive_vel=4, recover_alt=3, recover_vel=3):
        super().__init__(name)
        self.dive_ticks = dive_ticks
        self.dive_alt = dive_alt
        self.dive_vel = dive_vel
        self.recover_alt = recover_alt
        self.recover_vel = recover_vel
        self._phase = 0
        self._tick = 0

    def update(self):
        try:
            obs = self._obs()
            rel_b = obs.get("relative_bearing_deg", 0) * 180
            hdg = self._hdg_from_bearing(rel_b, 1.0)

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
    """공전/Head-on 탈출 — 하강 돌파."""
    TUNABLE_PARAMS = {
        "heading_gain": {"type": "cont", "range": (0.3, 1.5), "default": 0.8},
        "dive_alt":     {"type": "disc", "choices": [0, 1], "default": 1},
        "vel":          {"type": "disc", "choices": [3, 4], "default": 4},
    }

    def __init__(self, name="HeadOnBreak", heading_gain=0.8, dive_alt=1, vel=4):
        super().__init__(name)
        self.heading_gain = heading_gain
        self.dive_alt = dive_alt
        self.vel = vel

    def update(self):
        try:
            obs = self._obs()
            tau = obs.get("tau_deg", 0) * 180
            hdg = self._hdg_from_tau(tau, self.heading_gain)
            alt = self._safe_alt(self.dive_alt, obs)
            self.set_action(alt, hdg, self.vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
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
