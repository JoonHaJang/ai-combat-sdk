# 커스텀 노드 가이드

> 최종 갱신: 2026-04-09
> 목적: 커스텀 BT 노드 작성 규칙 + optimizer 자동 연동 패턴

---

## 1. 시스템 구조

```
BT Loader (src/behavior_tree/loader.cp314-win_amd64.pyd)
  ↓ YAML 파싱
  ↓ 노드 name으로 클래스 탐색
  ↓ 탐색 순서:
  ↓   1. agent_dir/nodes/__init__.py 의 import된 클래스
  ↓   2. pyd 빌트인 (actions.pyd, conditions.pyd)
  ↓
  ↓ 일치하는 클래스 발견 → 인스턴스 생성 (**params를 __init__에 전달)
  ↓ 미발견 → 에러 없이 무시 (조용한 실패)
```

**핵심: pyd 빌트인과 동명 클래스를 만들면 빌트인이 우선하여 커스텀이 무시됨 (BUG-4 사례)**

---

## 2. 파일 구조 (필수)

```
my_agent/
├── my_agent.yaml           # BT 정의 (name 필드로 노드 참조)
└── nodes/
    ├── __init__.py          # 모든 커스텀 클래스 명시적 import ← 필수
    ├── custom_actions.py    # BaseAction 상속 액션 노드
    └── custom_conditions.py # py_trees.behaviour.Behaviour 상속 조건 노드
```

**YAML 파일 위치가 중요: loader는 YAML과 같은 디렉토리의 `nodes/`를 탐색.**
→ temp YAML을 `logs/temp/`에 만들면 커스텀 노드 로딩 실패.
→ 반드시 `examples/adaptive_eagle/` 안에 생성해야 함.

---

## 3. 액션 노드 작성법

```python
import py_trees

class BaseAction(py_trees.behaviour.Behaviour):
    """모든 커스텀 액션의 베이스."""
    def __init__(self, name: str):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="action", access=py_trees.common.Access.WRITE)

    def set_action(self, alt_idx: int, hdg_idx: int, vel_idx: int):
        """액션 출력: [0-4, 0-8, 0-4]"""
        self.blackboard.action = [alt_idx, hdg_idx, vel_idx]


class MyAction(BaseAction):
    """YAML에서 name: MyAction 으로 참조."""

    # optimizer 자동 연동용 (Phase 3b+)
    TUNABLE_PARAMS = {
        "my_param": {"type": "cont", "range": (0.5, 2.0), "default": 1.0},
        "my_choice": {"type": "disc", "choices": [2, 3, 4], "default": 3},
    }

    def __init__(self, name: str = "MyAction", my_param: float = 1.0, my_choice: int = 3):
        super().__init__(name)
        self.my_param = my_param
        self.my_choice = my_choice

    def update(self) -> py_trees.common.Status:
        obs = self.blackboard.observation
        # 관측값 읽기 (단위 변환 주의)
        ata = obs.get("ata_deg", 0.5) * 180.0     # 0~1 → 0~180°
        dist = obs.get("distance_ft", 10000.0)     # 변환 불필요
        # 액션 출력
        self.set_action(2, 4, self.my_choice)
        return py_trees.common.Status.SUCCESS
```

---

## 4. 조건 노드 작성법

```python
class MyCondition(py_trees.behaviour.Behaviour):
    """YAML에서 name: MyCondition 으로 참조."""

    TUNABLE_PARAMS = {
        "threshold": {"type": "cont", "range": (50.0, 150.0), "default": 90.0},
    }

    def __init__(self, name: str = "MyCondition", threshold: float = 90.0):
        super().__init__(name)
        self.threshold = threshold
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)

    def update(self) -> py_trees.common.Status:
        obs = self.blackboard.observation
        val = obs.get("ata_deg", 0.5) * 180.0
        if val > self.threshold:
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.FAILURE
```

---

## 5. 관측값 단위 참조

### 각도 (0~1 정규화 → ×180 필수)

| 키 | 원본 범위 | 변환 | 실제 의미 |
|---|---|---|---|
| `ata_deg` | 0~1 | ×180 → 0~180° | 적과의 조준각 (0=정면) |
| `aa_deg` | 0~1 | ×180 → 0~180° | 적 관점 내 위치 (0=적 후방, 180=적 정면) |
| `hca_deg` | 0~1 | ×180 → 0~180° | 진행방향 교차각 |
| `tau_deg` | -1~1 | ×180 → -180~180° | 롤 보정 목표각 |
| `relative_bearing_deg` | -1~1 | ×180 → -180~180° | 상대 방위 (음=좌, 양=우) |

### 그 외 (변환 불필요)

| 키 | 단위 | 설명 |
|---|---|---|
| `distance_ft` | ft | 적과의 거리 |
| `ego_altitude_ft` | ft | 내 고도 |
| `ego_vc_kts` | kts | 내 속도 |
| `closure_rate_kts` | kts | 접근 속도 (양수=접근) |
| `turn_rate_degs` | °/s | 선회율 |
| `specific_energy_ft` | ft | 비에너지 (h + v²/2g) |
| `ps_fts` | ft/s | 잉여출력 |
| `alt_gap_ft` | ft | 고도차 (양수=적이 위) |
| `energy_diff_ft` | ft | 에너지차 (양수=아군 우세) |

### Bool / 이산

| 키 | 타입 | 설명 |
|---|---|---|
| `energy_advantage` | bool | 종합 에너지 우세 |
| `alt_advantage` | bool | 고도 우세 |
| `spd_advantage` | bool | 속도 우세 |
| `in_39_line` | bool | 적이 3-9 라인 내 (ATA<90°) |
| `overshoot_risk` | bool | 오버슈트 위험 |
| `in_wez` | bool | 적이 내 WEZ 내 |
| `enm_in_wez` | bool | 내가 적 WEZ 내 |
| `side_flag` | -1/0/1 | 적 방향 (좌/정면/우) |
| `tc_type` | str | "1-circle" / "2-circle" |
| `bfm_situation` | str | OBFM/DBFM/HABFM/UNKNOWN |

---

## 6. 액션 공간

```
set_action(alt_idx, hdg_idx, vel_idx)

alt_idx (0-4): 0=급하강, 1=하강, 2=유지, 3=상승, 4=급상승
hdg_idx (0-8): 0=급좌(-90°), 2=좌(-45°), 4=직진(0°), 6=우(+45°), 8=급우(+90°)
vel_idx (0-4): 0=급감속, 1=감속, 2=유지, 3=가속, 4=급가속

조향 단위: 22.5° (hdg_idx 1단계 = 22.5°)
WEZ: ATA<12° → 22.5° 단위보다 좁음 → PD 제어로 정밀 보정 필요
```

---

## 7. Heading 유틸리티 함수

```python
def _heading_from_tau(tau_deg: float, gain: float = 1.0) -> int:
    """tau(°) → heading index [0-8]. tau 기반 추적."""
    cmd = tau_deg * gain
    return max(0, min(8, int(round(cmd / 22.5)) + 4))

def _heading_from_bearing(bearing_deg: float, gain: float = 1.0) -> int:
    """relative_bearing(°) → heading index [0-8]. 방위 기반 추적."""
    cmd = bearing_deg * gain
    return max(0, min(8, int(round(cmd / 22.5)) + 4))
```

---

## 8. YAML 참조 방법

```yaml
# 커스텀 액션
- type: Action
  name: MyAction           # ← __init__.py에 import된 클래스명과 정확히 일치
  params:
    my_param: 1.5          # ← __init__(self, name, my_param=1.0) 의 파라미터명
    my_choice: 4

# 커스텀 조건
- type: Condition
  name: MyCondition
  params:
    threshold: 85.0
```

**params 키가 __init__ 파라미터명과 불일치하면 기본값 사용 (에러 없음, 조용한 무시)**

---

## 9. 빌트인 노드 목록 (이름 충돌 금지)

### 조건 노드 (pyd)

```
EnemyInRange, DistanceBelow, DistanceAbove,
AltitudeAbove, AltitudeBelow, BelowHardDeck,
VelocityAbove, VelocityBelow,
IsOffensiveSituation, IsDefensiveSituation, IsNeutralSituation,
ATAAbove, ATABelow, UnderThreat,
LOSAbove, LOSBelow, InEnemyWEZ,
EnergyHighPs, SpecificEnergyAbove, IsMerged,
Is39Line, IsOvershootRisk, IsTargetInSight,
IsOneCircle, IsTwoCircle,
IsEnergyAdvantage, IsAltAdvantage, IsSpdAdvantage,
EnergyDiffAbove, ClosureRateAbove, ClosureRateBelow, TurnRateAbove,
IsCircularOrbit
```

### 액션 노드 (pyd)

```
MaintainAltitude, Accelerate, Decelerate, Straight,
TurnLeft, TurnRight,
ClimbTo, DescendTo, AltitudeAdvantage,
Pursue, LeadPursuit, PurePursuit, LagPursuit,
DefensiveManeuver, BreakTurn, DefensiveSpiral,
ClimbingTurn, DescendingTurn, BarrelRoll, HighYoYo, LowYoYo,
OneCircleFight, TwoCircleFight, GunAttack,
Evade,
OvershootAvoidance, EnergyFight, TCFight
```

---

## 10. 체크리스트 (노드 추가 시)

```
[ ] 클래스명이 빌트인 목록(Section 9)과 충돌하지 않는가
[ ] 각도 필드에 ×180 변환을 적용했는가
[ ] __init__ 파라미터명이 YAML params와 일치하는가
[ ] __init__.py에 import했는가
[ ] TUNABLE_PARAMS를 선언했는가 (optimizer 연동)
[ ] update()가 SUCCESS/FAILURE를 반환하는가
[ ] 예외 처리에서 안전한 기본 액션을 출력하는가
[ ] python tools/test_suite.py <agent> → 5/5 PASS
```

---

## 11. TUNABLE_PARAMS 패턴 (optimizer 자동 연동)

```python
class SmartGunAttack(BaseAction):
    # optimizer가 이 dict를 읽어서 탐색 공간에 자동 등록
    TUNABLE_PARAMS = {
        "kp":  {"type": "cont", "range": (0.5, 2.5), "default": 1.2},
        "kd":  {"type": "cont", "range": (0.1, 1.0), "default": 0.5},
    }
```

**type:**
- `"cont"` — 연속 파라미터, `range: (min, max)`, CMA-ES가 [0,1]로 인코딩
- `"disc"` — 이산 파라미터, `choices: [a, b, c]`, CMA-ES가 bin으로 인코딩

**default:** 빌트인 동등값 또는 현재 최선값. optimizer 시작점으로 사용.

**규칙:**
- range는 물리적으로 가능한 전체 범위로 설정 (이론으로 축소하지 않음)
- 빌트인의 고정값이 range 안에 포함되어야 함
- optimizer가 전체 공간을 탐색하므로 결과 ≥ 빌트인 보장

---

## 12. 제어 루프 요약

```
관측 (0.2초/tick, 5Hz)
  → BT tick (Selector 순회 → 첫 SUCCESS Action 실행)
  → set_action(alt, hdg, vel)
  → JSBSim 12 substep @ 60Hz
  → 새 관측

제약:
  - 0.2초 반응 지연 (350kts에서 36m/tick)
  - 22.5° 조향 단위 (WEZ 12°보다 넓음)
  - 적 기동 예측 불가 (0.2초 후 ATA 변화로 간접 감지)
```
