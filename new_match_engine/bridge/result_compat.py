"""legacy 결과 호환 — new_engine MatchResult → SDK(`src/match/result.py`·runner) 형태.

근거(계약): `src/match/result.py`(MatchResult 필드), `src/match/runner.py:222·284`
  (`.health1`·`.health2` side-channel 이 `.current_health`·`.total_damage_dealt` 노출).
  `scripts/run_match.py:230` (`.winner`·`.steps`/`.total_steps`·`.elapsed_time`/`.duration_seconds`).
"""
from __future__ import annotations
from dataclasses import dataclass

# new_engine winner("agent1"/"agent2"/"draw") → legacy("tree1"/"tree2"/"draw")
_WINNER_MAP = {"agent1": "tree1", "agent2": "tree2", "draw": "draw"}


@dataclass
class HealthCompat:
    """legacy HealthGauge 호환 (runner.py 가 읽는 속성명)."""
    current_health: float
    total_damage_dealt: float
    total_damage_taken: float = 0.0


class LegacyMatchResult:
    """SDK 소비자가 기대하는 결과 객체 (result.py + runner side-channel 통합)."""

    def __init__(self, tree1_file, tree2_file, new_res,
                 replay_file=None, timestamp=""):
        self.tree1_file = tree1_file
        self.tree2_file = tree2_file
        self.winner = _WINNER_MAP.get(new_res.winner, new_res.winner)
        self.total_steps = new_res.steps
        self.duration_seconds = new_res.time_s
        # D1: new_engine 은 학습 reward 미산출 → damage_dealt 로 대용 (계획서 §6-D1)
        self.tree1_reward = new_res.damage_dealt1
        self.tree2_reward = new_res.damage_dealt2
        self.replay_file = replay_file
        self.timestamp = timestamp
        # 부가 정보 (new_engine 고유 — 진단용)
        self.condition = getattr(new_res.condition, "value", str(new_res.condition))
        self.health1_val = new_res.health1
        self.health2_val = new_res.health2

    # ── 별칭 (scripts/run_match.py:230 getattr 호환) ──
    @property
    def steps(self):
        return self.total_steps

    @property
    def elapsed_time(self):
        return self.duration_seconds

    def to_dict(self):
        return {
            "tree1_file": self.tree1_file, "tree2_file": self.tree2_file,
            "winner": self.winner, "total_steps": self.total_steps,
            "tree1_reward": self.tree1_reward, "tree2_reward": self.tree2_reward,
            "replay_file": self.replay_file, "duration_seconds": self.duration_seconds,
            "timestamp": self.timestamp,
            "condition": self.condition,
            "health1": self.health1_val, "health2": self.health2_val,
        }

    def __repr__(self):
        return (f"LegacyMatchResult(winner={self.winner!r}, steps={self.total_steps}, "
                f"H1={self.health1_val:.1f}, H2={self.health2_val:.1f}, "
                f"cond={self.condition})")
