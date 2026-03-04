# AI Combat SDK

**AI 전투기 대결 챌린지 - 참여자 개발 키트**

행동트리(Behavior Tree) 기반으로 AI 전투기를 설계하고, 다른 참여자의 AI와 대결하세요!

## 📋 시스템 요구사항

- **Python 3.14** (필수)
- Windows 10/11, Linux, macOS 지원

---

## 🚀 빠른 시작

### 1. 환경 설정

```bash
# 저장소 클론 (최초 한번)
git clone https://github.com/songhyonkim/ai-combat-sdk.git
cd ai-combat-sdk

# Python 3.14 가상환경 생성 및 활성화
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# 의존성 설치
pip install -r requirements.txt
```

### 2. 첫 번째 에이전트 만들기

`examples/my_agent.yaml` 파일을 생성하세요:

```yaml
name: "my_agent"
description: "나의 첫 번째 AI 전투기"

tree:
  type: Selector
  children:
    # 1. Hard Deck 회피 (필수! 최상단 배치)
    - type: Sequence
      children:
        - type: Condition
          name: BelowHardDeck
          params:
            threshold: 3281
        - type: Action
          name: ClimbTo
          params:
            target_altitude: 9843

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

### 3. 검증 및 대전

```bash
# 에이전트 문법 검증
python tools/validate_agent.py examples/my_agent.yaml

# 테스트 대전
python scripts/run_match.py --agent1 my_agent --agent2 simple

# 다중 라운드 대전
python scripts/run_match.py --agent1 my_agent --agent2 eagle1 --rounds 5
```

### 4. 리플레이 분석

[TacView](https://www.tacview.net/) (무료 버전 가능)로 `replays/*.acmi` 파일을 열어 전투 상황을 3D로 분석하세요.

---

## 🏁 대회 규칙 및 승패 조건

### 승패 판정 (우선순위 순)

| 우선순위 | 조건 | 결과 |
|---------|------|------|
| 1 | 상대 체력(HP)이 0이 됨 | 승리 |
| 2 | **Hard Deck 위반** (고도 < 1640ft) | **즉시 패배** |
| 3 | 시간 종료 (2000 스텝 ≈ 400초) 후 체력 우위 | 체력 많은 쪽 승리 |
| 4 | 시간 종료 후 체력 동점 | 무승부 |

### 데미지 시스템 (Gun WEZ 기반)

내 기체가 아래 두 조건을 **동시에** 만족하면 상대에게 데미지가 누적됩니다:

| 조건 | 값 |
|------|-----|
| **ATA (조준 각도)** | < 4° (기수 앞 ±4° 이내) |
| **거리** | 500ft ~ 3,000ft |

- **데미지**: 최대 25 HP/s × 거리계수 × 각도계수 × 0.2s (스텝당)
- **초기 체력**: 100 HP
- **전략적 의미**: ATA를 0°에 가깝게, 거리를 500~3000ft로 유지할수록 빠르게 격추 가능

### 토너먼트 순위

- **승점**: 승 3점, 무 1점, 패 0점
- **동점 시**: Elo 점수로 구분 (초기 1000, K-factor 32)

---

## 📊 관측값 (Observation Space)

행동트리 노드에서 `self.blackboard.observation`으로 접근합니다.

| 키 | 단위/범위 | 설명 |
|----|----------|------|
| `distance_ft` | ft, 0~65617 | 적과의 거리 |
| `ego_altitude_ft` | ft, 0~49213 | 내 고도 |
| `ego_vc_kts` | kts, 0~778 | 내 속도 |
| `alt_gap_ft` | ft, 양수=적이 위 | 고도 차이 (적 고도 − 내 고도) |
| `ata_deg` | **0~1 정규화** | ATA/180°: 0=정면조준, 1=후방 |
| `aa_deg` | **0~1 정규화** | AA/180°: 0=적 후방(안전), 1=정면위협 |
| `hca_deg` | **0~1 정규화** | HCA/180°: 두 기체 진행방향 교차각 |
| `tau_deg` | **-1~1 정규화** | TAU/180°: 롤 고려 목표 위치각 |
| `relative_bearing_deg` | **-1~1 정규화** | 상대 방위각/180°: 양수=오른쪽 |
| `side_flag` | -1, 0, 1 | 적 방향: -1=왼쪽, 0=정면, 1=오른쪽 |
| `closure_rate_kts` | kts (양수=접근) | 접근 속도 |
| `turn_rate_degs` | °/s, 양수 | 선회율 |
| `in_39_line` | bool | 적이 내 3-9 라인 안 (ATA < 90°) |
| `overshoot_risk` | bool | 오버슈트 위험 여부 |
| `tc_type` | `'1-circle'`/`'2-circle'` | 선회 유형 |
| `energy_advantage` | bool | 종합 에너지 우세 |
| `energy_diff_ft` | ft | 에너지 차이 (양수=아군 우세) |
| `alt_advantage` | bool | 고도 우세 |
| `spd_advantage` | bool | 속도 우세 |

> ⚠️ **주의**: `ata_deg`, `aa_deg`, `hca_deg`, `tau_deg`, `relative_bearing_deg`는 **정규화된 값**입니다. 실제 각도(°)로 변환하려면 180을 곱하세요.

```python
# 커스텀 노드에서 사용 예시
obs = self.blackboard.observation
distance_ft = obs.get("distance_ft", 32808.0)     # ft 단위
ata_deg     = obs.get("ata_deg", 0.0) * 180.0   # 정규화 → 실제 각도(°)
aa_deg      = obs.get("aa_deg", 0.0) * 180.0    # 정규화 → 실제 각도(°)
alt_gap_ft  = obs.get("alt_gap_ft", 0.0)        # ft 단위 (양수=적이 위)
side_flag = obs.get("side_flag", 0)            # -1/0/1
```

---

## 🎯 BFM 상황 분류 시스템

`IsOffensiveSituation`, `IsDefensiveSituation`, `IsNeutralSituation` 조건 노드는 `CombatGeometry`를 기반으로 자동 분류됩니다.

| 상황 | 분류 기준 | 권장 전술 |
|------|----------|----------|
| **OBFM** (공격 유리) | ATA<45°, AA<100°, 거리 0.3~3NM + 에너지/3-9Line 우세 | `LeadPursuit`, `GunAttack`, `HighYoYo`, `OvershootAvoidance` |
| **DBFM** (방어 필요) | AA>90°, ATA>60° 또는 에너지 열세+접근 중 | `BreakTurn`, `DefensiveManeuver`, `DefensiveSpiral`, `EnergyFight` |
| **HABFM** (정면 대등) | HCA>90° 또는 원거리 또는 2-circle 선회 | `OneCircleFight`, `TwoCircleFight`, `TCFight` |

### 핵심 각도 개념

모든 각도는 **NED 좌표계** (`[North, East, Down]`) 기반 3D 벡터 연산으로 계산됩니다.

---

#### ATA (Antenna Train Angle) — 안테나 조준각

**개념**: 내 속도 벡터(`v_a`)와 적까지의 시선 벡터(LOS, `ρ_a = p_t − p_a`) 사이의 각도.  
내가 적을 얼마나 정면으로 조준하고 있는지를 나타냅니다.

```
수식:
  ρ_a = p_t − p_a          (LOS 벡터: 아군→적)
  ATA = arccos( v_a · ρ_a / (|v_a| × |ρ_a|) )

해석:
  0°   = 내 기수가 적을 정확히 향함 (조준 완료, 공격 유리)
  90°  = 적이 내 측면에 위치
  180° = 적이 내 후방에 위치
```

```
         나(→)
          ↑ v_a
          |
  ATA=0°  |  ATA=90°
  [적]←───┼─────────→
          |
```

**전술적 의미**:
- ATA < 4° + 거리 500~3000ft → Gun WEZ 진입 (데미지 발생)
- `BFMClassifier`: ATA < 45° → OBFM 판정, ATA > 60° → DBFM 판정
- `LeadPursuit`: `ata_deg` 기반 WEZ 근접 시 정밀 조준 모드 전환
- `task.py`: `get_lead_params()`로 1초 후 미래 위치 기준 ATA 재계산 → `ata_lead_deg` 관측값으로 노출

---

#### AA (Aspect Angle) — 종횡비각

**개념**: 적 기준으로 내가 어느 위치에 있는지를 나타내는 각도.  
적의 속도 벡터(`v_t`)와 역-LOS 벡터(`−ρ_a`, 적→아군 방향) 사이 각도를 180°에서 뺀 값.

```
수식:
  ρ_t = −ρ_a               (역-LOS 벡터: 적→아군)
  ε   = arccos( v_t · ρ_t / (|v_t| × |ρ_t|) )
  AA  = 180° − ε

해석:
  0°   = 내가 적의 정후방(6시) → 가장 유리한 공격 위치
  90°  = 내가 적의 측면(3시/9시)
  180° = 내가 적의 정면(12시) → 적이 나를 조준 중, 가장 위험
```

```
         적(→) v_t
    ┌────┼────┐
    │    │    │
  AA=0° 적  AA=180°
  (내가  후방)  (내가 정면)
```

**전술적 의미**: AA < 100° = 공격 유리(OBFM), AA > 120° = 방어 필요(DBFM)

---

#### HCA (Heading Crossing Angle) — 진로 교차각

**개념**: 아군 속도 벡터(`v_a`)와 적 속도 벡터(`v_t`) 사이의 각도.  
두 기체가 서로 어떤 방향으로 비행하고 있는지를 나타냅니다.

```
수식:
  HCA = arccos( v_a · v_t / (|v_a| × |v_t|) )

해석:
  0°   = 두 기체가 같은 방향으로 비행 (추격 상황)
  90°  = 두 기체가 직각 방향으로 교차
  180° = 두 기체가 정면으로 마주보며 접근 (Head-on)
```

```
  HCA ≈ 0°          HCA ≈ 90°         HCA ≈ 180°
  나→  적→           나→               나→  ←적
  (추격)             적↓               (Head-on)
                   (교차)
```

**전술적 의미**: HCA > 90° → HABFM(정면/고측면) 판정, 선회 우위 확보 필요

---

#### TAU — 롤 보정 목표 위치각

**개념**: 기체의 롤(Roll) 자세를 고려하여 적이 조종사 기준으로 어느 방향에 있는지를 나타내는 각도.  
LOS 벡터를 **East-Down 평면에 2D 투영**한 뒤, 기체 Up 방향(`[0, −1]`)과의 각도를 계산하고 롤 각도를 보정합니다.

```
수식:
  b_t = [ρ_a[East], ρ_a[Down]]   (LOS의 East-Down 성분)
  b_a = [0, −1]                   (기체 Up 방향, NED에서 Down이 양수이므로 −1)
  τ   = arccos( b_t · b_a / (|b_t| × |b_a|) )
  if b_t[East] > 0: τ = −τ        (오른쪽이면 음수)
  TAU = τ + roll                  (롤 자세 보정)
  TAU = normalize(TAU, −180°~180°)

해석:
  0°   = 적이 기체 정상방(12시, 기수 위쪽)에 위치
  90°  = 적이 기체 오른쪽(3시)에 위치
  −90° = 적이 기체 왼쪽(9시)에 위치
  ±180°= 적이 기체 아래쪽(6시)에 위치
```

**전술적 의미**: `LagPursuit` 액션에서 TAU 기반으로 선회 방향 결정, 오버슈트 방지

---

#### 관측값 정규화 요약

| 값 | 원본 범위 | 정규화 | 변환 방법 |
|----|----------|--------|----------|
| `ata_deg` | 0° ~ 180° | 0 ~ 1 | `× 180.0` |
| `aa_deg` | 0° ~ 180° | 0 ~ 1 | `× 180.0` |
| `hca_deg` | 0° ~ 180° | 0 ~ 1 | `× 180.0` |
| `tau_deg` | −180° ~ 180° | −1 ~ 1 | `× 180.0` |

```python
obs = self.blackboard.observation
ata = obs.get("ata_deg", 0.0) * 180.0   # 0~180°
aa  = obs.get("aa_deg",  0.0) * 180.0   # 0~180°
hca = obs.get("hca_deg", 0.0) * 180.0   # 0~180°
tau = obs.get("tau_deg", 0.0) * 180.0   # -180~180°
```

Gun WEZ 진입 조건: ATA < 4° AND 거리 500~3000ft → 데미지 발생

---

## 📋 주요 명령어

```bash
# 단판 대전
python scripts/run_match.py --agent1 eagle1 --agent2 simple

# 다중 라운드 대전
python scripts/run_match.py --agent1 my_agent --agent2 eagle1 --rounds 5

# 에이전트 검증
python tools/validate_agent.py submissions/my_agent/my_agent.yaml
```

**에이전트 탐색 순서**: `submissions/{name}/{name}.yaml` → `examples/{name}.yaml` → `examples/{name}/{name}.yaml` → 직접 경로

---

## 📂 디렉토리 구조

```
ai-combat-sdk/
├── docs/
│   └── NODE_REFERENCE.md       # 전체 노드 + 파라미터 레퍼런스
├── tools/
│   ├── validate_agent.py       # 제출 전 검증 도구
│   └── test_agent.py           # 로컬 테스트 도구
├── examples/                   # 예제 에이전트 (테스트용)
│   ├── simple.yaml
│   ├── aggressive.yaml
│   ├── defensive.yaml
│   ├── ace/
│   │   └── ace.yaml
│   └── eagle1/
│       └── eagle1.yaml
├── submissions/                # 참가자 제출 디렉토리
│   └── my_agent/
│       ├── my_agent.yaml
│       └── nodes/             # 커스텀 노드 (선택)
├── scripts/
│   ├── run_match.py           # 대전 실행
│   └── run_tournament.py      # 토너먼트 실행
├── config/                    # 매치 설정
├── src/                       # 핵심 엔진 (컴파일된 바이너리)
├── requirements.txt
└── replays/                   # ACMI 리플레이 파일 (Tacview)
```

---

## 🌳 행동트리 개발 가이드

### 동작 원리

행동트리는 **매 스텝(0.2초)마다 한 번** 실행됩니다. 루트 노드부터 순서대로 평가하며 각 노드는 `SUCCESS` 또는 `FAILURE`를 반환합니다.

```
Selector (OR): 자식 중 하나라도 SUCCESS → SUCCESS, 모두 FAILURE → FAILURE
Sequence (AND): 모든 자식이 SUCCESS여야 SUCCESS, 하나라도 FAILURE → FAILURE
Condition: 조건 확인 → SUCCESS/FAILURE
Action: 액션 실행 → 항상 SUCCESS (예외 시 기본 액션 [2,4,2] 반환)
```

### 고수준 액션 공간 (5×9×5)

모든 액션 노드는 내부적으로 3개의 이산 인덱스를 출력합니다:

| 축 | 인덱스 | 의미 |
|----|--------|------|
| **고도** | 0=급하강, 1=하강, 2=유지, 3=상승, 4=급상승 | 5단계 |
| **방향** | 0=급좌(-90°), 1=강좌, 2=중좌, 3=약좌, 4=직진, 5=약우, 6=중우, 7=강우, 8=급우(+90°) | 9단계 |
| **속도** | 0=급감속, 1=감속, 2=유지, 3=가속, 4=급가속 | 5단계 |

이 고수준 명령은 사전 학습된 저수준 RNN 정책(BaselineActor)을 통해 실제 조종면(aileron, elevator, rudder, throttle)으로 자동 변환됩니다.

### 주요 노드 요약

**Condition 노드 (조건 확인)**

| 노드 | 기본값 | 설명 |
|------|--------|------|
| `BelowHardDeck` | `threshold=3281` ft | 고도 < 임계값 |
| `EnemyInRange` | `max_distance=16404` ft | 적이 지정 거리 이내 |
| `DistanceBelow` | `threshold=9843` ft | 거리 < 임계값 |
| `DistanceAbove` | `threshold=6562` ft | 거리 > 임계값 |
| `AltitudeAbove` | `min_altitude=9843` ft | 고도 ≥ 지정값 |
| `AltitudeBelow` | `min_altitude=3281` ft | 고도 ≤ 지정값 |
| `VelocityAbove` | `min_velocity=389` kts | 속도 ≥ 지정값 |
| `VelocityBelow` | `max_velocity=778` kts | 속도 ≤ 지정값 |
| `UnderThreat` | `aa_threshold=120` ° | AA > 임계값 (정면 위협) |
| `ATAAbove` | `threshold=60` ° | ATA > 임계값 (적이 측면/후방) |
| `ATABelow` | `threshold=30` ° | ATA < 임계값 (적이 전방) |
| `IsOffensiveSituation` | - | OBFM: 공격 유리 상황 |
| `IsDefensiveSituation` | - | DBFM: 방어 필요 상황 |
| `IsNeutralSituation` | - | HABFM: 정면/고측면 대등 상황 |
| `IsMerged` | `merge_threshold=1640` ft | 근접 교전 상황 |
| `EnergyHighPs` | `threshold=0` | 잊여 에너지(Ps) > 임계값 |
| `Is39Line` | - | 적이 내 3-9 라인 안 (ATA < 90°) |
| `IsOvershootRisk` | - | 오버슈트 위험 감지 |
| `IsEnergyAdvantage` | - | 종합 에너지 우세 |
| `IsAltAdvantage` | - | 고도 우세 |
| `IsSpdAdvantage` | - | 속도 우세 |
| `ClosureRateAbove` | `threshold=97` kts | 접근 속도 > 임계값 |
| `ClosureRateBelow` | `threshold=0` kts | 접근 속도 < 임계값 (멀어지는 중) |
| `TurnRateAbove` | `threshold=5` °/s | 선회율 > 임계값 |
| `IsOneCircle` | - | 1-circle 선회 상황 |
| `IsTwoCircle` | - | 2-circle 선회 상황 |
| `EnergyDiffAbove` | `threshold=1640` ft | 에너지 차이 > 임계값 |

**Action 노드 (액션 실행)**

| 노드 | 기본값 | 설명 |
|------|--------|------|
| `Pursue` | 파라미터 12개 | 거리·고도·방위각·ATA 종합 추적 |
| `LeadPursuit` | - | 선도 추적 (Gun WEZ 진입 최적화) |
| `PurePursuit` | - | 순수 추적 (적 현재 위치) |
| `LagPursuit` | - | 지연 추적 (오버슈트 방지) |
| `Evade` | - | 적 반대 방향 강선회 + 가속 |
| `ClimbTo` | `target_altitude=19685` ft | 목표 고도로 상승 |
| `DescendTo` | `target_altitude=13123` ft | 목표 고도로 하강 |
| `AltitudeAdvantage` | `target_advantage=1640` ft | 적보다 지정 고도 우위 유지 |
| `DefensiveManeuver` | `critical_aa_threshold=45`, `danger_aa_threshold=90` | AA 기반 방어 기동 |
| `BreakTurn` | - | 급선회 회피 + 하강 + 급가속 |
| `DefensiveSpiral` | - | 나선형 회피 |
| `HighYoYo` | - | 급상승+급선회 → 하강+공격 |
| `LowYoYo` | - | 급하강+가속 → 상승+위치 우위 |
| `OneCircleFight` | - | 급선회 + 감속 (선회 우위 시) |
| `TwoCircleFight` | - | 약선회 + 급가속 (에너지 우위 시) |
| `GunAttack` | - | 정밀 조준 (Gun WEZ 내) |
| `ClimbingTurn` | `direction="left"` | 상승하며 선회 |
| `DescendingTurn` | `direction="left"` | 하강하며 선회 |
| `BarrelRoll` | - | 나선형 상승↔하강 반복 |
| `TurnLeft` | `intensity="normal"` | 좌회전 (`"hard"` 시 급좌회전) |
| `TurnRight` | `intensity="normal"` | 우회전 (`"hard"` 시 급우회전) |
| `Accelerate` / `Decelerate` | - | 급가속 / 급감속 |
| `Straight` / `MaintainAltitude` | - | 직진 / 고도 유지 |
| `OvershootAvoidance` | - | 오버슈트 위험 시 자동 Lag/HighYoYo 전환 |
| `EnergyFight` | - | 에너지 상태 기반 최적 전술 자동 선택 |
| `TCFight` | - | 1/2-circle 선회 유형 기반 전술 자동 분기 |

📚 **파라미터 상세**: [docs/NODE_REFERENCE.md](docs/NODE_REFERENCE.md)

---

## 🔧 커스텀 노드 작성 (고급)

기본 제공 노드로 부족할 경우, Python으로 직접 노드를 작성할 수 있습니다.

### 디렉토리 구조

```
submissions/my_agent/
├── my_agent.yaml
├── README.md          # 전략 설명 (선택)
└── nodes/
    ├── __init__.py
    ├── custom_actions.py
    └── custom_conditions.py
```

### 커스텀 액션 노드 예시

```python
# submissions/my_agent/nodes/custom_actions.py
from src.behavior_tree.nodes.actions import BaseAction
import py_trees

class MyCustomAttack(BaseAction):
    def __init__(self, name: str = "MyCustomAttack",
                 attack_range: float = 1500.0):
        super().__init__(name)
        self.attack_range = attack_range
    
    def update(self) -> py_trees.common.Status:
        obs = self.blackboard.observation
        distance = obs.get("distance", 10000.0)
        ata_deg = obs.get("ata_deg", 1.0) * 180.0  # 정규화 → 실제 각도
        
        if distance < self.attack_range and ata_deg < 30:
            # 고도 유지(2), 직진(4), 가속(3)
            self.set_action(2, 4, 3)
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.FAILURE
```

### 커스텀 조건 노드 예시

```python
# submissions/my_agent/nodes/custom_conditions.py
import py_trees

class CloseAndAligned(py_trees.behaviour.Behaviour):
    """근거리 + 조준 완료 조건"""
    def __init__(self, name="CloseAndAligned",
                 max_distance=800.0, max_ata=10.0):
        super().__init__(name)
        self.max_distance = max_distance
        self.max_ata = max_ata
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key="observation", access=py_trees.common.Access.READ
        )
    
    def update(self) -> py_trees.common.Status:
        obs = self.blackboard.observation
        distance = obs.get("distance", 99999)
        ata_deg = obs.get("ata_deg", 1.0) * 180.0
        
        if distance < self.max_distance and ata_deg < self.max_ata:
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.FAILURE
```

### YAML에서 사용

```yaml
- type: Action
  name: MyCustomAttack
  params:
    attack_range: 2000

- type: Condition
  name: CloseAndAligned
  params:
    max_distance: 600
    max_ata: 5
```

---

## 📦 제출 방법

### 파일명 규칙

**파일명과 `name` 속성은 반드시 일치해야 합니다.**

```
✅ my_agent.yaml   →  name: "my_agent"
✅ viper1.yaml     →  name: "viper1"
❌ My Agent.yaml   →  공백 사용 금지
❌ ace-fighter.yaml →  하이픈 사용 금지
❌ Ace.yaml        →  대문자 사용 금지
```

- 소문자, 숫자, 언더스코어(`_`)만 사용
- 15자 이내 권장

### 제출 디렉토리 구조

```
submissions/
  my_agent/
    my_agent.yaml       # 행동트리 정의 (필수)
    nodes/              # 커스텀 노드 (선택)
      __init__.py
      custom_actions.py
      custom_conditions.py
    README.md           # 전략 설명 (선택)
```

### 제출 전 체크리스트

```bash
# 1. 문법 검증
python tools/validate_agent.py submissions/my_agent/my_agent.yaml

# 2. 여러 상대와 테스트
python scripts/run_match.py --agent1 my_agent --agent2 simple
python scripts/run_match.py --agent1 my_agent --agent2 eagle1
python scripts/run_match.py --agent1 my_agent --agent2 aggressive

# 3. Hard Deck 위반 없는지 확인 (리플레이 분석)
```

---

## 🏆 예제 에이전트

| 에이전트 | 위치 | 전략 | 난이도 |
|----------|------|------|--------|
| `simple` | examples/ | 기본 추적 (`Pursue`) | ⭐ |
| `aggressive` | examples/ | 적극적 공격 (`LeadPursuit` 중심) | ⭐⭐ |
| `defensive` | examples/ | 방어 중심 (`DefensiveManeuver`) | ⭐⭐ |
| `ace` | examples/ace/ | BFM 상황별 전술 | ⭐⭐⭐ |
| `eagle1` | examples/eagle1/ | 기본 노드 조합 | ⭐⭐ |
| `fuzzy_eagle1` | examples/fuzzy_eagle1/ | Fuzzy BT 기반 부드러운 상황 판단 | ⭐⭐⭐ |

```bash
# 예제 에이전트끼리 대전
python scripts/run_match.py --agent1 eagle1 --agent2 simple
python scripts/run_match.py --agent1 defensive --agent2 aggressive
```

---

## � 전략 개발 팁

### 1. 반드시 Hard Deck 회피를 최상단에 배치

```yaml
tree:
  type: Selector
  children:
    - type: Sequence   # ← 항상 첫 번째!
      children:
        - type: Condition
          name: BelowHardDeck
          params:
            threshold: 3281
        - type: Action
          name: ClimbTo
          params:
            target_altitude: 9843
    # ... 나머지 전술
```

### 2. BFM 상황별 전술 분리

```yaml
tree:
  type: Selector
  children:
    - type: Sequence  # Hard Deck 회피
      ...
    - type: Sequence  # OBFM: 공격 유리
      children:
        - type: Condition
          name: IsOffensiveSituation
        - type: Action
          name: LeadPursuit
    - type: Sequence  # DBFM: 방어 필요
      children:
        - type: Condition
          name: IsDefensiveSituation
        - type: Action
          name: BreakTurn
    - type: Sequence  # HABFM: 정면 대등
      children:
        - type: Condition
          name: IsNeutralSituation
        - type: Action
          name: OneCircleFight
    - type: Action    # 기본 추적
      name: Pursue
```

### 3. 거리 구간별 전술 분리

```yaml
# 근거리 (< 3281ft): Gun WEZ 진입 시도
- type: Sequence
  children:
    - type: Condition
      name: DistanceBelow
      params:
        threshold: 3281
    - type: Action
      name: GunAttack

# 중거리 (3281~9843ft): 선도 추적
- type: Sequence
  children:
    - type: Condition
      name: DistanceBelow
      params:
        threshold: 9843
    - type: Action
      name: LeadPursuit

# 원거리 (> 9843ft): 기본 추적 + 가속
- type: Action
  name: Pursue
```

### 4. `Pursue` 파라미터 튜닝

```yaml
# 공격적 추적
- type: Action
  name: Pursue
  params:
    close_range: 2500      # 더 넓은 근거리 판정
    bearing_straight: 3    # 더 정밀한 조준
    ata_lost: 45           # 더 빠른 회전 반응
    far_range: 5000        # 원거리 기준 확장

# 보수적 추적
- type: Action
  name: Pursue
  params:
    alt_gap_fast: 300      # 더 큰 고도차에서만 급기동
    bearing_hard: 80       # 더 큰 방위각에서만 급회전
```

### 5. 에너지 관리

- **고도 우위** = 에너지 우위 → `AltitudeAdvantage`로 적보다 높게 유지
- **속도 코너**: ATA가 클수록 감속하여 선회 반경 축소 (`Pursue`가 자동 처리)
- **HighYoYo**: 오버슈트 방지 + 에너지 변환에 효과적

---

## 📊 매 틱 전체 정보 로깅

### CSV 자동 로깅 (`log_csv`)

`BehaviorTreeMatch`에 `log_csv` 경로를 지정하면 매 틱마다 두 에이전트의 **모든 정보**를 CSV 파일로 자동 저장합니다.

```python
from src.match.runner import BehaviorTreeMatch

match = BehaviorTreeMatch(
    tree1_file="examples/eagle1/eagle1.yaml",
    tree2_file="examples/simple.yaml",
    log_csv="logs/match_log.csv",   # ← 경로 지정 시 자동 저장
)
result = match.run()
```

저장되는 CSV 컬럼 (에이전트별 1행씩, 총 2×N행):

| 카테고리 | 컬럼 |
|----------|------|
| **식별** | `step`, `agent_id`, `tree_name` |
| **위치/자세** | `ego_altitude`, `ego_vc`, `ego_vx/vy/vz`, `roll_deg`, `pitch_deg`, `specific_energy`, `ps` |
| **전투 기하** | `distance`, `ata_deg`, `aa_deg`, `hca_deg`, `tau_deg`, `relative_bearing_deg`, `alt_gap`, `closure_rate`, `turn_rate`, `in_39_line`, `overshoot_risk`, `tc_type`, `ata_lead_deg`, `tau_lead_deg`, `side_flag` |
| **에너지** | `energy_advantage`, `energy_diff`, `alt_advantage`, `spd_advantage` |
| **BFM** | `bfm_situation` |
| **매치 상태** | `ego_health`, `enm_health`, `ego_damage_dealt`, `enm_damage_dealt`, `ego_damage_received`, `enm_damage_received`, `in_wez`, `enm_in_wez`, `reward` |
| **고수준 액션** | `action_altitude`, `action_heading`, `action_velocity` |
| **저수준 제어** | `aileron`, `elevator`, `rudder`, `throttle` |
| **활성 노드** | `active_node` (최종 실행 노드), `active_nodes_path` (전체 경로) |

> ⚠️ **각도 컬럼 주의**: CSV의 `ata_deg`, `aa_deg`, `hca_deg`, `tau_deg`, `relative_bearing_deg` 값은 **실제 각도(°)** 로 저장됩니다 (blackboard의 정규화값 × 180 변환 적용).

---

### step_callback — 매 틱 실시간 처리

매 틱마다 호출되는 콜백을 등록하여 커스텀 로깅, 실시간 분석, 강화학습 데이터 수집 등에 활용할 수 있습니다.

#### CLI에서 바로 사용 (가장 간단)

```bash
# 콜백 로깅만 (콘솔 실시간 출력 + 파일 저장)
python scripts/run_match.py --agent1 eagle1 --agent2 simple --callback-log

# CSV 로깅 + 콜백 로깅 동시 사용
python scripts/run_match.py --agent1 eagle1 --agent2 simple --log-csv --callback-log
```

**콘솔 출력 예시 (실시간):**
```
[   0] A0100 | BFM=BFMSituation.HABFM   | HP=100.0/100.0 | Dmg= 0.0 | WEZ=False | Dist=1005m ATA= 90.0deg | Act=[2, 0, 3] | Node=LeadPursuit
[   0] B0100 | BFM=BFMSituation.HABFM   | HP=100.0/100.0 | Dmg= 0.0 | WEZ=False | Dist=1005m ATA= 90.0deg | Act=[2, 0, 0] | Node=Pursue
[   1] A0100 | BFM=BFMSituation.DBFM    | HP=100.0/100.0 | Dmg= 0.0 | WEZ=False | Dist=1285m ATA=116.8deg | Act=[0, 0, 0] | Node=IsDefensiveSituation
[1499] A0100 | BFM=BFMSituation.OBFM    | HP= 97.0/ 93.0 | Dmg= 3.0 | WEZ=False | Dist=1274m ATA= 80.9deg | Act=[1, 0, 3] | Node=LeadPursuit
```

**콜백 로그 파일 (`logs/callback.csv`):**
- 21개 컬럼: `step`, `agent_id`, `bfm_situation`, `ego_health`, `enm_health`, `ego_damage_dealt`, `enm_damage_dealt`, `in_wez`, `enm_in_wez`, `reward`, `distance`, `ata_deg`, `action_altitude`, `action_heading`, `action_velocity`, `aileron`, `elevator`, `rudder`, `throttle`, `active_node`, `active_nodes_count`

> 💡 **참고**: 콜백 로거는 내부적으로 모든 예외를 처리하므로, 로깅 오류가 발생해도 매치는 계속 진행됩니다. 오류 메시지는 `[콜백 오류]` 형식으로 콘솔에 출력됩니다.

#### Python 코드에서 사용

```python
from examples.full_logger_callback import create_full_logger
from src.match.runner import BehaviorTreeMatch

# 전체 로거 생성
logger = create_full_logger("logs/my_callback.csv")

match = BehaviorTreeMatch(
    tree1_file="examples/eagle1/eagle1.yaml",
    tree2_file="examples/simple.yaml",
    step_callback=logger,           # ← 콜백 등록
    log_csv="logs/match_log.csv",   # ← CSV 동시 사용 가능
)
result = match.run()
```

#### 커스텀 콜백 작성

```python
def my_tick_logger(step, agent_id, obs, action,
                   low_level_action, reward, health,
                   active_nodes, bfm_situation):
    # 원하는 정보만 선택적으로 로깅
    if obs.get('in_wez'):
        print(f"[WEZ!] {agent_id} at step {step}: ATA={obs.get('ata_deg',0)*180:.1f}°")

match = BehaviorTreeMatch(
    tree1_file="examples/eagle1/eagle1.yaml",
    tree2_file="examples/simple.yaml",
    step_callback=my_tick_logger,
)
result = match.run()
```

콜백 인자:

| 인자 | 타입 | 설명 |
|------|------|------|
| `step` | `int` | 현재 스텝 번호 (0부터) |
| `agent_id` | `str` | 에이전트 ID (`A0100` / `B0100`) |
| `obs` | `dict` | 전체 관측값 딕셔너리 (아래 확장 키 포함) |
| `action` | `list[int]` | 고수준 액션 `[altitude, heading, velocity]` |
| `low_level_action` | `dict` | `{"aileron", "elevator", "rudder", "throttle"}` |
| `reward` | `float` | 이번 틱 보상값 |
| `health` | `dict` | `{"ego": 98.0, "enm": 85.3}` |
| `active_nodes` | `list[tuple]` | `[(노드명, 상태), ...]` |
| `bfm_situation` | `str` | `"offensive"` / `"defensive"` / `"neutral"` |

---

### 확장된 observation 키

`step_callback` 또는 커스텀 노드의 `self.blackboard.observation`에서 접근 가능한 **추가 키**:

```python
obs = self.blackboard.observation

# 매치 상태 (Runner가 매 틱 갱신)
obs["ego_health"]           # float: 내 현재 체력 (0~100 HP)
obs["enm_health"]           # float: 상대 체력
obs["ego_damage_dealt"]     # float: 내가 가한 누적 데미지
obs["enm_damage_dealt"]     # float: 상대가 가한 누적 데미지
obs["ego_damage_received"]  # float: 내가 받은 누적 데미지
obs["enm_damage_received"]  # float: 상대가 받은 누적 데미지
obs["in_wez"]               # bool: 내가 Gun WEZ 내에 있는지 (ATA<4°, 500~3000ft)
obs["enm_in_wez"]           # bool: 상대가 내 WEZ 안에 있는지
obs["reward"]               # float: 이번 틱 보상값
obs["bfm_situation"]        # str: BFMClassifier 분류 결과
```

> 💡 **주의**: 커스텀 노드에서 위 키를 읽을 때, 첫 번째 틱은 초기값(체력=100, 데미지=0)이 들어있습니다. 이전 틱의 상태가 다음 틱에 반영됩니다.

---

## ❓ FAQ

**Q: `name`이 파일명과 다르면 어떻게 되나요?**  
A: 에이전트 로딩에 실패합니다. `validate_agent.py`로 미리 확인하세요.

**Q: Hard Deck 위반 없이도 지는 이유는?**  
A: 시간 종료(2000 스텝) 시 체력이 낮으면 집니다. 상대 체력을 더 빠르게 줄이는 전술이 필요합니다.

**Q: `ata_deg`가 0에 가까운데 데미지가 안 들어가요.**  
A: 거리가 500~3000ft 범위 밖이면 데미지가 없습니다. 거리 조건도 동시에 충족해야 합니다.

**Q: 커스텀 노드에서 `set_action(2, 4, 2)`의 의미는?**  
A: `(고도=유지, 방향=직진, 속도=유지)` 입니다. 인덱스 의미는 [고수준 액션 공간](#고수준-액션-공간-5×9×5) 참조.

**Q: `side_flag`와 `relative_bearing_deg`의 차이는?**  
A: `side_flag`는 -1/0/1의 이산값, `relative_bearing_deg`는 -1~1 정규화된 연속값입니다. 정밀한 방향 제어에는 `relative_bearing_deg`를 사용하세요.

**Q: `ModuleNotFoundError`가 발생해요.**  
A: 가상환경이 활성화되지 않았습니다. `.venv\Scripts\activate` (Windows) 또는 `source .venv/bin/activate` (Linux/Mac)를 실행하세요.

**Q: `Behavior tree file not found` 오류가 발생해요.**  
A: 에이전트 이름이 파일명과 일치하는지 확인하세요. `examples/my_agent/my_agent.yaml` 또는 `submissions/my_agent/my_agent.yaml` 구조여야 합니다.

---

## 📖 문서

| 문서 | 설명 |
|------|------|
| [docs/NODE_REFERENCE.md](docs/NODE_REFERENCE.md) | 전체 노드 + 파라미터 상세 레퍼런스 |
| [tools/validate_agent.py](tools/validate_agent.py) | 제출 전 YAML 검증 도구 |
| [tools/test_agent.py](tools/test_agent.py) | 로컬 대전 테스트 도구 |

---

## 📞 지원

- **GitHub Issues**: 버그 리포트 및 질문
- **예제**: `examples/`, `submissions/` 폴더 참고

---

**🛩️ 하늘을 지배할 당신의 AI를 개발하세요!**

Copyright © 2026 AI Combat Team. All rights reserved.
