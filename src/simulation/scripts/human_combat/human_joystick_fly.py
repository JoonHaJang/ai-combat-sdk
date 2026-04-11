#!/usr/bin/env python
"""
조이스틱 직접 제어 비행 스크립트

Logitech G Extreme 3D Pro 조이스틱을 사용하여 F-16을 직접 조종합니다.
Tacview Advanced와 연동하여 실시간 시각화를 지원합니다.

사용법:
    python human_joystick_fly.py

요구사항:
    - pygame 설치: pip install pygame
    - Tacview Advanced (실시간 렌더링용, 선택사항)
    - Logitech G Extreme 3D Pro 조이스틱 연결
"""

import sys
import os
import time
import traceback
import logging

# 경로 설정
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

from envs.JSBSim.envs.singlecontrol_env import SingleControlEnv
from envs.JSBSim.human_agent.JoystickAgent import JoystickAgent
from runner.tacview import Tacview


def setup_logging():
    """로깅 설정 (환경 변수 LOG_LEVEL 지원)"""
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    numeric_level = getattr(logging, log_level, logging.INFO)
    
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('joystick_fly.log', mode='w', encoding='utf-8')
        ]
    )
    logging.info(f"로깅 레벨: {log_level}")


def main():
    setup_logging()
    logging.info("=" * 60)
    logging.info("조이스틱 직접 제어 비행 시작")
    logging.info("=" * 60)
    
    # Tacview 초기화 (선택사항)
    tacview = None
    try:
        tacview = Tacview()
        logging.info("Tacview 연결 성공")
    except Exception as e:
        logging.warning(f"Tacview 연결 실패 (시각화 없이 진행): {e}")
    
    # 환경 초기화
    scenario_name = "1/JoystickFreeFly"
    logging.info(f"시나리오 로드: {scenario_name}")
    
    try:
        env = SingleControlEnv(scenario_name)
        logging.info("환경 초기화 완료")
    except Exception as e:
        logging.error(f"환경 초기화 실패: {e}")
        traceback.print_exc()
        return
    
    # 조이스틱 에이전트 초기화
    try:
        agent = JoystickAgent(
            env, 
            deadzone=0.05,              # 5% 데드존
            enable_display=True,        # pygame 디스플레이 활성화
            enable_calibration=False    # 캘리브레이션 비활성화 (필요시 True)
        )
        logging.info("조이스틱 에이전트 초기화 완료")
        logging.info("버튼 기능: 트리거=리셋, 엄지=일시정지, 사이드=브레이크")
    except Exception as e:
        logging.error(f"조이스틱 초기화 실패: {e}")
        traceback.print_exc()
        return
    
    # 환경 리셋
    observation = agent.reset()
    logging.info("환경 리셋 완료")
    
    # 메인 루프
    done = False
    timestamp = 0.0
    step_count = 0
    paused = False
    
    # Tacview 재연결 관련
    tacview_fail_count = 0
    MAX_TACVIEW_FAILS = 10
    
    # 정밀 타이밍 제어
    target_dt = 0.2  # 목표 간격 (초)
    next_step_time = time.perf_counter()
    
    logging.info("-" * 60)
    logging.info("비행 시작! 조이스틱으로 조종하세요.")
    logging.info("종료하려면 pygame 창을 닫거나 Ctrl+C를 누르세요.")
    logging.info("-" * 60)
    
    try:
        while not done and not agent.stop_event.is_set():
            # 리셋 버튼 처리
            if agent.is_reset_requested():
                logging.info("리셋 버튼 눌림 - 환경 리셋")
                observation = agent.reset()
                step_count = 0
                timestamp = 0.0
                next_step_time = time.perf_counter()
                continue
            
            # 일시정지 버튼 처리
            if agent.is_pause_requested():
                if not paused:
                    logging.info("일시정지")
                    paused = True
                time.sleep(0.1)
                continue
            else:
                if paused:
                    logging.info("재개")
                    paused = False
                    next_step_time = time.perf_counter()
            
            # 한 스텝 실행
            observation, reward, done, info = agent.step()
            step_count += 1
            
            # Tacview 렌더링 (재연결 로직 포함)
            if tacview is not None:
                render_data = [f"#{timestamp:.2f}\n"]
                for sim in env._jsbsims.values():
                    log_msg = sim.log()
                    if log_msg is not None:
                        render_data.append(log_msg + "\n")
                
                render_data_str = "".join(render_data)
                try:
                    tacview.send_data_to_client(render_data_str)
                    tacview_fail_count = 0  # 성공 시 리셋
                except Exception as e:
                    tacview_fail_count += 1
                    if tacview_fail_count >= MAX_TACVIEW_FAILS:
                        logging.warning("Tacview 재연결 시도...")
                        try:
                            tacview = Tacview()
                            tacview_fail_count = 0
                            logging.info("Tacview 재연결 성공")
                        except Exception as reconnect_error:
                            logging.error(f"Tacview 재연결 실패: {reconnect_error}")
                            tacview = None
                    elif tacview_fail_count % 10 == 0:
                        logging.warning(f"Tacview 전송 실패 ({tacview_fail_count}회): {e}")
            
            timestamp += target_dt
            
            # 상태 로깅 (10초마다)
            if step_count % 50 == 0:
                sim = list(env._jsbsims.values())[0]
                altitude_ft = sim.get_property_value(
                    env.task.state_var[3]
                ) * 3.28084  # m to ft
                velocity = sim.get_property_value(env.task.state_var[9])  # m/s
                brake_status = "ON" if agent.is_brake_active() else "OFF"
                
                logging.info(
                    f"Step {step_count}: "
                    f"Alt={altitude_ft:.0f}ft, "
                    f"Vel={velocity:.1f}m/s, "
                    f"Brake={brake_status}"
                )
            
            # 정밀 프레임 속도 제어
            next_step_time += target_dt
            sleep_time = next_step_time - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                # 프레임 드롭 경고
                if sleep_time < -0.05:  # 50ms 이상 지연
                    logging.warning(f"프레임 드롭: {-sleep_time:.3f}초 지연")
                next_step_time = time.perf_counter()
            
    except KeyboardInterrupt:
        logging.info("사용자에 의해 중단됨")
    except Exception as e:
        logging.error(f"실행 중 오류 발생: {e}")
        traceback.print_exc()
    finally:
        # 정리
        logging.info("정리 중...")
        agent.cleanup()
        logging.info("비행 종료")


if __name__ == "__main__":
    main()
