"""new_match_engine.bridge — legacy SDK core 드롭인(백엔드=new_engine).

사용 (호출부 import 한 줄 교체):
    # 기존:  from src.match.runner import BehaviorTreeMatch
    from new_match_engine.bridge import BehaviorTreeMatch
    m = BehaviorTreeMatch("aggressive.yaml", "ace.yaml", controller="lqr")
    res = m.run(replay_path="x.acmi")
    print(res.winner, res.health1.current_health, res.health2.current_health)

계획: docs/NEW_ENGINE_CORE_REPLACEMENT_PLAN.md
"""
from .core_adapter import BehaviorTreeMatch
from .result_compat import LegacyMatchResult, HealthCompat

__all__ = ["BehaviorTreeMatch", "LegacyMatchResult", "HealthCompat"]
