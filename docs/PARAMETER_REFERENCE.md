# 파라미터 레퍼런스

YAML에서 조정 가능한 모든 노드 파라미터의 상세 설명입니다.

> **💡 팁**: 모든 파라미터는 기본값이 설정되어 있어 생략 가능합니다. 전술에 맞게 필요한 파라미터만 조정하세요.

---

## 조건 노드 (Conditions)

### 거리/위치 조건

#### `EnemyInRange`
적이 지정 거리 내에 있는지 확인합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `max_distance` | float | 5000.0 | 최대 거리 (m) |

```yaml
- type: Condition
  name: EnemyInRange
  params:
    max_distance: 3000  # 3km 이내
```

#### `DistanceBelow` / `DistanceAbove`
거리가 임계값 이하/이상인지 확인합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `threshold` | float | 3000.0 / 2000.0 | 거리 임계값 (m) |

#### `InEnemyWEZ`
적의 무기 사거리(WEZ) 내에 있는지 확인합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `max_distance` | float | 3000.0 | WEZ 최대 거리 (m) |
| `max_los_angle` | float | 30.0 | WEZ 최대 LOS 각도 (°) |

```yaml
- type: Condition
  name: InEnemyWEZ
  params:
    max_distance: 2500
    max_los_angle: 25
```

#### `IsMerged`
Merge 상태(근접 교전)인지 확인합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `merge_threshold` | float | 500.0 | Merge 판정 거리 (m) |

---

### 고도/속도 조건

#### `AltitudeAbove` / `AltitudeBelow`
고도가 지정값 이상/이하인지 확인합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `min_altitude` | float | 3000.0 / 1000.0 | 고도 임계값 (m) |

#### `BelowHardDeck`
Hard Deck(최저 안전 고도) 위반 위험을 확인합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `threshold` | float | 1000.0 | Hard Deck 고도 (m) |

> ⚠️ **중요**: Hard Deck 위반 시 즉시 패배합니다. 반드시 회피 로직을 포함하세요!

#### `VelocityAbove` / `VelocityBelow`
속도가 지정값 이상/이하인지 확인합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `min_velocity` / `max_velocity` | float | 200.0 / 400.0 | 속도 임계값 (m/s) |

---

### 각도 조건

#### `ATAAbove` / `ATABelow`
ATA(Antenna Train Angle)가 임계값 이상/이하인지 확인합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `threshold` | float | 60.0 / 30.0 | ATA 임계값 (°) |

> **ATA 설명**: 내 속도 벡터와 적 방향 사이 각도
> - 0° = 적이 정면
> - 90° = 적이 측면
> - 180° = 적이 후방

#### `UnderThreat`
위협 상황(AA 기반)인지 확인합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `aa_threshold` | float | 120.0 | AA 위협 임계값 (°) |

> **AA 설명**: 적 기준 내 위치 각도
> - AA < 60° = 안전 (적 후방)
> - AA > 120° = 위험 (적 정면 노출)

---

### 에너지 조건

#### `EnergyHighPs`
Specific Excess Power(Ps) 기반 에너지 상태를 확인합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `threshold` | float | 0.0 | Ps 임계값 |

#### `SpecificEnergyAbove`
전체 에너지(He = 고도 + v²/2g)가 임계값 이상인지 확인합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `threshold` | float | 5000.0 | 비에너지 임계값 |

---

## 액션 노드 (Actions)

### `Pursue` - 적 추적
고수준 적 추적 기동입니다. 거리, 고도, 방위각에 따라 자동으로 최적의 기동을 선택합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| **거리 임계값** ||||
| `close_range` | float | 2000.0 | 근중거리 판정 (m) |
| `very_close_range` | float | 1500.0 | 근거리 판정 (m) |
| `far_range` | float | 4000.0 | 원거리 판정 (m) |
| `mid_far_range` | float | 2500.0 | 중원거리 판정 (m) |
| **고도 임계값** ||||
| `alt_gap_fast` | float | 200.0 | 급기동 고도차 (m) |
| `alt_gap_normal` | float | 100.0 | 일반 기동 고도차 (m) |
| **방위각 임계값** ||||
| `bearing_straight` | float | 5.0 | 직진 판정 각도 (°) |
| `bearing_hard` | float | 60.0 | 급회전 판정 각도 (°) |
| `bearing_strong` | float | 30.0 | 강회전 판정 각도 (°) |
| `bearing_medium` | float | 15.0 | 중회전 판정 각도 (°) |
| **ATA 임계값** ||||
| `ata_lost` | float | 60.0 | 적 놓침 판정 ATA (°) |
| `ata_side` | float | 30.0 | 적 측면 판정 ATA (°) |

```yaml
# 공격적 추적 설정
- type: Action
  name: Pursue
  params:
    close_range: 2500      # 더 넓은 근거리 판정
    bearing_straight: 3    # 더 정밀한 조준
    ata_lost: 45           # 더 빠른 회전 반응

# 보수적 추적 설정
- type: Action
  name: Pursue
  params:
    far_range: 5000        # 더 먼 거리에서 가속
    alt_gap_fast: 300      # 더 큰 고도차에서 급기동
```

---

### `DefensiveManeuver` - 방어 기동
AA 기반 방어 기동입니다. 적의 조준선에서 벗어나는 회피 기동을 수행합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `critical_aa_threshold` | float | 45.0 | 매우 위험 AA 임계값 (°) |
| `danger_aa_threshold` | float | 90.0 | 위험 AA 임계값 (°) |
| `alt_gap_threshold` | float | 150.0 | 고도 변경 임계값 (m) |

```yaml
# 더 민감한 방어 설정
- type: Action
  name: DefensiveManeuver
  params:
    critical_aa_threshold: 60  # 더 일찍 급회피
    danger_aa_threshold: 100   # 더 넓은 위험 범위
```

---

### `ClimbTo` / `DescendTo` - 고도 변경
목표 고도로 상승/하강합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `target_altitude` | float | 6000.0 / 4000.0 | 목표 고도 (m) |

---

### `AltitudeAdvantage` - 고도 우위 확보
적보다 높은 고도를 유지하여 에너지 우위를 확보합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `target_advantage` | float | 500.0 | 목표 고도 우위 (m) |

---

### `TurnLeft` / `TurnRight` - 선회
좌/우 선회를 수행합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `intensity` | str | "normal" | 선회 강도 ("normal", "hard") |

---

### `ClimbingTurn` / `DescendingTurn` - 상승/하강 선회
상승 또는 하강하면서 선회합니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `direction` | str | "left" | 선회 방향 ("left", "right", "auto") |

---

## 커스텀 노드 파라미터

참가자가 커스텀 노드를 작성할 경우, `__init__` 메서드에 파라미터를 추가하면 YAML에서 조정할 수 있습니다.

### 예시: 커스텀 액션 노드

```python
# submissions/my_agent/nodes/custom_actions.py
class MyCustomAttack(BaseAction):
    def __init__(self, name: str = "MyCustomAttack",
                 attack_range: float = 1500.0,
                 aggression: float = 0.8):
        super().__init__(name)
        self.attack_range = attack_range
        self.aggression = aggression
    
    def update(self):
        # self.attack_range, self.aggression 사용
        ...
```

```yaml
# submissions/my_agent/my_agent.yaml
- type: Action
  name: MyCustomAttack
  params:
    attack_range: 2000
    aggression: 0.9
```

---

## 전술별 파라미터 튜닝 가이드

### 🔥 공격적 전술
```yaml
params:
  close_range: 2500      # 더 넓은 교전 범위
  bearing_straight: 3    # 정밀 조준
  ata_lost: 45           # 빠른 반응
```

### 🛡️ 방어적 전술
```yaml
params:
  far_range: 5000        # 먼 거리 유지
  critical_aa_threshold: 60  # 민감한 위협 감지
  alt_gap_threshold: 200     # 적극적 고도 변경
```

### ⚡ 에너지 전투 전술
```yaml
params:
  alt_gap_fast: 300      # 큰 고도차 활용
  target_advantage: 800  # 높은 고도 우위
```

---

## 관련 문서

- [NODE_REFERENCE.md](NODE_REFERENCE.md) - 전체 노드 목록
- [QUICK_START.md](QUICK_START.md) - 빠른 시작 가이드
- [examples/](../../examples/) - 예제 에이전트
