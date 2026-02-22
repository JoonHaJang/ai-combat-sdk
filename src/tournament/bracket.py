import logging
from typing import List
from itertools import combinations
from .models import Team, Match, MatchPhase

logger = logging.getLogger(__name__)

class BracketGenerator:
    """대진표 생성기"""
    
    @staticmethod
    def generate_round_robin(teams: List[Team], phase: MatchPhase = MatchPhase.QUALIFICATION) -> List[Match]:
        """리그전 (Round Robin) 대진표 생성"""
        matches = []
        team_ids = [t.id for t in teams]
        
        # 모든 가능한 조합 생성 (순서 무관, 중복 없음)
        pairs = list(combinations(team_ids, 2))
        
        for i, (t1, t2) in enumerate(pairs):
            match_id = f"{phase.value}_{t1}_vs_{t2}_{i+1}"
            matches.append(Match(
                id=match_id,
                team1_id=t1,
                team2_id=t2,
                phase=phase
            ))
            
        return matches

    @staticmethod
    def generate_single_elimination(teams: List[Team], phase: MatchPhase = MatchPhase.SEMIFINALS) -> List[Match]:
        """싱글 엘리미네이션 (토너먼트) 대진표 생성"""
        # 팀 수는 2의 제곱수여야 이상적임 (4, 8, 16...)
        # 현재는 간단하게 순서대로 매칭
        
        matches = []
        n_teams = len(teams)
        
        if n_teams < 2:
            return []

        if n_teams % 2 != 0:
            logger.warning(
                f"홀수 팀({n_teams}팀)으로 싱글 엘리미네이션 대진표를 생성합니다. "
                f"마지막 팀 '{teams[-1].id}'은(는) 부전승 처리 없이 제외됩니다."
            )
            
        # 시드 배정 로직은 추후 고도화 (현재는 리스트 순서대로 1vs2, 3vs4...)
        for i in range(0, n_teams, 2):
            if i + 1 < n_teams:
                match_id = f"{phase.value}_{teams[i].id}_vs_{teams[i+1].id}_{i//2 + 1}"
                matches.append(Match(
                    id=match_id,
                    team1_id=teams[i].id,
                    team2_id=teams[i+1].id,
                    phase=phase
                ))
                
        return matches
