"""
에이전트 로컬 테스트 도구

사용법:
    python tools/test_agent.py my_agent
    python tools/test_agent.py my_agent --opponent ace --rounds 3
"""

import argparse
import os
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
# SDK 배포판(tools/): parent.parent = SDK 루트
# 개발 환경(sdk/tools/): parent.parent = sdk/, parent.parent.parent = 프로젝트 루트
_candidate = Path(__file__).parent.parent
if not (_candidate / "src").exists() and (_candidate.parent / "src").exists():
    project_root = _candidate.parent
else:
    project_root = _candidate
sys.path.insert(0, str(project_root))


def get_agent_path(name: str) -> Path:
    """에이전트 파일 경로 찾기
    
    탐색 순서:
        1. submissions/{name}/{name}.yaml
        2. examples/{name}.yaml
        3. 직접 경로
    """
    # 직접 경로인 경우 (플랫폼 독립적 처리)
    if os.sep in name or "/" in name or "\\" in name:
        direct_path = Path(name)
        if not direct_path.is_absolute():
            direct_path = project_root / name
        if direct_path.exists():
            return direct_path
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {name}")
    
    # submissions 폴더 확인
    submission_path = project_root / "submissions" / name / f"{name}.yaml"
    if submission_path.exists():
        return submission_path
    
    # examples 폴더 확인 (flat: examples/{name}.yaml)
    example_path = project_root / "examples" / f"{name}.yaml"
    if example_path.exists():
        return example_path
    
    # examples 폴더 확인 (sub-dir: examples/{name}/{name}.yaml)
    example_subdir_path = project_root / "examples" / name / f"{name}.yaml"
    if example_subdir_path.exists():
        return example_subdir_path
    
    raise FileNotFoundError(f"에이전트를 찾을 수 없습니다: {name}")


def main():
    parser = argparse.ArgumentParser(description="에이전트 로컬 테스트")
    parser.add_argument("agent", help="테스트할 에이전트 이름 또는 파일 경로")
    parser.add_argument("--opponent", default="simple", help="상대 에이전트")
    parser.add_argument("--rounds", type=int, default=1, help="테스트 라운드 수")
    parser.add_argument("--verbose", action="store_true", help="상세 출력")
    
    args = parser.parse_args()
    
    # 에이전트 파일 경로 확인
    try:
        agent_path = get_agent_path(args.agent)
        opponent_path = get_agent_path(args.opponent)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)
    
    print("🎮 에이전트 테스트 시작")
    print(f"   에이전트: {agent_path.stem}")
    print(f"   상대: {opponent_path.stem}")
    print(f"   라운드: {args.rounds}")
    print()
    
    # 매치 실행
    from src.match.runner import BehaviorTreeMatch
    
    wins = 0
    losses = 0
    
    for i in range(args.rounds):
        print(f"--- Round {i+1}/{args.rounds} ---")
        
        match = BehaviorTreeMatch(
            tree1_file=str(agent_path),
            tree2_file=str(opponent_path),
            config_name="1v1/NoWeapon/bt_vs_bt"
        )
        
        result = match.run(verbose=args.verbose)
        
        if result.winner == "tree1":
            wins += 1
            print("✅ 승리!")
        elif result.winner == "tree2":
            losses += 1
            print("❌ 패배")
        else:
            print("➖ 무승부")
        print()
    
    print("=" * 50)
    print(f"📊 결과: {wins}승 {losses}패 (승률: {wins/args.rounds*100:.1f}%)")


if __name__ == "__main__":
    main()
