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
| `EnemyInRange` | `max_distance_ft=16404.0` | `max_distance_ft` (ft) | 적이 지정 거리 이내 |
| `DistanceBelow` | `threshold_ft=9843.0` | `threshold_ft` (ft) | 거리 < 임계값 |
| `DistanceAbove` | `threshold_ft=6562.0` | `threshold_ft` (ft) | 거리 > 임계값 |

### 고도/속도 조건

| 노드 | 기본값 | 파라미터 | 설명 |
|-----|--------|---------|------|
| `AltitudeAbove` | `min_altitude_ft=9843.0` | `min_altitude_ft` (ft) | 고도 ≥ 지정값 |
| `AltitudeBelow` | `min_altitude_ft=3281.0` | `min_altitude_ft` (ft) | 고도 ≤ 지정값 |
| `BelowHardDeck` | `threshold_ft=1000.0` | `threshold_ft` (ft) | 고도 < 임계값 (Hard Deck 위반 위험) |
| `VelocityAbove` | `min_velocity_kts=389.0` | `min_velocity_kts` (kts) | 속도 ≥ 지정값 |
| `VelocityBelow` | `max_velocity_kts=778.0` | `max_velocity_kts` (kts) | 속도 ≤ 지정값 |

> ⚠️ **Hard Deck**: 고도 1000ft 이하 시 즉시 패배. `BelowHardDeck` + `ClimbTo`를 행동트리 최상단에 배치하세요.

### BFM 상황 조건

BFM 상황은 `CombatGeometry`(ATA, AA, HCA, 에너지, TC타입)를 기반으로 자동 분류됩니다.

| 노드 | 분류 기준 | 설명 |
|-----|----------|------|
| `IsOffensiveSituation` | ATA<45°, AA<100°, 거리 0.3~3NM + 에너지/3-9Line 우세 | OBFM - 공격 유리 상황 |
| `IsDefensiveSituation` | AA>90°, ATA>60° 또는 에너지 열세+접근 중 | DBFM - 방어 필요 상황 |
| `IsNeutralSituation` | HCA>90° 또는 원거리 또는 2-circle 선회 | HABFM - 정면/고측면 대등 상황 |

### 각도 조건

| 노드 | 기본값 | 파라미터 | 설명 |
|-----|--------|---------|------|
| `ATAAbove` | `threshold_deg=60.0` | `threshold_deg` (°) | ATA > 임계값 (적이 측면/후방) |
| `ATABelow` | `threshold_deg=30.0` | `threshold_deg` (°) | ATA < 임계값 (적이 전방) |
| `UnderThreat` | `aa_threshold_deg=120.0` | `aa_threshold_deg` (°) | AA > 임계값 (적 정면 노출 위험) |
| `LOSAbove` | `threshold_deg=15.0` | `threshold_deg` (°) | LOS 각도 > 임계값 |
| `LOSBelow` | `threshold_deg=15.0` | `threshold_deg` (°) | LOS 각도 < 임계값 |
| `InEnemyWEZ` | `max_distance_ft=9843.0`, `max_los_angle_deg=30.0` | `max_distance_ft` (ft), `max_los_angle_deg` (°) | 적 WEZ 내에 있음 |

> **ATA**: 0°=적이 정면, 90°=적이 측면, 180°=적이 후방  
> **AA**: 0°=내가 적 후방(안전), 180°=내가 적 정면(위험)

### 에너지 조건

| 노드 | 기본값 | 파라미터 | 설명 |
|-----|--------|---------|------|
| `EnergyHighPs` | `threshold_fts=0.0` | `threshold_fts` | Ps(Specific Excess Power) > 임계값 |
| `SpecificEnergyAbove` | `threshold_ft=16404.0` | `threshold_ft` (ft) | He(고도+v²/2g) ≥ 임계값 |
| `IsMerged` | `merge_threshold_ft=1640.0` | `merge_threshold_ft` (ft) | 거리 < 임계값 (근접 교전) |

### 전술 인사이트 기반 조건 (신규)

#### 전술 상태 조건

| 노드 | 기본값 | 설명 |
|-----|--------|------|
| `Is39Line` | - | 적이 내 3-9 라인 안(ATA < 90°) — 공격 우위 위치 |
| `IsOvershootRisk` | - | 오버슈트 위험 감지 (빠른 접근 + 근거리 + 낮은 ATA/선회율) |
| `IsTargetInSight` | - | 적이 시야 내 (ATA < 90°, `Is39Line`과 동일) |
| `IsOneCircle` | - | 1-circle 선회 상황 (HCA < 90°, 같은 방향 선회) |
| `IsTwoCircle` | - | 2-circle 선회 상황 (HCA > 90°, 반대 방향 선회) |

#### 에너지 우세 조건

| 노드 | 기본값 | 파라미터 | 설명 |
|-----|--------|---------|------|
| `IsEnergyAdvantage` | - | - | 종합 에너지(He = h + v²/2g) 우세 |
| `IsAltAdvantage` | - | - | 고도 우세 (내 고도 > 적 고도) |
| `IsSpdAdvantage` | - | - | 속도 우세 (내 속도 > 적 속도) |
| `EnergyDiffAbove` | `threshold_ft=1640.0` | `threshold_ft` (ft) | 에너지 차이 > 임계값 |

#### 접근/선회율 조건

| 노드 | 기본값 | 파라미터 | 설명 |
|-----|--------|---------|------|
| `ClosureRateAbove` | `threshold_kts=97.2` | `threshold_kts` (kts) | 접근 속도 > 임계값 (양수=접근 중) |
| `ClosureRateBelow` | `threshold_kts=0.0` | `threshold_kts` (kts) | 접근 속도 < 임계값 (멀어지는 중 감지) |
| `TurnRateAbove` | `threshold_degs=5.0` | `threshold_degs` (°/s) | 선회율 > 임계값 (기동 여유 있음) |

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
| `ClimbTo` | `target_altitude_ft=19685.0` | `target_altitude_ft` (ft) | 목표 고도로 상승/하강 |
| `DescendTo` | `target_altitude_ft=13123.0` | `target_altitude_ft` (ft) | 목표 고도로 하강/상승 |
| `AltitudeAdvantage` | `target_advantage_ft=1640.0` | `target_advantage_ft` (ft) | 적보다 지정 고도 우위 유지 |

> `ClimbTo`/`DescendTo`는 고도차 >656ft 시 급기동, >328ft 시 일반기동, 이하 시 유지.

### 추적 기동 (OBFM)

#### `Pursue` — 적 추적 (종합 추적)

거리·고도·방위각·ATA를 종합 판단하여 최적 기동을 자동 선택합니다.

| 파라미터 | 기본값 | 설명 |
|---------|--------|------|
| `close_range_ft` | 6562.0 ft | 근중거리 판정 |
| `very_close_range_ft` | 4921.0 ft | 근거리 판정 |
| `far_range_ft` | 13123.0 ft | 원거리 판정 (이상 시 급가속) |
| `mid_far_range_ft` | 8202.0 ft | 중원거리 판정 |
| `alt_gap_fast_ft` | 656.0 ft | 급기동 고도차 임계값 |
| `alt_gap_normal_ft` | 328.0 ft | 일반기동 고도차 임계값 |
| `bearing_straight_deg` | 5.0 ° | 직진 판정 방위각 |
| `bearing_hard_deg` | 60.0 ° | 급회전 판정 방위각 |
| `bearing_strong_deg` | 30.0 ° | 강회전 판정 방위각 |
| `bearing_medium_deg` | 15.0 ° | 중회전 판정 방위각 |
| `ata_lost_deg` | 60.0 ° | 적 놓침 판정 ATA (이상 시 급감속+급회전) |
| `ata_side_deg` | 30.0 ° | 적 측면 판정 ATA (이상 시 감속) |

```yaml
# 공격적 추적
- type: Action
  name: Pursue
  params:
    close_range_ft: 8202
    bearing_straight_deg: 3
    ata_lost_deg: 45

# 보수적 추적
- type: Action
  name: Pursue
  params:
    far_range_ft: 16404
    alt_gap_fast_ft: 984
```

#### `LeadPursuit` — 선도 추적

`relative_bearing_deg`와 `ata_deg` 기반으로 적의 미래 위치를 향해 선회합니다. Gun WEZ(±12°, 500~3000ft) 진입에 최적화.

#### `PurePursuit` — 순수 추적

`side_flag` 기반으로 적의 현재 위치를 향해 직접 추적합니다.

#### `LagPursuit` — 지연 추적

`tau_deg` 기반으로 적의 후방을 추적합니다. 오버슈트 방지 및 에너지 관리에 유리.

### 방어 기동 (DBFM)

#### `DefensiveManeuver` — AA 기반 방어 기동

| 파라미터 | 기본값 | 설명 |
|---------|--------|------|
| `critical_aa_threshold_deg` | 45.0 ° | 매우 위험 AA 임계값 (이하 시 급회피) |
| `danger_aa_threshold_deg` | 90.0 ° | 위험 AA 임계값 (이하 시 중간 회피) |
| `alt_gap_threshold_ft` | 492.0 ft | 고도 변경 임계값 |

```yaml
- type: Action
  name: DefensiveManeuver
  params:
    critical_aa_threshold_deg: 60
    danger_aa_threshold_deg: 100
```

#### `BreakTurn` — 급선회 회피

`side_flag` 반대 방향으로 급우/급좌회전 + 하강 + 급가속. 선회율 극대화.

#### `DefensiveSpiral` — 방어 나선

강선회 + 고도 조절 + 급가속으로 나선형 회피. 고도 4921ft 이하 시 상승 전환.

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
| `GunAttack` | `relative_bearing_deg` 기반 정밀 조준 (Gun WEZ: ±12°, 500~3000ft) |

### 회피 기동

| 노드 | 설명 |
|-----|------|
| `Evade` | `side_flag` 반대 방향으로 강선회 + 가속 |

### 전술 인사이트 기반 액션 (신규)

| 노드 | 설명 |
|-----|------|
| `OvershootAvoidance` | 오버슈트 위험 시 자동 Lag/HighYoYo 전환. 선회율 < 3°/s → HighYoYo, 빠른 접근+근거리 → 즉시 감속+Lag |
| `EnergyFight` | 에너지 상태 기반 최적 전술 자동 선택. 고도우세→하강공격, 속도우세→가속추격, 열세→상승회복 |
| `TCFight` | 선회 유형(1/2-circle) 기반 전술 자동 분기. 1-circle→급선회+감속, 2-circle→에너지유지+재접근 |

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
            threshold_ft: 3281
        - type: Action
          name: ClimbTo
          params:
            target_altitude_ft: 9843

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

### 기본 관측값

| 키 | 범위 | 설명 |
|----|------|------|
| `distance_ft` | 0 ~ 65617 ft | 적과의 거리 |
| `ego_altitude_ft` | 0 ~ 49213 ft | 내 고도 |
| `ego_vc_kts` | 0 ~ 778 kts | 내 속도 |
| `alt_gap_ft` | ft | 고도 차이 (양수=적이 위) |
| `ata_deg` | 0 ~ 1 (정규화) | ATA / 180° (0=정면조준) |
| `aa_deg` | 0 ~ 1 (정규화) | AA / 180° (0=적 후방, 1=정면위협) |
| `hca_deg` | 0 ~ 1 (정규화) | HCA / 180° |
| `tau_deg` | -1 ~ 1 (정규화) | TAU / 180° |
| `relative_bearing_deg` | -1 ~ 1 (정규화) | 상대 방위각 / 180° (양수=오른쪽) |
| `side_flag` | -1, 0, 1 | 적 방향 (-1=왼쪽, 0=정면, 1=오른쪽) |

### 전술 인사이트 기반 신규 관측값

| 키 | 범위/타입 | 설명 |
|----|----------|------|
| `closure_rate_kts` | kts (양수=접근) | 접근 속도 |
| `turn_rate_degs` | °/s | 선회율 (g·tan(bank)/v 공식) |
| `in_39_line` | bool | 적이 내 3-9 라인 안 (ATA < 90°) |
| `overshoot_risk` | bool | 오버슈트 위험 여부 |
| `tc_type` | `'1-circle'`/`'2-circle'` | 선회 유형 (HCA 기반) |
| `energy_advantage` | bool | 종합 에너지 우세 (He 기반) |
| `energy_diff_ft` | ft | 에너지 차이 (양수=아군 우세) |
| `alt_advantage` | bool | 고도 우세 |
| `spd_advantage` | bool | 속도 우세 |

---

## 주요 용어

| 용어 | 설명 |
|-----|------|
| **ATA** | Antenna Train Angle — 내 속도 벡터와 적 방향 사이 각도 (0°=정면조준) |
| **AA** | Aspect Angle — 적 기준 내 위치 각도 (0°=적 후방 안전, 180°=정면 위협) |
| **HCA** | Heading Crossing Angle — 두 기체의 진행 방향 교차 각도 |
| **TAU** | 롤 각도를 고려한 목표 위치 각도 |
| **WEZ** | Weapon Engagement Zone — Gun WEZ: ATA < 12°, 500~3000ft (ATA 0°·거리 500ft일수록 데미지 최대) |
| **BFM** | Basic Fighter Maneuvers — OBFM(공격)/DBFM(방어)/HABFM(정면) |
| **Hard Deck** | 최저 안전 고도 1000ft (위반 시 즉시 패배) |
| **Ps** | Specific Excess Power — 기체의 잉여 에너지 (>0이면 가속/상승 여유 있음) |
