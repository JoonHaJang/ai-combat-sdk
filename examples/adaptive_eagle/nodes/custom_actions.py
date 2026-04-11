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
    """빌트인 LeadPursuit 커스텀화 — heading + vel + alt 전부 튜닝."""
    TUNABLE_PARAMS = {
        "heading_gain":      {"type": "cont", "range": (0.3, 2.0), "default": 1.0},
        "vel_far":           {"type": "disc", "choices": [2, 3, 4], "default": 4},
        "vel_close":         {"type": "disc", "choices": [1, 2, 3, 4], "default": 3},
        "vel_energy_adv":    {"type": "disc", "choices": [3, 4], "default": 4},
        "far_dist_ft":       {"type": "cont", "range": (5000, 15000), "default": 8000},
        "closure_brake_kts": {"type": "cont", "range": (100, 500), "default": 300},
        "alt_dive_dist_ft":  {"type": "cont", "range": (2000, 8000), "default": 5000},
    }

    def __init__(self, name="SmartLeadPursuit", heading_gain=1.0,
                 vel_far=4, vel_close=3, vel_energy_adv=4,
                 far_dist_ft=8000, closure_brake_kts=300, alt_dive_dist_ft=5000):
        super().__init__(name)
        self.heading_gain = heading_gain
        self.vel_far = vel_far
        self.vel_close = vel_close
        self.vel_energy_adv = vel_energy_adv
        self.far_dist = far_dist_ft
        self.closure_brake = closure_brake_kts
        self.alt_dive_dist = alt_dive_dist_ft

    def update(self):
        try:
            obs = self._obs()
            rel_b = obs.get("relative_bearing_deg", 0) * 180
            dist = obs.get("distance_ft", 10000)
            closure = obs.get("closure_rate_kts", 0)
            energy_adv = obs.get("energy_advantage", False)
            alt_adv = obs.get("alt_advantage", False)

            hdg = self._hdg_from_bearing(rel_b, self.heading_gain)
            vel = self.vel_far if dist > self.far_dist else (2 if closure > self.closure_brake else (self.vel_energy_adv if energy_adv else self.vel_close))
            alt_idx = self._safe_alt(1 if alt_adv and dist < self.alt_dive_dist else 2, obs)

            self.set_action(alt_idx, hdg, vel)
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"SmartLeadPursuit: {e}")
            self.set_action(2, 4, 4)
            return py_trees.common.Status.SUCCESS


class SmartPurePursuit(BaseAction):
    """빌트인 PurePursuit 커스텀화 — side_flag 기반 직접 추적."""
    TUNABLE_PARAMS = {
        "turn_intensity": {"type": "disc", "choices": [1, 2, 3], "default": 2},
        "vel":            {"type": "disc", "choices": [2, 3, 4], "default": 3},
    }

    def __init__(self, name="SmartPurePursuit", turn_intensity=2, vel=3):
        super().__init__(name)
        self.turn_intensity = turn_intensity
        self.vel = vel

    def update(self):
        try:
            obs = self._obs()
            side = obs.get("side_flag", 0)
            hdg = 4 - self.turn_intensity if side <= 0 else 4 + self.turn_intensity
            self.set_action(2, max(0, min(8, hdg)), self.vel)
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
    """2-phase: 상승+선회 → 하강+공격. 오버슈트 방지."""
    TUNABLE_PARAMS = {
        "climb_ticks":    {"type": "disc", "choices": [4, 6, 8, 10, 12], "default": 8},
        "climb_alt":      {"type": "disc", "choices": [3, 4], "default": 4},
        "climb_vel":      {"type": "disc", "choices": [2, 3, 4], "default": 3},
        "dive_vel":       {"type": "disc", "choices": [2, 3, 4], "default": 3},
        "turn_intensity": {"type": "disc", "choices": [1, 2, 3], "default": 2},
    }

    def __init__(self, name="SmartHighYoYo", climb_ticks=8, climb_alt=4,
                 climb_vel=3, dive_vel=3, turn_intensity=2):
        super().__init__(name)
        self.climb_ticks = climb_ticks
        self.climb_alt = climb_alt
        self.climb_vel = climb_vel
        self.dive_vel = dive_vel
        self.turn_intensity = turn_intensity
        self._phase = 0
        self._tick = 0

    def update(self):
        try:
            obs = self._obs()
            side = obs.get("side_flag", 0)
            turn = 4 + self.turn_intensity if side >= 0 else 4 - self.turn_intensity

            if self._phase == 0:  # CLIMB
                self.set_action(self.climb_alt, max(0, min(8, turn)), self.climb_vel)
                self._tick += 1
                if self._tick >= self.climb_ticks:
                    self._phase = 1
                    self._tick = 0
            else:  # DIVE+ATTACK
                self.set_action(self._safe_alt(1, obs), max(0, min(8, turn)), self.dive_vel)
                self._tick += 1
                if self._tick >= self.climb_ticks:
                    self._phase = 0
                    self._tick = 0
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
    """빌트인 BreakTurn 커스텀화 — 고도 적응."""
    TUNABLE_PARAMS = {
        "alt_high":       {"type": "disc", "choices": [0, 1], "default": 1},
        "alt_mid":        {"type": "disc", "choices": [1, 2], "default": 2},
        "vel":            {"type": "disc", "choices": [3, 4], "default": 4},
    }

    def __init__(self, name="SmartBreakTurn", alt_high=1, alt_mid=2, vel=4):
        super().__init__(name)
        self.alt_high = alt_high
        self.alt_mid = alt_mid
        self.vel = vel

    def update(self):
        try:
            obs = self._obs()
            side = obs.get("side_flag", 0)
            alt_ft = obs.get("ego_altitude_ft", 10000)
            hdg = 0 if side >= 0 else 8  # 반대 방향 급선회
            alt_idx = self._safe_alt(self.alt_high if alt_ft > 8000 else self.alt_mid, obs)
            self.set_action(alt_idx, hdg, self.vel)
            return py_trees.common.Status.SUCCESS
        except Exception:
            self.set_action(2, 0, 4)
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
