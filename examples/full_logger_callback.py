"""
전체 인자 로깅 콜백 예제
step_callback으로 모든 정보를 콘솔과 파일에 기록합니다.
"""

from pathlib import Path

def create_full_logger(log_file: str = None):
    """
    모든 콜백 인자를 로깅하는 함수를 생성합니다.
    
    Args:
        log_file: 로그 파일 경로 (None이면 콘솔만 출력)
    
    Returns:
        step_callback 함수
    """
    # 로그 파일 초기화
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write("step,agent_id,bfm_situation,ego_health,enm_health,ego_damage_dealt,enm_damage_dealt,in_wez,enm_in_wez,reward,distance,ata_deg,action_altitude,action_heading,action_velocity,aileron,elevator,rudder,throttle,active_node,active_nodes_count\n")
    
    def full_logger(step, agent_id, obs, action, low_level_action, reward, health, active_nodes, bfm_situation):
        """매 틱마다 모든 정보를 로깅"""
        try:
            # BFM 상황 문자열 변환 (Enum 객체 처리)
            bfm_str = str(bfm_situation) if bfm_situation else ""
            
            # 관측값에서 주요 정보 추출
            distance = obs.get("distance", 0)
            ata_deg = obs.get("ata_deg", 0) * 180  # 정규화된 값을 각도로 변환
            
            # 활성 노드 정보 요약
            active_node = ""
            if active_nodes:
                success_nodes = [n for n, s in active_nodes if s == 'SUCCESS']
                active_node = success_nodes[-1] if success_nodes else ""
            
            # 콘솔 출력 (간결하게)
            print(f"[{step:4d}] {agent_id} | "
                  f"BFM={bfm_str:20} | "
                  f"HP={health['ego']:5.1f}/{health['enm']:5.1f} | "
                  f"Dmg={obs.get('ego_damage_dealt',0):4.1f} | "
                  f"WEZ={obs.get('in_wez',False)} | "
                  f"Dist={distance:4.0f}m ATA={ata_deg:5.1f}deg | "
                  f"Act={action} | "
                  f"Node={active_node}")
            
            # CSV 파일에 상세 기록
            if log_file:
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"{step},{agent_id},{bfm_str},"
                           f"{health['ego']},{health['enm']},"
                           f"{obs.get('ego_damage_dealt',0)},{obs.get('enm_damage_dealt',0)},"
                           f"{obs.get('in_wez',False)},{obs.get('enm_in_wez',False)},"
                           f"{reward:.6f},{distance:.1f},{ata_deg:.2f},"
                           f"{action[0]},{action[1]},{action[2]},"
                           f"{low_level_action.get('aileron',0):.4f},"
                           f"{low_level_action.get('elevator',0):.4f},"
                           f"{low_level_action.get('rudder',0):.4f},"
                           f"{low_level_action.get('throttle',0):.4f},"
                           f'"{active_node}",{len(active_nodes)}\n')
        except Exception as e:
            print(f"[콜백 오류] step={step}, agent={agent_id}: {e}")
            import traceback
            traceback.print_exc()
    
    return full_logger


# 사용 예제
if __name__ == "__main__":
    from src.match.runner import BehaviorTreeMatch
    
    # 전체 로거 생성 (콘솔 + 파일)
    logger = create_full_logger("logs/full_match_log.csv")
    
    # 매치 실행
    match = BehaviorTreeMatch(
        tree1_file="examples/eagle1/eagle1.yaml",
        tree2_file="examples/simple.yaml",
        step_callback=logger,
        log_csv="logs/match_data.csv",  # SDK 내장 CSV 로깅도 동시 사용
    )
    
    result = match.run(verbose=True)
    
    print("\n=== 로깅 완료 ===")
    print("콘솔: 간단한 요약 출력")
    print("logs/full_match_log.csv: 콜백 기반 상세 로그")
    print("logs/match_data.csv: SDK 내장 전체 데이터 로그")
