"""
Archetype shared custom actions — SCISSORS 아키타입용

Alpha2에서 검증된 커스텀 액션 노드를 공유.
ScissorsAccel, ReengageClimb
"""

import logging
import py_trees

logger = logging.getLogger(__name__)


class BaseAction(py_trees.behaviour.Behaviour):
    def __init__(self, name: str):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="action", access=py_trees.common.Access.WRITE)

    def set_action(self, delta_altitude_idx: int, delta_heading_idx: int, delta_velocity_idx: int):
        self.blackboard.action = [delta_altitude_idx, delta_heading_idx, delta_velocity_idx]


def _heading_from_tau(tau_deg: float, gain: float = 1.0) -> int:
    cmd = tau_deg * gain
    idx = int(round(cmd / 22.5)) + 4
    return max(0, min(8, idx))


class ScissorsAccel(BaseAction):
    """Scissors 교착 탈출 — 가속 + 완화 추적."""

    def __init__(self, name: str = "ScissorsAccel", heading_gain: float = 0.5):
        super().__init__(name)
        self.heading_gain = heading_gain

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            tau = obs.get("tau_deg", 0.0) * 180.0
            altitude = obs.get("ego_altitude_ft", 15000.0)
            heading_idx = _heading_from_tau(tau, self.heading_gain)
            delta_alt = 4 if altitude < 1200 else 2
            self.set_action(delta_alt, heading_idx, 4)
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"ScissorsAccel error: {e}")
            self.set_action(2, 4, 4)
            return py_trees.common.Status.FAILURE


class ReengageClimb(BaseAction):
    """이탈 상태 재접근 — 상승 + 중간 추적."""

    def __init__(self, name: str = "ReengageClimb", heading_gain: float = 0.7):
        super().__init__(name)
        self.heading_gain = heading_gain

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            tau = obs.get("tau_deg", 0.0) * 180.0
            altitude = obs.get("ego_altitude_ft", 15000.0)
            closure = obs.get("closure_rate_kts", 0.0)
            heading_idx = _heading_from_tau(tau, self.heading_gain)
            if altitude < 1200:
                delta_alt = 4
            elif altitude > 25000:
                delta_alt = 2
            else:
                delta_alt = 3
            delta_vel = 4 if closure < -200 else 3
            self.set_action(delta_alt, heading_idx, delta_vel)
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"ReengageClimb error: {e}")
            self.set_action(3, 4, 3)
            return py_trees.common.Status.FAILURE
