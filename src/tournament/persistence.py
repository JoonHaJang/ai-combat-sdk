import json
import copy
import logging
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import asdict
from datetime import datetime

from .models import Team, Match, MatchResult, MatchPhase, MatchStatus

logger = logging.getLogger(__name__)

class TournamentPersistence:
    """토너먼트 데이터 영속성 관리 (JSON 파일 저장/로드)"""
    
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.teams_file = self.data_dir / "teams.json"
        self.matches_file = self.data_dir / "matches.json"
        
    def save_teams(self, teams: Dict[str, Team]):
        """팀 데이터 저장"""
        data = {tid: asdict(t) for tid, t in teams.items()}
        self._save_json(self.teams_file, data)
        
    def load_teams(self) -> Dict[str, Team]:
        """팀 데이터 로드"""
        data = self._load_json(self.teams_file, default={})
        teams = {}
        for tid, t_data in data.items():
            teams[tid] = Team(**t_data)
        return teams
        
    @staticmethod
    def _serialize_match(m: Match) -> dict:
        """Match 객체를 JSON 직렬화 가능한 dict로 변환"""
        return {
            'id': m.id,
            'team1_id': m.team1_id,
            'team2_id': m.team2_id,
            'phase': m.phase.value,
            'status': m.status.value,
            'result': asdict(m.result) if m.result else None,
            'created_at': m.created_at.isoformat() if m.created_at else None,
            'started_at': m.started_at.isoformat() if m.started_at else None,
            'completed_at': m.completed_at.isoformat() if m.completed_at else None,
        }

    def save_matches(self, matches: List[Match]):
        """매치 데이터 저장"""
        data = [self._serialize_match(m) for m in matches]
        self._save_json(self.matches_file, data)
        
    def load_matches(self) -> List[Match]:
        """매치 데이터 로드"""
        data = self._load_json(self.matches_file, default=[])
        if not isinstance(data, list):
            return []
            
        matches = []
        for m_data in data:
            # Enum 변환
            if 'phase' in m_data:
                m_data['phase'] = MatchPhase(m_data['phase'])
            if 'status' in m_data:
                m_data['status'] = MatchStatus(m_data['status'])
            
            # datetime 변환
            for date_field in ['created_at', 'started_at', 'completed_at']:
                if m_data.get(date_field):
                    m_data[date_field] = datetime.fromisoformat(m_data[date_field])
            
            # Result 변환
            if m_data.get('result'):
                result_data = m_data['result']
                if 'duration' in result_data and result_data['duration'] is not None:
                    result_data['duration'] = float(result_data['duration'])
                # json.dump의 default=str로 인해 float 값이 str로 저장될 수 있으므로 명시적 변환
                if 'scores' in result_data and isinstance(result_data['scores'], dict):
                    converted = {}
                    for k, v in result_data['scores'].items():
                        try:
                            converted[k] = float(v)
                        except (ValueError, TypeError):
                            converted[k] = v  # victory_condition 등 문자열 값 유지
                    result_data['scores'] = converted
                m_data['result'] = MatchResult(**result_data)
                
            matches.append(Match(**m_data))
        return matches

    def _save_json(self, path: Path, data: Any):
        """JSON 파일 쓰기"""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            
    def _load_json(self, path: Path, default: Any = None) -> Any:
        """JSON 파일 읽기
        
        Args:
            path: JSON 파일 경로
            default: 파일이 없거나 파싱 실패 시 반환할 기본값
        """
        if default is None:
            default = {}
        
        if not path.exists():
            return copy.deepcopy(default)
            
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패 ({path}): {e}. 기본값으로 복구합니다. 원본 파일을 확인하세요.")
            return copy.deepcopy(default)
