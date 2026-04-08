"""
shared_state.py — runner ↔ BT 노드 간 Intent 공유 상태

OnlineIntentTracker의 예측 결과를 전역 딕셔너리로 공유.
BT 커스텀 조건 노드가 py_trees 블랙보드 수정 없이 읽을 수 있음.
"""

from typing import Optional

# agent_id → (intent: str, conf: dict[str, float])
_INTENT_STATE: dict[str, tuple[str, dict]] = {}

# agent_id 쌍 (매치 시작 시 등록)
_AGENT_PAIR: dict[str, str] = {}  # ego_id → enm_id


def register_agents(agent1_id: str, agent2_id: str):
    """매치 시작 시 양측 agent_id 쌍 등록."""
    _AGENT_PAIR[agent1_id] = agent2_id
    _AGENT_PAIR[agent2_id] = agent1_id


def set_intent(agent_id: str, intent: str, conf: dict):
    """agent_id의 예측 intent 저장."""
    _INTENT_STATE[agent_id] = (intent, conf)


def get_enemy_intent(ego_id: str) -> tuple[str, dict]:
    """
    ego_id의 적 의도 반환.
    등록된 쌍이 없으면 다른 모든 agent 중 첫 번째 반환.
    """
    enm_id = _AGENT_PAIR.get(ego_id)
    if enm_id and enm_id in _INTENT_STATE:
        return _INTENT_STATE[enm_id]
    # fallback: 등록 쌍 없을 때 다른 에이전트 검색
    for aid, val in _INTENT_STATE.items():
        if aid != ego_id:
            return val
    return ("UNKNOWN", {})


def get_intent(agent_id: str) -> tuple[str, dict]:
    """agent_id 자신의 intent (디버그용)."""
    return _INTENT_STATE.get(agent_id, ("UNKNOWN", {}))


def clear():
    """매치 종료 시 상태 초기화."""
    _INTENT_STATE.clear()
    _AGENT_PAIR.clear()
