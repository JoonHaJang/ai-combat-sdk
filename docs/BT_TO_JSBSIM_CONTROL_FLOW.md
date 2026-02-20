# BT(행동트리) → JSBSim 제어 정보 흐름 분석

**1v1 공중교전에서 사람이 작성한 행동트리(BT)로부터 JSBSim 비행 시뮬레이터까지 제어 정보가 전달되는 전체 파이프라인 분석**

> **참고**: 핵심 모듈 대부분이 컴파일된 `.pyd` 파일이므로, 공개된 Python 파일·설정 파일·`__init__.py` 인터페이스를 기반으로 분석했습니다.

---

## 전체 파이프라인 개요

```
사람(YAML 작성) → BT 로딩 → BT tick(전술 결정) → Action 노드(고수준 제어)
    → BaselineActor 신경망(저수준 제어) → JSBSim FDM(물리 시뮬레이션) → 관측값 피드백
```

---

## 1단계: 사람의 입력 — YAML 행동트리 정의

사람은 YAML 파일로 행동트리를 작성합니다. 이것이 제어 의도의 **최상위 진입점**입니다.

```yaml
# examples/simple.yaml
name: "simple"
version: "1.0"
description: "Hard Deck 회피 + 기본 추적만 하는 단순 전투기"

tree:
  type: Selector
  children:
    - type: Sequence
      children:
        - type: Condition
          name: BelowHardDeck
        - type: Action
          name: ClimbTo
          params:
            target_altitude: 2000
    - type: Action
      name: Pursue
```

### 노드 구성

| 노드 유형 | 개수 | 역할 |
|-----------|------|------|
| **Condition** | 30종 | 현재 전투 상태 판단 (거리, 각도, BFM 상황 등) |
| **Action** | 25종 | 구체적 기동 명령 생성 (`Pursue`, `LeadPursuit`, `BreakTurn` 등) |
| **Composite** | 3종 | `Selector`(OR), `Sequence`(AND), `Parallel`로 의사결정 트리 구성 |

### 관련 파일

- `examples/*.yaml` — 예제 행동트리
- `submissions/{name}/{name}.yaml` — 참가자 제출 행동트리

---

## 2단계: YAML 로딩 및 BT 인스턴스 생성

```
YAML 파일 → load_behavior_tree() → BehaviorTreeTask 인스턴스
```

### 관련 모듈

| 모듈 | 파일 | 역할 |
|------|------|------|
| `load_behavior_tree` | `src/behavior_tree/loader.pyd` | YAML 파싱 → 노드 객체 그래프 생성 |
| `BehaviorTreeTask` | `src/behavior_tree/task.pyd` | 매 스텝 트리 순회(tick) → Action 선택·실행 |
| `conditions` | `src/behavior_tree/nodes/conditions.pyd` | 30개 조건 노드 구현 |
| `actions` | `src/behavior_tree/nodes/actions.pyd` | 25개 액션 노드 구현 |

### 처리 흐름

1. `load_behavior_tree(yaml_path)` 호출
2. YAML 구조를 재귀적으로 파싱
3. 각 노드 타입(`Selector`, `Sequence`, `Condition`, `Action`)에 맞는 객체 인스턴스 생성
4. `params`가 있으면 노드 생성자에 전달
5. 완성된 트리를 `BehaviorTreeTask`로 래핑

---

## 3단계: 매치 실행 — BehaviorTreeMatch 오케스트레이션

```
BehaviorTreeMatch → SingleCombatEnv (JSBSim 환경) → 매 스텝 루프
```

### 매치 초기화

```python
# tools/test_agent.py 또는 scripts/run_match.py에서 호출
match = BehaviorTreeMatch(
    tree1_file=str(agent_path),
    tree2_file=str(opponent_path),
    config_name="1v1/NoWeapon/bt_vs_bt"
)
result = match.run(verbose=True)
```

### BehaviorTreeMatch가 수행하는 작업

1. 두 YAML 파일을 `load_behavior_tree()`로 로딩
2. `config_name`에 해당하는 환경 설정 로딩 (`bt_vs_bt.yaml`)
3. `SingleCombatEnv` (또는 `HierarchicalSingleCombatTask` 기반 환경) 초기화
4. **매 스텝 루프** 실행: `observation → BT tick → action → env.step(action)`

### 관련 모듈

| 모듈 | 파일 | 역할 |
|------|------|------|
| `BehaviorTreeMatch` | `src/match/runner.pyd` | 매치 전체 실행 관리 |
| `MatchResult` | `src/match/result.pyd` | 매치 결과 데이터 |
| `judge` | `src/match/judge.pyd` | 승패 판정 (체력, Hard Deck 등) |
| `replay_writer` | `src/match/replay_writer.pyd` | ACMI 리플레이 기록 |

---

## 4단계: 환경 설정 — 시뮬레이션 파라미터

### bt_vs_bt.yaml 핵심 설정

```yaml
# src/simulation/envs/JSBSim/configs/1v1/NoWeapon/bt_vs_bt.yaml
task: hierarchical_singlecombat    # 계층적 제어 구조

sim_freq: 60                       # JSBSim 내부 60Hz
agent_interaction_steps: 12        # 에이전트 행동 간격 = 12 sim steps = 0.2초

max_steps: 1500                    # 300초 (5분) 최대 교전 시간
altitude_limit: 304.8              # 1000 ft Hard Deck
acceleration_limit_x: 88.2        # 9G 과부하 제한

aircraft_configs:
  A0100: { model: f16, ... }       # Blue 팀 F-16
  B0100: { model: f16, ... }       # Red 팀 F-16
```

### 핵심 파라미터 의미

| 파라미터 | 값 | 의미 |
|---------|-----|------|
| `task` | `hierarchical_singlecombat` | **2단계 계층적 제어** (고수준 → 저수준) |
| `sim_freq` | 60 | JSBSim 물리 시뮬레이션 60Hz |
| `agent_interaction_steps` | 12 | 에이전트 5Hz 제어 (60/12 = 5Hz, 0.2초 간격) |
| `use_baseline` | false | 두 에이전트 모두 BT가 제어 |

---

## 5단계: Action 노드의 고수준 명령 → 저수준 제어 변환

이것이 **가장 핵심적인 단계**입니다. `hierarchical_singlecombat` 설정이 **2단계 계층적 제어 구조**를 의미합니다.

### 5-1. 고수준 제어: BT Action 노드 → delta 목표값

각 Action 노드는 현재 관측값(observation)을 기반으로 **고수준 제어 목표**를 생성합니다:

| 목표값 | 설명 | 단위 |
|--------|------|------|
| `delta_altitude` | 목표 고도 변화량 | km |
| `delta_heading` | 목표 방위각 변화량 | rad |
| `delta_velocity` | 목표 속도 변화량 | Mach |

이 패턴은 `BaselineAgent.set_delta_value()` 메서드에서 확인됩니다:

```python
# src/simulation/envs/JSBSim/model/baseline.py
class BaselineAgent(ABC):
    def get_observation(self, observation, delta_value):
        '''
        Baseline observation (12차원):
          0. ego delta altitude      (unit: 1km)
          1. ego delta heading       (unit: rad)
          2. ego delta velocities_u  (unit: Mach)
          3. ego_altitude            (unit: 5km)
          4. ego_roll_sin
          5. ego_roll_cos
          6. ego_pitch_sin
          7. ego_pitch_cos
          8. ego_body_v_x            (unit: Mach)
          9. ego_body_v_y            (unit: Mach)
          10. ego_body_v_z           (unit: Mach)
          11. ego_vc                 (unit: Mach)
        '''
        norm_obs = np.zeros(12)
        norm_obs[:3] = delta_value       # 고수준 목표 (3차원)
        norm_obs[3:12] = observation[:9]  # 현재 비행 상태 (9차원)
        return norm_obs
```

#### 예시: Pursue 액션의 delta 계산

```python
class PursueAgent(BaselineAgent):
    def set_delta_value(self, observation):
        delta_altitude = observation[10]           # 적과의 고도차
        delta_heading = observation[14] * observation[11]  # 적 방향 × 거리 가중치
        delta_velocity = observation[9]            # 적과의 속도차
        return np.array([delta_altitude, delta_heading, delta_velocity])
```

### 5-2. 저수준 제어: BaselineActor 신경망 → 이산 제어 명령

고수준 delta 목표값 + 현재 비행 상태(12차원)가 **사전 학습된 신경망(BaselineActor)**에 입력됩니다:

```python
# src/simulation/envs/JSBSim/model/baseline_actor.py
class BaselineActor(nn.Module):
    def __init__(self, input_dim=12):
        self.base = MLPBase(input_dim, '128 128')    # MLP 인코더
        self.rnn = GRULayer(128, 128, 1)             # GRU 시계열 처리
        self.act = ACTLayer(128, [41, 41, 41, 30])   # 4차원 이산 액션 출력

    def forward(self, obs, rnn_states):
        x = self.base(x)          # MLP 인코딩
        x, h_s = self.rnn(x, h_s) # GRU 시계열 처리
        actions = self.act(x)      # 이산 액션 출력
        return actions, h_s
```

#### 신경망 구조

```
입력 (12차원)
  ├── delta_altitude (1km 단위)
  ├── delta_heading (rad 단위)
  ├── delta_velocity (Mach 단위)
  ├── ego_altitude (5km 단위)
  ├── ego_roll_sin/cos
  ├── ego_pitch_sin/cos
  ├── ego_body_v_x/y/z (Mach 단위)
  └── ego_vc (Mach 단위)
       │
       ▼
  MLP (128 → 128, ReLU + LayerNorm)
       │
       ▼
  GRU (128 hidden, 1 layer)
       │
       ▼
  ACTLayer (Categorical 분포)
       │
       ▼
출력 (4차원 이산 액션)
  ├── action[0]: 41개 중 택1 → aileron (롤 제어)
  ├── action[1]: 41개 중 택1 → elevator (피치 제어)
  ├── action[2]: 41개 중 택1 → rudder (요 제어)
  └── action[3]: 30개 중 택1 → throttle (추력 제어)
```

#### 사전학습 모델

- 파일: `src/simulation/envs/JSBSim/model/baseline_model.pt` (558KB)
- 역할: "목표 고도/방위/속도로 비행하라"는 고수준 명령을 받아 F-16의 조종면을 제어하는 **목표 추종 컨트롤러**
- 학습 방식: PPO/MAPPO 강화학습으로 사전 학습됨

---

## 6단계: 환경(env.step) → JSBSim 시뮬레이터 적용

```
이산 액션 인덱스 → env_wrappers → SingleCombatEnv.step() → env_base → simulator.pyd → JSBSim FDM
```

### 환경 계층 구조

| 모듈 | 파일 | 역할 |
|------|------|------|
| `env_base` | `envs/env_base.pyd` | JSBSim 인스턴스 관리, step/reset 기본 구현 |
| `SingleCombatEnv` | `envs/singlecombat_env.pyd` | 1v1 교전 환경 |
| `env_wrappers` | `envs/env_wrappers.pyd` | 벡터화 래퍼 (`DummyVecEnv`, `SubprocVecEnv`) |
| `simulator` | `core/simulatior.pyd` | JSBSim FDM 인터페이스 |
| `catalog` | `core/catalog.pyd` | JSBSim 프로퍼티 카탈로그 |

### JSBSim 제어면 매핑

이산 액션 인덱스가 연속 제어값으로 디코딩되어 JSBSim FCS에 설정됩니다:

| 액션 차원 | JSBSim 프로퍼티 | 범위 | 설명 |
|-----------|----------------|------|------|
| action[0] (41) | `fcs/aileron-cmd-norm` | -1.0 ~ 1.0 | 에일러론 (롤 제어) |
| action[1] (41) | `fcs/elevator-cmd-norm` | -1.0 ~ 1.0 | 엘리베이터 (피치 제어) |
| action[2] (41) | `fcs/rudder-cmd-norm` | -1.0 ~ 1.0 | 러더 (요 제어) |
| action[3] (30) | `fcs/throttle-cmd-norm` | 0.0 ~ 1.0 | 스로틀 (추력 제어) |

### 시뮬레이션 실행 흐름

1. 이산 인덱스 → 연속 제어면 값으로 디코딩 (예: 인덱스 20/41 → aileron 0.0)
2. JSBSim FCS 프로퍼티에 값 설정
3. `JSBSim.run()` × 12회 호출 (60Hz × 12 = 0.2초)
4. 동일 제어 입력이 12 sim step 동안 유지
5. 새로운 항공기 상태 출력

---

## 7단계: JSBSim → 관측값 피드백 (역방향)

```
JSBSim FDM state → catalog.pyd (프로퍼티 추출) → Task (observation 구성) → BT Condition 노드 평가
```

### 관측값 구성

`catalog.pyd`가 JSBSim 프로퍼티를 추출하고, Task가 정규화된 observation 벡터로 구성합니다:

**자기(ego) 상태:**
- 고도, 롤/피치 (sin/cos), 속도(body frame x/y/z), 대기속도(Vc)

**상대(enemy) 상태:**
- 상대 거리, 방위각, ATA(Antenna Train Angle), AA(Aspect Angle), HCA(Heading Crossing Angle)

이 관측값이 다시 BT의 **Condition 노드**에 전달되어 다음 tick의 의사결정에 사용됩니다.

### 전투 판정 시스템

관측값은 동시에 다음 시스템에도 전달됩니다:

| 시스템 | 역할 |
|--------|------|
| `CombatGeometry` | ATA, AA, HCA, TAU 등 공중전 기하학 계산 |
| `BFMClassifier` | OBFM/DBFM/HABFM 상황 분류 |
| `WeaponEngagementZone` | Gun WEZ 판정 및 데미지 계산 |
| `HealthGauge` | 체력 관리 (초기 100 HP) |

---

## 전체 아키텍처 다이어그램

```
┌─────────────────────────────────────────────────────────────────┐
│  1. 사람 (BT 작성자)                                             │
│  ┌──────────────────────────────┐                               │
│  │  YAML 행동트리 작성           │  ← 전략적 의도 (고수준)        │
│  │  (Selector/Sequence/Action)  │                               │
│  └──────────┬───────────────────┘                               │
└─────────────┼───────────────────────────────────────────────────┘
              │ load_behavior_tree()
              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. BehaviorTreeMatch (매치 오케스트레이터)                       │
│  ┌──────────────────────────────┐                               │
│  │  BehaviorTreeTask.tick()     │  ← 매 0.2초마다 트리 순회      │
│  │  Condition 평가 → Action 선택 │                               │
│  └──────────┬───────────────────┘                               │
└─────────────┼───────────────────────────────────────────────────┘
              │ Action 노드 실행
              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. Action 노드 (고수준 제어)                                    │
│  ┌──────────────────────────────┐                               │
│  │  set_delta_value()           │  ← 기동 의도 → delta 목표값    │
│  │  [Δalt, Δheading, Δvel]     │    (고도차, 방위차, 속도차)     │
│  └──────────┬───────────────────┘                               │
└─────────────┼───────────────────────────────────────────────────┘
              │ delta_value + ego_state (12차원)
              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. BaselineActor (사전학습 신경망, 저수준 제어)                  │
│  ┌──────────────────────────────┐                               │
│  │  MLP → GRU → ACTLayer       │  ← 목표 추종 컨트롤러          │
│  │  출력: [41, 41, 41, 30]     │    (이산 제어 인덱스)           │
│  └──────────┬───────────────────┘                               │
└─────────────┼───────────────────────────────────────────────────┘
              │ 4차원 이산 액션
              ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. SingleCombatEnv.step() → simulator.pyd                      │
│  ┌──────────────────────────────┐                               │
│  │  이산 인덱스 → 연속 제어값    │  ← aileron, elevator,         │
│  │  JSBSim FCS 프로퍼티 설정     │    rudder, throttle           │
│  │  JSBSim.run() × 12 steps    │    (60Hz × 12 = 0.2초)        │
│  └──────────┬───────────────────┘                               │
└─────────────┼───────────────────────────────────────────────────┘
              │ JSBSim FDM 물리 시뮬레이션
              ▼
┌─────────────────────────────────────────────────────────────────┐
│  6. JSBSim Flight Dynamics Model (F-16)                         │
│  ┌──────────────────────────────┐                               │
│  │  6DOF 비행역학 계산           │  ← 공기역학, 엔진, 중력 등     │
│  │  새로운 항공기 상태 출력       │    위치/속도/자세/가속도        │
│  └──────────┬───────────────────┘                               │
└─────────────┼───────────────────────────────────────────────────┘
              │ catalog.pyd → observation 구성
              ▼
┌─────────────────────────────────────────────────────────────────┐
│  7. 관측값 피드백                                                │
│  ┌──────────────────────────────┐                               │
│  │  ego 상태 + enemy 상태       │  ← 다음 BT tick에 전달         │
│  │  → Condition 노드 평가        │    (5Hz 피드백 루프)           │
│  └──────────────────────────────┘                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 계층별 요약

| 계층 | 컴포넌트 | 데이터 형태 | 주기 |
|------|----------|------------|------|
| **전략** | 사람 → YAML | 행동트리 구조 (정적) | 매치 전 1회 |
| **전술** | BT tick → Action 선택 | Condition 평가 결과 → Action 노드 | 5Hz (0.2초) |
| **고수준 제어** | Action → delta 목표값 | `[Δalt, Δheading, Δvel]` (3차원 연속) | 5Hz |
| **저수준 제어** | BaselineActor 신경망 | `[ail, elev, rud, thr]` (4차원 이산, 41×41×41×30) | 5Hz |
| **물리 시뮬레이션** | JSBSim FDM | 제어면 연속값 → 6DOF 상태 | 60Hz |

---

## 핵심 설계 포인트

1. **계층적 분리**: 사람은 **"무엇을 할지"(전략/전술)**만 YAML로 정의하고, **"어떻게 비행할지"(저수준 제어)**는 사전학습된 `BaselineActor` 신경망이 자동 처리
2. **시간 스케일 분리**: 에이전트 의사결정 5Hz, JSBSim 물리 시뮬레이션 60Hz로 분리하여 효율적 제어
3. **이산 액션 공간**: 연속 제어면을 41/30개 구간으로 이산화하여 강화학습 안정성 확보
4. **GRU 기반 시계열 처리**: 저수준 컨트롤러가 과거 상태를 기억하여 부드러운 제어 실현

---

## 관련 파일 맵

```
ai-combat-sdk/
├── examples/*.yaml                          # [1단계] 사람의 BT 정의
├── src/behavior_tree/
│   ├── loader.pyd                           # [2단계] YAML → BT 객체 변환
│   ├── task.pyd                             # [2단계] BT tick 실행 엔진
│   └── nodes/
│       ├── conditions.pyd                   # [3단계] 30개 조건 노드
│       └── actions.pyd                      # [3단계] 25개 액션 노드
├── src/match/
│   └── runner.pyd                           # [3단계] BehaviorTreeMatch
├── src/simulation/envs/JSBSim/
│   ├── configs/1v1/NoWeapon/bt_vs_bt.yaml   # [4단계] 환경 설정
│   ├── model/
│   │   ├── baseline.py                      # [5단계] 고수준 delta 계산
│   │   ├── baseline_actor.py                # [5단계] 저수준 신경망
│   │   └── baseline_model.pt               # [5단계] 사전학습 가중치
│   ├── envs/
│   │   ├── env_base.pyd                     # [6단계] 환경 기반 클래스
│   │   └── singlecombat_env.pyd             # [6단계] 1v1 교전 환경
│   ├── core/
│   │   ├── simulatior.pyd                   # [6단계] JSBSim FDM 인터페이스
│   │   └── catalog.pyd                      # [7단계] 프로퍼티 추출
│   └── tasks/
│       └── singlecombat_task.pyd            # [7단계] observation 구성
├── src/control/
│   ├── combat_geometry.pyd                  # [7단계] ATA/AA/HCA 계산
│   ├── bfm_classifier.pyd                   # [7단계] BFM 상황 분류
│   └── health_manager.pyd                   # [7단계] WEZ/체력 관리
└── config/
    ├── match_rules.yaml                     # 매치 규칙 (시간, 체력, 승리조건)
    └── wez_params.yaml                      # Gun WEZ 파라미터
```
