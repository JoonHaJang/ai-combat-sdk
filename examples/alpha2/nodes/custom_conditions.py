"""
Alpha2 커스텀 조건 노드 — Phase 2 (분석기 기반)

데이터 근거: tools/analyze_metadata.py 출력
  - UNKNOWN BFM 세분화 (13.5.11)
  - TIR: Scissors에서 Accelerate→OBFM 51.6% (13.5.13)
"""

import logging
import py_trees

logger = logging.getLogger(__name__)


class IsScissors(py_trees.behaviour.Behaviour):
    """Scissors 교착 상태 감지.

    데이터 근거 (13.5.11):
      UNKNOWN의 43%, ATA 45~70°, closure < 0, AA < 70°
      양측 측면에서 서로 이탈 중인 선회 교착.

    TIR 근거 (13.5.13):
      이 상태에서 LeadPursuit→OBFM 20.8% vs Accelerate→OBFM 51.6%
      → 현재 기본 행동(LeadPursuit)이 비효율적인 구간.
    """

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
    """이탈 상태 감지.

    데이터 근거 (13.5.11):
      UNKNOWN의 36%, ATA > 70°, closure < -100kts
      적이 측후방이면서 빠르게 멀어지는 중.

    SAE 근거 (13.5.13):
      HighYoYo SAE +0.016 (유일한 양수), LeadPursuit SAE -0.034 (최하)
    """

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
    """공격 직전 상태 감지.

    데이터 근거 (13.5.11):
      UNKNOWN의 15%, ATA < 45°, 거리 ~1344ft
      OBFM 진입 직전이지만 에너지 등 조건 미충족.

    TIR 근거 (13.5.13):
      Near-Offensive에서 LeadPursuit→OBFM 13.7%, HighYoYo→OBFM 14.3%
    """

    def __init__(self, name: str = "IsNearOffensive",
                 ata_max: float = 45.0):
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
