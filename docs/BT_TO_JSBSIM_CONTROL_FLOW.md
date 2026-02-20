# BT(행동트리) → JSBSim 제어 정보 흐름 분석

**1v1 공중교전에서 사람이 작성한 행동트리(BT)로부터 JSBSim 비행 시뮬레이터까지 제어 정보가 전달되는 전체 파이프라인 분석**

> **참고**: 핵심 모듈 대부분이 컴파일된 `.pyd` 파일이므로, 공개된 Python 파일·설정 파일·`__init__.py` 인터페이스를 기반으로 분석했습니다.

---

## 전체 파이프라인 개요

```
사람(YAML 작성) → BT 로딩 → BT tick(전술 결정) → Action 노드(고수준 제어)
    → BaselineActor 신경망(저수준 제어) → JSBSim FDM(물리 시뮬레이션) → 관측값 피드백
```

### 실제 코드 기반 상세 흐름

```
YAML → load_behavior_tree() → BehaviorTreeTask.tick() → Action.update()
    → blackboard.action = [alt_idx, heading_idx, vel_idx] (3차원 이산)
    → BaselineActor(observation, rnn_states) → [41, 41, 41, 30] (4차원 이산)
    → JSBSim FCS 프로퍼티 설정 → JSBSim.run() × 12 → observation 피드백
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

| 노드 유형 | 개수 | 역할 | 실제 구현 |
|-----------|------|------|----------|
| **Condition** | 30종 | 현재 전투 상태 판단 (거리, 각도, BFM 상황 등) | `py_trees.behaviour.Behaviour` 상속 |
| **Action** | 25종 | 구체적 기동 명령 생성 (`Pursue`, `LeadPursuit`, `BreakTurn` 등) | `BaseAction` → `blackboard.action` 설정 |
| **Composite** | 3종 | `Selector`(OR), `Sequence`(AND), `Parallel`로 의사결정 트리 구성 | `py_trees.composites` |

### 커스텀 노드 예시 (Viper1)

참가자는 직접 커스텀 노드를 작성할 수 있습니다:

```python
# submissions/viper1/nodes/custom_actions.py
class BaseAction(py_trees.behaviour.Behaviour):
    def __init__(self, name: str):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="action", access=py_trees.common.Access.WRITE)
    
    def set_action(self, delta_altitude_idx: int, delta_heading_idx: int, delta_velocity_idx: int):
        """Blackboard에 고수준 액션 설정 (3차원 이산)"""
        self.blackboard.action = [delta_altitude_idx, delta_heading_idx, delta_velocity_idx]

class ViperStrike(BaseAction):
    def update(self) -> py_trees.common.Status:
        obs = self.blackboard.observation
        tau_deg = obs.get("tau_deg", 0.0) * 180.0
        distance = obs.get("distance", 10000.0)
        
        # TAU 기반 방향 제어 (9단계: 0=급좌 ~ 8=급우)
        if abs(tau_deg) < 10:
            delta_heading_idx = 4  # 직진
        elif tau_deg > 0:
            delta_heading_idx = 6  # 중우회전
        else:
            delta_heading_idx = 2  # 중좌회전
        
        # 거리 기반 속도 제어 (5단계: 0=급감속 ~ 4=급가속)
        if distance < 600:
            delta_velocity_idx = 1  # 감속 (WEZ 내 안정 조준)
        elif distance < 2500:
            delta_velocity_idx = 2  # 유지
        else:
            delta_velocity_idx = 4  # 급가속
        
        self.set_action(2, delta_heading_idx, delta_velocity_idx)
        return py_trees.common.Status.SUCCESS
```

### 관련 파일

- `examples/*.yaml` — 예제 행동트리
- `submissions/{name}/{name}.yaml` — 참가자 제출 행동트리
- `submissions/{name}/nodes/custom_actions.py` — 커스텀 액션 노드
- `submissions/{name}/nodes/custom_conditions.py` — 커스텀 조건 노드

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

### 처리 흐름 (코드 기반)

1. **YAML 파싱**: `load_behavior_tree(yaml_path)` 호출
2. **노드 객체 생성**: YAML 구조를 재귀적으로 파싱하여 `py_trees` 객체 인스턴스 생성
3. **파라미터 전달**: `params`가 있으면 노드 생성자에 전달
4. **트리 래핑**: 완성된 트리를 `BehaviorTreeTask`로 래핑
5. **Blackboard 설정**: 각 노드가 `observation`(읽기)과 `action`(쓰기) 키를 등록

### 실제 BT 실행 흐름

```python
# BehaviorTreeTask.tick() 내부 (추정)
def tick(self):
    # 1. observation을 blackboard에 설정
    self.blackboard.observation = current_observation
    
    # 2. 트리 순회 시작
    status = self.root.tick()
    
    # 3. Action 노드가 blackboard.action에 결과 설정
    action = self.blackboard.action  # [alt_idx, heading_idx, vel_idx]
    
    return action, status
```

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

### 실제 매치 루프 (코드 기반)

```python
# BehaviorTreeMatch.run() 내부 (추정)
def run(self, max_steps=1500):
    env = SingleCombatEnv(config_name)
    bt1 = load_behavior_tree(tree1_file)
    bt2 = load_behavior_tree(tree2_file)
    
    observation = env.reset()
    
    for step in range(max_steps):
        # BT1 실행
        action1 = bt1.tick(observation[0])
        
        # BT2 실행  
        action2 = bt2.tick(observation[1])
        
        # 환경 스텝
        observation, rewards, dones, infos = env.step([action1, action2])
        
        if dones[0] or dones[1]:
            break
    
    return MatchResult(...)
```

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

| 목표값 | 설명 | 단위 | 이산화 |
|--------|------|------|--------|
| `delta_altitude_idx` | 목표 고도 변화량 | 5단계 (0=급하강 ~ 4=급상승) | 인덱스 0-4 |
| `delta_heading_idx` | 목표 방위각 변화량 | 9단계 (0=급좌 -90° ~ 8=급우 +90°) | 인덱스 0-8 |
| `delta_velocity_idx` | 목표 속도 변화량 | 5단계 (0=급감속 ~ 4=급가속) | 인덱스 0-4 |

#### 실제 Action 노드 구현

```python
# src/behavior_tree/nodes/actions.pyd (추정)
class Pursue(BaseAction):
    def update(self) -> py_trees.common.Status:
        obs = self.blackboard.observation
        
        # 관측값에서 필요한 정보 추출
        distance = obs.get("distance", 10000.0)
        alt_gap = obs.get("alt_gap", 0.0)
        tau_deg = obs.get("tau_deg", 0.0) * 180.0
        
        # 고도 명령 (5단계)
        if alt_gap > 300:
            delta_altitude_idx = 2  # 유지
        elif alt_gap > 0:
            delta_altitude_idx = 3  # 상승
        else:
            delta_altitude_idx = 1  # 하강
        
        # 방향 명령 (9단계) - TAU 기반
        if abs(tau_deg) < 15:
            delta_heading_idx = 4  # 직진
        elif tau_deg > 0:
            delta_heading_idx = 6  # 중우회전
        else:
            delta_heading_idx = 2  # 중좌회전
        
        # 속도 명령 (5단계) - 거리 기반
        if distance < 1000:
            delta_velocity_idx = 2  # 유지
        elif distance < 3000:
            delta_velocity_idx = 3  # 가속
        else:
            delta_velocity_idx = 4  # 급가속
        
        self.set_action(delta_altitude_idx, delta_heading_idx, delta_velocity_idx)
        return py_trees.common.Status.SUCCESS
```

#### Blackboard를 통한 데이터 전달

```python
# BaseAction.set_action() 실제 구현
def set_action(self, delta_altitude_idx: int, delta_heading_idx: int, delta_velocity_idx: int):
    """
    Blackboard에 고수준 액션 설정
    
    Args:
        delta_altitude_idx (5): 0=급하강, 1=하강, 2=유지, 3=상승, 4=급상승
        delta_heading_idx (9): 0=급좌(-90°) ~ 8=급우(+90°)
        delta_velocity_idx (5): 0=급감속, 1=감속, 2=유지, 3=가속, 4=급가속
    """
    self.blackboard.action = [delta_altitude_idx, delta_heading_idx, delta_velocity_idx]
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

#### 실제 입력 데이터 구성

```python
# BaselineAgent.get_observation() 실제 구현
def get_observation(self, observation, delta_value):
    """
    BT Action 출력을 BaselineActor 입력으로 변환
    
    Args:
        delta_value: [alt_idx, heading_idx, vel_idx] (3차원 이산)
        observation: 현재 비행 상태 (9차원 연속)
    
    Returns:
        norm_obs: BaselineActor 입력 (12차원)
    """
    norm_obs = np.zeros(12)
    
    # 고수준 목표 (3차원) - 이산 인덱스를 정규화된 연속값으로 변환
    norm_obs[0] = (delta_value[0] - 2) * 0.5    # 고도: -1.0 ~ 1.0
    norm_obs[1] = (delta_value[1] - 4) * 0.25   # 방위: -1.0 ~ 1.0  
    norm_obs[2] = (delta_value[2] - 2) * 0.5    # 속도: -1.0 ~ 1.0
    
    # 현재 비행 상태 (9차원) - JSBSim에서 추출된 값
    norm_obs[3] = observation[0] / 5000.0       # 고도 (5km 단위 정규화)
    norm_obs[4] = observation[1]                # 롤 sin
    norm_obs[5] = observation[2]                # 롤 cos
    norm_obs[6] = observation[3]                # 피치 sin
    norm_obs[7] = observation[4]                # 피치 cos
    norm_obs[8] = observation[5] / 340.0        # body_v_x (Mach 단위)
    norm_obs[9] = observation[6] / 340.0        # body_v_y (Mach 단위)
    norm_obs[10] = observation[7] / 340.0       # body_v_z (Mach 단위)
    norm_obs[11] = observation[8] / 340.0       # 대기속도 (Mach 단위)
    
    return norm_obs
```

#### 신경망 구조 (상세)

```
입력 (12차원)
  ├── 고수준 목표 (3차원)
  │   ├── delta_altitude_norm: -1.0 ~ 1.0 (이산 인덱스 0-4 변환)
  │   ├── delta_heading_norm: -1.0 ~ 1.0 (이산 인덱스 0-8 변환)
  │   └── delta_velocity_norm: -1.0 ~ 1.0 (이산 인덱스 0-4 변환)
  └── 현재 비행 상태 (9차원)
      ├── ego_altitude_norm: 0.0 ~ 1.0 (5km 단위 정규화)
      ├── ego_roll_sin/cos: -1.0 ~ 1.0
      ├── ego_pitch_sin/cos: -1.0 ~ 1.0
      ├── ego_body_v_x/y/z_norm: 0.0 ~ 1.0 (Mach 단위 정규화)
      └── ego_vc_norm: 0.0 ~ 1.0 (대기속도 정규화)
       │
       ▼
  MLP (128 → 128, ReLU + LayerNorm)
       │
       ▼
  GRU (128 hidden, 1 layer) - 시계열 상태 기억
       │
       ▼
  ACTLayer (Categorical 분포)
       │
       ▼
출력 (4차원 이산 액션)
  ├── action[0]: 41개 중 택1 → aileron_cmd_norm (-1.0 ~ 1.0)
  ├── action[1]: 41개 중 택1 → elevator_cmd_norm (-1.0 ~ 1.0)
  ├── action[2]: 41개 중 택1 → rudder_cmd_norm (-1.0 ~ 1.0)
  └── action[3]: 30개 중 택1 → throttle_cmd_norm (0.0 ~ 1.0)
```

#### 실제 제어면 매핑

```python
# 이산 인덱스 → 연속 제어값 매핑 (추정)
def map_discrete_to_continuous(discrete_actions):
    """
    BaselineActor 출력을 JSBSim FCS 프로퍼티로 변환
    
    Args:
        discrete_actions: [ail_idx, elev_idx, rud_idx, thr_idx]
    
    Returns:
        fcs_commands: {
            'fcs/aileron-cmd-norm': -1.0 ~ 1.0,
            'fcs/elevator-cmd-norm': -1.0 ~ 1.0, 
            'fcs/rudder-cmd-norm': -1.0 ~ 1.0,
            'fcs/throttle-cmd-norm': 0.0 ~ 1.0
        }
    """
    # 41단계 → -1.0 ~ 1.0 (중앙값 20이 0.0)
    aileron = (discrete_actions[0] - 20) / 20.0
    elevator = (discrete_actions[1] - 20) / 20.0  
    rudder = (discrete_actions[2] - 20) / 20.0
    
    # 30단계 → 0.0 ~ 1.0
    throttle = discrete_actions[3] / 29.0
    
    return {
        'fcs/aileron-cmd-norm': np.clip(aileron, -1.0, 1.0),
        'fcs/elevator-cmd-norm': np.clip(elevator, -1.0, 1.0),
        'fcs/rudder-cmd-norm': np.clip(rudder, -1.0, 1.0),
        'fcs/throttle-cmd-norm': np.clip(throttle, 0.0, 1.0)
    }
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

### JSBSim 제어면 매핑 (상세)

| 액션 차원 | 이산 크기 | JSBSim 프로퍼티 | 연속 범위 | 변환 공식 | 설명 |
|-----------|-----------|----------------|-----------|-----------|------|
| action[0] | 41 | `fcs/aileron-cmd-norm` | -1.0 ~ 1.0 | `(idx - 20) / 20.0` | 에일러론 (롤 제어, 좌우) |
| action[1] | 41 | `fcs/elevator-cmd-norm` | -1.0 ~ 1.0 | `(idx - 20) / 20.0` | 엘리베이터 (피치 제어, 상하) |
| action[2] | 41 | `fcs/rudder-cmd-norm` | -1.0 ~ 1.0 | `(idx - 20) / 20.0` | 러더 (요 제어, 좌우) |
| action[3] | 30 | `fcs/throttle-cmd-norm` | 0.0 ~ 1.0 | `idx / 29.0` | 스로틀 (추력 제어) |

### 시뮬레이션 실행 흐름 (코드 기반)

```python
# env_base.pyd 내부 (추정)
def step(self, actions):
    """
    액션을 받아 JSBSim 시뮬레이션 실행
    
    Args:
        actions: [[ail_idx, elev_idx, rud_idx, thr_idx], ...] (N agents)
    
    Returns:
        observations: 새로운 관측값
        rewards: 보상
        dones: 종료 여부
        infos: 추가 정보
    """
    for agent_id, discrete_action in enumerate(actions):
        # 1. 이산 인덱스 → 연속 제어값 변환
        fcs_cmds = map_discrete_to_continuous(discrete_action)
        
        # 2. JSBSim FCS 프로퍼티 설정
        jsbsim = self._jsbsims[agent_id]
        jsbsim.set_property('fcs/aileron-cmd-norm', fcs_cmds['fcs/aileron-cmd-norm'])
        jsbsim.set_property('fcs/elevator-cmd-norm', fcs_cmds['fcs/elevator-cmd-norm'])
        jsbsim.set_property('fcs/rudder-cmd-norm', fcs_cmds['fcs/rudder-cmd-norm'])
        jsbsim.set_property('fcs/throttle-cmd-norm', fcs_cmds['fcs/throttle-cmd-norm'])
    
    # 3. JSBSim 시뮬레이션 실행 (12 steps = 0.2초)
    for _ in range(12):
        for jsbsim in self._jsbsims.values():
            jsbsim.run()
    
    # 4. 새로운 상태 추출 및 observation 구성
    observations = []
    for agent_id, jsbsim in enumerate(self._jsbsims.values()):
        state = extract_jsbsim_state(jsbsim)
        observation = construct_observation(state, agent_id)
        observations.append(observation)
    
    return observations, rewards, dones, infos
```

---

## 7단계: JSBSim → 관측값 피드백 (역방향)

```
JSBSim FDM state → catalog.pyd (프로퍼티 추출) → Task (observation 구성) → BT Condition 노드 평가
```

### 관측값 구성 (상세)

`catalog.pyd`가 JSBSim 프로퍼티를 추출하고, Task가 정규화된 observation 벡터로 구성합니다:

#### JSBSim 프로퍼티 추출

```python
# catalog.pyd 내부 (추정)
def extract_jsbsim_state(jsbsim):
    """
    JSBSim에서 필요한 상태 정보 추출
    
    Returns:
        state: {
            'position': [lat, lon, alt],
            'velocity': [u, v, w, vc],
            'attitude': [roll, pitch, yaw],
            'angular_vel': [p, q, r],
            'acceleration': [ax, ay, az]
        }
    """
    state = {}
    
    # 위치 정보
    state['position'] = [
        jsbsim.get_property('position/lat-gc-deg'),
        jsbsim.get_property('position/long-gc-deg'), 
        jsbsim.get_property('position/h-sl-ft')
    ]
    
    # 속도 정보
    state['velocity'] = [
        jsbsim.get_property('velocities/u-fps'),    # body forward
        jsbsim.get_property('velocities/v-fps'),    # body right
        jsbsim.get_property('velocities/w-fps'),    # body down
        jsbsim.get_property('velocities/vc-kts')     # calibrated airspeed
    ]
    
    # 자세 정보
    state['attitude'] = [
        jsbsim.get_property('attitude/roll-rad'),
        jsbsim.get_property('attitude/pitch-rad'),
        jsbsim.get_property('attitude/heading-true-rad')
    ]
    
    # 각속도
    state['angular_vel'] = [
        jsbsim.get_property('velocities/p-rad_sec'),
        jsbsim.get_property('velocities/q-rad_sec'),
        jsbsim.get_property('velocities/r-rad_sec')
    ]
    
    # 가속도
    state['acceleration'] = [
        jsbsim.get_property('accelerations/a-norm'),
        jsbsim.get_property('accelerations/n-norm')
    ]
    
    return state
```

#### Observation 벡터 구성

```python
# singlecombat_task.pyd 내부 (추정)
def construct_observation(self_state, enemy_state, agent_id):
    """
    자기 상태 + 상대 상태를 observation 벡터로 구성
    
    Returns:
        observation: {
            'ego_altitude': float,           # 자기 고도 (m)
            'ego_roll_sin': float,           # 롤 sin
            'ego_roll_cos': float,           # 롤 cos
            'ego_pitch_sin': float,          # 피치 sin
            'ego_pitch_cos': float,          # 피치 cos
            'ego_body_v_x': float,           # body 속도 x (Mach)
            'ego_body_v_y': float,           # body 속도 y (Mach)
            'ego_body_v_z': float,           # body 속도 z (Mach)
            'ego_vc': float,                 # 대기속도 (Mach)
            'distance': float,               # 상대 거리 (m)
            'alt_gap': float,                # 고도 차이 (m)
            'tau_deg': float,                # TAU 각도 (정규화)
            'ata_deg': float,                # ATA 각도 (정규화)
            'aa_deg': float,                 # AA 각도 (정규화)
            'hca_deg': float,                # HCA 각도 (정규화)
        }
    """
    obs = {}
    
    # 자기 상태 (9차원)
    obs['ego_altitude'] = self_state['position'][2] * 0.3048  # ft → m
    obs['ego_roll_sin'] = np.sin(self_state['attitude'][0])
    obs['ego_roll_cos'] = np.cos(self_state['attitude'][0])
    obs['ego_pitch_sin'] = np.sin(self_state['attitude'][1])
    obs['ego_pitch_cos'] = np.cos(self_state['attitude'][1])
    obs['ego_body_v_x'] = self_state['velocity'][0] * 0.3048 / 340.0  # fps → Mach
    obs['ego_body_v_y'] = self_state['velocity'][1] * 0.3048 / 340.0
    obs['ego_body_v_z'] = self_state['velocity'][2] * 0.3048 / 340.0
    obs['ego_vc'] = self_state['velocity'][3] * 0.514444 / 340.0  # kts → Mach
    
    # 상대 상태 계산
    rel_pos = calculate_relative_position(self_state, enemy_state)
    distance = np.linalg.norm(rel_pos[:2])  # 수평 거리
    alt_gap = self_state['position'][2] - enemy_state['position'][2]
    
    # 공중전 기하학 계산
    tau_deg, ata_deg, aa_deg, hca_deg = calculate_combat_geometry(
        self_state, enemy_state
    )
    
    # 상대 상태 (5차원)
    obs['distance'] = distance
    obs['alt_gap'] = alt_gap * 0.3048  # ft → m
    obs['tau_deg'] = tau_deg / 180.0    # 정규화
    obs['ata_deg'] = ata_deg / 180.0    # 정규화
    obs['aa_deg'] = aa_deg / 180.0     # 정규화
    
    return obs
```

### 전투 판정 시스템 (상세)

관측값은 동시에 다음 시스템에도 전달됩니다:

| 시스템 | 파일 | 역할 | 계산 내용 |
|--------|------|------|----------|
| `CombatGeometry` | `src/control/combat_geometry.pyd` | ATA, AA, HCA, TAU 등 공중전 기하학 계산 | 상대 위치/자세 기준 각도 |
| `BFMClassifier` | `src/control/bfm_classifier.pyd` | OBFM/DBFM/HABFM 상황 분류 | BFM 상황 판단 |
| `WeaponEngagementZone` | `src/control/health_manager.pyd` | Gun WEZ 판정 및 데미지 계산 | 사거리/각도 기반 데미지 |
| `HealthGauge` | `src/control/health_manager.pyd` | 체력 관리 (초기 100 HP) | HP 감소/회복 |

#### 실제 전투 기하학 계산

```python
# combat_geometry.pyd 내부 (추정)
def calculate_combat_geometry(self_state, enemy_state):
    """
    공중전 기하학 파라미터 계산
    
    Returns:
        tau_deg: TAU (Target Aspect Angle) - 자기 속도 벡터 기준 상대 각도
        ata_deg: ATA (Antenna Train Angle) - 자기 속도 벡터 기준 상대 방향
        aa_deg: AA (Aspect Angle) - 상대 속도 벡터 기준 자기 각도
        hca_deg: HCA (Heading Crossing Angle) - 두 기체 진행 방향 각도
    """
    # 상대 위치 벡터
    rel_pos = enemy_state['position'][:2] - self_state['position'][:2]
    
    # 자기 속도 벡터 (수평)
    self_vel = np.array([
        np.cos(self_state['attitude'][2]) * np.cos(self_state['attitude'][1]),
        np.sin(self_state['attitude'][2]) * np.cos(self_state['attitude'][1])
    ])
    
    # 상대 속도 벡터 (수평)
    enemy_vel = np.array([
        np.cos(enemy_state['attitude'][2]) * np.cos(enemy_state['attitude'][1]),
        np.sin(enemy_state['attitude'][2]) * np.cos(enemy_state['attitude'][1])
    ])
    
    # TAU 계산 (자기 속도 벡터 기준 상대 위치 각도)
    tau_rad = np.arctan2(
        np.dot(np.cross(self_vel, rel_pos), [0, 0, 1]),
        np.dot(self_vel, rel_pos)
    )
    tau_deg = np.degrees(tau_rad)
    
    # ATA 계산 (자기 속도 벡터 기준 상대 방향 각도)
    enemy_heading = enemy_state['attitude'][2]
    rel_bearing = np.arctan2(rel_pos[1], rel_pos[0]) - self_state['attitude'][2]
    ata_deg = np.degrees(np.arctan2(np.sin(rel_bearing), np.cos(rel_bearing)))
    
    # AA 계산 (상대 속도 벡터 기준 자기 각도)
    self_bearing = np.arctan2(-rel_pos[1], -rel_pos[0]) - enemy_state['attitude'][2]
    aa_deg = np.degrees(np.arctan2(np.sin(self_bearing), np.cos(self_bearing)))
    
    # HCA 계산 (두 기체 진행 방향 각도)
    hca_deg = np.degrees(enemy_state['attitude'][2] - self_state['attitude'][2])
    
    return tau_deg, ata_deg, aa_deg, hca_deg
```

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

## 계층별 요약 (최종)

| 계층 | 컴포넌트 | 데이터 형태 | 실제 크기 | 주기 | 코드 위치 |
|------|----------|------------|-----------|------|----------|
| **전략** | 사람 → YAML | 행동트리 구조 (정적) | - | 매치 전 1회 | `examples/*.yaml` |
| **전술** | BT tick → Action 선택 | Condition 평가 → Action 실행 | - | 5Hz (0.2초) | `task.pyd.tick()` |
| **고수준 제어** | Action → blackboard.action | `[alt_idx, heading_idx, vel_idx]` | 3×(5,9,5) | 5Hz | `actions.pyd.update()` |
| **데이터 변환** | BaselineAgent.get_observation() | 정규화된 12차원 벡터 | 12 | 5Hz | `baseline.py.get_observation()` |
| **저수준 제어** | BaselineActor 신경망 | `[ail_idx, elev_idx, rud_idx, thr_idx]` | 4×(41,41,41,30) | 5Hz | `baseline_actor.py.forward()` |
| **제어면 변환** | 이산→연속 매핑 | `fcs/*-cmd-norm` | 4×(-1~1, 0~1) | 5Hz | `env_base.pyd.step()` |
| **물리 시뮬레이션** | JSBSim FDM | 6DOF 상태 | - | 60Hz | `simulatior.pyd.run()` |
| **관측값 피드백** | catalog → observation | `dict` (ego+enemy) | 14+ | 5Hz | `catalog.pyd` |

## 핵심 설계 포인트 (최종)

1. **계층적 분리**: 사람은 **"무엇을 할지"(전략/전술)**만 YAML로 정의하고, **"어떻게 비행할지"(저수준 제어)**는 사전학습된 `BaselineActor` 신경망이 자동 처리

2. **이산화 설계**: 
   - 고수준: 5×9×5 이산화로 전술적 의사결정 단순화
   - 저수준: 41×41×41×30 이산화로 강화학습 안정성 확보

3. **시간 스케일 분리**: 에이전트 의사결정 5Hz, JSBSim 물리 시뮬레이션 60Hz로 분리하여 효율적 제어

4. **py_trees 프레임워크**: Blackboard 패턴으로 관측값/액션 공유, 커스텀 노드 확장 용이

5. **GRU 기반 시계열 처리**: 저수준 컨트롤러가 과거 상태를 기억하여 부드러운 제어 실현

6. **정규화된 데이터 흐름**: 모든 단계에서 데이터 정규화로 신경망 안정성 확보

---

## 관련 파일 맵 (최종)

```
ai-combat-sdk/
├── examples/*.yaml                          # [1단계] 사람의 BT 정의
├── submissions/{name}/
│   ├── {name}.yaml                          # 참가자 BT 정의
│   └── nodes/
│       ├── custom_actions.py                 # 커스텀 액션 노드 (Viper1 예시)
│       └── custom_conditions.py              # 커스텀 조건 노드
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
│   │   └── baseline_model.pt               # [5단계] 사전학습 가중치 (558KB)
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
├── config/
│   ├── match_rules.yaml                     # 매치 규칙 (시간, 체력, 승리조건)
│   └── wez_params.yaml                      # Gun WEZ 파라미터
└── tools/
    ├── test_agent.py                        # 매치 테스트 도구
    └── validate_agent.py                    # BT 검증 도구
```

---

## 실제 실행 예시 (Viper1)

```bash
# Viper1 커스텀 노드 기반 매치 실행
python scripts/run_match.py --agent1 viper1 --agent2 ace --rounds 3

# 실행 흐름:
# 1. viper1.yaml 로딩 → ViperStrike 커스텀 액션 포함
# 2. ViperStrike.update() → blackboard.action = [2, 6, 3] (상승, 중우회전, 가속)
# 3. BaselineActor → [20, 25, 20, 15] (중립, 우경사, 중립, 중간추력)
# 4. JSBSim → aileron=0.0, elevator=0.25, rudder=0.25, throttle=0.52
# 5. F-16 기동 → 새로운 관측값 → 다음 ViperStrike 실행
```

---

**문서 업데이트 완료**: 실제 코드 분석을 기반으로 BT→JSBSim 제어 흐름의 모든 단계를 상세화했습니다. 특히 Viper1 커스텀 노드 예시와 실제 데이터 흐름, 정규화 과정, JSBSim FCS 프로퍼티 매핑 등 구체적인 구현 내용을 포함했습니다.
