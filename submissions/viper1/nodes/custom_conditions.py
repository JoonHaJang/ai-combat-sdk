"""
Viper1 커스텀 조건 노드

Callsign: Viper1
"""

import logging
import py_trees

logger = logging.getLogger(__name__)


class HighEnergyState(py_trees.behaviour.Behaviour):
    """고에너지 상태 확인
    
    에너지 = 고도 + 속도^2 / 20
    """
    
    def __init__(self, name: str = "HighEnergyState", threshold: float = 12000):
        super().__init__(name)
        self.threshold = threshold
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)
    
    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            velocity = obs.get("ego_vc", 200.0)
            altitude = obs.get("ego_altitude", 5000.0)
            
            energy = altitude + (velocity ** 2) / 20
            
            if energy > self.threshold:
                return py_trees.common.Status.SUCCESS
            else:
                return py_trees.common.Status.FAILURE
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"HighEnergyState 실행 실패: {e}")
            return py_trees.common.Status.FAILURE


class LowEnergyState(py_trees.behaviour.Behaviour):
    """저에너지 상태 확인"""
    
    def __init__(self, name: str = "LowEnergyState", threshold: float = 8000):
        super().__init__(name)
        self.threshold = threshold
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)
    
    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            velocity = obs.get("ego_vc", 200.0)
            altitude = obs.get("ego_altitude", 5000.0)
            
            energy = altitude + (velocity ** 2) / 20
            
            if energy < self.threshold:
                return py_trees.common.Status.SUCCESS
            else:
                return py_trees.common.Status.FAILURE
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"LowEnergyState 실행 실패: {e}")
            return py_trees.common.Status.FAILURE


class OptimalAttackPosition(py_trees.behaviour.Behaviour):
    """최적 공격 위치 확인
    
    조건:
    - 거리: 800m ~ 2500m (WEZ 범위)
    - ATA: < 30도 (조준 가능)
    - 고도 우위: > 0m
    """
    
    def __init__(self, name: str = "OptimalAttackPosition"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)
    
    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            distance = obs.get("distance", 10000.0)
            ata_deg = obs.get("ata_deg", 1.0) * 180.0
            alt_gap = obs.get("alt_gap", 0.0)
            
            # 최적 거리
            if distance < 800 or distance > 2500:
                return py_trees.common.Status.FAILURE
            
            # 조준 가능 각도
            if abs(ata_deg) > 30:
                return py_trees.common.Status.FAILURE
            
            # 고도 우위
            if alt_gap < 0:
                return py_trees.common.Status.FAILURE
            
            return py_trees.common.Status.SUCCESS
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"OptimalAttackPosition 실행 실패: {e}")
            return py_trees.common.Status.FAILURE
