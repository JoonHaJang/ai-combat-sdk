"""
eagle2 커스텀 조건 노드 — EIM(Enemy Intent Model) 기반

OnlineIntentTracker 예측을 BT 조건으로 노출.
runner.py가 매 스텝 shared_state를 업데이트하면 이 노드가 읽음.

사용 클래스:
  EnemyIntentIs        — 적 intent가 특정 클래스인지 확인
  EnemyIntentConfidence — 특정 intent 신뢰도가 임계값 이상인지 확인
  EnemyIntentNot        — 적 intent가 특정 클래스가 아닐 때 SUCCESS
"""

from src.intent.bt_nodes import EnemyIntentIs, EnemyIntentConfidence, EnemyIntentNot

__all__ = ["EnemyIntentIs", "EnemyIntentConfidence", "EnemyIntentNot"]
