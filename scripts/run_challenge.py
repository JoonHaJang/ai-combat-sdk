"""
챌린지 매치 실행 스크립트

행동트리 또는 정책 에이전트 간의 대결을 실행합니다.
"""

import sys
import argparse
from pathlib import Path
import time

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.test_match import run_match


def main():
    parser = argparse.ArgumentParser(description="AI Combat Challenge Match")
    parser.add_argument("--agent1", type=str, required=True, help="Agent 1 파일 경로 (.yaml 또는 .py)")
    parser.add_argument("--agent2", type=str, required=True, help="Agent 2 파일 경로 (.yaml 또는 .py)")
    parser.add_argument("--agent1_type", type=str, default="bt", choices=["bt", "policy"], 
                        help="Agent 1 타입 (bt=행동트리, policy=정책)")
    parser.add_argument("--agent2_type", type=str, default="bt", choices=["bt", "policy"],
                        help="Agent 2 타입 (bt=행동트리, policy=정책)")
    parser.add_argument("--config", type=str, default="1v1/NoWeapon/bt_vs_bt",
                        help="환경 설정")
    parser.add_argument("--save_acmi", action="store_true", help="ACMI 파일 저장")
    parser.add_argument("--rounds", type=int, default=1, help="라운드 수")
    
    args = parser.parse_args()
    
    # 파일 경로 처리
    agent1_path = Path(args.agent1)
    agent2_path = Path(args.agent2)
    
    # .yaml 확장자 제거 (run_match는 확장자 없이 받음)
    if agent1_path.suffix == ".yaml":
        agent1_name = agent1_path.stem
    else:
        agent1_name = str(agent1_path)
    
    if agent2_path.suffix == ".yaml":
        agent2_name = agent2_path.stem
    else:
        agent2_name = str(agent2_path)
    
    print("\n" + "="*70)
    print("  AI Combat Challenge Match")
    print("="*70)
    print(f"\nAgent 1: {agent1_name} ({args.agent1_type})")
    print(f"Agent 2: {agent2_name} ({args.agent2_type})")
    print(f"Config: {args.config}")
    print(f"Rounds: {args.rounds}")
    print()
    
    # 정책 타입 지원은 향후 구현
    if args.agent1_type == "policy" or args.agent2_type == "policy":
        print("⚠️  정책 타입은 아직 지원되지 않습니다. 행동트리만 사용 가능합니다.")
        print("향후 업데이트에서 지원 예정입니다.")
        return
    
    # 다중 라운드 실행
    results = []
    for round_num in range(1, args.rounds + 1):
        if args.rounds > 1:
            print(f"\n{'='*70}")
            print(f"  Round {round_num}/{args.rounds}")
            print(f"{'='*70}\n")
        
        start_time = time.time()
        
        try:
            # 매치 실행
            result = run_match(agent1_name, agent2_name, f"{agent1_name} vs {agent2_name}")
            results.append(result)
            
        except Exception as e:
            print(f"❌ 매치 실행 실패: {e}")
            import traceback
            traceback.print_exc()
            continue
        
        elapsed = time.time() - start_time
        print(f"\nRound {round_num} 완료 (소요 시간: {elapsed:.2f}초)")
    
    # 전체 결과 요약
    if args.rounds > 1:
        print("\n" + "="*70)
        print("  전체 결과 요약")
        print("="*70)
        
        agent1_wins = sum(1 for r in results if r and r.get("winner") == "tree1")
        agent2_wins = sum(1 for r in results if r and r.get("winner") == "tree2")
        draws = sum(1 for r in results if r and r.get("winner") == "draw")
        
        print(f"\n{agent1_name}: {agent1_wins}승")
        print(f"{agent2_name}: {agent2_wins}승")
        print(f"무승부: {draws}")
        
        if agent1_wins > agent2_wins:
            print(f"\n🏆 승자: {agent1_name}")
        elif agent2_wins > agent1_wins:
            print(f"\n🏆 승자: {agent2_name}")
        else:
            print(f"\n🤝 무승부")
    
    print("\n" + "="*70)
    print("🎉 챌린지 완료!")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
