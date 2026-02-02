# 노드 레퍼런스

행동트리에서 사용 가능한 모든 노드 목록입니다.

> 📝 **파라미터 상세 정보**: [파라미터 레퍼런스](PARAMETER_REFERENCE.md)에서 모든 파라미터의 상세 설명과 튜닝 가이드를 확인하세요.

---

## 복합 노드 (Composites)

| 노드 | 설명 | 파라미터 |
|-----|------|---------|
| `Selector` | 자식 중 하나 성공 시 성공 (OR) | - |
| `Sequence` | 모든 자식 성공 시 성공 (AND) | - |
| `Parallel` | 자식 동시 실행 | `policy`: `SuccessOnOne`, `SuccessOnAll` |

---

## 조건 노드 (Conditions)

### 거리/위치 조건

| 노드 | 설명 | 파라미터 |
|-----|------|---------|
| `DistanceBelow` | 거리가 임계값 이하 | `threshold` (m) |
| `DistanceAbove` | 거리가 임계값 이상 | `threshold` (m) |
| `EnemyInFront` | 적이 전방에 있음 | `angle_threshold` |
| `EnemyBehind` | 적이 후방에 있음 | `angle_threshold` |

### 고도/속도 조건

| 노드 | 설명 | 파라미터 |
|-----|------|---------|
| `AltitudeAbove` | 고도가 지정값 이상 | `min_altitude` (m) |
| `AltitudeBelow` | 고도가 지정값 이하 | `min_altitude` (m) |
| `BelowHardDeck` | Hard Deck 위반 위험 | `threshold` (m) |
| `VelocityAbove` | 속도가 지정값 이상 | `min_velocity` (m/s) |
| `VelocityBelow` | 속도가 지정값 이하 | `max_velocity` (m/s) |

### BFM 상황 조건

| 노드 | 설명 | 파라미터 |
|-----|------|---------|
| `IsOffensiveSituation` | 공격 BFM 상황 (유리) | - |
| `IsDefensiveSituation` | 방어 BFM 상황 (불리) | - |
| `IsNeutralSituation` | 중립 BFM 상황 (대등) | - |
| `UnderThreat` | 위협 상황 (AA 기반) | `aa_threshold` (°) |
| `InEnemyWEZ` | 적 WEZ 내에 있음 | `max_distance`, `max_los_angle` |
| `IsMerged` | Merge 상태 (근접 교전) | `merge_threshold` |

### 각도 조건

| 노드 | 설명 | 파라미터 |
|-----|------|---------|
| `ATAAbove` | ATA가 임계값 이상 | `threshold` (°) |
| `ATABelow` | ATA가 임계값 이하 | `threshold` (°) |
| `LOSAbove` | LOS 각도가 임계값 이상 | `threshold` (°) |
| `LOSBelow` | LOS 각도가 임계값 이하 | `threshold` (°) |

### 에너지/기동 조건

| 노드 | 설명 | 파라미터 |
|-----|------|---------|
| `EnergyHigh` | 에너지 상태가 높음 | - |
| `HasSuperior` | 우위 상태 | - |
| `NotSuperior` | 우위 상태 아님 | - |

---

## 액션 노드 (Actions)

### 기본 기동

| 노드 | 설명 | 파라미터 |
|-----|------|---------|
| `Pursue` | 적 추적 (고수준) | [상세 파라미터](PARAMETER_REFERENCE.md#pursue---적-추적) |
| `Evade` | 적 회피 | - |
| `ClimbTo` | 목표 고도로 상승 | `target_altitude` (m) |
| `DescendTo` | 목표 고도로 하강 | `target_altitude` (m) |
| `MaintainAltitude` | 고도 유지 | - |
| `Accelerate` | 가속 | - |
| `Decelerate` | 감속 | - |
| `TurnLeft` | 좌회전 | `intensity` (1-3) |
| `TurnRight` | 우회전 | `intensity` (1-3) |
| `Straight` | 직진 | - |

### 추적 기동

| 노드 | 설명 | 파라미터 |
|-----|------|---------|
| `PurePursuit` | 순수 추적 (현재 위치) | - |
| `LeadPursuit` | 선도 추적 (예측 위치) | - |
| `LagPursuit` | 후방 추적 (에너지 보존) | - |

### 방어 기동

| 노드 | 설명 | 파라미터 |
|-----|------|---------|
| `DefensiveManeuver` | 방어 기동 | [상세 파라미터](PARAMETER_REFERENCE.md#defensivemaneuver---방어-기동) |
| `BreakTurn` | 급선회 회피 | - |
| `DefensiveSpiral` | 방어 나선 | - |
| `AltitudeAdvantage` | 고도 우위 확보 | `target_advantage` (m) |

### 에너지 기동

| 노드 | 설명 | 파라미터 |
|-----|------|---------|
| `HighYoYo` | 고고도 요요 | - |
| `LowYoYo` | 저고도 요요 | - |
| `ClimbingTurn` | 상승 선회 | `direction` |
| `DescendingTurn` | 하강 선회 | `direction` |
| `BarrelRoll` | 배럴 롤 | `direction` |

### 전투 기동

| 노드 | 설명 | 파라미터 |
|-----|------|---------|
| `OneCircleFight` | 1서클 전투 | - |
| `TwoCircleFight` | 2서클 전투 | - |
| `GunAttack` | Gun WEZ 정밀 조준 | - |

---

## YAML 사용 예제

```yaml
# 조건 노드 사용
- type: Condition
  name: DistanceBelow
  params:
    threshold: 1500

# 액션 노드 사용
- type: Action
  name: LeadPursuit

# 파라미터가 있는 액션
- type: Action
  name: ClimbTo
  params:
    target_altitude: 5000
```

---

## 파라미터 튜닝 가이드

모든 파라미터는 기본값이 설정되어 있어 **생략 가능**합니다. 전술에 맞게 필요한 파라미터만 조정하세요.

```yaml
# 공격적 전술 예시
- type: Action
  name: Pursue
  params:
    close_range: 2500      # 더 넓은 근거리 판정
    bearing_straight: 3    # 더 정밀한 조준
    ata_lost: 45           # 더 빠른 회전 반응

# 방어적 전술 예시
- type: Action
  name: DefensiveManeuver
  params:
    critical_aa_threshold: 60  # 더 일찍 급회피
    danger_aa_threshold: 100   # 더 넓은 위험 범위
```

상세한 파라미터 설명은 **[파라미터 레퍼런스](PARAMETER_REFERENCE.md)**를 참조하세요.

---

## 주요 용어

| 용어 | 설명 |
|-----|------|
| **ATA** | Antenna Train Angle - 내 속도 벡터와 적 방향 사이 각도 |
| **AA** | Aspect Angle - 적 기준 내 위치 각도 |
| **HCA** | Heading Crossing Angle - 두 기체의 진행 방향 각도 |
| **WEZ** | Weapon Engagement Zone - 무기 유효 영역 |
| **BFM** | Basic Fighter Maneuvers - 기본 전투기 기동 |
| **Hard Deck** | 최저 안전 고도 (위반 시 패배) |
