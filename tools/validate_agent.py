"""
에이전트 제출 전 검증 도구

사용법:
    python tools/validate_agent.py my_agent.yaml
    python tools/validate_agent.py examples/my_agent.yaml
"""

import argparse
import sys
from pathlib import Path
import yaml

# 프로젝트 루트를 path에 추가
# SDK 배포판(tools/): parent.parent = SDK 루트
# 개발 환경(sdk/tools/): parent.parent = sdk/, parent.parent.parent = 프로젝트 루트
_candidate = Path(__file__).parent.parent
if not (_candidate / "src").exists() and (_candidate.parent / "src").exists():
    project_root = _candidate.parent
else:
    project_root = _candidate
sys.path.insert(0, str(project_root))

from src.submission.validator import SubmissionValidator

def main():
    parser = argparse.ArgumentParser(description="에이전트 YAML 검증")
    parser.add_argument("agent", help="검증할 에이전트 YAML 파일")
    
    args = parser.parse_args()
    
    # 파일 경로 처리
    agent_path = Path(args.agent)
    if not agent_path.exists():
        # examples 폴더에서 찾기 시도
        possible_path = project_root / "examples" / args.agent
        possible_path_with_yaml = possible_path.with_suffix(".yaml")
        if possible_path.exists():
            agent_path = possible_path
        elif possible_path_with_yaml.exists():
            agent_path = possible_path_with_yaml
    
    if not agent_path.exists():
        # submissions 폴더에서 찾기 시도
        possible_path = project_root / "submissions" / args.agent / f"{args.agent}.yaml"
        if possible_path.exists():
            agent_path = possible_path
    
    if not agent_path.exists():
        print(f"❌ 에이전트 파일을 찾을 수 없습니다: {args.agent}")
        print("   시도한 경로:")
        print(f"   - {Path(args.agent).resolve()}")
        print(f"   - {project_root / 'examples' / args.agent}")
        print(f"   - {(project_root / 'examples' / args.agent).with_suffix('.yaml')}")
        print(f"   - {project_root / 'submissions' / args.agent / (args.agent + '.yaml')}")
        sys.exit(1)
    
    print(f"🔍 에이전트 검증: {agent_path.name}")
    print(f"   경로: {agent_path}")
    print()
    
    # YAML을 한 번만 파싱하여 검증과 stats 출력에 모두 재활용
    try:
        with open(agent_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"❌ YAML 파싱 오류: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 파일 읽기 오류: {e}")
        sys.exit(1)

    validator = SubmissionValidator()
    custom_nodes = validator._load_custom_nodes(agent_path.parent)
    result = validator.validate_data(data, custom_nodes)
    
    if result.warnings:
        for w in result.warnings:
            print(w)
        print()
    
    if result.success:
        print("✅ 검증 통과! 제출 가능합니다.")
        
        # 통계 출력 (선택 사항)
        try:
            has_root = "root" in data and data.get("root") is not None
            has_tree = "tree" in data and data.get("tree") is not None
            root = data.get("root") if has_root else (data.get("tree") if has_tree else None)
            if root is not None:
                stats = validator.get_stats(root)
                print(f"   - 노드 수: {stats['node_count']}")
                print(f"   - 깊이: {stats['depth']}")
        except Exception:
            pass
            
    else:
        print("❌ 검증 실패:")
        for error in result.errors:
            print(f"   - {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
