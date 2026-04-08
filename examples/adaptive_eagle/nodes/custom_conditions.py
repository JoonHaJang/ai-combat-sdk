"""
Adaptive Eagle 커스텀 조건 노드 — Phase 3 (v2)

실측 데이터 기반 재설계:
  eagle2 vs eagle1 교착 = circular orbit lock (ATA~50°, dist~4000ft, closure≈0)
  head-on(ATA<30°)은 500스텝 중 한 번도 발생 안 함 — 이전 가설 폐기

핵심 조건:
  IsCircularOrbit : NEUTRAL 구역에서 closure≈0 → limit cycle 감지

EIM 노드 재수출 (eagle2와 동일):
  EnemyIntentIs, EnemyIntentConfidence, EnemyIntentNot
"""

# EIM 노드 재수출 — BT 로더가 이 패키지에서 탐색
from src.intent.bt_nodes import EnemyIntentIs, EnemyIntentConfidence, EnemyIntentNot

import math
import logging
import py_trees

logger = logging.getLogger(__name__)


class IsHeadOn(py_trees.behaviour.Behaviour):
    """Head-on 교착 상황 감지.

    LAG 기준: AO<30° + TA<60°
    우리 obs 매핑: ata_deg(×180) = AO, aa_deg(×180) = TA

    이 상태 = 양측이 정면을 향해 접근 중.
    표준 LeadPursuit은 이 기하학을 깨지 못함 → HeadOnBreak 필요.
    """

    def __init__(self, name: str = "IsHeadOn",
                 ao_max_deg: float = 30.0,
                 ta_max_deg: float = 60.0,
                 dist_max_ft: float = 15000.0):
        super().__init__(name)
        self.ao_max = ao_max_deg
        self.ta_max = ta_max_deg
        self.dist_max = dist_max_ft
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            ao = obs.get("ata_deg", 0.5) * 180.0   # AO = 우리 조준각
            ta = obs.get("aa_deg", 0.5) * 180.0     # TA = 적 aspect angle
            dist = obs.get("distance_ft", 99999.0)

            if ao < self.ao_max and ta < self.ta_max and dist < self.dist_max:
                return py_trees.common.Status.SUCCESS
            return py_trees.common.Status.FAILURE
        except Exception as e:
            logger.warning(f"IsHeadOn error: {e}")
            return py_trees.common.Status.FAILURE


class IsOffensivePrime(py_trees.behaviour.Behaviour):
    """공격 최적 상황 감지 (적 후방).

    LAG 기준: AO<30° + TA>120°
    완화 기준: AO<45° + TA>100° (더 넓은 공격 기회 허용)

    이 상태 = 우리가 적 후방에 위치, 공격 기회 최대.
    RLInspiredAttack으로 하강 공격 기동.
    """

    def __init__(self, name: str = "IsOffensivePrime",
                 ao_max_deg: float = 45.0,
                 ta_min_deg: float = 100.0):
        super().__init__(name)
        self.ao_max = ao_max_deg
        self.ta_min = ta_min_deg
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            ao = obs.get("ata_deg", 0.5) * 180.0
            ta = obs.get("aa_deg", 0.5) * 180.0

            if ao < self.ao_max and ta > self.ta_min:
                return py_trees.common.Status.SUCCESS
            return py_trees.common.Status.FAILURE
        except Exception as e:
            logger.warning(f"IsOffensivePrime error: {e}")
            return py_trees.common.Status.FAILURE


class IsDefensiveGeometry(py_trees.behaviour.Behaviour):
    """방어적 기하학 감지 (우리가 적 전방 노출).

    LAG 기준: AO>90° + TA<60°
    이 상태 = 우리가 적에게 등을 보이는 중, 위협 최대.
    RLInspiredDefense: alt 유지 + 최고속으로 에너지 보존.
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


class IsStrategy(py_trees.behaviour.Behaviour):
    """SelectStrategy가 쓴 selected_strategy 값과 비교.

    SelectStrategy 노드가 blackboard.selected_strategy 를 설정하면,
    이 노드가 target 전략과 일치하는지 확인.

    params:
        strategy (str): HARD_DECK / SHOOT / DIVE_BREAK /
                        PRESS_ATTACK / TURN_FIGHT / ENERGY_ESCAPE / REPOSITION
    """

    def __init__(self, name: str = "IsStrategy", strategy: str = "TURN_FIGHT"):
        super().__init__(name)
        self.strategy = strategy
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="selected_strategy", access=py_trees.common.Access.READ)

    def update(self) -> py_trees.common.Status:
        try:
            s = self.blackboard.selected_strategy
            if s == self.strategy:
                return py_trees.common.Status.SUCCESS
            return py_trees.common.Status.FAILURE
        except Exception as e:
            logger.debug(f"IsStrategy error: {e}")
            return py_trees.common.Status.FAILURE


class IsCircularOrbit(py_trees.behaviour.Behaviour):
    """
    Circular orbit lock (limit cycle) 감지.

    실측 근거 (eagle2 vs eagle1, 500스텝):
      - ATA 평균 57.9°, WEZ 진입 0회
      - closure_rate 평균 -5 kts (접근/이탈 교차, 실질적 궤도)
      - 이 상태가 500스텝 내내 지속 = LeadPursuit limit cycle

    감지 조건:
      ata_threshold_min ≤ ATA ≤ ata_threshold_max  (NEUTRAL 구역)
      |closure_rate_kts| < closure_abs_max          (접근도 이탈도 아님)
      distance_ft > dist_min_ft                     (사격거리 밖)

    이 조건 = 두 LeadPursuit가 같은 선회율로 공전 중.
    해법 (LAG OFFENSIVE_DIVE): Accelerate → 선회 반경 차이로 limit cycle 탈출.
    """

    def __init__(
        self,
        name: str = "IsCircularOrbit",
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
            logger.debug(f"IsCircularOrbit error: {e}")
            return py_trees.common.Status.FAILURE
