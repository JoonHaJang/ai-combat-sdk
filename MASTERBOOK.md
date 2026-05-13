# KAPILOT Dogfight AI — 프로젝트 완전 정복서

> ⚠️ **본 문서는 2026-04-27 기준 옛 종합 정리서입니다.** 이후 BFM 수학 통합 작업이
> 진행되어 일부 내용이 최신과 다를 수 있습니다.
>
> - **최신 입문 안내**: [`docs/PROJECT_OVERVIEW/`](docs/PROJECT_OVERVIEW/README.md)
> - **최신 BFM 통합 상태**: [`examples/adaptive_eagle_v11_code/CURRENT_STATE_AND_DESIGN.md`](examples/adaptive_eagle_v11_code/CURRENT_STATE_AND_DESIGN.md)
>
> HCCA v12 / EIM / proof_of_win 등 통합 설명에는 여전히 유효합니다.

---

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
alt:     연속 alt_cont → {−1, 0, +1}  (하강/유지/상승)

저고도 안전: ego_alt < 500ft → alt = +1 강제
```

---

## 8. sim_dogfight_verify — 1:1 전황별 시뮬레이션 검증

> 파일: `examples/adaptive_eagle_v11_code/sim_dogfight_verify.py`  
> 목적: 순수 Python 물리 모델로 adaptive_eagle_v11_code BT를 전황별로 검증

### 8.1 HP 교환 비율 모델 — 승리 판정 방식

"첫 WEZ 진입 = WIN"이 아니라 **누가 더 오래 상대를 사격 위치에 두는가**로 판정:

```python
# 매 틱 누적
own_gun_ticks   += 1  if is_victory(geo) else 0
enemy_gun_ticks += 1  if is_enemy_win(geo) else 0

def is_victory(geo):
    """우리가 사격 가능한 조건."""
    dist_max = 4000.0 if geo["aa"] > 45.0 else 3000.0  # Extended WEZ
    return (geo["ata"] < 12.0
            and 500.0 < geo["dist"] < dist_max
            and geo["closure"] > 0.0)

def is_enemy_win(geo):
    """적이 우리를 사격 가능한 조건."""
    return (geo["aa"] < 12.0
            and 500.0 < geo["dist"] < 3000.0
            and geo["closure"] > 0.0)

# 최종 판정 (60틱마다 + 종료 시)
if own_gun_ticks > enemy_gun_ticks × 1.5 AND own_gun_ticks >= 5:  → "WIN"
elif enemy_gun_ticks > own_gun_ticks × 1.5:                       → "LOSS"
else:                                                              → "DRAW"
```

**Extended WEZ (AA > 45°)**: 꼬리-chase 상황에서 `dist_max = 4000ft`로 확장.  
근거: AA=180°는 적기가 나를 조준할 수 없는 완전한 후방 상황 → 정확도 향상 + 반격 없음.

### 8.2 전황 구역 분류 (Z1~Z6)

| 전황 | 이름 | ATA 범위 | 핵심 특징 |
|---|---|---|---|
| **Z1** | Gun Shot Opportunity | 0~12° | 사격 가능 위치, WEZ 진입 |
| **Z2** | Offensive Chase | 12~45° | 적 전방 확보, PN 추격 중 |
| **Z3** | Neutral Turning Fight | 45~110° | 선회 교착 / orbit / scissors |
| **Z4** | Defensive Geometry | 110~140° | 적이 우리 후방 진입 |
| **Z5** | Lost Pursuit | 140~180° | ATA 크고 closure 음수 (최악) |
| **Z6** | Energy Management | ATA 무관 | 에너지 결핍 상황 |

### 8.3 BT 브랜치 선택 로직 (select_bt_branch)

```python
def select_bt_branch(geo, avg_cl, own_spd=300.0, alt=8000.0):
    ata, aa, dist, cl, hca = ...

    if alt < 1200.0:
        return "HardDeckAvoidance"          ← 저고도 우선

    # Extended WEZ + 확장 HCA gate (TCA 부분 반영)
    dist_gun_max = 4000.0 if aa > 45.0 else 3000.0
    if ata < 12.0 and 500 < dist < dist_gun_max:
        if hca < 30.0 or hca > 150.0 or aa > 45.0:
            return "GunEngagement"          ← 사격 (HCA gate 3가지 조건)

    if ata < 45.0 and aa > 100.0 and dist < 4000.0:
        return "OffensivePursuit"           ← 적 후방 확보 상태

    if 35.0 <= ata <= 110.0 and abs(cl) < 200.0 and dist > 3000.0:
        return "CircularOrbitBreak"         ← 교착 감지 → 가속 탈출

    if ata > 140.0 and dist > 2000.0:
        return "LostPursuitReverse"         ← Z5 역전 기동

    if ata < 20.0 and dist > 3000.0 and cl < 20.0 and own_spd > 380.0:
        return "ScissorsBreak"              ← 고속 tail-chase 교착 탈출

    if avg_cl <= 0.0:
        return "StaleChaseBreak"            ← 장기 stale 감지

    if dist < 3000.0:
        return "CloseCombat"               ← 근접전

    if ata > 90.0 and aa < 70.0:
        return "DefensiveEscape"           ← 방어 기하학

    return "LeadPursuit"                   ← 기본 fallback
```

### 8.4 주요 BFM 기동 구현

#### N=0 Pure Pursuit (꼬리-chase 수렴 가속)

tail-chase(ATA<15°, dist>3000ft)에서 `N=0`으로 전환:

```python
if ata < 15.0 and dist > 3000.0:
    d_hdg, _ = pn_cmd(own, geo, N=0.0)   # pure pursuit
    accel = -15.0 if own.speed > CORNER_SPD and cl < 20.0 else 20.0
```

**물리 원리**: 두 PN 추격자(N=3 각각)는 안정적 원형 궤도(limit cycle)를 형성한다. N=0(현재 적 위치로 직접 조향)으로 변경하면 대칭이 깨져 나선형 수렴이 시작된다.

#### LostPursuitReverse (Z5 역전 기동)

ATA>140°, closure<0, dist>2000ft인 완전 역전 상황에서 2단계 BFM:

```python
# Phase 1: 스피드브레이크 → 적 오버슈트 유도
if phase == "speedbrake":
    d_hdg = 0.0          # 기수 고정 (회전하지 않음)
    accel = -MAX_ACCEL   # 최대 감속 → 적이 앞질러 지나가게

# Phase 2: 적 방향으로 하드턴 (각도 컷)
elif phase == "hardturn":
    err = ang_diff(bear, own.hdg)
    d_hdg = max(-MAX_TR, min(MAX_TR, err / (DT × 1.0)))
    accel = MAX_ACCEL    # 최대 가속 + 급선회
```

**BFM 교리**: Z5 역전 = "적 방향으로 하드턴(각도 컷)". 적 반대 방향으로 이탈하면 계속 ATA=180°로 수렴 — 틀린 기동. "시저스 기동은 neutral 선회전에서 쓰는 간보기 기동"이므로 Z5에서는 부적절.

#### CircularOrbitBreak (교착 탈출)

ATA∈[35°,110°], |closure|<200kts, dist>3000ft인 교착 상황:

```python
# 그냥 가속 (BT의 Accelerate 액션 매핑)
accel = MAX_ACCEL
# → closure -7kts → +200kts 즉시 역전 (T08에서 증명)
```

#### ScissorsBreak (고속 tail-chase 교착)

ATA<20°, cl<20kts, own_spd>380kts인 고속 정체 상황:

```python
# 적에 수직인 방향으로 선회 (측면 이격 생성)
perp = (bear ± 90.0) % 360.0   # 가까운 수직 방향
err = ang_diff(perp, own.hdg)
d_hdg = max(-MAX_TR, min(MAX_TR, err / (DT × 1.0)))
accel = -15.0 if own.speed > CORNER_SPD else 5.0   # corner speed로 감속
```

> **주의**: 시저스 기동은 중립 선회전의 간보기 기동. tail-chase 교착에서는 보조 수단으로만 사용 (cl<20kts인 극단적 정체 상황에만 발동).

### 8.5 시뮬레이션 결과 (2026-04-27)

175개 시나리오 (Z1~Z6 × 4개 적 정책):

| 결과 | 수 | 비율 |
|---|---|---|
| **WIN** | **166** | **95%** |
| DRAW | 9 | 5% |
| LOSS | 0 | 0% |

#### 잔여 DRAW 9개 — 수학적 분석

모두 `× offensive` 정책 상황. 물리적 한계로 인한 DRAW:

| 시나리오 | HP | 원인 |
|---|---|---|
| z1_headon × offensive | 11/11 | 완전 대칭 기하 → HP 동률 |
| z4_fast_enm × offensive | 0/0 | 비수렴 |
| z5_entry/typical/deep/tail/longrange × offensive | 0/0 | 물리적 불가 (↓) |
| z6_e_z5_entry/typical × offensive | 0/0 | 에너지 열위 + Z5 |

**Z5 × offensive: 왜 300틱 안에 불가능한가**

```
초기 상태: dist=9493ft, cl=+95kts (적이 우리를 추격)

closure 감쇠 (offensive 적 정책이 PN N=3으로 지속 추격):
  t=0:   cl=+95kts
  t=100: cl=+45kts  (적기 방향 변화로 LOS 성분 감쇠)
  t=236: cl=+1kts   (사실상 정체)

236틱 동안 총 이동거리 ≈ 3832ft
최종 dist = 9493 − 3832 = 5661ft

Extended WEZ(4000ft)에도 5661 > 4000 → 진입 불가
필요 틱 수: ≈ 463틱  →  시뮬 한도 300틱 초과
```

**근본 원인**: MAX_SPD=420kts 동일 → 추월 불가. LostPursuitReverse는 적의 PN 추격을 상쇄하기엔 물리적으로 역부족.

### 8.6 BT 브랜치 구조 (adaptive_eagle_v11_code.yaml)

```yaml
ROOT (Selector) — 우선순위 순
├── HardDeckAvoidance        ← alt < 1200ft → ClimbTo 3000ft
├── GunEngagement            ← ATA<12°, Extended WEZ, HCA gate (3조건)
├── OffensivePursuit         ← ATA<45°(적이 내 전방), AA>100°(나는 적 후방), dist<4000 → PNLeadPursuit
├── CircularOrbitBreak       ← 35<ATA<110, |cl|<200, dist>3000 → Accelerate
├── TacticalLookup           ← data-driven (tactical_lookup.json)
├── CounterGunRun            ← GUN_RUN intent → SmartBreakTurn
├── CounterClosing           ← CLOSING intent → SmartHighYoYo
├── CounterExtending         ← EXTENDING intent → SmartLowYoYo
├── CounterClimbing          ← CLIMBING intent → SmartLowYoYo
├── CounterDiving            ← DIVING intent → SmartHighYoYo
├── CounterOrbiting          ← ORBITING intent → PNLeadPursuit
├── LostPursuitReverse       ← ATA>140°, cl<-100, dist>2000 → HeadOnBreak
├── StaleChaseBreak          ← 30틱 평균 cl≤0 → SmartHighYoYo
├── CloseCombat              ← dist<3000 → PNLeadPursuit
├── DefensiveEscape          ← ATA>90°(적이 내 후방), AA<70°(적이 나를 향함) → ExtensionBreak
└── LeadPursuit              ← 기본 fallback
```

---

## 9. 수학적 승리 증명 (proof_of_win.py)

> 파일: `examples/adaptive_eagle_v11_code/proof_of_win.py`  
> 실행: `python3 examples/adaptive_eagle_v11_code/proof_of_win.py`  
> 결과: **91/91 PASSED (100%)**

### 9.1 승리 집합 V

$$
V = \{\, \text{ATA} < 12^{\circ} \;\text{AND}\; 500 < \text{dist} < 3000\,\text{ft} \;\text{AND}\; \text{closure} > 0 \,\}
$$

V에 진입 = GunEngagement 발동 = 사격 가능.

### 9.2 증명 구조

$$
\text{state } S \;\xrightarrow{\tau}\; \text{mode select} \;\xrightarrow{A}\; S' \quad \Rightarrow \quad d(S', V) < d(S, V)
$$

"다음 상태가 승리 집합에 더 가까워져야 한다" — 각 전황에서 이 조건이 성립함을 보임.

### 9.3 10개 정리 (Theorems)

| 정리 | 내용 | 체크 | 결과 |
|---|---|---|---|
| T01 | BT 브랜치 도달 가능성 — 모든 전황에 대응 브랜치 존재 | 12 | ✅ 12/12 |
| T02 | BT 우선순위 비중복성 — 경계 정확히 분리됨 | 10 | ✅ 10/10 |
| T03 | τ_threat 단조성 — Z5 > Z4 > Z3 > Z2 > Z1 | 9 | ✅ 9/9 |
| T04 | τ_opportunity 단조성 — Z1 > Z2 > Z3 > Z4 > Z5 | 7 | ✅ 7/7 |
| T05 | τ_energy 사이클 — 결핍→ENERGY→회복→복귀 루프 작동 | 8 | ✅ 8/8 |
| T06 | τ_pursuit 선회율 반응 — 선회율 반영, 2-circle lag-roll 확인 | 6 | ✅ 6/6 |
| T07 | Z2→Z1 수렴 — PN N=4에서 28틱(5.6초) 내 V 진입 가능 | 8 | ✅ 8/8 |
| T08 | Z3 탈출 — CircularOrbitBreak → closure 즉시 역전 | 12 | ✅ 12/12 |
| T09 | Z4/Z5 생존 — DEFEND → τ_threat 64~67% 감소 → Z3 복귀 | 7 | ✅ 7/7 |
| T10 | 상태 공간 커버 — 4D 그리드 600셀 전부 결정 존재 | 12 | ✅ 12/12 |
| **합계** | | **91** | **✅ 91/91** |

### 9.4 핵심 증명 결과 발췌

#### T07: Z2→Z1 수렴 (물리 방정식)

PN guidance 미분방정식:
$$\frac{d(\text{ATA})}{dt} = -N \cdot \frac{V_{\text{ego}} \cdot \sin(\text{ATA})}{\text{dist}}$$

ATA=35°, dist=4000ft, V=300kts, N=4 → dATA/dt = **16.6°/s** → V 진입: **28틱(5.6초)**

| 시나리오 | ATA | dist | closure | V 진입 |
|---|---|---|---|---|
| Z2 전형 | 35° | 4000ft | 80kts | 28틱(5.6s) |
| Z2 근접 | 30° | 3500ft | 100kts | 14틱(2.8s) |
| Z2 원방 | 45° | 5000ft | 60kts | 55틱(11.0s) |

#### T08: Z3 탈출

CircularOrbitBreak 발동 후: closure −7kts → +200kts 즉시 역전. orbit 탈출 후 Z2 복귀 → V 진입 45틱(9.0s).

#### T09: Z4/Z5 생존

| 전황 | τ_threat 초기 | τ_threat 이후 | 변화 |
|---|---|---|---|
| Z4 (ATA=125°) | 0.548 | 0.197 | −64% |
| Z5 (ATA=160°) | 0.703 | 0.230 | −67% |

#### T10: 상태 공간 커버

4D 그리드 (ATA×closure×dist×e_diff) 200 BT셀 × 3 에너지 = 600 모드셀:

| 전황 | 우세 모드 | 비율 |
|---|---|---|
| Z1 | PURSUE | 83% |
| Z2 | PURSUE | 54% |
| Z3 | PURSUE | 61% |
| Z4 | PURSUE | 59% |
| Z5 | DEFEND | 59% |

---

## 10. BFM 교리 기반 Red Team 분석

> 출처: AETC TTP 11-1, Boyd E-M Theory, DTIC AD1130933 등  
> 목적: 현실 BFM 교리 대비 현재 구현의 누락 요소 식별

### 10.1 🔴 HIGH — 전술 판단에 직결

#### Turn Radius / Turn Rate 비교 없음

**교리 근거**: "Turn radius is determined by airspeed and load factor. An aircraft with smaller turn radius can create and solve problems better."

**현재 구현**: `energy_diff`와 `Ps`만 있음. 실시간 선회반경 계산 없음.

**영향**: 1-circle fight에서 선회반경 우위/열위 판단 불가. Z2 추격 타이밍의 불확실성.

**수정 방향**:
```python
# Layer 0에 추가
turn_radius_own = ego_vc_kts**2 / (g × tan(bank_angle))  # ft
corner_margin = ego_vc_kts - 350.0                         # corner speed 기준 여유
```

#### Pursuit Mode 판별 없음

**교리 근거**: Lag pursuit(오버슈트 방지), Pure pursuit(현위치 조준), Lead pursuit(적 앞 조준)의 명확한 구분.

**현재 구현**: `tc_type=="2-circle"`로 N 감소(lag-roll)를 부분 구현했으나, 실시간 pursuit mode 판별 로직 없음.

**영향**: 오버슈트 타이밍의 오판 가능성.

#### Control Zone 개념 없음

**교리 근거**: Control zone = 2000ft aft ±20° ~ 4000ft aft ±40°. 최적 공격 준비 위치.

**현재 구현**: `in_39_line`을 ATTACK 모드에서 N 보너스에 활용하지만, 본격적인 control zone 판별은 없음.

### 10.2 🟡 MEDIUM — 성능 최적화에 영향

#### Aspect-Dependent WEZ — 부분 구현 완료

**교리**: AA=0°(적 후방) → WEZ 범위 더 넓음.

**현재 구현**: AA>45°이면 WEZ를 4000ft로 확장 (sim_dogfight_verify.py) ✅.  
단, 본체 custom_actions.py에는 아직 미반영.

#### E-M 코너속도 최적화 — ENERGY 모드에 부분 구현

**현재 구현**: `if ego_spd > corner+80: vel = min(vel, 2.5)` — 기본 코너속도 클램프 구현 ✅.  
단, E-M Diagram(속도별 지속 선회율 곡선) 전체는 미반영.

### 10.3 현재 구현 상태 종합

| 항목 | 교리 중요도 | 현재 반영 |
|---|---|---|
| Turn Radius Ratio | 🔴 Critical | ❌ 없음 |
| Pursuit Mode 판별 | 🔴 Critical | △ tc_type만 |
| Control Zone | 🔴 Critical | △ in_39_line 보너스만 |
| Track Crossing Angle (HCA gate) | 🔴 Critical | ✅ GunEngagement gate 구현 |
| Aspect-Dependent WEZ | 🟡 High | △ sim만 구현, 본체 미반영 |
| E-M 코너속도 최적화 | 🟡 High | ✅ ENERGY 모드 구현 |
| 2-circle lag-roll | 🔴 Critical | ✅ PURSUE 모드 구현 |
| Lateral Displacement | 🟡 High | ❌ 없음 |

---

## 11. Superplan: PhaseController & 어택큐

> **상태**: 설계 완료, 미구현. HCCA v12 검증 후 진행 예정.

### 11.1 반응형 AI의 한계

현재 HCCA v12는 매 틱 τ에 반응. 문제:

```
반응형: 관찰 → 분류 → 대응 → (반복)  ← 매 3~5틱 모드 전환 → orbital lock
선제형: 목표 결정 → 단계 실행 → 조건 달성 → 다음 단계
```

데이터 증거:
- `eagle2`: dist<5000ft 후 LeadPursuit 50+ 틱 고정 → WR 98.4%
- 우리(v9): 매 3~5틱 전환 → orbital lock

### 11.2 어택큐 (Attack Queue) — BFM 교리

공중전은 **단일 목표(WEZ 진입+사격)를 향한 순차 진행**이다.

```
Phase 1  ENERGY      → e_diff > 1500ft, Ps > 0 달성
Phase 2  POSITION    → ATA < 55°, alt_advantage 달성
Phase 3  ATTACK_RUN  → dist < 3000ft, ATA < 15° 진입
Phase 4  FIRE        → 사격
Phase 5  BREAK       → 이탈, 에너지 회복

[INTERRUPT] τ_threat > 0.75 → 즉시 DEFEND, 해소 시 복귀
```

### 11.3 PhaseController 전이 조건

| 전이 | 조건 |
|---|---|
| ENERGY → POSITION | `e_diff > 1500 AND Ps > 0` |
| POSITION → ATTACK_RUN | `ATA < 55° AND alt_advantage` |
| ATTACK_RUN → FIRE | `dist < 3000 AND ATA < 15°` |
| FIRE → BREAK | `dist < 500 OR 20틱 경과` |
| BREAK → ENERGY | `dist > 6000 AND closure < 50` |
| POSITION → ENERGY (후퇴) | `score_energy < 0.35` |
| ATTACK_RUN → POSITION (후퇴) | `ATA > 70° OR e_diff < −2000` |

### 11.4 7-브랜치 BT 구조 (목표)

```
ROOT (Selector)
├── [1] HardDeckSafety        ← 저고도 불변조건
├── [2] GunWEZ                ← 즉시 사격 조건
├── [3] DefendInterrupt       ← τ_threat > 0.75
├── [4] PhaseController       ← 핵심: 어택큐 순차 실행
├── [5] ForcingAction         ← 수동적 상대 forcing (stale > 20틱)
├── [6] OrbitBreak            ← 교착 탈출 (|closure| < 80kts)
└── [7] SafetyFallback        ← LeadPursuit
```

기존 48 노드 → **7 브랜치** (~28 파라미터 → CMA-ES 최적화 가능)

### 11.5 성공 기준

| 기준 | 목표 |
|---|---|
| 전체 WR | > 66.7% (v11_code baseline) |
| vs defensive | 0% → ≥ 33% |
| vs eagle2 | 0% → ≥ 33% |
| 어떤 상대도 | v11_code 대비 −20pp 이하 없을 것 |

---

## 12. 다음 스프린트 & 로드맵

### 12.1 현재 상태 (2026-04-27)

| 항목 | 상태 |
|---|---|
| Sprint A: 측정 인프라 (schema 1.0, Wilson CI) | ✅ 완료 |
| Sprint B: Hypothesis Miner 4종 통합 | ✅ 완료 |
| EIM ProtoNet 98.8% 정확도 | ✅ 완료 |
| HCCA v12 5-레이어 구현 | ✅ 완료 |
| proof_of_win.py 91/91 증명 | ✅ 완료 |
| sim_dogfight_verify WIN=166(95%) | ✅ 완료 |
| 데이터 축적: 4,242 매치 | ✅ 완료 |
| PhaseController 구현 | 🔲 미착수 |
| Universal WR 65% | 🔲 미달성 |

### 12.2 Sprint C — 데이터 확장 + Intent 학습 준비

```bash
# C-1. 클래스 분포 확인 (dry-run)
python tools/train_intent_model.py --data logs/metadata/ --dry-run

# C-2. Hypothesis Miner 재실행 (4242 매치 누적)
python tools/hypothesis_miner.py mine \
  --matches logs/knowledge/matches.jsonl --top-k 20
```

**Gate**: per-class ≥ 100 sample 확보.

### 12.3 Sprint D — EIM 학습

```bash
python tools/train_intent_model.py \
  --data logs/metadata/ \
  --output models/intent_model.pt \
  --episodes 2000 --k-shot 5
```

**Gate**: per-class accuracy ≥ 75%.

### 12.4 Sprint E — Counter Selector

1. `(intent_predicted, active_node, outcome)` 추출 → `intent_node_outcomes.jsonl`
2. Wilson CI로 per-intent best node 집계 → `counter_table.json`
3. Gate: Wilson lower ≥ 0.55, n ≥ 100

### 12.5 Sprint F — APPLY + Universal 검증

```bash
python tools/build_bt_from_counter_table.py \
  --counter-table logs/knowledge/counter_table.json \
  --output examples/adaptive_eagle_v7/adaptive_eagle_v7.yaml

python tools/adaptive_optimizer.py --validate \
  examples/adaptive_eagle_v7/adaptive_eagle_v7.yaml \
  --validate-rounds 10
```

**목표**: Universal WR ≥ **65%**

### 12.6 미해결 과제

| 과제 | 우선순위 | 비고 |
|---|---|---|
| Z5 × offensive DRAW (9개) | 🟡 중간 | 시뮬 한도 300→500틱 확장으로 해결 가능 |
| Turn Radius Ratio L0 추가 | 🟡 중간 | 갭#1 근본 해결 |
| control_zone 본체 반영 | 🟡 중간 | in_39_line 활용 확대 |
| PhaseController 구현 | 🟢 장기 | Sprint F 이후 |
| Universal WR 65% | 🔴 목표 | Sprint F 검증 |

---

## 13. 부록

### 13.1 파일 구조

```
ai-combat-sdk/
├── MASTERBOOK.md                              ← 이 문서 (유일한 정본)
├── CLAUDE.md                                  ← Claude Code 지침
├── README.md                                  ← 프로젝트 소개 (외부용)
├── examples/adaptive_eagle_v11_code/
│   ├── adaptive_eagle_v11_code.yaml           ← BT 구조 정의 (16 브랜치)
│   ├── nodes/
│   │   ├── custom_actions.py                  ← HCCA v12 구현 (L0~L4, 2459줄)
│   │   └── custom_conditions.py               ← BT 조건 노드
│   ├── sim_dogfight_verify.py                 ← 1:1 전황별 Python 시뮬 (979줄)
│   ├── proof_of_win.py                        ← 수학적 증명 91 assertions
│   └── poc_orbit_fix.py                       ← orbit 수정 검증 52 assertions
├── tools/
│   ├── hypothesis_miner.py
│   ├── train_intent_model.py
│   └── adaptive_optimizer.py
├── logs/
│   └── knowledge/
│       ├── tactical_lookup.json
│       └── matches.jsonl                      ← 4,242 매치 결과
└── src/match/runner.py                        ← 매치 실행기
```

### 13.2 설계 갭 이력 (수정 완료 항목)

| 갭 | 증상 | 수정 내용 | 상태 |
|---|---|---|---|
| B1: τ_opp 과포화 | 에너지 위기에서 PURSUE 오선택 | op_suppress 완화 로직 추가 | ✅ 완료 |
| B2: 원거리 ATTACK 오선택 | dist=7000ft에서 ATTACK 선택 | dist_decay 감쇠 추가 | ✅ 완료 |
| 갭#1: stale closure 조건 | closure=+20kts에서 stale 미발동 | abs(closure)<50 조건으로 변경 | ✅ 완료 |
| 갭#3: flat scissors 무한 PURSUE | closure±30kts 진동 시 탈출 불가 | τ_pu<0.65 임계값 상향 | ✅ 완료 |
| 갭#2: 2-circle lag-roll | lead pursuit 에너지 과소모 | tc_type 기반 N 감소 구현 | ✅ 완료 |
| GunEngagement HCA gate | head-on에서 사격 오시도 | hca<30° OR hca>150° OR aa>45° | ✅ 완료 |
| PURSUE stale orbit | orbit 교착 탈출 미발동 | dist>6000 sprint 조건 추가 | ✅ 완료 |
| GAP-Z45: DEFEND 오선택 | ATA<45°에서 방어 기동 | ata 범위별 모드 강제 전환 | ✅ 완료 |

### 13.3 이론 참고 문헌

| 출처 | 내용 |
|---|---|
| AETC TTP 11-1 | 미 공군 Fighter Fundamentals 공식 교범 |
| Boyd E-M Theory (1960s) | Energy-Maneuverability Theory |
| DTIC AD1130933 | Air Combat Maneuvers via Operations Research |
| Springer 2023 | Deep RL for Air Combat |
| AIAA I011234 | Manual-Based Automated Maneuvering Decisions |
| Springer Nature 2024 | Tactical Intent-Driven Autonomous Air Combat |

---

*이 문서는 프로젝트의 유일한 정본(Single Source of Truth)입니다.*  
*코드 변경 시 관련 섹션을 함께 갱신하십시오.*
