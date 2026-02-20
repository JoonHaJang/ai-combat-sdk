# AI Combat SDK

**AI 전투기 대결 챌린지 - 참여자 개발 키트**

행동트리(Behavior Tree) 기반으로 AI 전투기를 설계하고, 다른 참여자의 AI와 대결하세요!

---

## 🚀 빠른 시작

### 1. 환경 설정

```bash
# 저장소 클론 (최초 한번)
git clone https://github.com/songhyonkim/ai-combat-sdk.git
cd ai-combat-sdk

# 가상환경 생성 및 활성화
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

### 3. 검증 및 대전

```bash
# 에이전트 문법 검증
python tools/validate_agent.py examples/my_agent.yaml

# 테스트 대전
python scripts/run_match.py --agent1 my_agent --agent2 simple

# 다중 라운드 대전
python scripts/run_match.py --agent1 my_agent --agent2 ace --rounds 5
```

### 4. 리플레이 분석

[TacView](https://www.tacview.net/) (무료 버전 가능)로 `replays/*.acmi` 파일을 열어 전투 상황을 3D로 분석하세요.

---

## 🏁 대회 규칙 및 승패 조건

### 승패 판정 (우선순위 순)

| 우선순위 | 조건 | 결과 |
|---------|------|------|
| 1 | 상대 체력(HP)이 0이 됨 | 승리 |
| 2 | **Hard Deck 위반** (고도 < 500m) | **즉시 패배** |
| 3 | 시간 종료 (2000 스텝 ≈ 400초) 후 체력 우위 | 체력 많은 쪽 승리 |
| 4 | 시간 종료 후 체력 동점 | 무승부 |

### 데미지 시스템 (Gun WEZ 기반)

내 기체가 아래 두 조건을 **동시에** 만족하면 상대에게 데미지가 누적됩니다:

| 조건 | 값 |
|------|-----|
| **ATA (조준 각도)** | < 4° (기수 앞 ±4° 이내) |
| **거리** | 152m ~ 914m (500ft ~ 3,000ft) |

- **데미지**: 최대 25 HP/s × 거리계수 × 각도계수 × 0.2s (스텝당)
- **초기 체력**: 100 HP
- **전략적 의미**: ATA를 0°에 가깝게, 거리를 152~914m로 유지할수록 빠르게 격추 가능

### 토너먼트 순위

- **승점**: 승 3점, 무 1점, 패 0점
- **동점 시**: Elo 점수로 구분 (초기 1000, K-factor 32)

---

## 📊 관측값 (Observation Space)

행동트리 노드에서 `self.blackboard.observation`으로 접근합니다.

| 키 | 단위/범위 | 설명 |
|----|----------|------|
| `distance` | m, 0~20000 | 적과의 거리 |
| `ego_altitude` | m, 0~15000 | 내 고도 |
| `ego_vc` | m/s, 0~400 | 내 속도 |
| `alt_gap` | m, 양수=적이 위 | 고도 차이 (적 고도 − 내 고도) |
| `ata_deg` | **0~1 정규화** | ATA/180°: 0=정면조준, 1=후방 |
| `aa_deg` | **0~1 정규화** | AA/180°: 0=적 후방(안전), 1=정면위협 |
| `hca_deg` | **0~1 정규화** | HCA/180°: 두 기체 진행방향 교차각 |
| `tau_deg` | **-1~1 정규화** | TAU/180°: 롤 고려 목표 위치각 |
| `relative_bearing_deg` | **-1~1 정규화** | 상대 방위각/180°: 양수=오른쪽 |
| `side_flag` | -1, 0, 1 | 적 방향: -1=왼쪽, 0=정면, 1=오른쪽 |

> ⚠️ **주의**: `ata_deg`, `aa_deg`, `hca_deg`, `tau_deg`, `relative_bearing_deg`는 **정규화된 값**입니다. 실제 각도(°)로 변환하려면 180을 곱하세요.

```python
# 커스텀 노드에서 사용 예시
obs = self.blackboard.observation
distance  = obs.get("distance", 10000.0)        # m 단위 그대로
ata_deg   = obs.get("ata_deg", 0.0) * 180.0    # 정규화 → 실제 각도(°)
aa_deg    = obs.get("aa_deg", 0.0) * 180.0     # 정규화 → 실제 각도(°)
alt_gap   = obs.get("alt_gap", 0.0)            # m 단위 그대로 (양수=적이 위)
side_flag = obs.get("side_flag", 0)            # -1/0/1
```

---

## 🎯 BFM 상황 분류 시스템

`IsOffensiveSituation`, `IsDefensiveSituation`, `IsNeutralSituation` 조건 노드는 `CombatGeometry`를 기반으로 자동 분류됩니다.

| 상황 | 분류 기준 | 권장 전술 |
|------|----------|----------|
| **OBFM** (공격 유리) | ATA<45°, AA<100°, 거리 0.3~3NM | `LeadPursuit`, `GunAttack`, `HighYoYo` |
| **DBFM** (방어 필요) | AA>120°, ATA>90° | `BreakTurn`, `DefensiveManeuver`, `DefensiveSpiral` |
| **HABFM** (정면 대등) | HCA<90°, 동일 고도 | `OneCircleFight`, `TwoCircleFight` |

### 핵심 각도 개념

```
ATA (Antenna Train Angle): 내 속도 벡터와 적 방향 사이 각도
  → 0°   = 내가 적을 정면으로 조준 중 (공격 유리)
  → 90°  = 적이 내 측면
  → 180° = 적이 내 후방

AA (Aspect Angle): 적 기준으로 내가 어느 방향에 있는지
  → 0°   = 내가 적의 후방 (안전, 공격 유리)
  → 90°  = 내가 적의 측면
  → 180° = 내가 적의 정면 (위험, 적이 나를 조준 중)

Gun WEZ 진입 조건: ATA < 4° AND 거리 152~914m → 데미지 발생
```

---

## 📋 주요 명령어

```bash
# 단판 대전
python scripts/run_match.py --agent1 my_agent --agent2 simple

# 다중 라운드 대전
python scripts/run_match.py --agent1 my_agent --agent2 ace --rounds 5

# 에이전트 검증
python tools/validate_agent.py submissions/my_agent/my_agent.yaml
```

**에이전트 탐색 순서**: `submissions/{name}/{name}.yaml` → `examples/{name}.yaml` → 직접 경로

---

## 📂 디렉토리 구조

```
ai-combat-sdk/
├── sdk/
│   ├── docs/
│   │   └── NODE_REFERENCE.md   # 전체 노드 + 파라미터 레퍼런스
│   └── tools/
│       └── validate_agent.py   # 제출 전 검증 도구
├── examples/                   # 예제 에이전트 (테스트용)
│   ├── simple.yaml
│   ├── aggressive.yaml
│   ├── defensive.yaml
│   └── ace.yaml
├── submissions/                # 참여자 제출 디렉토리
│   ├── viper1/
│   │   ├── viper1.yaml
│   │   └── nodes/             # 커스텀 노드 (선택)
│   └── eagle1/
├── scripts/
│   └── run_match.py           # 대전 실행
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
| `BelowHardDeck` | `threshold=1000` m | 고도 < 임계값 |
| `EnemyInRange` | `max_distance=5000` m | 적이 지정 거리 이내 |
| `DistanceBelow` | `threshold=3000` m | 거리 < 임계값 |
| `DistanceAbove` | `threshold=2000` m | 거리 > 임계값 |
| `AltitudeAbove` | `min_altitude=3000` m | 고도 ≥ 지정값 |
| `AltitudeBelow` | `min_altitude=1000` m | 고도 ≤ 지정값 |
| `VelocityAbove` | `min_velocity=200` m/s | 속도 ≥ 지정값 |
| `VelocityBelow` | `max_velocity=400` m/s | 속도 ≤ 지정값 |
| `UnderThreat` | `aa_threshold=120` ° | AA > 임계값 (정면 위협) |
| `ATAAbove` | `threshold=60` ° | ATA > 임계값 (적이 측면/후방) |
| `ATABelow` | `threshold=30` ° | ATA < 임계값 (적이 전방) |
| `IsOffensiveSituation` | - | OBFM: 공격 유리 상황 |
| `IsDefensiveSituation` | - | DBFM: 방어 필요 상황 |
| `IsNeutralSituation` | - | HABFM: 정면/고측면 대등 상황 |
| `IsMerged` | `merge_threshold=500` m | 근접 교전 상태 |
| `EnergyHighPs` | `threshold=0` | 잉여 에너지(Ps) > 임계값 |

**Action 노드 (액션 실행)**

| 노드 | 기본값 | 설명 |
|------|--------|------|
| `Pursue` | 파라미터 12개 | 거리·고도·방위각·ATA 종합 추적 |
| `LeadPursuit` | - | 선도 추적 (Gun WEZ 진입 최적화) |
| `PurePursuit` | - | 순수 추적 (적 현재 위치) |
| `LagPursuit` | - | 지연 추적 (오버슈트 방지) |
| `Evade` | - | 적 반대 방향 강선회 + 가속 |
| `ClimbTo` | `target_altitude=6000` m | 목표 고도로 상승 |
| `DescendTo` | `target_altitude=4000` m | 목표 고도로 하강 |
| `AltitudeAdvantage` | `target_advantage=500` m | 적보다 지정 고도 우위 유지 |
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
python scripts/run_match.py --agent1 my_agent --agent2 aggressive
python scripts/run_match.py --agent1 my_agent --agent2 ace

# 3. Hard Deck 위반 없는지 확인 (리플레이 분석)
```

---

## 🏆 예제 에이전트

| 에이전트 | 위치 | 전략 | 난이도 |
|----------|------|------|--------|
| `simple` | examples/ | 기본 추적 (`Pursue`) | ⭐ |
| `aggressive` | examples/ | 적극적 공격 (`LeadPursuit` 중심) | ⭐⭐ |
| `defensive` | examples/ | 방어 중심 (`DefensiveManeuver`) | ⭐⭐ |
| `ace` | examples/ | BFM 상황별 전술 | ⭐⭐⭐ |
| `viper1` | submissions/ | 커스텀 노드 포함 | ⭐⭐⭐ |
| `eagle1` | submissions/ | 기본 노드 조합 | ⭐⭐ |

```bash
# 예제 에이전트끼리 대전
python scripts/run_match.py --agent1 ace --agent2 aggressive
python scripts/run_match.py --agent1 defensive --agent2 simple
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
            threshold: 1000
        - type: Action
          name: ClimbTo
          params:
            target_altitude: 3000
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
# 근거리 (< 1000m): Gun WEZ 진입 시도
- type: Sequence
  children:
    - type: Condition
      name: DistanceBelow
      params:
        threshold: 1000
    - type: Action
      name: GunAttack

# 중거리 (1000~3000m): 선도 추적
- type: Sequence
  children:
    - type: Condition
      name: DistanceBelow
      params:
        threshold: 3000
    - type: Action
      name: LeadPursuit

# 원거리 (> 3000m): 기본 추적 + 가속
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

## ❓ FAQ

**Q: `name`이 파일명과 다르면 어떻게 되나요?**  
A: 에이전트 로딩에 실패합니다. `validate_agent.py`로 미리 확인하세요.

**Q: Hard Deck 위반 없이도 지는 이유는?**  
A: 시간 종료(2000 스텝) 시 체력이 낮으면 집니다. 상대 체력을 더 빠르게 줄이는 전술이 필요합니다.

**Q: `ata_deg`가 0에 가까운데 데미지가 안 들어가요.**  
A: 거리가 152~914m 범위 밖이면 데미지가 없습니다. 거리 조건도 동시에 충족해야 합니다.

**Q: 커스텀 노드에서 `set_action(2, 4, 2)`의 의미는?**  
A: `(고도=유지, 방향=직진, 속도=유지)` 입니다. 인덱스 의미는 [고수준 액션 공간](#고수준-액션-공간-5×9×5) 참조.

**Q: `side_flag`와 `relative_bearing_deg`의 차이는?**  
A: `side_flag`는 -1/0/1의 이산값, `relative_bearing_deg`는 -1~1 정규화된 연속값입니다. 정밀한 방향 제어에는 `relative_bearing_deg`를 사용하세요.

**Q: `ModuleNotFoundError`가 발생해요.**  
A: 가상환경이 활성화되지 않았습니다. `.venv\Scripts\activate` (Windows) 또는 `source .venv/bin/activate` (Linux/Mac)를 실행하세요.

---

## 📖 문서

| 문서 | 설명 |
|------|------|
| [docs/NODE_REFERENCE.md](docs/NODE_REFERENCE.md) | 전체 노드 + 파라미터 상세 레퍼런스 |

---

## 📞 지원

- **GitHub Issues**: 버그 리포트 및 질문
- **예제**: `examples/`, `submissions/` 폴더 참고

---

**🛩️ 하늘을 지배할 당신의 AI를 개발하세요!**

Copyright © 2026 AI Combat Team. All rights reserved.
