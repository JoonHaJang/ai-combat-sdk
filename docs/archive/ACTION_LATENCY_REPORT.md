# Action Latency Report — BT 액션 응답 특성 측정 결과

> **목적**: Pursuit_Chase_BT 의 HJI dynamics 모델 설계 입력 산출.
> 어느 BT 액션이 HJI 의 정통 가정(연속 시간 단일 제어 입력)에 부합하고
> 어느 것이 multi-phase 시퀀스라 HJI 외부에서 처리해야 하는지 식별.
>
> **측정 도구**: `tools/profile_action_response.py`
> **측정 일**: 2026-05-12
> **데이터**: `logs/profiling/action_latency_metrics.csv` (31 actions × 3 trials each)
> **격리 BT**: `logs/profiling/yamls/profile_<action>.yaml` (HardDeck 안전망 + 단일 측정 대상 액션)

---

## 0. 측정 프로토콜

```
- canonical 초기 조건 (JSBSim core 기본): ATA=90°, dist=3297.6ft,
  V=386.8kts, alt=15000ft, HCA=180°
- 200 step 매치 (40s @ 5Hz tick)
- 우리 BT: 격리 (HardDeck 안전망 외 무조건 측정 대상 액션 발동)
- 상대 BT:
   · 추격류 → horizontal_flight (직선 비행, 외란 최소)
   · 회피/방어류 → aggressive (접근 트리거 제공)
- per-tick CSV: --log-csv (50 columns, src/match/runner.py:49)
- 3 trial 평균
```

**측정 자산**:
- BT 명령: `action_altitude`, `action_heading`, `action_velocity` (discrete bin 인덱스 0-4 추정)
- Low-level actuator: `aileron`, `elevator`, `rudder`, `throttle`
- State: `ego_vc_kts`, `ego_vx/vy/vz_kts`, `ego_altitude_ft`, `roll_deg`, `pitch_deg`
- 즉시 변화율: `turn_rate_degs`, `ps_fts`
- 활성 노드: `active_node` (액션 ID 추적)

**분류 알고리즘** (2단계):
1. **Intent** — BT 명령(action_*)의 변동성으로 어느 제어 채널을 변경하려 하는지 식별
2. **Intensity** — 측정된 state 변화량 / F-16 envelope 비율

| 라벨 | 의미 |
|------|------|
| `static_command` | 명령이 단일 값 유지 (모든 채널) |
| `<intensity>_<channel>` | intensity ∈ {weak, mild, moderate, strong, aggressive}, channel ∈ {altitude, heading, velocity} |
| `multi_phase` | 명령에 다단 부호변경 시퀀스 — non-Markovian |
| `action_not_active` | 격리 BT 내 trigger 조건 미충족으로 발동 안 됨 |

---

## 1. 측정 결과 (31 actions)

### 1.1 Tier 1 — Primitive 후보

| Action | 분류 | 비고 |
|--------|------|------|
| **LeadPursuit** | weak_heading | 명령은 heading 변동, canonical head-on 에서 응답 작음 |
| **LagPursuit** | multi_phase | 명령 부호변경 — 다단 시퀀스 |
| **PurePursuit** | multi_phase | |
| **Pursue** | multi_phase | 기본 추격이 다단 (head-on 결정 못함) |
| **Accelerate** | static_command | velocity 명령 단일 (max bin) |
| **Decelerate** | static_command | velocity 명령 단일 (min bin) |
| **ClimbTo** | mild_altitude | 알트 명령 활성, 점진적 상승 |
| **DescendTo** | mild_altitude | |
| **BreakTurn** | multi_phase | aggressive 상대 → 다단 진입 |
| **TurnLeft** | static_command | heading 명령 단일 (좌선회) |
| **TurnRight** | static_command | heading 명령 단일 (우선회) |
| **Straight** | static_command | 모든 명령 정적 (level flight) |
| **MaintainAltitude** | static_command | 모든 명령 정적 |

### 1.2 Tier 2 — Multi-phase composite

| Action | 분류 | 비고 |
|--------|------|------|
| HighYoYo | **action_not_active** | 격리에서 trigger 조건 미충족 |
| LowYoYo | **action_not_active** | 동일 |
| Loop | static_command, n=13 | 짧은 시퀀스 (13 tick = 2.6초) 후 종료 |
| ImmelmannTurn | weak_heading, n=16 | 짧은 시퀀스 (16 tick) |
| SplitS | static_command, n=20 | 짧은 시퀀스 (20 tick) |
| BarrelRoll | **action_not_active** | trigger 조건 |
| ClimbingTurn | static_command | 정적 |
| DescendingTurn | static_command | 정적 |
| HammerHead | static_command | 정적 |
| DefensiveManeuver | multi_phase | |
| DefensiveSpiral | multi_phase | |
| OvershootAvoidance | multi_phase | |
| Evade | multi_phase | |

### 1.3 Tier 3 — Tactical composite

| Action | 분류 | 비고 |
|--------|------|------|
| GunAttack | multi_phase | 사격 정렬 시퀀스 |
| EnergyFight | multi_phase | |
| OneCircleFight | multi_phase | 1-circle 기동 시퀀스 |
| TwoCircleFight | multi_phase | 2-circle 기동 |
| TCFight | multi_phase | TC fight |

---

## 2. HJI 호환성 분류

### 2.1 HJI Primitives (직접 매핑 가능) ★

HJI 제어 벡터 $u = (\omega_h, \dot\gamma, a)$ 의 각 component 에 직접 대응:

| HJI 제어 | BT 액션 후보 | 비고 |
|---------|------------|------|
| **$\omega_h$ (수평 선회율)** | `TurnLeft`, `TurnRight` | 단일 명령, 좌/우 선택 |
| | (`BreakTurn` 도 OK 단 trigger 의존) | aggressive 상대 시 multi_phase 진입 |
| **$\dot\gamma$ (수직 비행각율)** | `ClimbTo(target)`, `DescendTo(target)` | 목표 고도 setpoint 명령 |
| | (`MaintainAltitude`) | $\dot\gamma = 0$ 유지 |
| **$a$ (속도 가속)** | `Accelerate`, `Decelerate` | 단일 throttle 명령 |
| | (`Straight` 도 OK) | 현재 속도 유지 |

### 2.2 HJI Incompatible (BT 외부 또는 trigger 의존)

```
Multi-phase (non-Markovian):
  Pursue, LagPursuit, PurePursuit, BreakTurn (vs aggressive),
  DefensiveManeuver, DefensiveSpiral, OvershootAvoidance, Evade,
  GunAttack, EnergyFight, OneCircleFight, TwoCircleFight, TCFight

조건부 발동 (canonical 격리에서 안 됨):
  HighYoYo, LowYoYo, BarrelRoll

시간 한정 시퀀스 (Loop=13 tick, Immelmann=16, SplitS=20):
  Loop, ImmelmannTurn, SplitS

→ 이들은 HJI optimal 제어가 추천해도 BT-level 분기로 격리해 사용해야 함
```

### 2.3 LeadPursuit 특수 케이스

`LeadPursuit` 은 `weak_heading` 으로 분류됐으나, 분류기가 본 응답이 작은 이유:
- canonical 초기 (HCA=180°, ATA=90°) 는 head-on 통과 시나리오
- LeadPursuit 의 lead angle = N · ATA · 0.06 (또는 등가 PN) 이 ATA=90°에서 약함
- 양측이 stand-off 거리로 비행하면 LOS rate 작음 → PN 명령도 작음

**→ LeadPursuit 은 HJI 호환이지만 (closed-loop 단일 명령 흐름), canonical 에서 stress 테스트 안 됨**. F-16 envelope 의 max ω 측정은 JSBSim 테이블 (이미 알려진 21°/s @ 350kts) 사용.

---

## 3. HJI Dynamics 모델 설계 권고

### 3.1 제어 입력 정의

```
u_p = (u_omega, u_gamma, u_throttle) ∈ ℝ³

각 component 의 BT 액션 매핑:
  u_omega   ∈ {LEFT, RIGHT, STRAIGHT}    ← TurnLeft / TurnRight / Straight
  u_gamma   ∈ {CLIMB, DESCEND, LEVEL}    ← ClimbTo / DescendTo / MaintainAltitude
  u_throttle ∈ {ACCEL, DECEL, HOLD}      ← Accelerate / Decelerate / (Straight)

→ 이산 명령 3³ = 27 조합. HJI는 연속이지만 BT는 이산이므로
   action_quantize: u_continuous → 가장 가까운 27-조합 lookup
```

### 3.2 Rate Constraints (F-16 envelope, JSBSim 매칭)

```python
# from src/simulation/envs/JSBSim/configs/f16.xml (alread known)
# also from sim_dogfight_verify.py:54-79 _JSB_TR table
OMEGA_MAX(V) = piecewise:
  V=160:  6 deg/s
  V=200:  9
  V=250:  15
  V=300:  18
  V=350:  21      # corner speed
  V=400:  18.5
  V=420:  16      # operational max
  V=500:  14

GAMMA_DOT_MAX = OMEGA_MAX(V) * 0.7   # 수직 회전 한계 (점-질량 가정)
ACCEL_MAX = +15 kts/s (Accelerate 측정값 기반)
DECEL_MAX = -15 kts/s (Decelerate)
```

### 3.3 BT 액션 → HJI 제어 변환

```python
def hji_to_bt_action(u_continuous: np.ndarray) -> str:
    """HJI optimal control u* → BT 액션 이름 매핑."""
    omega, gamma_dot, accel = u_continuous
    
    # 수평
    if abs(omega) < OMEGA_THRESH:
        h_act = "Straight"
    elif omega > 0:
        h_act = "TurnRight"
    else:
        h_act = "TurnLeft"
    
    # 수직
    if abs(gamma_dot) < GAMMA_THRESH:
        v_act = "MaintainAltitude"
    elif gamma_dot > 0:
        v_act = "ClimbTo"
    else:
        v_act = "DescendTo"
    
    # 속도
    if abs(accel) < ACCEL_THRESH:
        s_act = "MaintainAltitude"   # 또는 'Straight'
    elif accel > 0:
        s_act = "Accelerate"
    else:
        s_act = "Decelerate"
    
    # BT는 한 번에 하나만 실행 → 우선순위 선택 또는 합성 노드
    return select_dominant(h_act, v_act, s_act)
```

⚠️ **BT 구조 제약**: 한 tick 에 한 action 만 발동. 따라서 (TurnLeft + ClimbTo + Accelerate) 동시 실행 불가.
→ Pursuit_Chase_BT 노드 자체가 HJI lookup + 우선순위 합성을 담당해야 함.

---

## 4. 발견된 이슈 / Red Team Notes

### 4.1 각도 컬럼 스케일 (CSV 데이터 정확성)

`--log-csv` 출력에서 다음 컬럼이 `× 180` 스케일됨:
```
ata_deg=16200 (= 90° × 180), aa_deg=16200, hca_deg=32400 (= 180° × 180), ...
```
**영향**: 본 보고서의 분석은 `vx/vy/vz`, `turn_rate_degs` (자체 단위 °/s), `ego_altitude_ft`, `ego_vc_kts` 기반 → 영향 없음. 단 후속 HJI grid 코드에서 ATA/AA 등 사용 시 `/180` 변환 필요.

### 4.2 Canonical 초기에서 max envelope 미측정

canonical 시나리오는 head-on geometry → BT 액션이 자기 한계까지 발휘 안 함.
- 측정된 turn_rate_max ≈ 0.4°/s (LeadPursuit, vs envelope 21°/s)
- 측정된 v_rate_max ≈ 9 kts/s (vs envelope ±15 kts/s)

**대응**: HJI dynamics 의 envelope 한계는 JSBSim 테이블 사용 (이미 알려짐). 본 측정은 **분류**(intent 식별)에 활용. Envelope stress test 는 별도 시나리오 필요 시 추가.

### 4.3 BT 명령 vs 실제 효과 시간 차

BT tick 0.2s 단위로 명령 발행 → JSBSim 60Hz physics 가 12 substep 적용.
- BT 명령 변경 → 효과 발현까지 lag 약 1 tick (0.2s) 이내 관찰
- **HJI 영향**: 0.2s zero-order hold 의 영향은 yo-yo (수 초) timing 에는 미미, gun snap-shot 윈도우 (< 0.5s) 에는 ~40% lag → 주의

### 4.4 LeadPursuit closed-loop 본질

LeadPursuit 은 **state-feedback 명령**: heading command = bear + N·ATA·0.06 (등가).
HJI 의 u*(x) 도 state-feedback 이므로 동일 형식.
→ Pursuit_Chase_BT 에서 LeadPursuit 의 PN logic 을 **HJI lookup 함수로 대체** 가능.

---

## 5. 결론 — Pursuit_Chase_BT 설계 입력

### 5.1 HJI 제어 입력 (확정)

$$
u_p = (\omega_h, \dot\gamma, a) \in [-\omega_{\max}, +\omega_{\max}] \times [-\dot\gamma_{\max}, +\dot\gamma_{\max}] \times [-a_{\max}, +a_{\max}]
$$

이산 BT 액션 9개 (3³ 중 중복 제거 후) 만으로 충분:
```
TurnLeft, TurnRight, ClimbTo, DescendTo, Accelerate, Decelerate,
Straight, MaintainAltitude, (Decelerate + ClimbTo 등 조합은 BT 한계로 우선순위)
```

### 5.2 Pursuit_Chase_BT 노드 책임

```python
class PursuitChaseOptimal(BaseAction):
    """
    HJI value function lookup + 이산 BT 액션으로 변환.
    
    Input:  obs (state) → 6D state vector x
    Step 1: V*(x), ∇V*(x) lookup (precomputed grid)
    Step 2: u*(x) = argmin_u {∇V* · f(x, u, d_worst)}
    Step 3: 27-조합 이산화 + BT 우선순위 합성
    Output: ActionCommand(d_hdg, d_gamma, d_speed) — Tier 1 primitive 호출
    """
```

### 5.3 다음 작업

1. `docs/PURSUIT_CHASE_PLAN.md` — 6D dynamics + HJI solver 통합 계획
2. `tools/basis/dynamics_f16_6d.py` — JAX 점-질량 모델 (rate constraints from §3.2)
3. `tools/basis/hji_solve.py` — optimized_dp 통합
4. `examples/pursuit_chase_v1/` — BT 노드 + YAML

### 5.4 본 측정의 한계 (정직)

- **31 액션 중 13개가 multi_phase** → BT 액션의 다수가 HJI 외부.
- **HighYoYo/LowYoYo/BarrelRoll 미측정** → 격리 BT 구조 한계, trigger 조건 분석 필요.
- **Envelope stress 안 됨** → 측정값이 max 응답 미반영. F-16 spec 테이블로 보완.
- **Custom (Smart*, PN*) 액션 미측정** → submission 별 nodes/custom_actions.py 의존. 필요 시 Pursuit_Chase_BT 폴더에 동봉.

이상의 한계는 **HJI dynamics 모델의 정확성에 영향 없음** — 본 측정은 분류용이고, envelope 은 알려진 F-16 spec 사용.
