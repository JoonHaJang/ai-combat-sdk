# Superplan: 계층적 연속 제어 아키텍처 (HCCA v12)

## 1. 현재 문제

v11_code는 PNLeadPursuit 내부만 연속 함수화 (tau, ga). BT 라우팅은 여전히 16개 boolean 조건 → 25개 이산 action 선택.
**"문 안쪽은 연속, 문 여는 조건은 이산"** = 구조적 모순.

### 현재 v11_code 성능 (8 opponents × 3 rounds)

| Opponent | WR |
|----------|-----|
| simple | 66% |
| aggressive | 66% |
| defensive | 0% |
| eagle1 | 100% |
| golden | 100% |
| viper1 | 100% |
| ace | 100% |
| eagle2 | 0% |
| **TOTAL** | **66.7%** |

## 2. 목표

| 항목 | 현재 (v11_code) | 목표 (HCCA v12) |
|------|----------------|-----------------|
| 조건 노드 | 16개 boolean (hard threshold) | 4개 연속 스코어 함수 |
| 행동 노드 | 25개 개별 action | 4개 모드 컨트롤러 (내부 연속) |
| BT 구조 | 48 노드, depth 3 | 5 노드, depth 2 (안전 shell) |
| 제어 연속성 | PNLeadPursuit만 | **전체 시스템** |
| 전략 시야 | 반응형 (현재 tick만) | 장기 추세 + 인내 전략 |

## 3. 핵심 설계 결정: Blend vs Select

### 문제
ATTACK이 "hard left" (hdg=0), DEFEND가 "hard right" (hdg=8)일 때
→ blend하면 "straight" (hdg=4) = **최악** (공격도 방어도 안 됨)

### 해법: Commitment Architecture
- **Select, don't blend**: 가장 높은 weight의 모드 하나를 **선택** (blend 아님)
- **Hysteresis**: 모드 전환에 `switch_margin`(0.15) 이상 차이 필요
- **Min commitment**: 최소 5 tick(1초) 유지 후 재평가
- **Safety override**: tau_threat > 0.85면 즉시 DEFEND (hysteresis 무시)
- 같은 모드 **내부**의 sub-behavior는 방향이 호환되므로 연속 blend 가능

```
실제 파일럿도 동일: 기동 결정 → 실행 → 재평가 (동시에 두 기동 blend 안 함)
```

---

## 4. 5-Layer 아키텍처

```
Layer 0: State Estimation     → EMA 스무딩 + 미분 + 물리 파생
Layer 1: Strategic Assessment  → 4개 연속 스코어 (threat/opportunity/energy/pursuit)
Layer 2: Mode Selection        → Commitment Architecture로 모드 선택
Layer 3: Mode Controllers      → 선택된 모드가 (hdg, vel, alt) 연속 출력
Layer 4: Output               → 이산화 + 안전 클램프
```

### 4.1. Layer 0: State Estimation

**입력**: obs dict (28개 필드)
**출력**: StateEstimate (스무딩된 관측 + 미분 + 물리 파생)

```python
# EMA 스무딩 (2종)
alpha_fast = 0.3   # 미분용 (~1.1초 유효 윈도우)
alpha_slow = 0.1   # 추세용 (~3.3초 유효 윈도우)

# 관측값에서 EMA 계산하는 미분들:
ata_rate     = EMA_fast(delta_ATA / dt)     # LOS rate [deg/s]
aa_rate      = EMA_fast(delta_AA / dt)      # 적 추적 성공도 [deg/s]
range_rate   = EMA_fast(delta_dist / dt)    # 거리 변화율 [ft/s]
energy_rate  = EMA_fast(delta_e_diff / dt)  # 에너지 추세 [ft/s]

# 장기 추세 (EMA slow):
closure_trend = EMA_slow(closure)            # ~3초 평균 closure
ata_trend     = EMA_slow(delta_ATA)          # ~3초 ATA 변화 추세
energy_trend  = EMA_slow(delta_e_diff)       # ~5초 에너지 추세

# 물리 파생:
geo_advantage = sigmoid((AA - ATA) / ga_scale)  # ga in [0,1]
turn_radius   = V^2 / (g * sqrt(n^2 - 1))       # 현재 선회 반경 [ft]
t_impact      = dist / closure_fps               # 병합까지 시간 [s]
t_turn        = ATA / omega                      # 추적 완료까지 시간 [s]
overshoot     = t_impact < t_turn * margin
```

**Tunable (4개)**: alpha_fast(0.3), alpha_slow(0.1), ga_scale(45), overshoot_margin(2.0)

### 4.2. Layer 1: Strategic Assessment

16개 boolean 조건 → **4개 연속 스코어**, 각각 sigmoid(weighted_sum) in [0,1]

#### 1a. tau_threat (위협 평가)
**대체**: IsDefensiveGeometry, IsUnderFire, in_wez 판정

```
tau_threat = sigmoid(
    w1 * (closure / rdot_scale)           # 빠른 접근 = 위험
  + w2 * (1 - AA/180)                     # 적이 우리를 향함
  + w3 * (-aa_rate / aa_rate_scale)       # 적의 추적 성공도
  + w4 * (-energy_rate / edot_scale)      # 에너지 소모 추세
  + w5 * in_wez * 3.0                     # WEZ 진입 = 긴급
  + w6 * max(0, closure/300) * max(0, 1-dist/2000)  # 근거리+고속
  + bias
)
```
**Tunable (10개)**: w1-w6, bias, rdot_scale, aa_rate_scale, edot_scale

#### 1b. tau_opportunity (기회 평가)
**대체**: IsOffensiveGeometry, ATABelow, enm_in_wez

```
tau_opp = sigmoid(
    w1 * (1 - ATA/180)                    # 작은 ATA = 조준 중
  + w2 * (AA/180)                          # 큰 AA = 적 꼬리 잡음
  + w3 * max(0, 1 - dist/wez_max)         # 가까울수록 좋음
  + w4 * enm_in_wez * 3.0                 # 사격 가능
  + w5 * ga                                # 기하학적 우위
  + bias
)
```
**Tunable (7개)**: w1-w5, bias, wez_max_range

#### 1c. tau_energy (에너지 상태)
**대체**: IsHighEnergy, IsLowEnergy, energy_advantage

```
tau_energy = sigmoid(
    w1 * (e_diff / ediff_scale)           # 에너지 차이
  + w2 * alt_advantage * 1.5              # 고도 우위
  + w3 * spd_advantage * 1.0              # 속도 우위
  + w4 * (Ps / ps_scale)                  # 여분 추력
  + w5 * (energy_trend / edot_scale)      # 에너지 추세
  + bias
)
```
**Tunable (9개)**: w1-w5, bias, ediff_scale, ps_scale, edot_scale

#### 1d. tau_pursuit (추적 진행도)
**대체**: IsLostPursuit, IsChaseStale, CustomOrbitDetector

```
tau_pursuit = sigmoid(
    w1 * (closure_trend / closure_scale)   # 접근 추세
  + w2 * (-ata_trend / ata_scale)          # ATA 감소 = 진전
  + w3 * (range_rate / range_scale)        # 거리 좁힘
  + w4 * ga                                # 기하학적 우위
  + bias
)
```
- 낮은 tau_pursuit = 추적 실패/교착 → 전략 변경 필요
- **Tunable (8개)**: w1-w4, bias, closure_scale, ata_scale, range_scale

### 4.3. Layer 2: Mode Selection

4개 모드 가중치 → Commitment Architecture로 최종 선택

```python
# 모드 가중치 (Layer 1 스코어의 비선형 조합)
w_attack = tau_opp * (1 - tau_threat) * max(0.3, tau_energy)
w_defend = tau_threat * (1 - tau_opp * 0.5)
w_energy = (1 - tau_energy) * (1 - tau_threat * 0.7) * (1 - tau_opp * 0.7)
w_pursue = tau_pursuit * (1 - tau_threat * 0.5) * (1 - tau_opp * 0.3)

# Softmax 정규화
weights = softmax([w_attack, w_defend, w_energy, w_pursue] / temperature)

# Commitment으로 최종 모드 선택 (Section 3 참조)
```

**장기 전략 수정자** (패턴 기반 보정):
- **인내 수정**: ATTACK 60tick+ 진전 없음 → attack_penalty, energy_bonus
- **시간 수정**: 잔여시간 < 20% → 이기면 보수적, 지면 공격적
- **교전 단계**: merge 횟수 추적, 에너지 추세로 HP 대리 추정

**Tunable (5개)**: temperature(0.3), switch_margin(0.15), min_commit_ticks(5), critical_threat(0.85), patience_ticks(60)

### 4.4. Layer 3: Mode Controllers

각 모드는 연속 (hdg_cont, vel_cont, alt_cont) 출력.

#### ATTACK 모드 (공격/사격)

```
hdg: PN heading (P + N*lambda_dot + I항)
     N = n_base + (1 - tau_threat) * n_bonus
     overshoot시 N 제한

vel: 2-orbit 에너지-기하학 커플링
     근거리: vel_corner (선회율 극대화, R 축소)
     원거리+뒤잡음: vel_sprint (거리 좁힘)
     overshoot시: vel_brake

alt: e_diff > threshold + alt_advantage → dive (에너지 전환)
     그 외 level
```
**Tunable (11개)**: kp, ki, n_base, n_bonus, n_cap, blend_dist, vel_corner, vel_max, vel_brake, dive_thresh, dive_dist

#### DEFEND 모드 (방어/이탈)

```
hdg: 적 반대 방향으로 break (side_flag 기반)
     intensity = f(tau_threat, dist, in_wez)

vel: panic break → corner speed (최대 선회율)
     extension → max speed (분리)

alt: 고도 높으면 dive, 낮으면 climb
     초근거리+WEZ → 수직면 회피
```
**Tunable (7개)**: vel_desperate, vel_close, vel_medium, vel_extend, panic_dist, alt_split_high, alt_split_low

#### ENERGY 모드 (에너지 관리)

```
hdg: 느슨한 추적 (kp_energy = 0.5, 에너지 절약)

vel/alt: 에너지 적자 → climb (위치에너지 저축)
         에너지 흑자+뒤잡음 → dive attack 셋업
         에너지 흑자+앞 → climb higher (yo-yo 준비)
         균형 → 순항 유지

핵심: 에너지 과잉(>5000ft)이 오히려 패배 원인 → 축적이 아닌 전환 타이밍
```
**Tunable (7개)**: kp_energy, deficit_thresh, surplus_thresh, vel_build, vel_convert, vel_cruise, stall_thresh

#### PURSUE 모드 (추적/접근) — 기본 교전 모드

```
hdg: PN pursuit, N = f(ga)
     ga 낮음(적 앞) → 높은 N (inside cut)
     ga 높음(적 뒤) → 낮은 N (오버슈트 방지)

vel: 2-orbit 방정식
     원거리: sprint (접근)
     뒤잡음(ga>0.7): 적정 속도 (위치 유지)
     분리 중(closure<0): sprint
     교착(tau_pursuit 낮음): 가속 + 선회 완화 (orbit 탈출)
     선회전: corner speed (최대 omega)

alt: 에너지 적자 → gentle climb
     에너지 흑자 → gentle dive
```
**Tunable (13개)**: kp, n_base, n_gain, far_dist, ga_sprint, stale_closure, stale_pursuit, vel_sprint, vel_behind, vel_corner, orbit_break, energy_floor, energy_ceiling

### 4.5. Layer 4: Output

```python
# 연속값 → 이산 인덱스
hdg_idx = clamp(round(hdg_cont / 22.5) + 4, 0, 8)
vel_idx = clamp(round(vel_cont), 0, 4)
alt_idx = clamp(round(alt_cont + 2), 0, 4)

# 안전 클램프
if ego_alt < 2000 and alt_idx < 2: alt_idx = 3   # 강제 상승
if ego_alt < 1200: alt_idx = 4                     # 긴급 상승
```

---

## 5. 2-Orbit 방정식: 에너지-기하학 커플링

공중전의 근본 trade-off:

```
선회 반경:  R = V^2 / (g * sqrt(n^2 - 1))
선회율:    omega = g * sqrt(n^2 - 1) / V
비추력:    Ps = (T - D) * V / W

→ 속도 DOWN = R DOWN (tighter) + omega UP (faster turn) BUT 에너지 DOWN (지속 불가)
→ 속도 UP   = R UP (wider)    + omega DOWN (slower turn) BUT 에너지 UP (지속 가능)

"Corner speed" ≈ 300kts (vel_idx 2-3): omega 극대화 지점
```

**각 모드에서의 적용**:
| 모드 | 속도 전략 | 물리적 이유 |
|------|----------|------------|
| PURSUE(원거리) | V=high | R 크지만 접근 빠름. 선회전 아직 아님 |
| ATTACK(근거리) | V=corner | omega 극대화. 적 turn circle 안쪽 진입 |
| ENERGY | He 보존 | h <-> V^2/(2g) 교환. zoom climb/dive |
| DEFEND(panic) | V=corner | 최대 선회율로 적 tracking 무력화 |

---

## 6. BT YAML 구조

```yaml
name: "adaptive_eagle_v11_code"
version: "12.0.0"
description: |
  Hierarchical Continuous Control Architecture (HCCA)
  5-layer continuous function replaces boolean routing.
  BT shell: hard deck safety + WEZ priority + master controller.

tree:
  type: Selector
  children:
    # 1. Hard Deck 안전 (불변 - 물리적으로 이산인 유일한 케이스)
    - type: Sequence
      name: HardDeckAvoidance
      children:
        - type: Condition
          name: BelowHardDeck
          params:
            threshold_ft: 1200
        - type: Action
          name: ClimbTo
          params:
            target_altitude_ft: 3000

    # 2. Gun WEZ 기회 (boolean이 적절한 유일한 케이스)
    - type: Sequence
      name: GunEngagement
      children:
        - type: Condition
          name: DistanceBelow
          params:
            threshold_ft: 3000
        - type: Condition
          name: DistanceAbove
          params:
            threshold_ft: 500
        - type: Condition
          name: ATABelow
          params:
            threshold_deg: 12
        - type: Action
          name: SmartGunAttack
          params:
            kp: 1.2
            kd: 0.5

    # 3. 마스터 연속 컨트롤러 (나머지 전부)
    - type: Action
      name: ContinuousMasterController
```

48 노드 → **5 노드**. Hard deck과 WEZ만 boolean 유지.

---

## 7. 구현 파일

| 파일 | 변경 내용 |
|------|----------|
| `examples/adaptive_eagle_v11_code/nodes/custom_actions.py` | ContinuousMasterController 클래스 추가 (SmartGunAttack 유지) |
| `examples/adaptive_eagle_v11_code/adaptive_eagle_v11_code.yaml` | 최소 3-branch BT로 교체 |
| `examples/adaptive_eagle_v11_code/nodes/custom_conditions.py` | 기존 유지 (BelowHardDeck 등) |
| `examples/adaptive_eagle_v11_code/nodes/__init__.py` | ContinuousMasterController export 추가 |

## 8. 구현 순서

1. **Phase 1 - Core Framework**: StateEstimator + Layer 1 scores + ModeSelector + discretize
2. **Phase 2 - Mode Controllers**: ATTACK, DEFEND, PURSUE, ENERGY 각각 구현
3. **Phase 3 - Integration**: ContinuousMasterController 통합 + YAML + __init__.py
4. **Phase 4 - Validation**: validate_agent.py 통과 확인
5. **Phase 5 - A/B Test**: 8 opponents x 3 rounds vs v11_code baseline (66.7%)

## 9. Tunable Parameters 총계

| Layer | 수 | 역할 |
|-------|---|------|
| L0 State | 4 | EMA alpha, ga_scale, overshoot |
| L1 Threat | 10 | 위협 가중치 + scale |
| L1 Opportunity | 7 | 기회 가중치 + scale |
| L1 Energy | 9 | 에너지 가중치 + scale |
| L1 Pursuit | 8 | 추적 가중치 + scale |
| L2 Mode | 5 | temperature, commitment, safety |
| L3 Attack | 11 | PN heading + velocity + altitude |
| L3 Defend | 7 | break intensity + velocity |
| L3 Energy | 7 | heading gain + energy thresholds |
| L3 Pursue | 13 | PN pursuit + 2-orbit velocity |
| **Total** | **~81** | 모두 물리 기반 기본값 |

## 10. 검증 기준

- 8 opponents x 3 rounds A/B test (v11_code 66.7% baseline)
- **핵심 테스트**: defensive(0%), eagle2(0%) 개선 여부
- **안전 기준**: 어떤 opponent에서도 v11_code 대비 20pp 이상 후퇴 없을 것
- WEZ precision (SmartGunAttack 유지) 확인

## 11. 리스크 & 완화

| 리스크 | 완화 |
|--------|------|
| 파라미터 ~81개 → 최적화 어려움 | 물리 기반 기본값, 계층별 단계적 튜닝 |
| Commitment 지연 → 느린 반응 | Safety override (tau>0.85 즉시 DEFEND), min_commit=1초 |
| BT 단순화 → 디버깅 어려움 | 모드 로깅 추가 |
| Blend 불가 문제 | Commitment Architecture (blend 안 함) |
| defensive 0% 유지 가능성 | PURSUE 모드의 교착 탈출 로직 + ENERGY의 인내 전략 |
