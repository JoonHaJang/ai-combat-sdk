# BT → RNN 제어기 병목 분석 (2026-06-01)

## 요약

BT(Behavior Tree)의 고수준 속도 명령(vel bin)이 RNN 저수준 제어기에 실제로 반영되지 않음.  
vel=4 (급가속) 명령 시에도 **throttle = 0.50 고정** — 80 ticks(~8초) 이상 연속 명령 후에야 서서히 반응.

---

## 1. 제어 파이프라인 구조

```
BT Action (cost_branch_selector.py)
    ↓  [delta_alt_idx, delta_hdg_idx, delta_vel_idx]  5×9×5 discrete
singlecombat_task.normalize_action()
    ↓  12-dim input_obs 조립
RNN (GRU, 128-hidden, 5Hz)
    ↓  [aileron, elevator, rudder, throttle] continuous
JSBSim (6-DOF physics, 20Hz)
```

---

## 2. RNN 입력 12차원 구조

```python
# singlecombat_task.py L353-359
input_obs[0]  = norm_delta_altitude[action[0]]   # -0.4 ~ +0.4
input_obs[1]  = norm_delta_heading[action[1]]    # -π/2 ~ +π/2
input_obs[2]  = norm_delta_velocity[action[2]]   # -0.08 ~ +0.08  ← 너무 작음
input_obs[3]  = ego_alt / 5000                   # 고도
input_obs[4]  = roll_sin
input_obs[5]  = roll_cos
input_obs[6]  = pitch_sin
input_obs[7]  = pitch_cos
input_obs[8]  = v_body_x / 340
input_obs[9]  = v_body_y / 340
input_obs[10] = v_body_z / 340
input_obs[11] = vc / 340                          # 현재 속도 정규화  ← 핵심
```

**문제**: vel=4 입력 `norm_delta_velocity[4] = +0.08` 이 12개 입력 중 **가장 작은 신호**. 현재 속도 `vc/340 ≈ 0.94` (320kts) 대비 +0.08 추가는 미미.

---

## 3. RNN 모델 구조 (BaselineActor)

```
input(12) → MLP(128→128) → GRU(128, 1-layer) → ACTLayer
                                                  ├── aileron   (Categorical, 41 bins)
                                                  ├── elevator  (Categorical, 41 bins)
                                                  ├── rudder    (Categorical, 41 bins)
                                                  └── throttle  (Categorical, 30 bins)  ← 분리 학습
```

**throttle 변환**:
```python
norm_act[3] = ll_action[3] / 58 + 0.4   # ll_action[3] = 0~40 → throttle 0.4~1.09
```

throttle = 0.50 → `ll_action[3] ≈ 5.8` = RNN이 현재 상태에서 이 값이 optimal이라 학습됨.

---

## 4. 진단: 왜 vel=4가 throttle에 반영 안 되는가

### 4.1 학습 환경에서의 throttle 결정 방식

RNN은 **PPO/MAPPO로 reward 최대화** 학습. 학습 중 throttle은 vel hint가 아닌 **현재 속도 + 에너지 상태**에서 optimal을 스스로 결정. 결과:
- `vc ≈ 320~400 kts` 범위에서 throttle ≈ 0.5 가 "에너지 효율 최적"으로 수렴
- vel=4 hint (+0.08)는 12개 입력 중 1개 — 나머지 9개 ego state가 훨씬 강한 신호

### 4.2 실측 데이터 (AGG 매치)

| step | vel 명령 | throttle | vc | 결과 |
|---|---|---|---|---|
| 0~100 | K11 vel=1 → OFFP vel=4 | 0.500 | 387→360 | vc 감소 |
| 100~250 | OFFP vel=2 | 0.500 | 360→331 | vc 계속 감소 |
| 250~350 | K40 vel=4 연속 | **0.500 고정** | 331→323 | **무반응** |
| 350~600 | K40 vel=4 계속 | 0.500 | 323→400 | 80 ticks 후 서서히 증가 |

**핵심**: vel=4를 80 ticks(~8초, RNN 5Hz × 40 call) 연속 줘야 GRU state가 서서히 밀림.

### 4.3 ACE 매치에서는 왜 추격이 빠른가

ACE는 우리쪽으로 다가오면서 closure > 0 구간 발생 → RNN이 "적이 접근한다" 학습된 반응으로 throttle ↑. 우리 vel=4 명령 덕분이 아님. **게임 dynamics 자체가 RNN state를 고속 상태로 유도**.

---

## 5. BT vel bin의 실제 의미 (재정의 필요)

| bin | norm 값 | 실제 기능 | 기대 기능 |
|---|---|---|---|
| 0 (급감속) | -0.08 | GRU state hint | 즉각 throttle=0 |
| 1 (감속)   | -0.04 | 약한 hint | throttle 낮춤 |
| 2 (유지)   | 0.00  | no hint | throttle 유지 |
| 3 (가속)   | +0.04 | 약한 hint | throttle 올림 |
| 4 (급가속) | +0.08 | 약한 hint | **즉각 throttle=1.0 → 실제는 무반응** |

---

## 6. 결론: BT → RNN 병목이 생기는 이유

1. **BT vel bin은 RNN hint** — 직접 throttle 제어가 아님
2. **RNN throttle은 ego state 기반 자율 결정** — vel hint는 1/12 약한 신호
3. **GRU memory 지연** — 상태 변화에 ~8초(80 ticks) ramp-up 필요
4. **학습 분포 고착** — `vc ≈ 320~400kts`에서 throttle=0.5 → local optimum

**결과**: AGG/DEF 처럼 초반부터 고속 도주하는 적 대상으로 burst 명령 무효화.

---

## 7. 해결 방법 비교

### 방법 A: throttle 직접 override (즉각 구현 가능)

```python
# singlecombat_task.py L366-371 수정
norm_act[3] = ll_action[3] / 58 + 0.4
# override
if vel_idx == 4: norm_act[3] = 1.0    # 즉각 max throttle
elif vel_idx == 0: norm_act[3] = 0.0  # 즉각 min throttle
```

- 장점: 1줄 수정, 즉각 효과
- 단점: RNN 물리 모델과 충돌 가능 (elevator/aileron은 RNN, throttle만 BT) → 비행 불안정 가능

### 방법 B: RNN fine-tuning (학습 필요, 중간 난이도)

학습 코드 존재: `src/simulation/scripts/train/train_jsbsim.py`

```bash
# 기존 학습 환경
python train_jsbsim.py \
  --env-name SingleCombat \
  --scenario-name 1v1/NoWeapon/bt_vs_bt \
  --algorithm-name mappo
```

vel=4 입력 시 고throttle 출력하도록 **reward shaping 추가**:
- 현재 reward: 적 HP 감소 + Hard Deck 회피
- 추가 reward: `vel_cmd == 4 AND vc < target_vc → throttle_reward`

- 장점: RNN 물리적 일관성 유지 + 장기적 해결
- 단점: 학습 시간 필요 (GPU + ~수 시간), 기존 성능 보존 불확실

### 방법 C: Low-level 제어기 교체 (큰 작업)

`baseline_model.pt`를 PID/MPC 기반 저수준 제어기로 교체.

- 장점: vel bin이 직접 throttle 명령으로 작동
- 단점: JSBSim 학습 분포 완전 교체, 기존 flight envelope 잃음

### 방법 D: BT mode에서 vel=2 유지 + 긴 horizon 버스트 (현재 K40)

vel=4 연속 8초 이상 유지 → 결국 throttle ↑. 현재 K40_CHASE_BURST가 이 방법.

- 장점: 엔진 수정 불필요, ACE 격파 보존
- 단점: AGG/DEF match에서 8초 동안 이미 15000ft 격차

---

## 7b. 실측 매핑 품질 (2026-06-01, tools/verify/bt_mapping_direct.py)

4개 매치 (6000 env steps) 실측. **모든 축 비선형**.

### vel bin → dvc (kt/env_step)

| vel=0 | vel=1 | vel=2 | vel=3 | vel=4 |
|---|---|---|---|---|
| -0.23 | **-0.26** ← 역전 | -0.19 | -0.09 | **+0.13 (유일 가속)** |

- vel=0~3 모두 감속. vel=4만 가속 → 사실상 on/off
- vel=1이 vel=0보다 더 감속 (역전)

### alt bin → dalt (ft/env_step)

| alt=0 | alt=1 | alt=2 | alt=3 |
|---|---|---|---|
| -11.2 | **+2.6** | **+0.6** | +7.4 |

- alt=0(급하강)만 하강. alt=1(하강 의도)인데 **실제 상승 +2.6**
- alt=2(수평)가 alt=3(상승)보다 낮은 +0.6 → **비단조**

### hdg bin → turn_rate (deg/s)

| hdg=0 | hdg=1 | hdg=2 | hdg=3 | hdg=4 | hdg=7 | hdg=8 |
|---|---|---|---|---|---|---|
| 32 | 26 | 34 | 11 | **2** | 46 | 23 |

- hdg=4(직진) = 최소 turn_rate=2 ✓
- hdg=0~3/7~8 모두 큰 turn이지만 **방향 일관성 없음**

### 결론
BT 9개 bin 중 **vel=4만 의도대로 동작**. alt/hdg는 RNN이 상태 기반으로 재해석. 재학습 시 단조성 보장 reward 설계 필수.

---

## 8. 학습 코드 위치 및 재학습 가능성

```
src/simulation/scripts/train/
├── train_jsbsim.py           # JSBSim 환경 학습 진입점
├── train_gym.py              # OpenAI Gym 환경 학습
└── config.py                 # 학습 하이퍼파라미터

ai-combat-core-main/src/simulation/envs/JSBSim/model/
├── baseline_actor.py         # BaselineActor 모델 정의 (GRU 기반)
├── baseline.py               # 학습용 full model (Actor+Critic)
└── baseline_model.pt         # 학습된 가중치 (~2MB)
```

**재학습 가능**: 코드 존재. 단 아래 의존성 필요:
- `wandb` (실험 추적)
- `setproctitle`
- PPO/MAPPO 학습 프레임워크 (`runner/share_jsbsim_runner.py`)
- GPU 권장 (CPU 가능하나 느림)

**가장 현실적인 방법 B (fine-tuning)**:
1. 기존 `baseline_model.pt` 로드
2. CHASE scenario (1v1, aggressive BT 상대) 에서 vel=4 reward shaping 추가
3. 수백 episode fine-tune (~1~2시간)
4. 새 `baseline_model_chase.pt` 생성

---

## 9. 현재 상태 및 권고

| 상태 | 값 |
|---|---|
| best known W | **85/100 (H40b)** |
| ACE | 63.00 ± 0.0 (W=5/5 deterministic) |
| AGG/DEF/v51 | 0/5 (D=5 — throttle 병목) |
| taken | 0 (H40b) |

**단기 권고**: 방법 A (throttle override) 테스트 → 비행 안정성 확인  
**중기 권고**: 방법 B (fine-tuning, ~1-2시간) → 근본 해결
