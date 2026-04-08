"""
Adaptive Eagle 커스텀 액션 노드 — Phase 4 + Phase 3a

Phase 3a 추가:
  SmartLeadPursuit — 빌트인 LeadPursuit 교체 (vel/alt 상황 적응)
  SmartGunAttack   — 빌트인 GunAttack 교체 (PD 제어 + 거리별 속도)

LAG 모델 핵심 통찰:
  - 모든 상황에서 throttle avg 0.87+ → vel=4가 기본 최적
  - 에너지 우위 시 하강→속도 변환이 가장 효과적
"""

import logging
import py_trees

logger = logging.getLogger(__name__)


class BaseAction(py_trees.behaviour.Behaviour):
    """커스텀 액션 베이스."""

    def __init__(self, name: str):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="action", access=py_trees.common.Access.WRITE)

    def set_action(self, delta_altitude_idx: int, delta_heading_idx: int, delta_velocity_idx: int):
        self.blackboard.action = [delta_altitude_idx, delta_heading_idx, delta_velocity_idx]


def _heading_from_tau(tau_deg: float, gain: float = 1.0) -> int:
    """tau → heading index [0-8]."""
    cmd = tau_deg * gain
    idx = int(round(cmd / 22.5)) + 4
    return max(0, min(8, idx))


class HeadOnBreak(BaseAction):
    """Head-on 교착 탈출 — LAG OFFENSIVE_DIVE 패턴 적용.

    전술 원리:
      하강 돌파(pitch_down) + 풀 스로틀 → 기하학 교란.
      적 시선 아래 통과 → AO 변화 → 교착 벗어나면 LeadPursuit 재개.

    적용 조건 (yaml): EnemyIntentIs(NEUTRAL_CIRCLE) + CustomOrbitDetector
    """

    def __init__(self, name: str = "HeadOnBreak",
                 heading_gain: float = 0.8):
        super().__init__(name)
        self.heading_gain = heading_gain

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            tau = obs.get("tau_deg", 0.0) * 180.0
            altitude = obs.get("ego_altitude_ft", 10000.0)

            heading_idx = _heading_from_tau(tau, self.heading_gain)

            if altitude < 2000:
                delta_alt = 3
            else:
                delta_alt = 1

            delta_vel = 4

            self.set_action(delta_alt, heading_idx, delta_vel)
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"HeadOnBreak error: {e}")
            self.set_action(1, 4, 4)
            return py_trees.common.Status.FAILURE


def _heading_from_bearing(bearing_deg: float, gain: float = 1.0) -> int:
    """relative_bearing(도) → heading index [0-8].
    bearing < 0 → 좌선회, bearing > 0 → 우선회.
    """
    cmd = bearing_deg * gain
    idx = int(round(cmd / 22.5)) + 4
    return max(0, min(8, idx))


class SmartLeadPursuit(BaseAction):
    """에너지 인식 선도 추적 — 빌트인 LeadPursuit(vel=3 고정) 교체.

    개선점:
      1. 속도 적응: 원거리 vel=4(급가속), 고접근 vel=2(오버슈트 방지),
         에너지 우위 vel=4(압박)
      2. 고도 적응: 에너지 우위+근거리 시 하강→속도 변환,
         저고도 시 상승
      3. Heading: relative_bearing 기반 PN 추적 (gain 튜닝 가능)

    근거: LAG 정책 "모든 상황에서 throttle 0.87+" → vel=4가 기본 최적
    """

    def __init__(self, name: str = "SmartLeadPursuit",
                 heading_gain: float = 1.0,
                 far_dist_ft: float = 8000.0,
                 close_dist_ft: float = 3000.0,
                 closure_brake_kts: float = 300.0,
                 alt_dive_threshold_ft: float = 5000.0):
        super().__init__(name)
        self.heading_gain = heading_gain
        self.far_dist = far_dist_ft
        self.close_dist = close_dist_ft
        self.closure_brake = closure_brake_kts
        self.alt_dive_threshold = alt_dive_threshold_ft

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            rel_b = obs.get("relative_bearing_deg", 0.0) * 180.0
            dist = obs.get("distance_ft", 10000.0)
            closure = obs.get("closure_rate_kts", 0.0)
            alt = obs.get("ego_altitude_ft", 10000.0)
            energy_adv = obs.get("energy_advantage", False)
            alt_adv = obs.get("alt_advantage", False)

            # Heading: PN 추적 (빌트인과 동등하되 gain 튜닝 가능)
            hdg = _heading_from_bearing(rel_b, self.heading_gain)

            # Velocity: 상황별 적응 (빌트인은 항상 3)
            if dist > self.far_dist:
                vel = 4           # 원거리: 급가속으로 빠르게 접근
            elif closure > self.closure_brake:
                vel = 2           # 빠른 접근: 유지 (오버슈트 방지)
            elif energy_adv:
                vel = 4           # 에너지 우위: 급가속으로 압박
            else:
                vel = 4           # 기본: 급가속 (LAG 통찰)

            # Altitude: 에너지 관리 (빌트인은 항상 2)
            if alt < 2000:
                alt_idx = 3       # Hard Deck 근접: 상승
            elif alt_adv and dist < self.alt_dive_threshold:
                alt_idx = 1       # 고도 우위 + 근거리: 하강→속도 변환
            else:
                alt_idx = 2       # 기본: 유지

            self.set_action(alt_idx, hdg, vel)
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"SmartLeadPursuit error: {e}")
            self.set_action(2, 4, 4)
            return py_trees.common.Status.FAILURE


class SmartGunAttack(BaseAction):
    """PD 제어 정밀 사격 — 빌트인 GunAttack(고정 gain) 교체.

    개선점:
      1. PD 제어: tau의 미분항(tau_rate)으로 오버슈트 방지
      2. 거리별 속도: 접근 시 가속, WEZ 내 감속 (안정 사격 플랫폼)
      3. 파라미터 튜닝: kp, kd를 optimizer에 등록 가능

    근거: Golden BT (120W-0L)의 PNAttack 패턴 참고
    """

    def __init__(self, name: str = "SmartGunAttack",
                 kp: float = 1.2,
                 kd: float = 0.5):
        super().__init__(name)
        self.kp = kp
        self.kd = kd
        self._prev_tau = 0.0

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            tau = obs.get("tau_deg", 0.0) * 180.0
            dist = obs.get("distance_ft", 1000.0)
            alt = obs.get("ego_altitude_ft", 10000.0)

            # PD 제어 heading
            tau_rate = tau - self._prev_tau
            self._prev_tau = tau
            cmd = self.kp * tau + self.kd * tau_rate
            hdg = max(0, min(8, int(round(cmd / 22.5)) + 4))

            # 거리별 속도 (빌트인은 고정 감속)
            if dist > 3000:
                vel = 3           # 접근: 가속
            elif dist > 914:
                vel = 2           # WEZ 근접: 유지
            elif dist > 152:
                vel = 1           # WEZ 내: 감속 (안정 사격)
            else:
                vel = 0           # 너무 가까움: 급감속

            # 고도: 유지 (사격 안정성)
            alt_idx = 3 if alt < 2000 else 2

            self.set_action(alt_idx, hdg, vel)
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"SmartGunAttack error: {e}")
            self.set_action(2, 4, 2)
            return py_trees.common.Status.FAILURE


class ExtensionBreak(BaseAction):
    """이탈(Extension) 기동 — relative_bearing 부호로 반방향 이탈.

    전술 원리:
      DEFENSIVE 기하학(ATA > 90°)에서 적과 반방향으로 이탈.
      max speed(vel=4) + alt 유지(alt=2) → 에너지 보존하며 이탈.
      이탈 후 재공격은 LeadPursuit 브랜치가 담당.

    적용 조건 (yaml): IsDefensiveGeometry(AO>90°, TA<70°)
    """

    def __init__(self, name: str = "ExtensionBreak"):
        super().__init__(name)

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            rel_b = obs.get("relative_bearing_deg", 0.0)
            if isinstance(rel_b, (int, float)):
                rel_b_deg = float(rel_b) * 180.0
            else:
                rel_b_deg = 0.0

            altitude = obs.get("ego_altitude_ft", 10000.0)

            heading_idx = 6 if rel_b_deg <= 0 else 2

            if altitude < 1500:
                delta_alt = 4
            else:
                delta_alt = 2

            self.set_action(delta_alt, heading_idx, 4)
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"ExtensionBreak error: {e}")
            self.set_action(2, 6, 4)
            return py_trees.common.Status.FAILURE
