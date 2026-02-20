# 노드 & 파라미터 레퍼런스

행동트리에서 사용 가능한 모든 노드와 파라미터 상세 설명입니다.

> **� 팁**: 모든 파라미터는 기본값이 설정되어 있어 생략 가능합니다. 전술에 맞게 필요한 파라미터만 조정하세요.

---

## 고수준 액션 공간 (5×9×5)

모든 액션 노드는 내부적으로 아래 3개의 이산 인덱스를 `Blackboard`에 설정합니다.

| 축 | 인덱스 | 의미 |
|----|--------|------|
| **delta_altitude** (5) | 0=급하강, 1=하강, 2=유지, 3=상승, 4=급상승 | 고도 변화 명령 |
| **delta_heading** (9) | 0=급좌(-90°) ~ 4=직진 ~ 8=급우(+90°) | 방향 변화 명령 |
| **delta_velocity** (5) | 0=급감속, 1=감속, 2=유지, 3=가속, 4=급가속 | 속도 변화 명령 |

---

## 복합 노드 (Composites)

| 노드 | 설명 |
|-----|------|
| `Selector` | 자식 중 하나 성공 시 성공 (OR 논리) |
| `Sequence` | 모든 자식 성공 시 성공 (AND 논리) |

---

## 조건 노드 (Conditions)

### 거리 조건

| 노드 | 기본값 | 파라미터 | 설명 |
|-----|--------|---------|------|
| `EnemyInRange` | `max_distance=5000.0` | `max_distance` (m) | 적이 지정 거리 이내 |
| `DistanceBelow` | `threshold=3000.0` | `threshold` (m) | 거리 < 임계값 |
| `DistanceAbove` | `threshold=2000.0` | `threshold` (m) | 거리 > 임계값 |

### 고도/속도 조건

| 노드 | 기본값 | 파라미터 | 설명 |
|-----|--------|---------|------|
| `AltitudeAbove` | `min_altitude=3000.0` | `min_altitude` (m) | 고도 ≥ 지정값 |
| `AltitudeBelow` | `min_altitude=1000.0` | `min_altitude` (m) | 고도 ≤ 지정값 |
| `BelowHardDeck` | `threshold=1000.0` | `threshold` (m) | 고도 < 임계값 (Hard Deck 위반 위험) |
| `VelocityAbove` | `min_velocity=200.0` | `min_velocity` (m/s) | 속도 ≥ 지정값 |
| `VelocityBelow` | `max_velocity=400.0` | `max_velocity` (m/s) | 속도 ≤ 지정값 |

> ⚠️ **Hard Deck**: 고도 500m 이하 시 즉시 패배. `BelowHardDeck` + `ClimbTo`를 행동트리 최상단에 배치하세요.

### BFM 상황 조건

BFM 상황은 `CombatGeometry`(ATA, AA, HCA)를 기반으로 자동 분류됩니다.

| 노드 | 분류 기준 | 설명 |
|-----|----------|------|
| `IsOffensiveSituation` | ATA<45°, AA<100°, 거리 0.3~3NM | OBFM - 공격 유리 상황 |
| `IsDefensiveSituation` | AA>120°, ATA>90° | DBFM - 방어 필요 상황 |
| `IsNeutralSituation` | HCA<90°, 동일 고도 | HABFM - 정면/고측면 대등 상황 |

### 각도 조건

| 노드 | 기본값 | 파라미터 | 설명 |
|-----|--------|---------|------|
| `ATAAbove` | `threshold=60.0` | `threshold` (°) | ATA > 임계값 (적이 측면/후방) |
| `ATABelow` | `threshold=30.0` | `threshold` (°) | ATA < 임계값 (적이 전방) |
| `UnderThreat` | `aa_threshold=120.0` | `aa_threshold` (°) | AA > 임계값 (적 정면 노출 위험) |
| `LOSAbove` | `threshold=15.0` | `threshold` (°) | LOS 각도 > 임계값 |
| `LOSBelow` | `threshold=15.0` | `threshold` (°) | LOS 각도 < 임계값 |
| `InEnemyWEZ` | `max_distance=3000.0`, `max_los_angle=30.0` | `max_distance` (m), `max_los_angle` (°) | 적 WEZ 내에 있음 |

> **ATA**: 0°=적이 정면, 90°=적이 측면, 180°=적이 후방  
> **AA**: 0°=내가 적 후방(안전), 180°=내가 적 정면(위험)

### 에너지 조건

| 노드 | 기본값 | 파라미터 | 설명 |
|-----|--------|---------|------|
| `EnergyHighPs` | `threshold=0.0` | `threshold` | Ps(Specific Excess Power) > 임계값 |
| `SpecificEnergyAbove` | `threshold=5000.0` | `threshold` | He(고도+v²/2g) ≥ 임계값 |
| `IsMerged` | `merge_threshold=500.0` | `merge_threshold` (m) | 거리 < 임계값 (근접 교전) |

---

## 액션 노드 (Actions)

### 기본 기동

| 노드 | 내부 액션 | 설명 |
|-----|----------|------|
| `MaintainAltitude` | `(2, 4, 2)` | 고도·방향·속도 모두 유지 |
| `Accelerate` | `(2, 4, 4)` | 급가속 |
| `Decelerate` | `(2, 4, 0)` | 급감속 |
| `Straight` | `(2, 4, 2)` | 직진 유지 |
| `TurnLeft` | `(2, 2, 2)` / `(2, 0, 2)` | 중좌회전 / `intensity="hard"` 시 급좌회전 |
| `TurnRight` | `(2, 6, 2)` / `(2, 8, 2)` | 중우회전 / `intensity="hard"` 시 급우회전 |

**파라미터:**
- `TurnLeft`, `TurnRight`: `intensity` — `"normal"` (기본) 또는 `"hard"`

### 고도 기동

| 노드 | 기본값 | 파라미터 | 설명 |
|-----|--------|---------|------|
| `ClimbTo` | `target_altitude=6000.0` | `target_altitude` (m) | 목표 고도로 상승/하강 |
| `DescendTo` | `target_altitude=4000.0` | `target_altitude` (m) | 목표 고도로 하강/상승 |
| `AltitudeAdvantage` | `target_advantage=500.0` | `target_advantage` (m) | 적보다 지정 고도 우위 유지 |

> `ClimbTo`/`DescendTo`는 고도차 >200m 시 급기동, >100m 시 일반기동, 이하 시 유지.

### 추적 기동 (OBFM)

#### `Pursue` — 적 추적 (종합 추적)

거리·고도·방위각·ATA를 종합 판단하여 최적 기동을 자동 선택합니다.

| 파라미터 | 기본값 | 설명 |
|---------|--------|------|
| `close_range` | 2000.0 m | 근중거리 판정 |
| `very_close_range` | 1500.0 m | 근거리 판정 |
| `far_range` | 4000.0 m | 원거리 판정 (이상 시 급가속) |
| `mid_far_range` | 2500.0 m | 중원거리 판정 |
| `alt_gap_fast` | 200.0 m | 급기동 고도차 임계값 |
| `alt_gap_normal` | 100.0 m | 일반기동 고도차 임계값 |
| `bearing_straight` | 5.0 ° | 직진 판정 방위각 |
| `bearing_hard` | 60.0 ° | 급회전 판정 방위각 |
| `bearing_strong` | 30.0 ° | 강회전 판정 방위각 |
| `bearing_medium` | 15.0 ° | 중회전 판정 방위각 |
| `ata_lost` | 60.0 ° | 적 놓침 판정 ATA (이상 시 급감속+급회전) |
| `ata_side` | 30.0 ° | 적 측면 판정 ATA (이상 시 감속) |

```yaml
# 공격적 추적
- type: Action
  name: Pursue
  params:
    close_range: 2500
    bearing_straight: 3
    ata_lost: 45

# 보수적 추적
- type: Action
  name: Pursue
  params:
    far_range: 5000
    alt_gap_fast: 300
```

#### `LeadPursuit` — 선도 추적

`relative_bearing_deg`와 `ata_deg` 기반으로 적의 미래 위치를 향해 선회합니다. Gun WEZ(±4°, 152~914m) 진입에 최적화.

#### `PurePursuit` — 순수 추적

`side_flag` 기반으로 적의 현재 위치를 향해 직접 추적합니다.

#### `LagPursuit` — 지연 추적

`tau_deg` 기반으로 적의 후방을 추적합니다. 오버슈트 방지 및 에너지 관리에 유리.

### 방어 기동 (DBFM)

#### `DefensiveManeuver` — AA 기반 방어 기동

| 파라미터 | 기본값 | 설명 |
|---------|--------|------|
| `critical_aa_threshold` | 45.0 ° | 매우 위험 AA 임계값 (이하 시 급회피) |
| `danger_aa_threshold` | 90.0 ° | 위험 AA 임계값 (이하 시 중간 회피) |
| `alt_gap_threshold` | 150.0 m | 고도 변경 임계값 |

```yaml
- type: Action
  name: DefensiveManeuver
  params:
    critical_aa_threshold: 60
    danger_aa_threshold: 100
```

#### `BreakTurn` — 급선회 회피

`side_flag` 반대 방향으로 급우/급좌회전 + 하강 + 급가속. 선회율 극대화.

#### `DefensiveSpiral` — 방어 나선

강선회 + 고도 조절 + 급가속으로 나선형 회피. 고도 1500m 이하 시 상승 전환.

### 에너지 기동

| 노드 | 파라미터 | 설명 |
|-----|---------|------|
| `ClimbingTurn` | `direction="left"/"right"/"auto"` | 상승하며 선회 (에너지 저장) |
| `DescendingTurn` | `direction="left"/"right"/"auto"` | 하강하며 선회 (속도 획득) |
| `BarrelRoll` | - | 나선형 상승↔하강 반복 회피 |
| `HighYoYo` | - | 급상승+급선회 → 하강+공격 (오버슈트 방지) |
| `LowYoYo` | - | 급하강+가속 → 상승+위치 우위 (속도 확보) |

> `direction="auto"`: `side_flag` 기반으로 적 방향 자동 선택

### 정면 교전 기동 (HABFM)

| 노드 | 설명 |
|-----|------|
| `OneCircleFight` | 적 방향으로 급선회 + 감속 (작은 반경, 선회 우위 시) |
| `TwoCircleFight` | 적 반대 방향으로 약선회 + 급가속 (큰 반경, 에너지 우위 시) |
| `GunAttack` | `relative_bearing_deg` 기반 정밀 조준 (Gun WEZ: ±4°, 152~914m) |

### 회피 기동

| 노드 | 설명 |
|-----|------|
| `Evade` | `side_flag` 반대 방향으로 강선회 + 가속 |

---

## YAML 사용 예제

```yaml
name: "my_agent"
description: "BFM 기반 전술"

tree:
  type: Selector
  children:
    # 1. Hard Deck 회피 (필수 - 최상단 배치)
    - type: Sequence
      children:
        - type: Condition
          name: BelowHardDeck
          params:
            threshold: 1000
        - type: Action
          name: ClimbTo
          params:
            target_altitude: 3000

    # 2. 공격 유리 상황 → 선도 추적
    - type: Sequence
      children:
        - type: Condition
          name: IsOffensiveSituation
        - type: Action
          name: LeadPursuit

    # 3. 방어 필요 상황 → 급선회 회피
    - type: Sequence
      children:
        - type: Condition
          name: IsDefensiveSituation
        - type: Action
          name: BreakTurn

    # 4. 기본 추적
    - type: Action
      name: Pursue
```

---

## 관측값 (Blackboard `observation`)

| 키 | 범위 | 설명 |
|----|------|------|
| `distance` | 0 ~ 20000 m | 적과의 거리 |
| `ego_altitude` | 0 ~ 15000 m | 내 고도 |
| `ego_vc` | 0 ~ 400 m/s | 내 속도 |
| `alt_gap` | -15000 ~ 15000 m | 고도 차이 (양수=적이 위) |
| `ata_deg` | 0 ~ 1 (정규화) | ATA / 180° (0=정면조준) |
| `aa_deg` | 0 ~ 1 (정규화) | AA / 180° (0=적 후방, 1=정면위협) |
| `hca_deg` | 0 ~ 1 (정규화) | HCA / 180° |
| `tau_deg` | -1 ~ 1 (정규화) | TAU / 180° |
| `relative_bearing_deg` | -1 ~ 1 (정규화) | 상대 방위각 / 180° (양수=오른쪽) |
| `side_flag` | -1, 0, 1 | 적 방향 (-1=왼쪽, 0=정면, 1=오른쪽) |

---

## 주요 용어

| 용어 | 설명 |
|-----|------|
| **ATA** | Antenna Train Angle — 내 속도 벡터와 적 방향 사이 각도 (0°=정면조준) |
| **AA** | Aspect Angle — 적 기준 내 위치 각도 (0°=적 후방 안전, 180°=정면 위협) |
| **HCA** | Heading Crossing Angle — 두 기체의 진행 방향 교차 각도 |
| **TAU** | 롤 각도를 고려한 목표 위치 각도 |
| **WEZ** | Weapon Engagement Zone — Gun WEZ: ±4°, 152~914m |
| **BFM** | Basic Fighter Maneuvers — OBFM(공격)/DBFM(방어)/HABFM(정면) |
| **Hard Deck** | 최저 안전 고도 500m (위반 시 즉시 패배) |
| **Ps** | Specific Excess Power — 기체의 잉여 에너지 (>0이면 가속/상승 여유 있음) |
