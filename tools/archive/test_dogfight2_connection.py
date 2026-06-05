"""
Dogfight 2 연결 테스트 스크립트

사용법:
1. Dogfight 2 실행 (dogfight-sandbox-hg2)
2. 네트워크 모드 진입 (방향키)
3. 이 스크립트 실행

python tools/test_dogfight2_connection.py
"""

import sys
from pathlib import Path

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.visualization.dogfight2_client import Dogfight2Client


def test_connection():
    """Dogfight 2 연결 테스트"""
    
    print("=" * 70)
    print("  Dogfight 2 연결 테스트")
    print("=" * 70)
    print()
    print("⚠️  먼저 Dogfight 2를 실행하고 네트워크 모드에 진입하세요!")
    print()
    
    # 연결 정보 입력
    host = input("Dogfight 2 서버 IP (기본값: 127.0.0.1): ").strip() or "127.0.0.1"
    port_str = input("Dogfight 2 서버 포트 (기본값: 50888): ").strip() or "50888"
    port = int(port_str)
    
    print()
    print(f"연결 시도: {host}:{port}")
    print()
    
    # 클라이언트 생성 및 연결
    client = Dogfight2Client(host=host, port=port)
    
    if not client.connect():
        print()
        print("❌ 연결 실패!")
        print()
        print("확인 사항:")
        print("  1. Dogfight 2가 실행 중인가?")
        print("  2. 네트워크 모드에 진입했는가?")
        print("  3. IP:Port가 올바른가?")
        return False
    
    try:
        # 비행기 목록 가져오기
        print()
        print("비행기 목록 가져오기...")
        planes = client.get_planes_list()
        print(f"✓ 비행기 {len(planes)}대 발견: {planes}")
        
        if len(planes) > 0:
            # 첫 번째 비행기 상태 확인
            plane_id = planes[0]
            print()
            print(f"비행기 '{plane_id}' 상태 확인...")
            state = client.get_plane_state(plane_id)
            
            if state:
                print(f"✓ 위치: {state.get('position', 'N/A')}")
                print(f"✓ Heading: {state.get('heading', 'N/A')}°")
                print(f"✓ Pitch: {state.get('pitch_attitude', 'N/A')}°")
                print(f"✓ Roll: {state.get('roll_attitude', 'N/A')}°")
                print(f"✓ 속도: {state.get('linear_speed', 'N/A')} m/s")
        
        # 비행기 초기화 테스트
        if len(planes) >= 2:
            print()
            print("2대 비행기 초기화 테스트...")
            if client.initialize_planes(2):
                print("✓ 초기화 성공!")
                print(f"  Agent1 → {client.plane_ids.get('agent1')}")
                print(f"  Agent2 → {client.plane_ids.get('agent2')}")
        
        print()
        print("=" * 70)
        print("  ✅ 모든 테스트 통과!")
        print("=" * 70)
        print()
        print("다음 단계:")
        print("  - VisualizationManager 구현")
        print("  - MatchCore 통합")
        print("  - 실제 대전 시각화 테스트")
        
        return True
        
    except Exception as e:
        print()
        print(f"❌ 테스트 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # 연결 종료
        client.disconnect()


if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)
