"""
에이전트 로컬 테스트 도구

사용법:
    python sdk/tools/test_agent.py my_agent.yaml
    python sdk/tools/test_agent.py my_agent.yaml --opponent ace_fighter --rounds 3
"""

import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def main():
    parser = argparse.ArgumentParser(description="에이전트 로컬 테스트")
    parser.add_argument("agent", help="테스트할 에이전트 YAML 파일명 (examples/ 내)")
    parser.add_argument("--opponent", default="simple_fighter", help="상대 에이전트")
    parser.add_argument("--rounds", type=int, default=1, help="테스트 라운드 수")
    parser.add_argument("--verbose", action="store_true", help="상세 출력")
    
    args = parser.parse_args()
    
    # 에이전트 파일 경로 확인
    agent_path = project_root / "examples" / f"{args.agent}"
    if not agent_path.suffix:
        agent_path = agent_path.with_suffix(".yaml")
    
    if not agent_path.exists():
        print(f"❌ 에이전트 파일을 찾을 수 없습니다: {agent_path}")
        sys.exit(1)
    
    print(f"🎮 에이전트 테스트 시작")
    print(f"   에이전트: {args.agent}")
    print(f"   상대: {args.opponent}")
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
            tree2_file=str(project_root / "examples" / f"{args.opponent}.yaml"),
            config_name="1v1/NoWeapon/bt_vs_bt"
        )
        
        result = match.run(verbose=args.verbose)
        
        if result.winner == "tree1":
            wins += 1
            print(f"✅ 승리! (데미지: {result.tree1_damage:.1f} HP)")
        elif result.winner == "tree2":
            losses += 1
            print(f"❌ 패배 (받은 데미지: {result.tree2_damage:.1f} HP)")
        else:
            print(f"➖ 무승부")
        print()
    
    print("=" * 50)
    print(f"📊 결과: {wins}승 {losses}패 (승률: {wins/args.rounds*100:.1f}%)")


if __name__ == "__main__":
    main()
