# Blackboard 키 레퍼런스 (공식 문서)

> **Single Source of Truth** — Blackboard `observation` 딕셔너리에 저장되는 모든 키의 이름, 단위, 범위, 부호 규약을 정의합니다.

---

## 단위 규약

| 접미사 | 단위 | 예시 |
|--------|------|------|
| `_ft` | feet | `distance_ft`, `alt_gap_ft`, `ego_altitude_ft` |
| `_kts` | knots | `ego_vc_kts`, `closure_rate_kts` |
| `_deg` | degrees (°) | `ata_deg`, `aa_deg`, `tau_deg` |
| `_degs` | degrees/second (°/s) | `turn_rate_degs` |
| `_fts` | feet/second (ft/s) | `ps_fts` |
| (없음) | boolean / enum / 무차원 | `side_flag`, `in_39_line`, `tc_type` |

> **핵심 원칙**: 변수명의 접미사가 곧 단위입니다. 별도 변환 없이 값을 바로 사용하세요.

---

## 기본 관측값

`task.py._update_blackboard()`에서 JSBSim 15차원 벡터로부터 추출됩니다.

| 키 | 타입 | 단위 | 범위 | 설명 |
|----|------|------|------|------|
| `raw` | `np.ndarray` | - | - | 원본 15차원 정규화 벡터 |
| `ego_altitude_ft` | `float` | ft | 0 ~ 49,213 | 내 고도 |
| `ego_vc_kts` | `float` | kts | 0 ~ 778 | 내 교정 대기속도 |
| `distance_ft` | `float` | ft | 0 ~ 65,617 | 적과의 거리 |
| `side_flag` | `int` | - | -1, 0, 1 | 적 방향 (-1=왼쪽, 0=정면, 1=오른쪽) |
| `roll_deg` | `float` | ° | -180 ~ 180 | 내 롤 각도 |
| `pitch_deg` | `float` | ° | -90 ~ 90 | 내 피치 각도 |
| `specific_energy_ft` | `float` | ft | ≥ 0 | 비에너지 He = h + v²/2g |
| `ps_fts` | `float` | ft/s | - | Specific Excess Power (dHe/dt) |

---

## CombatGeometry 파라미터 (각도)

`CombatGeometry` 클래스에서 계산되며, **실제 도(°) 단위**로 저장됩니다.

> ⚠️ **Breaking Change**: 이전에는 `/180.0`으로 정규화된 0~1 값이었습니다. 이제 실제 도(°) 단위입니다.

| 키 | 타입 | 단위 | 범위 | 부호 | 설명 |
|----|------|------|------|------|------|
| `ata_deg` | `float` | ° | 0 ~ 180 | 항상 양수 | ATA (Antenna Train Angle) — 내 속도 벡터와 적 방향 사이 각도. 0°=정면조준, 180°=후방 |
| `aa_deg` | `float` | ° | 0 ~ 180 | 항상 양수 | AA (Aspect Angle) — 적 기준 내 위치. 0°=적 후방(안전), 180°=적 정면(위험) |
| `hca_deg` | `float` | ° | 0 ~ 180 | 항상 양수 | HCA (Heading Crossing Angle) — 진로 교차각. 0°=동방향, 180°=대향 |
| `tau_deg` | `float` | ° | -180 ~ 180 | 부호 있음 | TAU — 롤 보정 목표 위치각. 양수=오른쪽, 음수=왼쪽 |
| `relative_bearing_deg` | `float` | ° | -180 ~ 180 | 부호 있음 | 상대 방위각. 양수=적이 오른쪽, 음수=적이 왼쪽 |
| `alt_gap_ft` | `float` | ft | - | 부호 있음 | 고도 차이. 양수=적이 위, 음수=적이 아래(=내가 위) |

### Lead 파라미터 (1초 후 예측)

| 키 | 타입 | 단위 | 범위 | 설명 |
|----|------|------|------|------|
| `ata_lead_deg` | `float` | ° | 0 ~ 180 | 1초 후 예측 ATA |
| `tau_lead_deg` | `float` | ° | -180 ~ 180 | 1초 후 예측 TAU |

---

## 전술 인사이트 파라미터

`task.py._update_blackboard()`에서 추가 계산됩니다.

### 접근/선회 상태

| 키 | 타입 | 단위 | 설명 |
|----|------|------|------|
| `closure_rate_kts` | `float` | kts | 접근 속도. 양수=접근 중, 음수=멀어짐 |
| `turn_rate_degs` | `float` | °/s | 선회율 (항상 양수) |

### 전술 상태 (boolean/enum)

| 키 | 타입 | 설명 |
|----|------|------|
| `in_39_line` | `bool` | 적이 내 3-9 라인 안 (ATA < 90°) |
| `overshoot_risk` | `bool` | 오버슈트 위험 여부 |
| `tc_type` | `str` | 선회 유형: `'1-circle'` 또는 `'2-circle'` |
| `energy_advantage` | `bool` | 종합 에너지 우세 (He 기반) |
| `energy_diff_ft` | `float` | 에너지 차이 (ft, 양수=아군 우세) |
| `alt_advantage` | `bool` | 고도 우세 (내 고도 > 적 고도) |
| `spd_advantage` | `bool` | 속도 우세 (내 속도 > 적 속도) |

---

## Blackboard 전역 키 (`/` 접두사)

조건 노드에서 직접 읽기 위해 노출되는 키입니다.

| BB 키 | 타입 | 사용 노드 |
|--------|------|-----------|
| `/Distance_ft` | `float` | `InEnemyWEZ` |
| `/Speed_kts` | `float` | - |
| `/CurrentRoll` | `float` | - |
| `/CurrentPitch` | `float` | `IsVerticalMove` |
| `/MyLOSAngle` | `float` | `LOSAbove`, `LOSBelow` |
| `/EnemyLOSAngle` | `float` | `InEnemyWEZ` |
| `/TurnLeft` | `bool` | `TurnLeft`, `IsTurningLeft` |
| `/TurnRight` | `bool` | `IsTurningRight` |
| `/ClosureRate_kts` | `float` | `ClosureRateAbove/Below` |
| `/TurnRate_degs` | `float` | `TurnRateAbove` |
| `/In39Line` | `bool` | `Is39Line`, `IsTargetInSight` |
| `/OvershootRisk` | `bool` | `IsOvershootRisk` |
| `/TCType` | `str` | `IsOneCircle`, `IsTwoCircle` |
| `/EnergyAdvantage` | `bool` | `IsEnergyAdvantage` |
| `/EnergyDiff_ft` | `float` | `EnergyDiffAbove` |
| `/AltAdvantage` | `bool` | `IsAltAdvantage` |
| `/SpdAdvantage` | `bool` | `IsSpdAdvantage` |
| `/MergeDistance_ft` | `float` | `IsMerged` |
| `/Superior` | `bool` | `HasSuperior`, `NotSuperior` |
| `/EnergyState` | `bool` | `EnergyHigh` |
| `bfm_situation` | `BFMSituation` | `IsOffensive/Defensive/Neutral` |

---

## 사용 예시

```python
# 커스텀 액션 노드에서 사용
obs = self.blackboard.observation

# 각도: 실제 도(°) 단위 — 변환 불필요
ata_deg = obs.get("ata_deg", 0.0)               # 0°~180°
tau_deg = obs.get("tau_deg", 0.0)               # -180°~180°
rel_bearing = obs.get("relative_bearing_deg", 0.0)  # -180°~180°

# 거리/고도: ft 단위
distance_ft = obs.get("distance_ft", 32808.0)   # ft
alt_gap_ft = obs.get("alt_gap_ft", 0.0)         # ft (양수=적이 위)

# 속도: kts 단위
ego_vc_kts = obs.get("ego_vc_kts", 389.0)       # kts

# 전술 상태
side_flag = obs.get("side_flag", 0)              # -1/0/1
energy_adv = obs.get("energy_advantage", False)  # bool
```

---

## 마이그레이션 가이드 (기존 코드 수정)

기존에 `* 180.0` 변환을 사용하던 코드를 수정해야 합니다:

```diff
 # Before (이전)
-ata_deg = obs.get("ata_deg", 0.0) * 180.0
-tau_deg = obs.get("tau_deg", 0.0) * 180.0
-rel_bearing = obs.get("relative_bearing_deg", 0.0) * 180.0

 # After (현재)
+ata_deg = obs.get("ata_deg", 0.0)
+tau_deg = obs.get("tau_deg", 0.0)
+rel_bearing = obs.get("relative_bearing_deg", 0.0)
```

> **주의**: `direct_control_task.py`의 RL obs 벡터용 `/180.0`은 Blackboard 키와 무관한 신경망 입력 정규화이므로 그대로 유지됩니다.
