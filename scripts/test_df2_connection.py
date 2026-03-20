r"""
Dogfight 2 연결 테스트 스크립트

사용법:
  1. 먼저 Dogfight 2를 실행하고 Network 모드에 진입
     cd c:\Users\Joon\Desktop\AI-pilot\AI_Pilot\dogfight-sandbox-hg2\source
     python main.py
     (게임에서 Network 미션 선택)

  2. 이 스크립트 실행
     cd c:\Users\Joon\Desktop\AI-pilot\AI_Pilot\ai-combat-sdk
     .venv\Scripts\python.exe scripts\test_df2_connection.py
"""
import sys
import os
import time
import argparse

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.visualization.dogfight2_client import Dogfight2Client, get_local_ip


def test_connection(host: str, port: int):
    """기본 연결 테스트"""
    print("=" * 60)
    print(f"[TEST 1] Connecting to Dogfight 2 at {host}:{port}...")
    print("=" * 60)

    client = Dogfight2Client(host, port)
    if not client.connect():
        print("\n*** CONNECTION FAILED ***")
        print("확인 사항:")
        print("  1. Dogfight 2가 실행 중인지 확인")
        print("  2. Network 미션을 선택했는지 확인")
        print(f"  3. IP:Port가 맞는지 확인 ({host}:{port})")
        print("  4. 방화벽 설정 확인")
        return None

    print("  -> Connection OK!\n")
    return client


def test_planes_list(client: Dogfight2Client):
    """비행기 목록 테스트"""
    print("=" * 60)
    print("[TEST 2] Getting planes list...")
    print("=" * 60)

    planes = client.get_planes_list()
    if not planes:
        print("  -> No planes returned (empty list)")
        return []

    print(f"  -> Found {len(planes)} planes:")
    for i, plane_id in enumerate(planes):
        print(f"     [{i}] {plane_id}")
    print()
    return planes


def test_plane_state(client: Dogfight2Client, plane_id: str):
    """비행기 상태 조회 테스트"""
    print("=" * 60)
    print(f"[TEST 3] Getting state of '{plane_id}'...")
    print("=" * 60)

    state = client.get_plane_state(plane_id)
    if not state:
        print("  -> Failed to get plane state")
        return None

    print(f"  Position  : {state.get('position', 'N/A')}")
    print(f"  Altitude  : {state.get('altitude', 'N/A')}")
    print(f"  Heading   : {state.get('heading', 'N/A')}")
    print(f"  Pitch     : {state.get('pitch_attitude', 'N/A')}")
    print(f"  Roll      : {state.get('roll_attitude', 'N/A')}")
    print(f"  Speed     : {state.get('linear_speed', 'N/A')}")
    print(f"  Thrust    : {state.get('thrust_level', 'N/A')}")
    print(f"  Health    : {state.get('health_level', 'N/A')}")
    print(f"  Active    : {state.get('active', 'N/A')}")
    print(f"  Type      : {state.get('type', 'N/A')}")
    print(f"  Nationality: {state.get('nationality', 'N/A')}")
    print()
    return state


def test_setup_visualization(client: Dogfight2Client):
    """시각화 설정 테스트"""
    print("=" * 60)
    print("[TEST 4] Setting up visualization mode...")
    print("=" * 60)

    client.disable_log()
    print("  -> Log disabled")

    client.set_client_update_mode(True)
    print("  -> Client update mode ON")

    client.set_renderless_mode(False)
    print("  -> Renderless mode OFF (visualization ON)")

    ts = client.get_timestep()
    if ts:
        print(f"  -> Timestep: {ts}")
    print()


def test_initialize_and_fly(client: Dogfight2Client, planes: list):
    """F-16 2대 초기화 및 비행 테스트"""
    print("=" * 60)
    print("[TEST 5] Initializing 2 planes and flying...")
    print("=" * 60)

    if len(planes) < 2:
        print("  -> Not enough planes for 2-plane test")
        return

    # F-16 찾기 (plane_id에 'F16' 또는 'f16'이 포함된 것)
    f16_planes = [p for p in planes if 'f16' in p.lower() or 'F16' in p]
    if f16_planes:
        print(f"  -> Found F-16 planes: {f16_planes}")
    else:
        print(f"  -> No F-16 found in plane names, using first 2 planes")

    plane1 = planes[0]
    plane2 = planes[1]
    print(f"  -> Using plane1={plane1}, plane2={plane2}")

    # 리셋
    client.reset_machine(plane1)
    client.reset_machine(plane2)
    print("  -> Planes reset")

    # 추력 설정
    client.set_plane_thrust(plane1, 1.0)
    client.set_plane_thrust(plane2, 1.0)
    print("  -> Thrust set to 1.0")

    # 기어 접기
    client.retract_gear(plane1)
    client.retract_gear(plane2)
    print("  -> Gear retracted")

    # 10프레임 업데이트
    print("  -> Running 10 scene updates...")
    for i in range(10):
        client.update_scene()
        time.sleep(0.05)

    # 상태 확인
    state1 = client.get_plane_state(plane1)
    state2 = client.get_plane_state(plane2)
    if state1:
        print(f"  -> Plane1 pos={state1.get('position')}, alt={state1.get('altitude'):.1f}, speed={state1.get('linear_speed', 0):.1f}")
    if state2:
        print(f"  -> Plane2 pos={state2.get('position')}, alt={state2.get('altitude'):.1f}, speed={state2.get('linear_speed', 0):.1f}")
    print()


def test_custom_physics(client: Dogfight2Client, planes: list):
    """커스텀 물리 모드 테스트 (JSBSim 데이터로 기체 위치 직접 제어)"""
    print("=" * 60)
    print("[TEST 6] Custom physics mode test...")
    print("=" * 60)

    if len(planes) < 1:
        print("  -> No planes available")
        return

    plane1 = planes[0]

    # 커스텀 물리 모드 활성화
    client.set_machine_custom_physics_mode(plane1, True)
    print(f"  -> Custom physics ON for {plane1}")

    # 단위 행렬 + 위치를 [0, 1000, 0] (고도 1000m)으로 설정
    # matrix_3_4: column-major [r0c0, r1c0, r2c0, r0c1, r1c1, r2c1, r0c2, r1c2, r2c2, r0c3, r1c3, r2c3]
    identity_at_altitude = [
        1, 0, 0,   # col0 (X-axis)
        0, 1, 0,   # col1 (Y-axis)
        0, 0, 1,   # col2 (Z-axis)
        0, 1000, 0  # col3 (position: x=0, y=1000m, z=0)
    ]
    velocity = [100, 0, 0]  # 100 m/s forward

    client.update_machine_kinetics(plane1, identity_at_altitude, velocity)
    print(f"  -> Set position=[0, 1000, 0], velocity=[100, 0, 0]")

    client.update_scene()

    state = client.get_plane_state(plane1)
    if state:
        print(f"  -> Plane1 pos={state.get('position')}, alt={state.get('altitude'):.1f}")

    # 커스텀 물리 모드 비활성화
    client.set_machine_custom_physics_mode(plane1, False)
    print(f"  -> Custom physics OFF for {plane1}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Dogfight 2 Connection Test")
    default_ip = get_local_ip()
    parser.add_argument('--host', type=str, default=default_ip,
                        help=f'Dogfight 2 host IP (default: {default_ip})')
    parser.add_argument('--port', type=int, default=50888, help='Dogfight 2 port')
    parser.add_argument('--quick', action='store_true', help='Quick test (connection only)')
    args = parser.parse_args()

    print(f"[INFO] Local IP (Dogfight 2 server): {default_ip}")
    print()

    # Test 1: Connection
    client = test_connection(args.host, args.port)
    if not client:
        sys.exit(1)

    try:
        # Test 2: Planes list
        planes = test_planes_list(client)

        if args.quick:
            print("Quick test done!")
            return

        if not planes:
            print("No planes available. Exiting.")
            return

        # Test 3: Plane state
        test_plane_state(client, planes[0])

        # Test 4: Setup visualization
        test_setup_visualization(client)

        # Test 5: Initialize and fly
        test_initialize_and_fly(client, planes)

        # Test 6: Custom physics
        test_custom_physics(client, planes)

        print("=" * 60)
        print("ALL TESTS PASSED!")
        print("=" * 60)

    except Exception as e:
        print(f"\n*** TEST ERROR: {e} ***")
        import traceback
        traceback.print_exc()
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
