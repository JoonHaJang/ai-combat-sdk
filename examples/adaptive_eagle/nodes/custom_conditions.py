"""
Adaptive Eagle 커스텀 조건 노드 — Phase 4 (dead code 정리 완료)

EIM 노드 재수출:
  EnemyIntentIs — BT에서 적 의도 매칭에 사용

커스텀 조건:
  IsDefensiveGeometry — 방어적 기하학 감지
  CustomOrbitDetector — Circular orbit lock 감지 (BUG-4 수정: 이름 변경)
"""

# EIM 노드 재수출 — BT 로더가 이 패키지에서 탐색
from src.intent.bt_nodes import EnemyIntentIs

import logging
import py_trees

logger = logging.getLogger(__name__)


class IsDefensiveGeometry(py_trees.behaviour.Behaviour):
    """방어적 기하학 감지 (우리가 적 전방 노출).

    LAG 기준: AO>90° + TA<60°
    이 상태 = 우리가 적에게 등을 보이는 중, 위협 최대.
    ExtensionBreak로 이탈.
    """

    def __init__(self, name: str = "IsDefensiveGeometry",
                 ao_min_deg: float = 90.0,
                 ta_max_deg: float = 70.0):
        super().__init__(name)
        self.ao_min = ao_min_deg
        self.ta_max = ta_max_deg
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            ao = obs.get("ata_deg", 0.5) * 180.0
            ta = obs.get("aa_deg", 0.5) * 180.0

            if ao > self.ao_min and ta < self.ta_max:
                return py_trees.common.Status.SUCCESS
            return py_trees.common.Status.FAILURE
        except Exception as e:
            logger.warning(f"IsDefensiveGeometry error: {e}")
            return py_trees.common.Status.FAILURE


class CustomOrbitDetector(py_trees.behaviour.Behaviour):
    """Circular orbit lock (limit cycle) 감지.
    [BUG-4 수정] IsCircularOrbit → CustomOrbitDetector로 이름 변경.
    pyd 빌트인 IsCircularOrbit과 동명 충돌로 Python 버전이 무시되던 문제 해결.

    감지 조건:
      ata_threshold_min ≤ ATA ≤ ata_threshold_max  (NEUTRAL 구역)
      |closure_rate_kts| < closure_abs_max          (접근도 이탈도 아님)
      distance_ft > dist_min_ft                     (사격거리 밖)

    해법: Accelerate 또는 HeadOnBreak → 선회 반경 차이로 limit cycle 탈출.
    """

    def __init__(
        self,
        name: str = "CustomOrbitDetector",
        ata_min_deg: float = 35.0,
        ata_max_deg: float = 85.0,
        closure_abs_max_kts: float = 30.0,
        dist_min_ft: float = 2000.0,
    ):
        super().__init__(name)
        self.ata_min = ata_min_deg
        self.ata_max = ata_max_deg
        self.closure_abs_max = closure_abs_max_kts
        self.dist_min = dist_min_ft
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key="observation", access=py_trees.common.Access.READ
        )

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            ata = obs.get("ata_deg", 0.5) * 180.0
            closure = obs.get("closure_rate_kts", 999.0)
            dist = obs.get("distance_ft", 0.0)

            if (self.ata_min <= ata <= self.ata_max
                    and abs(closure) < self.closure_abs_max
                    and dist > self.dist_min):
                return py_trees.common.Status.SUCCESS
            return py_trees.common.Status.FAILURE
        except Exception as e:
            logger.debug(f"CustomOrbitDetector error: {e}")
            return py_trees.common.Status.FAILURE
