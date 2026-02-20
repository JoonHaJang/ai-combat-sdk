from pathlib import Path
from typing import Optional
import shutil
import tempfile
import os
import atexit

from .validator import SubmissionValidator

class SubmissionRunner:
    """에이전트 제출 및 실행 관리 (보안/샌드박스 고려)"""
    
    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root)
        self.validator = SubmissionValidator()
        self.temp_dir = tempfile.mkdtemp(prefix="ai_combat_runner_")
        self._temp_dirs = {self.temp_dir}
        atexit.register(self._atexit_cleanup)

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

    def _ensure_temp_dir(self):
        """임시 디렉토리가 없으면 새로 생성"""
        if not self.temp_dir or not os.path.exists(self.temp_dir):
            self.temp_dir = tempfile.mkdtemp(prefix="ai_combat_runner_")
            self._temp_dirs.add(self.temp_dir)

    def prepare_agent(self, submission_path: str, agent_id: str) -> Optional[str]:
        """제출된 에이전트 파일을 실행 가능한 상태로 준비 (검증 포함)"""
        path = Path(submission_path)
        
        if not path.exists():
            print(f"❌ 제출 파일을 찾을 수 없음: {submission_path}")
            return None
            
        # 1. 유효성 검증
        result = self.validator.validate(str(path))
        if not result.success:
            print(f"❌ 에이전트 검증 실패 ({agent_id}):")
            for error in result.errors:
                print(f"   - {error}")
            return None
            
        # 2. 임시 디렉토리로 복사 (격리 실행 준비)
        # cleanup() 후 재호출 시에도 안전하게 동작하도록 디렉토리 재생성
        self._ensure_temp_dir()
        agent_dir = Path(self.temp_dir) / agent_id
        agent_dir.mkdir(exist_ok=True)
        
        dest_path = agent_dir / path.name
        shutil.copy2(path, dest_path)
        
        # nodes/ 폴더가 있으면 함께 복사 (커스텀 노드 지원)
        nodes_src = path.parent / "nodes"
        if nodes_src.exists():
            nodes_dst = agent_dir / "nodes"
            if nodes_dst.exists():
                shutil.rmtree(nodes_dst)
            shutil.copytree(nodes_src, nodes_dst)
        
        return str(dest_path)

    def cleanup(self):
        """리소스 정리. 다음 prepare_agent 호출 시 디렉토리가 새로 생성됨."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        self.temp_dir = None

    def _atexit_cleanup(self):
        """프로세스 종료 시 생성했던 임시 디렉토리를 모두 정리."""
        for temp_dir in list(self._temp_dirs):
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
