# KAPILOT Dogfight AI — 프로젝트 완전 정복서

> **최종 갱신**: 2026-04-27  
> **현재 구현 버전**: adaptive_eagle_v11_code (BT) + HCCA v12 (연속 제어)  
> **시뮬레이션 결과**: WIN=166 (95%) / DRAW=9 (5%) / LOSS=0 — 175 시나리오  
> **수학적 증명**: proof_of_win.py — 91/91 assertions PASSED (100%)

---

## 목차

1. [핵심 용어 사전](#1-핵심-용어-사전)
2. [프로젝트 전체 그림](#2-프로젝트-전체-그림)
3. [왜 정적 BT로는 부족한가](#3-왜-정적-bt로는-부족한가)
4. [BT Generator Platform — 세 단계 파이프라인](#4-bt-generator-platform--세-단계-파이프라인)
5. [EIM — 적 의도 분류기](#5-eim--적-의도-분류기)
6. [관측 벡터 — 전체 정의](#6-관측-벡터--전체-정의)
7. [HCCA v12 — 5-레이어 연속 제어 아키텍처](#7-hcca-v12--5-레이어-연속-제어-아키텍처)
8. [sim_dogfight_verify — 1:1 전황별 시뮬레이션 검증](#8-sim_dogfight_verify--11-전황별-시뮬레이션-검증)
9. [수학적 승리 증명 (proof_of_win.py)](#9-수학적-승리-증명-proof_of_winpy)
10. [BFM 교리 기반 Red Team 분석](#10-bfm-교리-기반-red-team-분석)
11. [Superplan: PhaseController & 어택큐](#11-superplan-phasecontroller--어택큐)
12. [다음 스프린트 & 로드맵](#12-다음-스프린트--로드맵)
13. [부록](#13-부록)

---

## 1. 핵심 용어 사전

> 처음 읽는 사람을 위한 참조. 본문에서 처음 등장할 때 다시 설명하므로 지금 다 외울 필요 없음.

| 용어 | 의미 |
|---|---|
| **BT** | Behavior Tree. 전투기 AI의 행동 결정 구조. "거리 1500ft 이하 + ATA 12° 이하 → GunAttack"처럼 조건-행동 규칙을 트리로 연결한 규칙 기반 시스템 |
| **HCCA** | Hierarchical Continuous Control Architecture. 5-레이어 연속 제어 아키텍처 — 이 프로젝트의 핵심 AI 엔진 |
| **EIM** | Enemy Intent Model. 적의 현재 의도(CLOSING/GUN_RUN 등)를 관측 시계열로 분류하는 모델 |
| **BFM** | Basic Fighter Maneuvers. 공중전 기본 기동 교리. OBFM(공격)/DBFM(방어)/HABFM(정면교전) 3종류 |
| **τ (tau)** | HCCA Layer 1의 4개 연속 점수. 각각 sigmoid로 [0,1] 범위 |
| **ATA** | Antenna Train Angle. **내 기수**와 적 방위 사이의 각도. 0°=내가 적을 정면으로 향함(적이 내 전방), 180°=적이 내 후방에 있음 |
| **AA** | Aspect Angle. **적 기수**와 나를 향한 방위 사이의 각도. 0°=적이 나를 정면으로 향함(head-on), 180°=나는 적의 6시 방향(내가 적 후방에 있음) |
| **HCA** | Hot/Cold Angle. 두 비행 경로 벡터 사이의 교차각 (TCA, Track Crossing Angle과 유사) |
| **WEZ** | Weapon Engagement Zone. 사격 유효 구간. 기본: ATA<12°, 500<dist<3000ft |
| **closure** | 접근속도. 양수=가까워짐, 음수=멀어짐. 단위: kts |
| **PN** | Proportional Navigation (비례 항법). N×LOS 각속도로 조향하는 미사일/전투기 유도법 |
| **ga** | Geometry Advantage. `σ((AA−ATA)/45)`. >0.5이면 **내가** 기하학적으로 유리 (AA↑=내가 적 후방, ATA↓=내가 적을 향해 있음) |
| **aa_facing** | `1 − AA/180`. 적기 기수가 나를 향하는 정도 (AA=0°일 때 1=head-on, AA=180°일 때 0=내가 적 후방) |
| **corner speed** | 선회 최적 속도 (~350kts). 이 속도에서 선회율 최대화, 선회반경 최소화 |
| **Z1~Z6** | 전황 구역. ATA와 closure 기반 6개 상태 공간 분할 |
| **HP** | Hit Points 누적. 사격 가능 상태(WEZ 안)에서 머문 틱 수 |
| **tick** | 시뮬레이터 최소 시간 단위 (1 tick = 0.2초) |

---

## 2. 프로젝트 전체 그림

### 2.1 시스템 아키텍처

JSBSim 6DOF 물리 시뮬레이터 위에서 돌아가는 1:1 공중전 AI 연구 플랫폼.

```
scripts/run_match.py                ← CLI 진입점
  └─ src/match/runner.py            ← BehaviorTreeMatch (CSV + 시각화)
       └─ src/match/runner_core.py  ← MatchCore (주 루프)
            ├─ JSBSim SingleCombatEnv     (60Hz × 12 substep 물리)
            ├─ BehaviorTreeTask × 2 .pyd  (BT 트리 실행)
            ├─ HealthGauge × 2 .pyd       (체력 관리)
            └─ wez_engine.pyd             (총기 피해 계산)
```

| 입력 | 처리 | 출력 |
|------|------|------|
| BT YAML 2개 | JSBSim 물리 + BT 평가 | MatchResult (winner, health, steps) |
| match_config.yaml | WEZ 총기 피해 계산 | logs/*.csv (93컬럼 텔레메트리) |
| CLI flags | Tacview TCP 스트리밍 | replays/*.acmi |

### 2.2 핵심 질문

> **"다양한 적 행동 패턴에 대해 최적의 BFM 기동을 자동으로 도출하는 AI를 만들 수 있는가?"**

인간 조종사처럼 — 상대의 움직임 패턴을 읽고(EIM), 카운터 기술을 선택하고(BT), 상대의 자세에 맞춰 미세조정(HCCA)하는 것이 목표다.

---

## 3. 왜 정적 BT로는 부족한가

### 3.1 실험 데이터로 확인된 한계

H-E family 실험 (4 variants, 전부 기각):

같은 에너지 로직 변경이:
- 상대 A에게: **+63 HP** (승률 상승)  
- 상대 B에게: **−17 HP** (승률 하락)

이것이 **Pareto trade-off**다. 한 상대 개선 = 다른 상대 저하. 단일 전략으로 모두를 이길 수 없다.

### 3.2 이론적 근거: Jensen 부등식

$$
\underbrace{\mathbb{E}_o\!\left[\max_x f(x, o)\right]}_{\text{Adaptive}}
\;\geq\;
\underbrace{\max_x \mathbb{E}_o\!\left[f(x, o)\right]}_{\text{Static}}
$$

*(Adaptive: 상대마다 최적 전략 선택 / Static: 모든 상대에 평균 최적)*

**해석**: "상대마다 최적 전략을 골라 쓴 평균 성능"은 항상 "단일 고정 전략"보다 같거나 낫다. Adaptive BT의 이론적 우위는 수학적으로 보장된다.

> **단서**: 이 보장은 "상대 식별이 정확하다"는 전제 위에 성립. EIM 커버리지가 낮은 구간에서는 보장 붕괴.

### 3.3 실험 검증 결과

| 방식 | 6 opponents WR | 695 풀 WR |
|---|---|---|
| Static BT (v6h2) | 83.3% | 54.96% |
| Adaptive BT (v9) | **100%** (+16.7pp) | 55.01% (+0.05pp) |

695 풀 차이가 오차범위 내 → EIM coverage gap(73.1%)에서 adaptive가 실제로 기여 못함을 확인.

---

## 4. BT Generator Platform — 세 단계 파이프라인

### 4.1 한 문장 아이디어

> **적의 관측 궤적 패턴을 실시간 분류하고(EIM), 각 패턴에 대해 가장 높은 승률을 기록한 BFM 기동을 선택하고(BT), 그 기동을 상대방 관측값에 따라 파라미터 수준에서 최적화한다(HCCA).**

### 4.2 세 단계 파이프라인

```
EXPLORE (탐색)
    └─ 대규모 1v1 매치 → 관측 시계열 수집 → failures 분류
           ↓
LEARN (학습)
    └─ 궤적 패턴 분류 (EIM: ProtoNet)
    └─ intent × node → WR 집계 (Counter Table)
    └─ 새 가설 생성 (Hypothesis Miner)
           ↓
APPLY (적용)
    └─ BT 자동 생성 (Counter Table → YAML)
    └─ HCCA: 매 틱 상태 평가 → 최적 기동 선택
```

### 4.3 현재 달성 상태

| 지표 | 목표 | 현재 |
|---|---|---|
| 6 opponents WR | ≥ 90% | 100% ✅ |
| EIM accuracy | ≥ 75% | 98.8% ✅ |
| Universal WR (695 풀) | ≥ 65% | 검증 대기 |
| sim_dogfight WIN | ≥ 90% | 95% (166/175) ✅ |

---

## 5. EIM — 적 의도 분류기

### 5.1 왜 노드 이름이 아닌 궤적 패턴인가

**A안 — Node-based intent (73.7%, 폐기)**:
- 적의 `active_node` 이름을 보고 의도를 분류
- 문제: 같은 노드라도 파라미터에 따라 완전히 다른 행동. 미지의 상대에 무용.

**B안 — Trajectory-based intent (98.8%, 채택)**:
- 적의 **관측 시퀀스 → 궤적 패턴**을 직접 분류
- 노드 이름을 모르는 미지 상대에도 작동

### 5.2 6개 궤적 클래스

| 클래스 | 판정 조건 | BFM 해석 | 우리 BT 대응 |
|---|---|---|---|
| **CLOSING** | closure > +100kts 지속 | 적이 접근 중 | SmartHighYoYo (오버슈트 유도) |
| **EXTENDING** | closure < −100kts 지속 | 적이 이탈 중 | SmartLowYoYo (dive 가속) |
| **ORBITING** | \|closure\| < 50 + dist 안정 | 교착/선회 | PNLeadPursuit |
| **CLIMBING** | alt 500ft+ 상승/window | 에너지 축적 | SmartLowYoYo (따라감) |
| **DIVING** | alt 하강 지속 | 에너지 소모 | SmartHighYoYo |
| **GUN_RUN** | closure > +200 + ATA<15° | 사격 접근 | SmartBreakTurn |

### 5.3 ProtoNet 구조

```
입력: 관측 시퀀스 (20 tick × 28 feature = 560차원)
  ↓
임베딩 네트워크 (CNN+MLP) → 64차원 벡터
  ↓
프로토타입 매칭: 각 클래스 대표 벡터와의 거리 계산
  ↓
intent 클래스 (6개) + confidence
```

> **프로토타입(Prototype)**: 각 클래스 학습 샘플들의 임베딩 평균값. 유사한 패턴끼리는 임베딩 공간에서 가까이 위치. "같은 상황을 자주 겪은 샘플들이 비슷한 벡터를 가진다"는 아이디어.

---

## 6. 관측 벡터 — 전체 정의

매 틱(0.2초)마다 28개 수치가 수집된다.

> **⚠️ 단위 규약**: `_deg` 변수는 내부 저장값이 0~1 범위. 도(°)로 쓰려면 반드시 ×180 필요. 이 규약 위반 = BUG-4 수준의 silent failure.

### 6.1 연속형 (14개)

| 변수명 | 의미 | 단위 |
|---|---|---|
| `distance_ft` | 나 ↔ 적 거리 | ft |
| `ata_deg` | 적이 나를 바라보는 각도 (×180 → 도) | 0~1 |
| `aa_deg` | 내가 적을 바라보는 각도 (×180 → 도) | 0~1 |
| `hca_deg` | 두 비행 경로 교차각 (×180 → 도) | 0~1 |
| `relative_bearing_deg` | 상대 방위각 | 0~1 |
| `ego_altitude_ft` | 내 고도 | ft |
| `ego_vc_kts` | 내 속도 (계기 대기속도) | kts |
| `specific_energy_ft` | 단위 중량당 총 역학 에너지 $E_s = h + v^2/2g$ | ft |
| `ps_fts` | 비에너지 변화율 $\dot{E}_s$ (양수=에너지 축적 중) | ft/s |
| `energy_diff_ft` | 나 − 적 비에너지 차이 (양수=내가 우세) | ft |
| `closure_rate_kts` | 접근속도 (양수=가까워짐) | kts |
| `turn_rate_degs` | 내 선회율 | °/s |
| `alt_gap_ft` | 나 − 적 고도차 (양수=내가 위) | ft |
| `tau_deg` | 충돌 여유 시간을 각도로 환산 | -1~1 |

> **비에너지(Specific Energy) 상세**: $E_s = h + \frac{v^2}{2g}$ (g = 32.174 ft/s²). 질량에 무관하게 전투 여력을 비교할 수 있다. "에너지 고도(Energy Height)"라고도 부른다. 고도 5000ft + 300kts ≡ 고도 1000ft + 400kts가 될 수 있다. John Boyd의 E-M Theory(1960s) 기반.

### 6.2 이진형 (7개)

| 변수명 | 의미 |
|---|---|
| `in_wez` | 적이 나를 쏠 수 있는 WEZ 안에 내가 있는가 |
| `enm_in_wez` | 내가 적을 쏠 수 있는 WEZ 안에 적이 있는가 |
| `in_39_line` | 내가 적의 전방 반구(3-9 라인 앞쪽) 안에 있는가 |
| `overshoot_risk` | 오버슈트(앞지르기) 위험 존재 여부 |
| `energy_advantage` | 내 비에너지 > 적 비에너지 |
| `alt_advantage` | 내 고도 > 적 고도 |
| `spd_advantage` | 내 속도 > 적 속도 |

> **3-9 Line**: 전투기를 위에서 내려다봤을 때 양쪽 날개 끝을 이은 가상의 선. `in_39_line=1`이면 내가 적의 사격 위협권 안, `0`이면 내가 적의 등 뒤를 잡은 공격 우위 위치.

### 6.3 BFM 상황 플래그 (7개)

현재 BT가 실행 중인 기동 카테고리를 원-핫 인코딩으로 표현:

```
OBFM | DBFM | HABFM | UNKNOWN | UNK_NEAR_OFF | UNK_SCISSORS | UNK_DISENGAGING
```

> **원-핫 인코딩이란**: 7개 자리 중 현재 카테고리 하나만 1로 표시하고 나머지는 0. 카테고리에 순서·크기 관계를 만들지 않기 위해 사용.

---

## 7. HCCA v12 — 5-레이어 연속 제어 아키텍처

### 7.1 왜 HCCA인가

기존 v11_code 문제:
```
16개 boolean 조건 → 25개 이산 action 선택
"문 안쪽은 연속(PNLeadPursuit 내부의 τ, ga), 문 여는 조건은 이산" = 구조적 모순
```

HCCA v12 해법:
```
4개 연속 점수 τ → commitment 아키텍처 → 4개 모드 컨트롤러(내부 연속)
전체 시스템이 하나의 연속 제어 흐름
```

### 7.2 5-레이어 구조

```
L0  상황 인식  → EMA 스무딩, 미분, 물리 파생 변수
L1  위협/기회  → τ_threat, τ_opp, τ_energy, τ_pursuit  (각 sigmoid [0,1])
L2  모드 선택  → softmax + commitment (ATTACK / DEFEND / ENERGY / PURSUE)
L3  기동 계산  → 모드별 연속 (hdg, vel, alt) 출력
L4  이산화     → hdg_idx [0~8], vel [1~5], alt [-1/0/+1]
```

### 7.3 Layer 0 — 상황 인식 보조 공식

Layer 0은 raw 관측값을 받아서 스무딩·미분·물리 파생을 계산한다. 이후 Layer 1~3이 이 값들을 참조한다.

| 변수 | 공식 | 의미 |
|---|---|---|
| `ga` | `σ((AA−ATA)/45)` | 기하 우위; >0.5이면 적이 유리 |
| `aa_facing` | `1 − AA/180` | 적기 기수가 나를 향하는 정도 (1=정면, 0=꼬리) |
| `closure_trend` | EWMA\_slow(closure) | ~3초 평균 closure 추세 |
| `ata_trend` | EWMA\_slow(ΔATA) | ATA 장기 변화 추세 |
| `aa_rate_fast` | EWMA\_fast(ΔAA/Δt) | AA 변화율 (빠른 감지) |
| `energy_rate` | EWMA\_fast(Δe\_diff/Δt) | 에너지 추세 |
| `range_rate` | EWMA\_fast(Δdist/Δt) | 거리 변화율 |
| `tr_cap` | `min(1.0, turn_rate/20)` | 선회율 정규화 (20°/s = 포화) |
| `hca_threat` | `max(0, (HCA−90)/90)` | HCA>90°(교차각 심함) 위협 성분 |
| `circle_bonus` | `0.3 if tc_type=="2-circle"` | 2-circle 상황 추격 보너스 |

### 7.4 Layer 1 — 4개 연속 점수 (τ)

Layer 1은 Layer 0의 보조 변수들로 4개의 sigmoid 점수를 계산한다. 각 점수는 "현재 상황이 해당 속성에 얼마나 해당하는가"를 0~1로 표현한다.

#### τ_threat (위협)

적이 나를 위협하는 강도. 높을수록 방어가 필요.

```
z = th_w[0] × (closure/300) × aa_facing        ← 접근하는 적이 나를 향할수록 위협
  + th_w[1] × aa_facing                         ← 적이 나를 바라보는 것 자체가 위협
  + th_w[2] × (−aa_rate_fast/10)                ← AA가 빠르게 증가(적이 조준 중)
  + th_w[3] × (−energy_rate/1000)               ← 에너지가 빠르게 감소 중
  + th_w[4] × in_wez                            ← 이미 사격 위협권 안에 있음
  + th_w[5] × (closure/300) × proximity × aa_facing  ← 근거리 고속 접근 위협
  + th_w_hca × hca_threat × aa_facing           ← 교차각 크고 적이 나를 향할 때
  + th_bias

τ_threat = σ(z)
기본값: th_w=[2.0, 1.5, 1.0, 0.5, 3.0, 1.5], th_w_hca 추가, th_bias=−1.5
```

> **th_w[4] (in_wez)**: 3.0으로 큰 가중치. 이미 WEZ 안에 있다면 위협 점수를 즉시 크게 올린다. 이것이 Safety Override(`τ_threat > 0.85 → 즉시 DEFEND`)를 빠르게 발동시키는 핵심.

#### τ_opportunity (기회)

우리에게 사격 기회가 얼마나 있는가. 높을수록 공격 유리.

```
dist_decay = max(0, 1 − dist/8000)       ← B2 수정: 원거리 감쇠

z = op_w[0] × (1 − ATA/180)              ← ATA 작을수록 기회 (적 기수가 나를 향하지 않음)
  + op_w[1] × (AA/180)                   ← AA 클수록 기회 (내가 적 후방에 있음)
  + op_w[2] × WEZ_proximity              ← WEZ 가까울수록 기회
  + op_w[3] × enm_in_wez                 ← 이미 사격 가능
  + op_w[4] × ga                         ← 기하 우위
  + op_bias
  − 1.5 × (1 − dist_decay)              ← 원거리일수록 기회 점수 감쇠

τ_opp = σ(z)
기본값: op_w=[2.0, 1.5, 1.5, 3.0, 1.5], op_bias=−1.5
```

> **`AA/180` 양의 항**: AA가 클수록(내가 적 꼬리 쪽에 있을수록) 기회가 높다는 뜻. 이전 문서의 `aa_facing` 페널티 항과 다름. 현재 구현에서 AA 180°(완전한 꼬리 잡기)가 최대 기회.

#### τ_energy (에너지 우위)

우리의 에너지 상태. 높을수록 에너지 우위, 낮을수록 에너지 보충 필요.

```
z = en_w[0] × (e_diff/5000)              ← 에너지 차이 (우위/열위)
  + en_w[1] × alt_advantage              ← 고도 우위 보너스
  + en_w[2] × spd_advantage              ← 속도 우위 보너스
  + en_w[3] × (Ps/200)                   ← 잉여 추력 (양수=에너지 축적 중)
  + en_w[4] × (energy_rate/1000)         ← 에너지 추세 (개선 중인가)
  + en_bias

τ_energy = σ(z)
기본값: en_w=[2.0, 1.5, 1.0, 1.0, 1.0], en_bias=0.0
```

> **B1 수정 (op_suppress)**: `τ_energy < 0.3`이면 에너지 위기. 이때 τ_opp가 높아도 w_energy를 억압하는 효과를 줄여서 ENERGY 모드가 선택될 수 있게 한다. 없으면 "에너지 위기인데도 PURSUE"하는 오선택 발생.

#### τ_pursuit (추격 품질)

현재 추격이 얼마나 잘 진행되고 있는가. 높을수록 추격 우세.

```
z = pu_w[0] × (closure_trend/200)        ← 꾸준히 접근하고 있는가
  + pu_w[1] × (−ata_trend/10)            ← ATA가 개선되고 있는가 (감소 추세)
  + pu_w[2] × (range_rate/300)           ← 거리가 줄고 있는가
  + pu_w[3] × ga                         ← 기하 우위
  + pu_w_tr × (tr_cap − 0.5)             ← 선회율 기여 (0.5 기준, 고선회율=추격 유리)
  + circle_bonus                          ← 2-circle 상황이면 +0.3 보너스
  + pu_bias

τ_pursuit = σ(z)
기본값: pu_w=[2.0, 1.5, 1.5, 1.0], pu_w_tr=0.8, pu_bias=0.0
```

> **circle_bonus**: 2-circle 상황(`tc_type=="2-circle"`)이면 0.3 추가. 2-circle에서 대향 선회는 추격 기회를 높이기 때문. **이전 문서에 없던 항** — 현재 구현에서 추가된 2-circle 인식 기능.

### 7.5 Layer 2 — 모드 선택 (Commitment Architecture)

#### 왜 blend가 아니라 select인가

```
ATTACK이 hdg=LEFT, DEFEND가 hdg=RIGHT일 때
blend → hdg=STRAIGHT = 공격도 방어도 안 됨 (최악)

→ 해법: 가장 높은 weight의 모드 하나를 선택
        모드 내부에서만 연속 blend 가능
```

#### 모드 가중치 계산

```python
# B1 수정: 에너지 위기 시 op_suppress 완화
op_suppress = 0.7 × min(1.0, τ_energy / 0.3)

w_attack = τ_opp × (1 − τ_threat) × max(0.3, τ_energy)
w_defend = τ_threat × (1 − τ_opp × 0.5)
w_energy = (1 − τ_energy) × (1 − τ_threat × 0.7) × (1 − τ_opp × op_suppress)
w_pursue = τ_pursuit × (1 − τ_threat × 0.5) × (1 − τ_opp × 0.3)

# softmax(weights / temperature=0.3) → 선택 모드
```

#### Safety Override (hysteresis 무시)

```
τ_threat > 0.85           → 즉시 DEFEND
enm_in_wez AND ATA < 20°  → 즉시 ATTACK
```

#### Commitment 로직

```
switch_margin = 0.15   ← 현재 모드 유지 보너스 (급격한 전환 방지)
min_commit = 5 ticks   ← 최소 유지 시간 (1초)

# 실제 조종사도 동일: 기동 결정 → 실행 → 재평가
# 동시에 두 기동을 blend하지 않음
```

#### GAP-Z45 게이트 (방어 오선택 방지)

```python
# DEFEND가 선택됐더라도:
if current_mode == DEFEND and ata < 45°:
    # Z1/Z2 공격 기하학 → ATTACK으로 전환
    current_mode = ATTACK

if current_mode == DEFEND and ata > 100°:
    # Z4/Z5 역전 필요 → PURSUE로 전환
    current_mode = PURSUE
```

> **이 게이트가 없으면**: τ_threat가 0.5 근처일 때 Z2(ATA=30°) 상황에서 DEFEND가 선택되어 공격 기회를 낭비하는 오선택이 발생.

### 7.6 Layer 3 — 모드별 기동 계산

Layer 3은 선택된 모드에 따라 (hdg, vel, alt)의 연속 값을 계산한다.

#### ATTACK 모드

공격 우위 상황. 빠르게 WEZ 진입을 추구.

```python
# N 계수 결정 (높을수록 공격적 lead pursuit)
N = atk_n_base(3.5) + (1 − τ_threat) × atk_n_bonus(1.5)   → [2.0, 5.0]

# Control Zone 보너스 (in_39_line 활용 — Gap#4 부분 반영)
if in_39_line AND 2000 < dist < 5000:
    N = min(N × 1.2, 6.0)

# Overshoot 방지
if overshoot_risk:
    N = min(N, atk_n_cap=2.0)    ← lag 전환

# 속도 — 2-orbit 블렌딩
range_blend = σ((dist − 3000) / 1500)
vel = vel_turn(2.5) × (1−blend) + vel_chase(4.0) × blend
if closure < 0:  vel = 4.0   ← separation sprint
if overshoot:    vel = 1.0   ← 급제동

# 고도
if e_diff > 2500 AND alt_advantage AND dist < 4000:
    alt = −1   ← dive attack (위치에너지 → 속도)
```

#### DEFEND 모드

방어 우위 상황. 적의 사격을 회피.

```python
intensity = min(1.0, τ_threat × 1.2)
if in_wez: intensity = 1.0       ← WEZ 안이면 최대 강도

# 방향: ±90° break turn
hdg = side_flag × intensity × 90°

# 거리별 전술 차이
if dist < 3000:
    hdg = side_flag × 90°      ← 근거리: 타이트한 break turn
else:
    hdg = side_flag × 45°      ← 원거리: extension break

# 속도
if dist < 1500:  vel = 2.0   ← 최후 수단 (corner speed 이하)
elif dist < 2500: vel = 3.0   ← 근접 break
elif dist < 5000: vel = 3.5   ← 중거리
else:             vel = 4.0   ← extension sprint

# 고도 — 수직 이격
if ego_alt > 8000: alt = −1   ← 강하
if ego_alt < 3000: alt = +1   ← 상승
```

#### ENERGY 모드

에너지 열위 상황. 에너지를 회복하면서 추격 기회를 기다림.

```python
# 느슨한 추격 (에너지 관리가 주목적)
hdg = tau_lead × 0.5          ← 기수를 약하게 적 방향으로

# 에너지 상태별 서브-행동
if e_diff < −2000:            ← 에너지 결핍
    vel = 3.0, alt = +0.5    ← 완만한 상승으로 에너지 축적

elif e_diff > 3000:           ← 에너지 우위
    if ga > 0.6:
        vel = 3.5, alt = −1.0  ← dive attack (고도→속도 전환)
    else:
        vel = 3.0, alt = +0.5  ← Yo-Yo setup

else:                         ← 균형 상태
    vel = 3.0, alt = 0.0    ← 순항

# 실속 보호
if ego_spd < 200: vel = max(vel, 3.5), alt = min(alt, −0.5)

# E-M 코너속도 최적화 (Tier 2-F 반영)
if ego_spd > corner + 80:  vel = min(vel, 2.5)   ← 너무 빠름, 선회반경 큼
elif ego_spd < corner − 80: vel = max(vel, 3.0)  ← 너무 느림, 실속 위험
```

#### PURSUE 모드

추격 중. 효율적으로 ATA를 줄이며 WEZ 진입을 준비.

```python
# N 계수 — ga 낮을수록(우리가 유리) N 증가
N = 3.0 + (1 − ga) × 1.5

# Gap#2 수정: 2-circle lag-roll (현재 구현됨 ✅)
if tc_type == "2-circle" AND ata > 60° AND dist > 3000:
    lag_reduction = 2.0 × (ata − 60) / 30
    N = max(1.0, N − lag_reduction)
    # 2-circle에서는 N을 줄여 에너지 소모를 아끼고 오버슈트 방지

# 속도 — 원거리 sprint, 근거리 turn fight
if dist > 6000:   vel = 4.0                           ← 원거리 sprint
elif dist > 3000: vel = 3.0 + (dist−3000)/3000        ← 선형 블렌딩
elif ga > 0.7:    vel = 3.0                           ← 적 후방: corner 선회
elif abs(closure) < 50 AND τ_pu < 0.65 AND dist < 3000:
    vel = 3.5, hdg *= 0.7  ← Gap#1+#3: stale 교착 탈출 (heading lock 완화)
else:             vel = 3.0

if closure < −50:  vel = 4.0   ← separation sprint

# 고도
if e_diff < −2000:  alt = +0.5   ← 에너지 열위 시 상승
elif e_diff > 4000: alt = −0.5   ← 에너지 우위 시 dive
else:               alt = 0.0
```

> **Gap#2 수정 완료**: 이전 문서에서는 "갭#2 미수정"으로 기록됐지만, 현재 구현에서 `tc_type=="2-circle"` 조건으로 N을 줄이는 lag-roll이 구현되어 있다. 2-circle에서 N=3.67(과도한 lead) → N ≈ 1.0~2.0(적절한 lag)으로 조정.

### 7.7 Layer 4 — 이산화

```
hdg_idx: 연속 hdg_deg → [0~8] 정수  (−90°=0, 0°=4, +90°=8)
vel:     연속 vel_cont → [1~5] 정수  (1=idle, 3=corner, 5=max)
