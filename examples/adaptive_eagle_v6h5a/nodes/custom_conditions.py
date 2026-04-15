"""
Adaptive Eagle 전체 BFM 커스텀 조건 노드

모든 조건에 TUNABLE_PARAMS → optimizer가 임계값을 자동 탐색.

카테고리:
  1. 기하학 조건: IsDefensiveGeometry, IsOffensiveGeometry, IsNeutralGeometry
  2. 에너지 조건: IsHighEnergy, IsLowEnergy
  3. 교전 조건: IsCloseCombat, IsWEZOpportunity, IsUnderFire
  4. 선회전 조건: IsOneCircleSituation, IsTwoCircleSituation
  5. 기타: CustomOrbitDetector, IsOvershooting
  6. EIM: EnemyIntentIs (re-export)
"""

from src.intent.bt_nodes import EnemyIntentIs

import logging
import py_trees

logger = logging.getLogger(__name__)


class _CondBase(py_trees.behaviour.Behaviour):
    """조건 노드 베이스."""
    def __init__(self, name):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)

    def _obs(self):
        return self.blackboard.observation

    def _ok(self):
        return py_trees.common.Status.SUCCESS

    def _no(self):
        return py_trees.common.Status.FAILURE


# ═══════════════════════════════════════════════════════════════
# 1. 기하학 조건
# ═══════════════════════════════════════════════════════════════

class IsDefensiveGeometry(_CondBase):
    """AO > threshold AND TA < threshold → 방어 필요."""
    TUNABLE_PARAMS = {
        "ao_min_deg": {"type": "cont", "range": (60, 150), "default": 90},
        "ta_max_deg": {"type": "cont", "range": (30, 120), "default": 70},
    }

    def __init__(self, name="IsDefensiveGeometry", ao_min_deg=90.0, ta_max_deg=70.0):
        super().__init__(name)
        self.ao_min = ao_min_deg
        self.ta_max = ta_max_deg

    def update(self):
        try:
            obs = self._obs()
            ao = obs.get("ata_deg", 0.5) * 180
            ta = obs.get("aa_deg", 0.5) * 180
            return self._ok() if ao > self.ao_min and ta < self.ta_max else self._no()
        except Exception:
            return self._no()


class IsOffensiveGeometry(_CondBase):
    """AO < threshold AND TA > threshold → 공격 유리."""
    TUNABLE_PARAMS = {
        "ao_max_deg": {"type": "cont", "range": (20, 60), "default": 45},
        "ta_min_deg": {"type": "cont", "range": (80, 150), "default": 100},
    }

    def __init__(self, name="IsOffensiveGeometry", ao_max_deg=45.0, ta_min_deg=100.0):
        super().__init__(name)
        self.ao_max = ao_max_deg
        self.ta_min = ta_min_deg

    def update(self):
        try:
            obs = self._obs()
            ao = obs.get("ata_deg", 0.5) * 180
            ta = obs.get("aa_deg", 0.5) * 180
            return self._ok() if ao < self.ao_max and ta > self.ta_min else self._no()
        except Exception:
            return self._no()


class IsNeutralGeometry(_CondBase):
    """AO 40~100° → 중립 (선회전 영역)."""
    TUNABLE_PARAMS = {
        "ao_min_deg": {"type": "cont", "range": (30, 60), "default": 40},
        "ao_max_deg": {"type": "cont", "range": (80, 130), "default": 100},
    }

    def __init__(self, name="IsNeutralGeometry", ao_min_deg=40.0, ao_max_deg=100.0):
        super().__init__(name)
        self.ao_min = ao_min_deg
        self.ao_max = ao_max_deg

    def update(self):
        try:
            obs = self._obs()
            ao = obs.get("ata_deg", 0.5) * 180
            return self._ok() if self.ao_min <= ao <= self.ao_max else self._no()
        except Exception:
            return self._no()


# ═══════════════════════════════════════════════════════════════
# 2. 에너지 조건
# ═══════════════════════════════════════════════════════════════

class IsHighEnergy(_CondBase):
    """에너지 우위 + 특정 에너지 차이 이상."""
    TUNABLE_PARAMS = {
        "energy_diff_min_ft": {"type": "cont", "range": (0, 5000), "default": 1000},
    }

    def __init__(self, name="IsHighEnergy", energy_diff_min_ft=1000.0):
        super().__init__(name)
        self.energy_diff_min = energy_diff_min_ft

    def update(self):
        try:
            obs = self._obs()
            e_adv = obs.get("energy_advantage", False)
            e_diff = obs.get("energy_diff_ft", 0)
            return self._ok() if e_adv and e_diff > self.energy_diff_min else self._no()
        except Exception:
            return self._no()


class IsLowEnergy(_CondBase):
    """에너지 열위."""
    TUNABLE_PARAMS = {
        "energy_diff_max_ft": {"type": "cont", "range": (-5000, 0), "default": -1000},
    }

    def __init__(self, name="IsLowEnergy", energy_diff_max_ft=-1000.0):
        super().__init__(name)
        self.energy_diff_max = energy_diff_max_ft

    def update(self):
        try:
            obs = self._obs()
            e_diff = obs.get("energy_diff_ft", 0)
            return self._ok() if e_diff < self.energy_diff_max else self._no()
        except Exception:
            return self._no()


# ═══════════════════════════════════════════════════════════════
# 3. 교전 조건
# ═══════════════════════════════════════════════════════════════

class IsCloseCombat(_CondBase):
    """거리 < threshold → 근접전."""
    TUNABLE_PARAMS = {
        "dist_max_ft": {"type": "cont", "range": (1000, 6000), "default": 3000},
    }

    def __init__(self, name="IsCloseCombat", dist_max_ft=3000.0):
        super().__init__(name)
        self.dist_max = dist_max_ft

    def update(self):
        try:
            return self._ok() if self._obs().get("distance_ft", 99999) < self.dist_max else self._no()
        except Exception:
            return self._no()


class IsWEZOpportunity(_CondBase):
    """WEZ 진입 가능 조건: ATA < threshold + 거리 범위."""
    TUNABLE_PARAMS = {
        "ata_max_deg":  {"type": "cont", "range": (5, 25), "default": 15},
        "dist_max_ft":  {"type": "cont", "range": (500, 2000), "default": 914},
        "dist_min_ft":  {"type": "cont", "range": (100, 300), "default": 152},
    }

    def __init__(self, name="IsWEZOpportunity", ata_max_deg=15.0,
                 dist_max_ft=914.0, dist_min_ft=152.0):
        super().__init__(name)
        self.ata_max = ata_max_deg
        self.dist_max = dist_max_ft
        self.dist_min = dist_min_ft

    def update(self):
        try:
            obs = self._obs()
            ata = obs.get("ata_deg", 1) * 180
            dist = obs.get("distance_ft", 99999)
            return self._ok() if ata < self.ata_max and self.dist_min < dist < self.dist_max else self._no()
        except Exception:
            return self._no()


class IsUnderFire(_CondBase):
    """적 WEZ 내에 있음."""
    TUNABLE_PARAMS = {}

    def __init__(self, name="IsUnderFire"):
        super().__init__(name)

    def update(self):
        try:
            return self._ok() if self._obs().get("enm_in_wez", False) else self._no()
        except Exception:
            return self._no()


# ═══════════════════════════════════════════════════════════════
# 4. 선회전 조건
# ═══════════════════════════════════════════════════════════════

class IsOneCircleSituation(_CondBase):
    """1-circle 선회 (HCA < 90°, 동방향)."""
    TUNABLE_PARAMS = {}

    def __init__(self, name="IsOneCircleSituation"):
        super().__init__(name)

    def update(self):
        try:
            return self._ok() if self._obs().get("tc_type", "") == "1-circle" else self._no()
        except Exception:
            return self._no()


class IsTwoCircleSituation(_CondBase):
    """2-circle 선회 (HCA > 90°, 역방향)."""
    TUNABLE_PARAMS = {}

    def __init__(self, name="IsTwoCircleSituation"):
        super().__init__(name)

    def update(self):
        try:
            return self._ok() if self._obs().get("tc_type", "") == "2-circle" else self._no()
        except Exception:
            return self._no()


# ═══════════════════════════════════════════════════════════════
# 5. 기타
# ═══════════════════════════════════════════════════════════════

class CustomOrbitDetector(_CondBase):
    """Circular orbit lock 감지. BUG-4 수정: 빌트인 IsCircularOrbit 이름 충돌 회피."""
    TUNABLE_PARAMS = {
        "ata_min_deg":        {"type": "cont", "range": (15, 60), "default": 35},
        "ata_max_deg":        {"type": "cont", "range": (60, 130), "default": 85},
        "closure_abs_max_kts": {"type": "cont", "range": (50, 400), "default": 200},
        "dist_min_ft":        {"type": "cont", "range": (1000, 5000), "default": 2000},
    }

    def __init__(self, name="CustomOrbitDetector", ata_min_deg=35.0, ata_max_deg=85.0,
                 closure_abs_max_kts=200.0, dist_min_ft=2000.0):
        super().__init__(name)
        self.ata_min = ata_min_deg
        self.ata_max = ata_max_deg
        self.closure_abs_max = closure_abs_max_kts
        self.dist_min = dist_min_ft

    def update(self):
        try:
            obs = self._obs()
            ata = obs.get("ata_deg", 0.5) * 180
            closure = obs.get("closure_rate_kts", 999)
            dist = obs.get("distance_ft", 0)
            if self.ata_min <= ata <= self.ata_max and abs(closure) < self.closure_abs_max and dist > self.dist_min:
                return self._ok()
            return self._no()
        except Exception:
            return self._no()


class IsOvershooting(_CondBase):
    """오버슈트 위험 감지."""
    TUNABLE_PARAMS = {
        "closure_min_kts": {"type": "cont", "range": (100, 400), "default": 200},
        "dist_max_ft":     {"type": "cont", "range": (500, 3000), "default": 1500},
    }

    def __init__(self, name="IsOvershooting", closure_min_kts=200.0, dist_max_ft=1500.0):
        super().__init__(name)
        self.closure_min = closure_min_kts
        self.dist_max = dist_max_ft

    def update(self):
        try:
            obs = self._obs()
            closure = obs.get("closure_rate_kts", 0)
            dist = obs.get("distance_ft", 99999)
            overshoot = obs.get("overshoot_risk", False)
            return self._ok() if overshoot or (closure > self.closure_min and dist < self.dist_max) else self._no()
        except Exception:
            return self._no()


# ═══════════════════════════════════════════════════════════════
# 6. Rigid-behavior 감지 조건 (v5.1 피드백 분석 기반)
# ═══════════════════════════════════════════════════════════════

class IsLostPursuit(_CondBase):
    """추격 실패: ATA가 큼(적이 뒤/측면) + closure 음수(벌어지는 중) + 일정 거리 이상.

    발동 조건: ATA > ata_min AND closure < closure_max AND dist > dist_min
    H1: dist 조건 추가 — 근접 교차(cross-merge) 순간의 false positive 제거.
    """
    TUNABLE_PARAMS = {
        "ata_min_deg":    {"type": "cont", "range": (90, 150), "default": 120},
        "closure_max_kts": {"type": "cont", "range": (-200, 0), "default": -50},
        "dist_min_ft":    {"type": "cont", "range": (1000, 4000), "default": 2000},
    }

    def __init__(self, name="IsLostPursuit", ata_min_deg=120.0,
                 closure_max_kts=-50.0, dist_min_ft=2000.0):
        super().__init__(name)
        self.ata_min = ata_min_deg
        self.closure_max = closure_max_kts
        self.dist_min = dist_min_ft

    def update(self):
        try:
            obs = self._obs()
            ata = obs.get("ata_deg", 0.5) * 180
            closure = obs.get("closure_rate_kts", 0)
            dist = obs.get("distance_ft", 99999)
            return self._ok() if (ata > self.ata_min
                                  and closure < self.closure_max
                                  and dist > self.dist_min) else self._no()
        except Exception:
            return self._no()


class IsChaseStale(_CondBase):
    """추격 정체: closure 평균 < stale_closure_max (v6h2 버전).

    H2 상태 유지. eagle2 DRAW 이슈 있음 (비교 baseline용).
    """
    TUNABLE_PARAMS = {
        "streak_len":       {"type": "disc", "choices": [20, 30, 50], "default": 30},
        "stale_closure_max": {"type": "cont", "range": (-100, 50), "default": 0},
    }

    def __init__(self, name="IsChaseStale", streak_len=30, stale_closure_max=0.0):
        super().__init__(name)
        self.streak_len = streak_len
        self.stale_closure_max = stale_closure_max
        self._buf = []

    def update(self):
        try:
            obs = self._obs()
            closure = obs.get("closure_rate_kts", 0)
            self._buf.append(closure)
            if len(self._buf) > self.streak_len:
                self._buf = self._buf[-self.streak_len:]
            if len(self._buf) < self.streak_len:
                return self._no()
            avg = sum(self._buf) / len(self._buf)
            return self._ok() if avg < self.stale_closure_max else self._no()
        except Exception:
            return self._no()


class IsExtensionFailing(_CondBase):
    """Extension 실패: ATA가 빠르게 증가 중.

    시계열 ATA의 변화율을 측정. 2초 사이 10° 이상 증가하면 failing.
    """
    TUNABLE_PARAMS = {
        "window_ticks":   {"type": "disc", "choices": [10, 20, 30], "default": 10},
        "ata_delta_min":  {"type": "cont", "range": (5, 30), "default": 10},
    }

    def __init__(self, name="IsExtensionFailing", window_ticks=10, ata_delta_min=10.0):
        super().__init__(name)
        self.window_ticks = window_ticks
        self.ata_delta_min = ata_delta_min
        self._buf = []

    def update(self):
        try:
            obs = self._obs()
            ata = obs.get("ata_deg", 0.5) * 180
            self._buf.append(ata)
            if len(self._buf) > self.window_ticks:
                self._buf = self._buf[-self.window_ticks:]
            if len(self._buf) < self.window_ticks:
                return self._no()
            delta = self._buf[-1] - self._buf[0]
            return self._ok() if delta > self.ata_delta_min else self._no()
        except Exception:
            return self._no()
