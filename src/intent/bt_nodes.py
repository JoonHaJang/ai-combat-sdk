"""
bt_nodes.py — Intent 기반 BT 조건 노드

OnlineIntentTracker 예측 결과를 BT 조건으로 노출.
runner.py가 shared_state를 매 스텝 업데이트하면 이 노드가 읽음.

사용 예 (YAML):
  - type: Condition
    name: EnemyIntentIs
    params:
      intent: GUN_ATTACK
      min_confidence: 0.4

  - type: Condition
    name: EnemyIntentConfidence
    params:
      intent: GUN_ATTACK
      threshold: 0.6
"""

import logging
import py_trees

from . import shared_state

logger = logging.getLogger(__name__)


class EnemyIntentIs(py_trees.behaviour.Behaviour):
    """
    적의 현재 intent가 지정 클래스와 일치하는지 확인.

    params:
        intent (str): 확인할 intent 클래스
                      GUN_ATTACK / PURSUIT / DEFENSIVE / ENERGY /
                      NEUTRAL_CIRCLE / NEUTRAL_SCISSORS
        min_confidence (float): 최소 신뢰도 (기본 0.35)
    """

    def __init__(
        self,
        name: str = "EnemyIntentIs",
        intent: str = "GUN_ATTACK",
        min_confidence: float = 0.35,
    ):
        super().__init__(name)
        self.intent = intent
        self.min_confidence = min_confidence
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key="observation", access=py_trees.common.Access.READ
        )

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            ego_id = str(obs.get("agent_id", ""))
            pred_intent, conf = shared_state.get_enemy_intent(ego_id)

            if pred_intent == self.intent:
                c = conf.get(self.intent, 0.0) if conf else 0.0
                if c >= self.min_confidence:
                    return py_trees.common.Status.SUCCESS
            return py_trees.common.Status.FAILURE
        except Exception as e:
            logger.debug(f"EnemyIntentIs error: {e}")
            return py_trees.common.Status.FAILURE


class EnemyIntentConfidence(py_trees.behaviour.Behaviour):
    """
    적의 특정 intent 신뢰도가 임계값 이상인지 확인.
    현재 예측된 intent와 무관하게 특정 클래스의 원시 신뢰도 사용.

    params:
        intent (str): 신뢰도를 확인할 intent 클래스
        threshold (float): 신뢰도 임계값 (기본 0.5)
    """

    def __init__(
        self,
        name: str = "EnemyIntentConfidence",
        intent: str = "GUN_ATTACK",
        threshold: float = 0.5,
    ):
        super().__init__(name)
        self.intent = intent
        self.threshold = threshold
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key="observation", access=py_trees.common.Access.READ
        )

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            ego_id = str(obs.get("agent_id", ""))
            _, conf = shared_state.get_enemy_intent(ego_id)
            c = conf.get(self.intent, 0.0) if conf else 0.0
            if c >= self.threshold:
                return py_trees.common.Status.SUCCESS
            return py_trees.common.Status.FAILURE
        except Exception as e:
            logger.debug(f"EnemyIntentConfidence error: {e}")
            return py_trees.common.Status.FAILURE


class EnemyIntentNot(py_trees.behaviour.Behaviour):
    """
    적의 intent가 특정 클래스가 아닐 때 SUCCESS.
    안전한 공격 기회 포착용.

    params:
        intent (str): 아니어야 할 intent 클래스 (기본 DEFENSIVE)
        min_confidence (float): 신뢰도 임계값
    """

    def __init__(
        self,
        name: str = "EnemyIntentNot",
        intent: str = "DEFENSIVE",
        min_confidence: float = 0.35,
    ):
        super().__init__(name)
        self.intent = intent
        self.min_confidence = min_confidence
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key="observation", access=py_trees.common.Access.READ
        )

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            ego_id = str(obs.get("agent_id", ""))
            pred_intent, conf = shared_state.get_enemy_intent(ego_id)

            if pred_intent == "UNKNOWN":
                return py_trees.common.Status.SUCCESS  # 모름 → 공격 허용

            c = conf.get(self.intent, 0.0) if conf else 0.0
            if pred_intent != self.intent or c < self.min_confidence:
                return py_trees.common.Status.SUCCESS
            return py_trees.common.Status.FAILURE
        except Exception as e:
            logger.debug(f"EnemyIntentNot error: {e}")
            return py_trees.common.Status.SUCCESS  # 오류 시 공격 허용
