"""
Adaptive Eagle 커스텀 액션 노드 — Phase 3 + Option A (전략 선택기)

데이터 근거: logs/analysis/lag_dt_rules.json (tools/distill_lag_dt.py 출력)
  - HEAD_ON: OFFENSIVE_DIVE (66.7%) — avg_ele=-0.367, avg_thr=0.873
    → bt_alt_idx=1 (하강), bt_vel_idx=4 (최고속)
  - OFFENSIVE_PRIME: OFFENSIVE_DIVE (66.7%) — 후방 진입 시 하강 공격
  - DEFENSIVE: NEUTRAL_FAST (83.3%) — alt 유지, 고속 가속

LAG 모델 핵심 통찰 (query_lag_policy.py):
  - 모든 상황에서 throttle avg 0.87+ → 항상 최고속 유지
  - HEAD_ON에서 pitch_down (-0.367) = 하강 돌파로 head-on 기하학 교란
    → 교착 후 적 위에 위치 변경, AO 개선 기회 생성
  - DEFENSIVE에서 alt_maintain + 가속 = 에너지 소모 최소화
"""

import logging
import py_trees

from src.intent import shared_state

logger = logging.getLogger(__name__)


class BaseAction(py_trees.behaviour.Behaviour):
    """커스텀 액션 베이스 (alpha2와 동일 패턴)."""

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

    근거 (lag_dt_rules.json):
      HEAD_ON 상황: OFFENSIVE_DIVE 66.7%, avg_ele=-0.367, avg_thr=0.873
      bt_alt_idx=1 (완만한 하강), bt_vel_idx=4 (최고속)

    전술 원리:
      eagle1과 head-on 교착 상태 → 양측 LeadPursuit으로 0 damage 루프.
      LAG 해법: 하강 돌파(pitch_down) + 풀 스로틀 → 기하학 교란.
        1. 하강으로 적 시선 아래 통과 → AO 변화
        2. 속도 유지로 통과 후 재공격 위치 확보
        3. 교착 벗어나면 LeadPursuit 재개

    적용 조건 (yaml에서 설정):
      IsHeadOn: AO < 30° + TA < 60° + R < 15000ft
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

            # Heading: tau 기반 추적 (하강하면서도 적 방향 유지)
            heading_idx = _heading_from_tau(tau, self.heading_gain)

            # Altitude: 하강 (LAG avg_ele=-0.367 → alt_idx=1)
            # Hard Deck 근접 시 예외 처리
            if altitude < 2000:
                delta_alt = 3   # 저고도에서는 상승으로 전환
            else:
                delta_alt = 1   # 완만한 하강 — head-on 돌파

            # Velocity: 최고속 (LAG avg_thr=0.873 → vel_idx=4)
            delta_vel = 4

            self.set_action(delta_alt, heading_idx, delta_vel)
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"HeadOnBreak error: {e}")
            self.set_action(1, 4, 4)
            return py_trees.common.Status.FAILURE


class RLInspiredAttack(BaseAction):
    """공격적 하강 기동 — LAG OFFENSIVE_PRIME/OFFENSIVE_DIVE 패턴.

    근거 (lag_dt_rules.json):
      OFFENSIVE_PRIME: OFFENSIVE_DIVE 66.7%, avg_ele=-0.367, avg_thr=0.873
      bt_alt_idx=1, bt_vel_idx=4

    전술 원리:
      적 후방 진입(low AO + high TA) 시 하강 + 고속으로 공격 각도 유지.
      표준 LeadPursuit과 달리 altitude를 소모해 속도 변환 → 사격 기회 극대화.
      거리 < 3000ft에서는 GunAttack 조건과 조합 예정.

    적용 조건 (yaml):
      IsOffensivePrime: AO < 45° + TA > 100°
    """

    def __init__(self, name: str = "RLInspiredAttack",
                 heading_gain: float = 1.0):
        super().__init__(name)
        self.heading_gain = heading_gain

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            tau = obs.get("tau_deg", 0.0) * 180.0
            altitude = obs.get("ego_altitude_ft", 10000.0)
            distance = obs.get("distance_ft", 10000.0)

            # Heading: 정확한 추적 (gain=1.0)
            heading_idx = _heading_from_tau(tau, self.heading_gain)

            # Altitude: 하강 공격 (에너지→속도 변환)
            # 거리 가까울수록 더 완만하게 (GunWEZ 유지)
            if altitude < 2000:
                delta_alt = 3   # 저고도 예외
            elif distance < 3000:
                delta_alt = 2   # 근거리: 유지 (사격 각도 보존)
            else:
                delta_alt = 1   # 원거리: 하강 공격

            # Velocity: 최고속
            delta_vel = 4

            self.set_action(delta_alt, heading_idx, delta_vel)
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"RLInspiredAttack error: {e}")
            self.set_action(2, 4, 4)
            return py_trees.common.Status.FAILURE


class RLInspiredDefense(BaseAction):
    """방어 유지 + 고속 — LAG DEFENSIVE/NEUTRAL_FAST 패턴.

    근거 (lag_dt_rules.json):
      DEFENSIVE: NEUTRAL_FAST 83.3%, avg_ele=0.108, avg_thr=0.867
      bt_alt_idx=2 (유지), bt_vel_idx=4 (최고속)

    전술 원리:
      불리한 기하학(AO>90°, 적이 후방)에서 LAG의 선택:
        고도 유지 + 최고속 → 에너지 보존, 방어 기동 준비.
      기존 AltitudeAdvantage(상승)와 달리 alt 소모 없이 에너지 유지.
      이후 BFM이 NEUTRAL/TRANSITION으로 변화할 때 반전 공격 기회.

    적용 조건 (yaml):
      IsDefensiveGeometry: AO > 90° + TA < 70° (적이 우리 후방)
    """

    def __init__(self, name: str = "RLInspiredDefense",
                 heading_gain: float = 0.6):
        super().__init__(name)
        self.heading_gain = heading_gain

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            tau = obs.get("tau_deg", 0.0) * 180.0
            altitude = obs.get("ego_altitude_ft", 10000.0)

            # Heading: 완화된 회피 (급선회 방지 — 에너지 보존)
            heading_idx = _heading_from_tau(tau, self.heading_gain)

            # Altitude: 유지 (LAG avg_ele=0.108 ≈ neutral → alt_idx=2)
            if altitude < 1500:
                delta_alt = 4   # Hard Deck
            else:
                delta_alt = 2   # 유지

            # Velocity: 최고속 (에너지 보존의 핵심)
            delta_vel = 4

            self.set_action(delta_alt, heading_idx, delta_vel)
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"RLInspiredDefense error: {e}")
            self.set_action(2, 4, 4)
            return py_trees.common.Status.FAILURE


class ExtensionBreak(BaseAction):
    """이탈(Extension) 기동 — tau_deg 의존 없이 relative_bearing 부호로 반방향 이탈.

    문제 (PIPELINE_AUDIT.md 감사 발견):
      RLInspiredDefense는 tau_deg로 heading 계산 → 초기 조건 1°차로 heading=0 vs 5 분기
      → 50% 확률로 이탈 실패 (궤도 유지)

    해법:
      relative_bearing_deg 부호만 사용 → 적이 왼쪽(-) 이면 오른쪽(6), 오른쪽(+) 이면 왼쪽(2)
      → 반방향 이탈(Extension) 결정적으로 보장
      → max speed(vel=4), alt 유지(alt=2) → 에너지 보존하며 이탈

    전술 원리:
      DEFENSIVE 기하학(ATA > 90°)에서:
        1. 적과 반방향으로 이탈 (Extension)
        2. 이탈 중 에너지(속도) 축적
        3. 적이 쫓아오면 ATA가 더 벌어져 재공격 반전 기회
      이탈 후 re-attack: LeadPursuit/CloseCompat 브랜치가 담당
    """

    def __init__(self, name: str = "ExtensionBreak"):
        super().__init__(name)

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            rel_b = obs.get("relative_bearing_deg", 0.0)
            # relative_bearing_deg is in radians in obs dict
            if isinstance(rel_b, (int, float)):
                rel_b_deg = float(rel_b) * 180.0
            else:
                rel_b_deg = 0.0

            altitude = obs.get("ego_altitude_ft", 10000.0)

            # 적이 왼쪽(-) → 오른쪽으로 이탈(heading=6), 오른쪽(+) → 왼쪽(heading=2)
            heading_idx = 6 if rel_b_deg <= 0 else 2

            # Hard Deck 예외
            if altitude < 1500:
                delta_alt = 4  # 비상 상승
            else:
                delta_alt = 2  # 고도 유지 (에너지 소모 없음)

            self.set_action(delta_alt, heading_idx, 4)  # vel=4 최고속
            return py_trees.common.Status.SUCCESS
        except Exception as e:
            logger.warning(f"ExtensionBreak error: {e}")
            self.set_action(2, 6, 4)
            return py_trees.common.Status.FAILURE


class SelectStrategy(py_trees.behaviour.Behaviour):
    """Option A: (내 기하학 상태, 적 EIM intent) → strategy_id 매핑.

    매 스텝 blackboard.selected_strategy 를 업데이트하고 항상 SUCCESS 반환.

    내 기하학 상태 분류 (우선순위 순):
      HARD_DECK    : 고도 < 1200ft
      CLOSE_WEZ    : 거리 < 900ft + ATA < 10°
      HEAD_ON      : AO < 30° + TA < 60°
      OFFENSIVE    : AO < 45°
      NEUTRAL      : 45° ≤ AO ≤ 90°
      DEFENSIVE    : AO > 90°

    전략 ID → BT 액션:
      HARD_DECK     → ClimbTo(3000ft)
      SHOOT         → GunAttack
      DIVE_BREAK    → HeadOnBreak (LAG: pitch_down + fullspeed)
      PRESS_ATTACK  → LeadPursuit
      TURN_FIGHT    → PurePursuit (거리 좁히기)
      ENERGY_ESCAPE → RLInspiredDefense (alt 유지 + 최고속)
      REPOSITION    → AltitudeAdvantage (기하학 개선)
    """

    # (내 기하학, 적 intent) → strategy
    STRATEGY_MAP = {
        # OFFENSIVE: 내가 유리한 위치 → 항상 압박
        ('OFFENSIVE', 'GUN_ATTACK'):        'PRESS_ATTACK',
        ('OFFENSIVE', 'PURSUIT'):           'PRESS_ATTACK',
        ('OFFENSIVE', 'DEFENSIVE'):         'PRESS_ATTACK',
        ('OFFENSIVE', 'ENERGY'):            'PRESS_ATTACK',
        ('OFFENSIVE', 'NEUTRAL_CIRCLE'):    'PRESS_ATTACK',
        ('OFFENSIVE', 'NEUTRAL_SCISSORS'):  'PRESS_ATTACK',
        ('OFFENSIVE', 'UNKNOWN'):           'PRESS_ATTACK',

        # NEUTRAL: 중립 기하학 → 적 intent에 따라 대응
        ('NEUTRAL', 'GUN_ATTACK'):          'ENERGY_ESCAPE',   # 적 사격 중 → 이탈
        ('NEUTRAL', 'PURSUIT'):             'TURN_FIGHT',      # 적 추격 중 → 선회전
        ('NEUTRAL', 'DEFENSIVE'):           'TURN_FIGHT',      # 적 방어 중 → 접근
        ('NEUTRAL', 'ENERGY'):              'REPOSITION',      # 적 에너지 축적 → 고도 선점
        ('NEUTRAL', 'NEUTRAL_CIRCLE'):      'TURN_FIGHT',
        ('NEUTRAL', 'NEUTRAL_SCISSORS'):    'TURN_FIGHT',
        ('NEUTRAL', 'UNKNOWN'):             'TURN_FIGHT',

        # DEFENSIVE: 적이 유리한 위치 → 생존 + 기하학 개선
        ('DEFENSIVE', 'GUN_ATTACK'):        'REPOSITION',      # 적 사격 + 내 후방 노출 → 즉시 고도
        ('DEFENSIVE', 'PURSUIT'):           'ENERGY_ESCAPE',   # 적 추격 → 고속 이탈
        ('DEFENSIVE', 'DEFENSIVE'):         'REPOSITION',      # 양측 방어 → 기하학 리셋
        ('DEFENSIVE', 'ENERGY'):            'ENERGY_ESCAPE',   # 적 에너지 축적 → 먼저 확장
        ('DEFENSIVE', 'NEUTRAL_CIRCLE'):    'REPOSITION',
        ('DEFENSIVE', 'NEUTRAL_SCISSORS'):  'ENERGY_ESCAPE',
        ('DEFENSIVE', 'UNKNOWN'):           'REPOSITION',
    }

    # EIM 신뢰도 낮을 때 기하학만으로 결정
    # 근거: dist<5000ft 내에서는 LeadPursuit(PRESS_ATTACK)이 항상 효과적 (v1.1 검증)
    GEO_FALLBACK = {
        'OFFENSIVE': 'PRESS_ATTACK',
        'NEUTRAL':   'PRESS_ATTACK',   # EIM 불확실 + 근거리 → 공격 유지
        'DEFENSIVE': 'REPOSITION',
    }
    NEUTRAL_CLOSE_THRESHOLD_FT = 5000  # 이 거리 이내 NEUTRAL → PRESS_ATTACK

    MIN_EIM_CONF = 0.40

    def __init__(self, name: str = "SelectStrategy"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="selected_strategy", access=py_trees.common.Access.WRITE)

    def _classify_geo(self, obs: dict) -> str:
        altitude = obs.get("ego_altitude_ft", 10000.0)
        dist = obs.get("distance_ft", 99999.0)
        ao = obs.get("ata_deg", 0.5) * 180.0
        ta = obs.get("aa_deg", 0.5) * 180.0

        if altitude < 1200:
            return "HARD_DECK"
        if dist < 900 and ao < 10:
            return "CLOSE_WEZ"
        if ao < 30 and ta < 60:
            return "HEAD_ON"
        if ao < 45:
            return "OFFENSIVE"
        if ao <= 90:
            return "NEUTRAL"
        return "DEFENSIVE"

    def update(self) -> py_trees.common.Status:
        try:
            obs = self.blackboard.observation
            geo = self._classify_geo(obs)

            # 즉각 대응 (EIM 무관)
            if geo in ("HARD_DECK", "CLOSE_WEZ", "HEAD_ON"):
                strategy_map = {"HARD_DECK": "HARD_DECK", "CLOSE_WEZ": "SHOOT", "HEAD_ON": "DIVE_BREAK"}
                self.blackboard.selected_strategy = strategy_map[geo]
                return py_trees.common.Status.SUCCESS

            # EIM intent 읽기
            ego_id = str(obs.get("agent_id", ""))
            pred_intent, conf = shared_state.get_enemy_intent(ego_id)
            conf_val = conf.get(pred_intent, 0.0) if conf else 0.0

            dist = obs.get("distance_ft", 99999.0)

            if conf_val >= self.MIN_EIM_CONF and pred_intent != "UNKNOWN":
                strategy = self.STRATEGY_MAP.get(
                    (geo, pred_intent),
                    self.GEO_FALLBACK.get(geo, "PRESS_ATTACK")
                )
                # NEUTRAL + 원거리(>5000ft)에서만 TURN_FIGHT 허용
                # NEUTRAL + 근거리(<5000ft)에서는 EIM 무관 PRESS_ATTACK
                if geo == "NEUTRAL" and dist < self.NEUTRAL_CLOSE_THRESHOLD_FT:
                    strategy = "PRESS_ATTACK"
            else:
                strategy = self.GEO_FALLBACK.get(geo, "PRESS_ATTACK")

            self.blackboard.selected_strategy = strategy
            return py_trees.common.Status.SUCCESS

        except Exception as e:
            logger.warning(f"SelectStrategy error: {e}")
            self.blackboard.selected_strategy = "TURN_FIGHT"
            return py_trees.common.Status.SUCCESS  # 항상 SUCCESS
