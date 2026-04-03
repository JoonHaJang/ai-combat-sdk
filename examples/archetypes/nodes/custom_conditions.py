"""
Archetype shared custom conditions — SCISSORS 아키타입용

Alpha2에서 검증된 커스텀 조건 노드를 공유.
IsScissors, IsDisengaging, IsNearOffensive
"""

import logging
import py_trees

logger = logging.getLogger(__name__)


class IsScissors(py_trees.behaviour.Behaviour):
    """Scissors 교착 상태 감지: UNKNOWN BFM + 45≤ATA<70° + closure<0."""

    def __init__(self, name: str = "IsScissors",
                 ata_min: float = 45.0,
                 ata_max: float = 70.0,
                 closure_max_kts: float = 0.0):
        super().__init__(name)
        self.ata_min = ata_min
        self.ata_max = ata_max
        self.closure_max = closure_max_kts
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            ata = obs.get("ata_deg", 0.5) * 180.0
            closure = obs.get("closure_rate_kts", 0.0)
            bfm = str(obs.get("bfm_situation", ""))
            if ("UNKNOWN" in bfm and
                    self.ata_min <= ata <= self.ata_max and
                    closure < self.closure_max):
                return py_trees.common.Status.SUCCESS
            return py_trees.common.Status.FAILURE
        except Exception as e:
            logger.warning(f"IsScissors error: {e}")
            return py_trees.common.Status.FAILURE


class IsDisengaging(py_trees.behaviour.Behaviour):
    """이탈 상태 감지: UNKNOWN BFM + ATA≥70° + closure<-50kts."""

    def __init__(self, name: str = "IsDisengaging",
                 ata_min: float = 70.0,
                 closure_max_kts: float = -50.0):
        super().__init__(name)
        self.ata_min = ata_min
        self.closure_max = closure_max_kts
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            ata = obs.get("ata_deg", 0.5) * 180.0
            closure = obs.get("closure_rate_kts", 0.0)
            bfm = str(obs.get("bfm_situation", ""))
            if ("UNKNOWN" in bfm and
                    ata >= self.ata_min and
                    closure < self.closure_max):
                return py_trees.common.Status.SUCCESS
            return py_trees.common.Status.FAILURE
        except Exception as e:
            logger.warning(f"IsDisengaging error: {e}")
            return py_trees.common.Status.FAILURE


class IsNearOffensive(py_trees.behaviour.Behaviour):
    """공격 직전 상태 감지: UNKNOWN BFM + ATA<45°."""

    def __init__(self, name: str = "IsNearOffensive", ata_max: float = 45.0):
        super().__init__(name)
        self.ata_max = ata_max
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            ata = obs.get("ata_deg", 0.5) * 180.0
            bfm = str(obs.get("bfm_situation", ""))
            if "UNKNOWN" in bfm and ata < self.ata_max:
                return py_trees.common.Status.SUCCESS
            return py_trees.common.Status.FAILURE
        except Exception as e:
            logger.warning(f"IsNearOffensive error: {e}")
            return py_trees.common.Status.FAILURE
