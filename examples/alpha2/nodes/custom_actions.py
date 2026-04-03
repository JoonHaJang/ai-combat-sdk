"""
Alpha2 커스텀 액션 노드 — Phase 2 (분석기 기반)

데이터 근거: tools/analyze_metadata.py 출력
  - TIR: Scissors → Accelerate→OBFM 51.6%
  - SAE: Disengaging → HighYoYo +0.016 (유일한 양수)
  - WPP: WEZ 진입 선행 = OBFM + ATA<20° + closure>186kts
"""

import logging
import py_trees

logger = logging.getLogger(__name__)


class BaseAction(py_trees.behaviour.Behaviour):
    """Custom action base class"""

    def __init__(self, name: str):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="action", access=py_trees.common.Access.WRITE)

    def set_action(self, delta_altitude_idx: int, delta_heading_idx: int, delta_velocity_idx: int):
        self.blackboard.action = [delta_altitude_idx, delta_heading_idx, delta_velocity_idx]


def _heading_from_tau(tau_deg: float, gain: float = 1.0) -> int:
    """tau → heading index [0-8]."""
    cmd = tau_deg * gain
    idx = int(round(cmd / 22.5)) + 4
    return max(0, min(8, idx))


class ScissorsAccel(BaseAction):
    """Scissors 교착 탈출 — Accelerate + 완화 추적.

    데이터 근거 (TIR):
      Scissors에서 Accelerate→OBFM 전이율 51.6% (LeadPursuit 20.8%의 2.5배)

    전술: 교착 시 가속으로 에너지 확보 → 선회 우위 → OBFM 전이.
    heading은 tau 기반 완화 추적 (gain=0.5, 급선회 방지).
    """

    def __init__(self, name: str = "ScissorsAccel",
                 heading_gain: float = 0.5):
        super().__init__(name)
        self.heading_gain = heading_gain

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            tau = obs.get("tau_deg", 0.0) * 180.0
            altitude = obs.get("ego_altitude_ft", 15000.0)

            # Heading: 완화된 추적 (gain 0.5 = 급선회 방지, 에너지 보존)
            heading_idx = _heading_from_tau(tau, self.heading_gain)

            # Altitude: 유지 (에너지 소모 최소화)
            if altitude < 1200:
                delta_alt = 4  # Hard Deck 근접 시 급상승
            else:
                delta_alt = 2  # 유지

            # Velocity: 급가속 (핵심 — TIR 51.6%의 근거)
            delta_vel = 4

            self.set_action(delta_alt, heading_idx, delta_vel)
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"ScissorsAccel error: {e}")
            self.set_action(2, 4, 4)
            return py_trees.common.Status.FAILURE


class ReengageClimb(BaseAction):
    """이탈 상태에서 재접근 — HighYoYo 변형.

    데이터 근거 (SAE):
      Disengaging에서 HighYoYo SAE +0.016 (유일한 양수)
      LeadPursuit SAE -0.034, Pursue -0.024 (모두 음수)

    전술: 이탈 시 상승으로 위치 에너지 확보 → 하강 가속 재접근.
    heading은 tau 기반 중간 추적.
    """

    def __init__(self, name: str = "ReengageClimb",
                 heading_gain: float = 0.7):
        super().__init__(name)
        self.heading_gain = heading_gain

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            tau = obs.get("tau_deg", 0.0) * 180.0
            altitude = obs.get("ego_altitude_ft", 15000.0)
            closure = obs.get("closure_rate_kts", 0.0)

            # Heading: 중간 추적 (적 방향 유지하되 급선회 않기)
            heading_idx = _heading_from_tau(tau, self.heading_gain)

            # Altitude: 상승 (위치 에너지 확보, HighYoYo 원리)
            if altitude < 1200:
                delta_alt = 4
            elif altitude > 25000:
                delta_alt = 2  # 고도 상한 근접 시 유지
            else:
                delta_alt = 3  # 상승

            # Velocity: 가속 (재접근 준비)
            if closure < -200:
                delta_vel = 4  # 빠르게 벌어지면 급가속
            else:
                delta_vel = 3  # 일반 가속

            self.set_action(delta_alt, heading_idx, delta_vel)
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"ReengageClimb error: {e}")
            self.set_action(3, 4, 3)
            return py_trees.common.Status.FAILURE
