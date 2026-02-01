"""
AI Combat Match Runner - 행동트리 기반 매치 실행 스크립트

참가자는 행동트리(YAML)와 커스텀 노드(Python)를 제출하여 대전합니다.
"""

import sys
import argparse
import time
from datetime import datetime
from pathlib import Path

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.match.runner import BehaviorTreeMatch


def get_tree_path(name: str) -> str:
    """행동트리 파일 경로 결정
    
    Args:
        name: 에이전트 이름 또는 파일 경로
        
    Returns:
        str: 행동트리 파일 절대 경로
        
    탐색 순서:
        1. submissions/{name}/{name}.yaml
        2. examples/{name}.yaml
        3. 직접 경로 (절대 경로 또는 PROJECT_ROOT 기준 상대 경로)
    """
    # 경로 구분자가 포함된 경우 직접 경로로 처리
    if "/" in name or "\\" in name or Path(name).is_absolute():
        direct_path = Path(name)
        if not direct_path.is_absolute():
            direct_path = PROJECT_ROOT / name
        if direct_path.exists():
            return str(direct_path.resolve())
        raise FileNotFoundError(f"Behavior tree file not found: {name}")
    
    # 먼저 submissions 폴더 확인
    submission_path = PROJECT_ROOT / "submissions" / name / f"{name}.yaml"
    if submission_path.exists():
        return str(submission_path)
    
    # examples 폴더 확인
    example_path = PROJECT_ROOT / "examples" / f"{name}.yaml"
    if example_path.exists():
        return str(example_path)
    
    raise FileNotFoundError(f"Behavior tree file not found: {name}")


def run_match(
    agent1: str,
    agent2: str,
    rounds: int = 1,
    scenario: str = 'bt_vs_bt',
    max_steps: int = 1500,
    verbose: bool = True
) -> list:
    """두 행동트리 간 매치 실행
    
    Args:
        agent1: 첫 번째 에이전트 이름
        agent2: 두 번째 에이전트 이름
        rounds: 라운드 수 (기본값 1)
        scenario: 시나리오 이름 (기본값 'bt_vs_bt')
        max_steps: 최대 스텝 (기본값 1500 = 300초, dt=0.2)
        verbose: 상세 출력 여부
        
    Returns:
        list: 매치 결과 객체 리스트
    """
    print("\n" + "=" * 70)
    print("  AI Combat Match")
    print("=" * 70)
    print(f"\nAgent 1: {agent1}")
    print(f"Agent 2: {agent2}")
    print(f"Rounds: {rounds}")
    print(f"Scenario: {scenario}")
    print()

    try:
        tree1 = get_tree_path(agent1)
        tree2 = get_tree_path(agent2)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return []

    # 에이전트 이름 추출 (파일 경로에서 stem만 사용)
    agent1_name = Path(tree1).stem
    agent2_name = Path(tree2).stem

    config_name = f"1v1/NoWeapon/{scenario}"
    results = []
    
    for round_num in range(1, rounds + 1):
        if rounds > 1:
            print(f"\n{'='*70}")
            print(f"  Round {round_num}/{rounds}")
            print(f"{'='*70}\n")
        
        start_time = time.time()
        
        replay_dir = PROJECT_ROOT / "replays"
        replay_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        replay_path = replay_dir / f"{timestamp}_{agent1_name}_vs_{agent2_name}.acmi"

        match = BehaviorTreeMatch(
            tree1_file=tree1,
            tree2_file=tree2,
            config_name=config_name,
            max_steps=max_steps,
            tree1_name=agent1_name,
            tree2_name=agent2_name,
        )

        print(f"{agent1_name} vs {agent2_name}")
        
        try:
            result = match.run(replay_path=str(replay_path), verbose=verbose)
        except Exception as e:
            print(f"❌ 매치 실행 실패: {e}")
            continue

        # 호환성 있는 속성 이름 사용
        steps = getattr(result, 'steps', getattr(result, 'total_steps', 'N/A'))
        elapsed_time = getattr(result, 'elapsed_time', getattr(result, 'duration_seconds', 'N/A'))
        tree1_reward = getattr(result, 'tree1_reward', 0.0)
        tree2_reward = getattr(result, 'tree2_reward', 0.0)
        winner = getattr(result, 'winner', 'unknown')

        print(f"  리플레이: {replay_path.name}")

        # 표준화된 결과 객체 (딕셔너리 사용으로 클래스 중복 제거)
        match_result = {
            'winner': winner,
            'total_steps': steps if steps != 'N/A' else 0,
            'duration_seconds': elapsed_time if elapsed_time != 'N/A' else 0,
            'tree1_reward': tree1_reward,
            'tree2_reward': tree2_reward,
            'success': True,
        }
        results.append(match_result)
        
        elapsed = time.time() - start_time
        print(f"\nRound {round_num} 완료 (소요 시간: {elapsed:.2f}초)")
    
    # 전체 결과 요약
    if rounds > 1 and results:
        print("\n" + "=" * 70)
        print("  전체 결과 요약")
        print("=" * 70)
        
        agent1_wins = sum(1 for r in results if r['winner'] == "tree1")
        agent2_wins = sum(1 for r in results if r['winner'] == "tree2")
        draws = sum(1 for r in results if r['winner'] == "draw")
        
        print(f"\n{agent1}: {agent1_wins}승")
        print(f"{agent2}: {agent2_wins}승")
        print(f"무승부: {draws}")
        
        if agent1_wins > agent2_wins:
            print(f"\n🏆 승자: {agent1}")
        elif agent2_wins > agent1_wins:
            print(f"\n🏆 승자: {agent2}")
        else:
            print("\n🤝 무승부")
    
    print("\n" + "=" * 70)
    print("🎉 매치 완료!")
    print("=" * 70 + "\n")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="AI Combat Match Runner - 행동트리 기반 매치 실행",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python run_match.py --agent1 ace_fighter --agent2 simple_fighter
  python run_match.py --agent1 sample_behavior_tree --agent2 aggressive_fighter --rounds 3
  python run_match.py --agent1 my_submission --agent2 ace_fighter --scenario tail_chase
        """
    )
    
    parser.add_argument('--agent1', type=str, required=True, help='Agent 1 이름 (submissions/ 또는 examples/ 폴더)')
    parser.add_argument('--agent2', type=str, required=True, help='Agent 2 이름')
    parser.add_argument('--rounds', type=int, default=1, help='라운드 수 (기본값: 1)')
    parser.add_argument('--scenario', type=str, default='bt_vs_bt', 
                        choices=['bt_vs_bt', 'tail_chase'], help='시나리오 (기본값: bt_vs_bt)')
    parser.add_argument('--max-steps', type=int, default=1500, help='최대 스텝 수 (기본값: 1500)')
    parser.add_argument('--quiet', action='store_true', help='상세 출력 비활성화')
    
    args = parser.parse_args()
    
    run_match(
        agent1=args.agent1,
        agent2=args.agent2,
        rounds=args.rounds,
        scenario=args.scenario,
        max_steps=args.max_steps,
        verbose=not args.quiet
    )


if __name__ == "__main__":
    main()
