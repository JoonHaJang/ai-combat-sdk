"""
Viper1 커스텀 액션 노드

Callsign: Viper1
전술: 공격적 추적 + 에너지 관리
"""

import logging
import py_trees
from src.behavior_tree.nodes.actions import BaseAction

logger = logging.getLogger(__name__)


class ViperStrike(BaseAction):
    """Viper Strike - 공격적 추적 기동
    
    특징:
    - TAU 기반 정밀 추적
    - 거리별 속도 최적화
    - 고도 우위 유지
    """
    
    def __init__(self, name: str = "ViperStrike",
                 close_range: float = 1000.0,
                 wez_range: float = 600.0,
                 mid_range: float = 1200.0,
                 far_range: float = 2500.0,
                 alt_gap_high: float = 300.0,
                 alt_gap_low: float = -200.0,
                 tau_straight_close: float = 3.0,
                 tau_straight_far: float = 10.0,
                 tau_strong: float = 20.0,
                 tau_hard: float = 40.0):
        super().__init__(name)
        # 거리 임계값 (m)
        self.close_range = close_range
        self.wez_range = wez_range
        self.mid_range = mid_range
        self.far_range = far_range
        # 고도 임계값 (m)
        self.alt_gap_high = alt_gap_high
        self.alt_gap_low = alt_gap_low
        # TAU 임계값 (도)
        self.tau_straight_close = tau_straight_close
        self.tau_straight_far = tau_straight_far
        self.tau_strong = tau_strong
        self.tau_hard = tau_hard
    
    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            
            # TAU 기반 방향 제어
            tau_normalized = obs.get("tau_deg", 0.0)
            tau_deg = tau_normalized * 180.0
            
            distance = obs.get("distance", 10000.0)
            alt_gap = obs.get("alt_gap", 0.0)
            # ata_deg는 현재 사용되지 않지만 향후 확장을 위해 주석 처리
            # ata_deg = obs.get("ata_deg", 0.0) * 180.0
            
            # 고도 명령: 공격 시 고도 우위 유지
            if alt_gap > self.alt_gap_high:
                delta_altitude_idx = 2  # 유지
            elif alt_gap > 0:
                delta_altitude_idx = 3  # 상승
            elif alt_gap > self.alt_gap_low:
                delta_altitude_idx = 3  # 상승 (우위 확보)
            else:
                delta_altitude_idx = 1  # 하강 (과도한 고도 차이)
            
            # 방향 명령: TAU 기반 정밀 추적
            if distance < self.close_range:  # 근거리 - 정밀 제어
                if abs(tau_deg) < self.tau_straight_close:
                    delta_heading_idx = 4  # 직진
                elif tau_deg > 0:
                    if abs(tau_deg) > self.tau_strong:
                        delta_heading_idx = 7  # 강우회전
                    elif abs(tau_deg) > self.tau_straight_far:
                        delta_heading_idx = 6  # 중우회전
                    else:
                        delta_heading_idx = 5  # 약우회전
                else:
                    if abs(tau_deg) > self.tau_strong:
                        delta_heading_idx = 1  # 강좌회전
                    elif abs(tau_deg) > self.tau_straight_far:
                        delta_heading_idx = 2  # 중좌회전
                    else:
                        delta_heading_idx = 3  # 약좌회전
            else:  # 중원거리 - 빠른 추적
                if abs(tau_deg) < self.tau_straight_far:
                    delta_heading_idx = 4  # 직진
                elif tau_deg > 0:
                    if abs(tau_deg) > self.tau_hard:
                        delta_heading_idx = 8  # 급우회전
                    else:
                        delta_heading_idx = 6  # 중우회전
                else:
                    if abs(tau_deg) > self.tau_hard:
                        delta_heading_idx = 0  # 급좌회전
                    else:
                        delta_heading_idx = 2  # 중좌회전
            
            # 속도 명령: 거리 기반 최적화
            if distance < self.wez_range:  # 매우 근거리 - WEZ 내
                delta_velocity_idx = 1  # 감속 (안정적 조준)
            elif distance < self.mid_range:  # 근거리
                delta_velocity_idx = 2  # 유지
            elif distance < self.far_range:  # 중거리
                delta_velocity_idx = 3  # 가속 (접근)
            else:  # 원거리
                delta_velocity_idx = 4  # 급가속 (빠른 접근)
            
            self.set_action(delta_altitude_idx, delta_heading_idx, delta_velocity_idx)
            return py_trees.common.Status.SUCCESS
            
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"ViperStrike 실행 실패: {e}")
            self.set_action(2, 4, 2)
            return py_trees.common.Status.FAILURE


class EnergyManeuver(BaseAction):
    """Energy Maneuver - 에너지 관리 기동
    
    특징:
    - 속도-고도 트레이드오프
    - 에너지 상태 기반 기동
    """
    
    def __init__(self, name: str = "EnergyManeuver",
                 low_energy_threshold: float = 8000.0,
                 high_energy_threshold: float = 12000.0,
                 min_velocity: float = 250.0,
                 alt_gap_threshold: float = 300.0,
                 tau_straight: float = 10.0):
        super().__init__(name)
        # 에너지 임계값
        self.low_energy_threshold = low_energy_threshold
        self.high_energy_threshold = high_energy_threshold
        # 속도 임계값 (m/s)
        self.min_velocity = min_velocity
        # 고도 임계값 (m)
        self.alt_gap_threshold = alt_gap_threshold
        # TAU 임계값 (도)
        self.tau_straight = tau_straight
    
    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            
            velocity = obs.get("ego_vc", 200.0)
            altitude = obs.get("ego_altitude", 5000.0)
            alt_gap = obs.get("alt_gap", 0.0)
            
            # 에너지 상태 판단 (간단한 비에너지 근사)
            # E = mgh + 0.5mv^2
            # 정규화: 고도(m) + 속도^2 / 20
            my_energy = altitude + (velocity ** 2) / 20
            
            # 에너지 기반 전술
            if my_energy < self.low_energy_threshold:  # 저에너지
                # 에너지 회복: 속도 증가 또는 고도 유지
                if velocity < self.min_velocity:
                    delta_velocity_idx = 4  # 급가속
                    delta_altitude_idx = 1  # 하강 (속도 확보)
                else:
                    delta_velocity_idx = 3  # 가속
                    delta_altitude_idx = 2  # 유지
            elif my_energy > self.high_energy_threshold:  # 고에너지
                # 에너지 활용: 고도 우위 확보
                if alt_gap < self.alt_gap_threshold:
                    delta_altitude_idx = 4  # 급상승
                    delta_velocity_idx = 1  # 감속 (고도 전환)
                else:
                    delta_altitude_idx = 2  # 유지
                    delta_velocity_idx = 2  # 유지
            else:  # 중간 에너지
                # 균형 유지
                delta_altitude_idx = 2
                delta_velocity_idx = 2
            
            # 방향은 적 추적 (tau_deg 사용)
            tau_deg = obs.get("tau_deg", 0.0) * 180.0
            if abs(tau_deg) < self.tau_straight:
                delta_heading_idx = 4
            elif tau_deg > 0:
                delta_heading_idx = 6
            else:
                delta_heading_idx = 2
            
            self.set_action(delta_altitude_idx, delta_heading_idx, delta_velocity_idx)
            return py_trees.common.Status.SUCCESS
            
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"EnergyManeuver 실행 실패: {e}")
            self.set_action(2, 4, 2)
            return py_trees.common.Status.FAILURE
