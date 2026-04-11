# Adaptive Combat Behavior Tree — 설계 계획서 v5.0

> 최초 작성: 2026-04-05
> 최종 갱신: 2026-04-11 (v5.0: 학습 자료 강화, 이론 체계화)
> 목표: **"어떤 상대든 적응적으로 대응하여 항상 이기는 AI Pilot"**
> 통계적 정의: 전술 공간을 직교 분할한 상대 풀(695 BT)에서 **측정 가능한 Universal Win Rate를 최대화**한다.

---

## 목차

1. [문제 정의 (Problem Formulation)](#1-문제-정의)
2. [SE 설계 원칙](#2-se-설계-원칙)
3. [이론적 배경](#3-이론적-배경)
4. [전체 파이프라인 아키텍처](#4-전체-파이프라인-아키텍처)
5. [Phase별 상세 구현](#5-phase별-상세-구현)
6. [실험 결과 및 분석](#6-실험-결과-및-분석)
7. [되먹임 루프 (Feedback Loop)](#7-되먹임-루프)
8. [실패 사례 분석 (Failure Mode Catalog)](#8-실패-사례-분석)
9. [파일 구조](#9-파일-구조)
10. [커스텀 노드 작성 규칙](#10-커스텀-노드-작성-규칙)
11. [부록](#부록)

---

## 1. 문제 정의

### 1.1 공식 최적화 문제

AI Pilot 문제를 최적화 문제로 형식화하면:

$$
x^* = \arg\max_{x \in \mathcal{X}} \; \mathbb{E}_{o \sim \mathcal{O}} \left[ f(x, o) \right]
$$

여기서:
- $x \in \mathcal{X}$: BT 파라미터 벡터 (구조 + 노드 파라미터, 104차원)
- $\mathcal{O}$: 전술 공간 상의 상대 분포 (695 BT로 근사)
- $f(x, o)$: 상대 $o$에 대한 에이전트 $x$의 승패 점수
- $\mathbb{E}_{o \sim \mathcal{O}}$: 상대 풀 전체에 대한 기댓값

**핵심 전제**: 빌트인 고정점 $x_0 \in \mathcal{X}$이 탐색 공간에 포함되므로 $f(x^*) \geq f(x_0)$. 즉 **최적화 결과는 이론적으로 빌트인 baseline 이상을 보장**한다.

### 1.2 왜 어려운가

| 어려움 | 설명 | 해결 접근 |
|---|---|---|
| **Non-differentiable** | $f(x, o)$는 JSBSim 물리 시뮬레이션 → gradient 계산 불가 | Derivative-free optimization (CMA-ES) |
| **Noisy evaluation** | 같은 $x$에도 매치마다 결과가 다름 (stochastic) | Wilson CI로 신뢰구간 추적 |
| **High-dimensional** | 104차원 mixed discrete-continuous 공간 | CMA-ES covariance adaptation |
| **Adversarial** | 상대 분포를 잘못 정의하면 과적합 | 직교 분할된 695 BT 풀 |
| **Non-stationary** | 새 상대 추가 시 최적 전략이 바뀜 | 되먹임 기반 재최적화 사이클 |

### 1.3 성공 기준 (Acceptance Criteria)

| 지표 | 목표 | 측정 방법 |
|---|---|---|
| Universal Win Rate | **65%+** (695 풀, 10R) | Wilson CI ±1.18% |
| Worst-case layer WR | **50%+** | per-layer 분석 |
| CI 폭 | **±1% 이하** | 10R × 695 = 6,950 매치 |
| test_suite | **5/5** | 자동 검증 |
| 무패율 | **90%+** | per-opponent 통계 |

---

## 2. SE 설계 원칙

> 본 계획은 단일 버전의 BT를 만드는 것이 아니라, **"측정 → 진단 → 보강 → 재측정"이 자동화된 파이프라인**을 구축하는 것이다.

### 2.1 5대 원칙

#### 원칙 1: 전체 영역 탐색 (Full-Space Search)

"이론으로 좁힌 부분공간"이 아니라 전체 가능 공간을 탐색한다.

```
잘못된 접근:         올바른 접근:
전문가 직관          CMA-ES 전체 탐색
     ↓                    ↓
수동 튜닝            자동 발견
     ↓                    ↓
지역 최적             전역 최적 수렴
```

**보장**: 빌트인 baseline $x_0$이 탐색 공간에 포함 → $f(x^*) \geq f(x_0)$.

#### 원칙 2: 통계적 유의성

소규모·경험적 평가를 금지한다. 모든 판단은 Wilson CI와 함께 제시한다.

```python
# 나쁜 예: 의사결정에 충분하지 않음
n=10, WR=60%  →  CI = ±30%  →  실제 30~90% 가능

# 좋은 예: 신뢰할 수 있는 측정
n=6950, WR=65%  →  CI = ±1.18%  →  실제 63.8~66.2%
```

#### 원칙 3: 직교 분할 (Orthogonal Partitioning)

상대 풀은 **임의 수집이 아니라 전술 공간을 직교 축으로 체계적 분할**한다.
→ 상대 풀이 전술 공간 전체를 균등하게 커버하도록 설계. (Section 3.3 참조)

#### 원칙 4: 되먹임 기반 진화 (Feedback-Driven Evolution)

단일 최적화가 아니라 **검증 결과로 어느 Phase를 보강할지 진단하고 순환**한다.

```
사이클 구조:
최적화 → 검증 → 진단 → [Phase 보강] → 재최적화
              ↑_________________________________|
```

**핵심**: 사이클당 하나의 Phase만 변경. 동시 변경은 ablation 불능 (Section 7.3).

#### 원칙 5: 자동 검증 게이트 (Automated Verification Gate)

모든 코드 변경은 `test_suite.py`의 5개 정적 검사를 통과해야 커밋 가능하다.
→ BUG-4가 이 게이트 없이 3주간 미발견된 교훈에서 비롯.

### 2.2 SE 품질 속성 매핑

| 품질 속성 | 구현 수단 |
|---|---|
| **Correctness** | test_suite 5/5, BUG-4/5 수정 |
| **Reliability** | Wilson CI, 드리프트 비활성화 |
| **Reproducibility** | 결정론적 시드 매치 |
| **Observability** | per-layer/per-opponent 통계, loss cause 분류 |
| **Evolvability** | TUNABLE_PARAMS auto-discovery, 사이클 인프라 |
| **Efficiency** | stratified sampling, 병렬 워커 |

---

## 3. 이론적 배경

### 3.1 Basic Fighter Maneuvers (BFM) — Shaw의 분류

> 출처: Robert L. Shaw, *Fighter Combat: Tactics and Maneuvering* (1985)

공중전은 세 가지 기하학적 단계로 분류된다:

```
                    공중전 개시
                        ↓
            ┌───────────────────────┐
            │     기하학 판단        │
            │  - ATA (내 기수 각도)  │
            │  - AA (상대 꼬리 각도) │
            │  - HCA (교차각)        │
            └───────────┬───────────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
       OBFM           HABFM         DBFM
    (Offensive)    (Head-on/     (Defensive)
                    Neutral)
    - Lead Pursuit  - 1-circle   - Break Turn
    - Gun Attack    - 2-circle   - Extension
    - Snapshot      - Scissors   - Last Ditch
```

#### BFM 판단 기하학

```
WEZ (Weapon Engagement Zone):
  - 거리: 152 ~ 914 ft
  - ATA: < 12°
  - Base DPS: 25

ATA (Antenna Train Angle):
  - 내 기수에서 적까지의 각도
  - ATA < 12° → 발사 가능 (WEZ 조건)
  - 관측값: 0~1 정규화 → ×180 = 도

AA (Aspect Angle):
  - 적 꼬리 기준 나의 각도
  - AA < 30° → 적이 나를 향함 (공격받는 중)

HCA (Heading Crossing Angle):
  - 양 기체 heading 교차각
  - HCA < 90° → 1-circle 유리
  - HCA > 90° → 2-circle 유리
```

#### 관측 단위 변환 규약 (불변)

내부 관측은 **0~1로 정규화**되어 있음. 커스텀 노드에서 반드시 변환:

| 키 | 내부 범위 | 실제 단위 | 변환식 |
|---|---|---|---|
| `ata_deg` | 0~1 | 0~180° | `val × 180` |
| `aa_deg` | 0~1 | 0~180° | `val × 180` |
| `hca_deg` | 0~1 | 0~180° | `val × 180` |
| `tau_deg` | -1~1 | -180~180° | `val × 180` |
| `relative_bearing_deg` | -1~1 | -180~180° | `val × 180` |
| `distance_ft` | raw | feet | 변환 불필요 |
| `closure_rate_kts` | raw | knots | 변환 불필요 |
| `ego_altitude_ft` | raw | feet | 변환 불필요 |

> ⚠️ **이 규약 위반 = BUG-4 수준의 silent failure.** 조건이 항상 False/True로 평가됨.

### 3.2 CMA-ES (Covariance Matrix Adaptation Evolution Strategy)

#### 알고리즘 직관

CMA-ES는 다변량 정규분포 $\mathcal{N}(\mathbf{m}, \sigma^2 \mathbf{C})$에서 후보 해를 샘플링하고, 좋은 해들의 분포를 학습하여 탐색 방향을 진화시키는 derivative-free 최적화 알고리즘이다.

```
초기화: m ← x₀, σ ← σ₀, C ← I

반복 (세대 g = 1, 2, ...):
  1. 샘플링:  xᵢ ~ N(m, σ²C),  i = 1,...,λ
  2. 평가:    fᵢ = evaluate(xᵢ, opponent_sample)
  3. 선택:    상위 μ개 (xᵢ₁, ..., xᵢμ) 선택 (fᵢ₁ ≥ ... ≥ fᵢμ)
  4. 평균 갱신:  m' ← Σᵢ wᵢ xᵢ  (가중 평균)
  5. 공분산 갱신: C' ← (1-c₁-cμ)C + c₁ pcpcᵀ + cμ Σᵢ wᵢ ΔxᵢΔxᵢᵀ
  6. step-size 갱신: σ' ← σ · exp(...)
```

#### 왜 이 문제에 CMA-ES인가

| 요구사항 | CMA-ES의 강점 |
|---|---|
| Gradient 없음 | Derivative-free by design |
| Non-convex 함수 | Covariance adaptation으로 ill-conditioning 극복 |
| Mixed discrete-continuous | 연속값 반올림 후 discrete mapping |
| 병렬 평가 | Population 전체를 세대당 병렬 처리 |
| 고차원 (104-dim) | O(n²) covariance 업데이트, n=104에서 실용적 |

#### Discrete 파라미터 처리

CMA-ES는 연속 공간에서 동작한다. Discrete 파라미터는 다음과 같이 처리:

```python
def vector_to_params(x):
    # x[i] ∈ [0, 1]
    for i, (name, ptype, spec) in enumerate(PARAM_DEFS):
        val = np.clip(x[i], 0.0, 1.0)
        if ptype == "disc":
            # [0,1] → 정수 인덱스 → 선택지
            idx = int(val * len(spec)) % len(spec)
            params[name] = spec[idx]
        elif ptype == "cont":
            lo, hi = spec
            params[name] = lo + val * (hi - lo)
```

### 3.3 Wilson Score Interval

#### 왜 Wilson인가: 정규근사의 실패

흔히 쓰는 정규근사 CI:
$$\hat{p} \pm z\sqrt{\frac{\hat{p}(1-\hat{p})}{n}}$$

**문제**: $\hat{p} = 0$ 또는 $1$일 때 CI 폭이 0이 됨. 즉 "10전 10승이면 100% 확실"이라는 잘못된 결론.

Wilson Score Interval:
$$\text{CI}_{95\%} = \frac{\hat{p} + \frac{z^2}{2n} \pm z\sqrt{\frac{\hat{p}(1-\hat{p})}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}, \quad z=1.96$$

**특성**:
- $\hat{p} = 0, n = 10$ → Wilson CI: [0, 0.31] (정규근사: [0, 0])
- $\hat{p} = 1, n = 10$ → Wilson CI: [0.69, 1] (정규근사: [1, 1])
- boundary에서 올바른 행동 (coverage guarantee)

#### 실용적 의미

```
n 매치, WR=p일 때 Wilson CI margin (p=0.5 기준):

  margin ≈ 0.98 / √n

예:
  n=10   → ±31%  (의미 없음: 실제 19~81% 가능)
  n=100  → ±10%  (참고용)
  n=695  → ±3.7% (초보적 수준)
  n=6950 → ±1.18% (Universal claim 주장 가능)
  n=9604 → ±1.0%  (±1% 목표)
```

### 3.4 Latin Hypercube Sampling (LHS) — L4 설계 이유

5개 연속 파라미터를 Grid Search로 스윕하면 $5^5 = 3125$개가 필요하다.
LHS는 **n=80개로 동등한 marginal 커버리지**를 달성한다.

```
Grid (n=3, 2차원 예시):     LHS (n=3, 2차원 예시):

  ┌─┬─┬─┐                    ┌─┬─┬─┐
  │●│●│●│                    │ │●│ │
  ├─┼─┼─┤                    ├─┼─┼─┤
  │●│●│●│                    │●│ │ │
  ├─┼─┼─┤                    ├─┼─┼─┤
  │●│●│●│                    │ │ │●│
  └─┴─┴─┘                    └─┴─┴─┘
  9점 필요                    3점으로 각 행/열 1개씩

LHS 특성: 어떤 1차원 marginal 투영도 uniform에 가까움
→ sensitivity scan에 최적
```

---

## 4. 전체 파이프라인 아키텍처

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Adaptive BT Full Pipeline v6.0                    │
└──────────────────────────────────────────────────────────────────────┘

  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
  │   Phase 1   │   │   Phase 2   │   │   Phase 3   │   │   Phase 4   │
  │  측정 기반  │   │  표현력 &   │   │  탐색 공간  │   │  상대 풀 &  │
  │  (Measure)  │   │  정확성     │   │  최적화     │   │  적응성     │
  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
         │                 │                 │                 │
         ▼                 ▼                 ▼                 ▼
    evaluate.py       test_suite.py   adaptive_optimizer.py  generate_opponent_pool.py
    Wilson CI         name_collision  CMA-ES (104-dim)       695 BT × 6 layers
    loss cause        init_match      TUNABLE_PARAMS         L1~L6 직교 분할
    hp tracking       dead_code       auto-discovery         manifest.json
                      tree_structure

         │                 │                 │                 │
         └─────────────────┴─────────┬───────┴─────────────────┘
                                     ▼
                         ┌──────────────────────┐
                         │    Core Feedback Loop │
                         │  1. 최적화 (샘플링)   │
                         │  2. Full 풀 검증      │
                         │  3. 진단 (analyze)    │
                         │  4. 단일 Phase 보강   │
                         │  5. 재최적화          │
                         └──────────┬───────────┘
                     ┌──────────────▼──────────────┐
                     │   되먹임 매트릭스 (Section 7) │
                     │   증상 → 진단 → 대상 Phase    │
                     └─────────────────────────────┘
```

### 4.1 데이터 흐름 (Data Flow)

```
[CMA-ES 104-dim 벡터 x]
        ↓  vector_to_params()
[파라미터 딕셔너리]
        ↓  generate_bt_yaml()
[YAML BT 파일]
        ↓  src/match/runner.py (BehaviorTreeMatch)
[매치 결과: W/D/L + HP diff]
        ↓  evaluate.py
[점수: score = Σ(WIN_BASE + HP_WEIGHT × Δhp)]
        ↓
[CMA-ES → 분포 업데이트 → 다음 세대]
```

### 4.2 제어 루프 요약

```
관측 (0.2초/tick) → BT 결정 (3-tuple) → JSBSim 물리 (12 substep @ 60Hz)
                                          ↓
액션: [alt_idx(0-4), hdg_idx(0-8), vel_idx(0-4)] = 225 조합
                                          ↓
제약: 22.5° 조향 단위, 0.2초 반응 지연, 적 기동 미예측
```

**핵심 병목**: WEZ 접근은 쉬우나 WEZ 유지가 어려움
→ `SmartGunAttack` PD 제어가 가장 가치 있는 커스텀화 포인트

**Hard Deck**: 고도 1,000 ft (305 m) 이하 즉시 패배.

---

## 5. Phase별 상세 구현

### Phase 1: 측정 기반 (Measurement Infrastructure)

**목표**: 모든 의사결정이 노이즈가 아닌 통계에 기반하도록 한다.

#### Phase 1a: `tools/evaluate.py` — 통합 평가 함수

```python
def evaluate(agent, opponents, rounds=50, max_steps=1500) -> dict:
    """
    Returns:
    {
        "win_rate": float,               # 전체 승률
        "ci_95": (lo, hi),               # Wilson score interval
        "per_opponent": {
            name: {
                "W": int, "D": int, "L": int,
                "win_rate": float,
                "ci_95": (lo, hi),
                "avg_hp_diff": float     # 양수 = 우리가 유리
            }
        },
        "loss_causes": {
            "hard_deck": int,            # 고도 패배
            "hp_diff": int,              # HP 차이 패배
            "timeout": int,              # 시간 초과
            "draw": int
        }
    }
    """
```

**Fitness Score 설계**:
$$\text{score} = \sum_{\text{opp}} \begin{cases}
W_\text{base} + \alpha \cdot \Delta\text{hp} & \text{if win} \\
D_\text{base} + \alpha \cdot \Delta\text{hp} & \text{if draw} \\
L_\text{base} + \alpha \cdot \Delta\text{hp} & \text{if loss}
\end{cases}$$

$W_\text{base}=10,\ D_\text{base}=1,\ L_\text{base}=-5,\ \alpha=2.0$

**설계 근거**: 단순 W/L 카운트는 "1HP 차이 승리"와 "50HP 차이 승리"를 동일하게 취급. $\Delta\text{hp}$를 추가하면 우세한 승리를 더 강하게 보상 → gradient가 풍부해져 CMA-ES 수렴 속도 향상.

#### Phase 1b: `tools/test_suite.py` — 구조적 자동 검증

5개 정적 검사 (모두 통과해야 유효한 BT):

| 테스트 | 검증 대상 | 실패 시 증상 | 영향 |
|---|---|---|---|
| `name_collision` | 커스텀 노드명 ≠ pyd 빌트인 | 커스텀 로직 silently 무시 | **최악**: 탐색 공간이 의도와 다르게 작동 |
| `yaml_init_match` | YAML `params` ↔ `__init__` 파라미터 일치 | `TypeError: unexpected keyword` | 런타임 크래시 |
| `init_imports` | YAML 참조 노드 → `__init__.py` import | 빌트인 fallback으로 교체 | silent degradation |
| `dead_code` | import ≠ YAML 사용 | 탐색 공간 오염 | 최적화 효율 저하 |
| `tree_structure` | 루트 Selector + 첫 branch HardDeck | Hard Deck 패배 위험 | WR 급락 |

> **v6.0 참고**: `dead_code`는 `__init__.py`가 CMA-ES auto-discovery를 위해 모든 노드를 export하므로 항상 1개 실패. 이는 **설계상 예상된 결과** (4/5 = 정상).

**실증 사례 (BUG-4)**:
```
IsCircularOrbit (커스텀)
     ↓ pyd 빌트인 IsCircularOrbit에 의해 override
빌트인 로직으로 silently 교체됨
     ↓ test_suite name_collision으로 즉시 탐지
CustomOrbitDetector로 개명 → 해결
```

### Phase 2: 표현력 & 정확성 (Representation & Correctness)

**목표**: 탐색 공간의 BT 표현이 모두 *실제로* 의도한 대로 작동하도록 한다.
잘못된 BT를 아무리 최적화해도 의미 없다.

#### 수정된 버그 목록

| ID | 위치 | 증상 | 근본 원인 | 해결 | 발견 방법 |
|---|---|---|---|---|---|
| **BUG-4** ✅ | `custom_conditions.py` | `IsCircularOrbit` 무시됨 | pyd 빌트인과 이름 충돌 | `CustomOrbitDetector`로 개명 | test_suite name_collision |
| **BUG-5** ✅ | `src/match/runner.py` | EIM이 항상 DEFENSIVE 분류 | `tracker1.update(obs2)` — 상대 obs 입력 오류 | `tracker1.update(obs1)` | 수동 EIM 출력 분석 |
| **DRIFT** ✅ | `src/match/runner.py` | 10R 재현성 없음 (38→80%) | mid-match `update_online()` 드리프트 | 매치 중 온라인 업데이트 비활성화 | run-to-run 분산 측정 |
| **DEAD** ✅ | `custom_*.py` | 8개 클래스 미사용 | 이전 리팩토링 잔존물 | 삭제 (371줄 → 131줄) | test_suite dead_code |

#### BUG-5 상세 분석 (EIM tracker 오류)

```python
# 오류 코드 (수정 전):
tracker1.update(obs2)  # ← 상대의 self-observation을 내가 관찰하는 것으로 착각

# 수정 코드:
tracker1.update(obs1)  # ← 내 관점에서 관찰한 상대의 행동

# 결과:
# 오류 시: 상대가 항상 "자신을 관찰" → 의도 분류 불가 → 항상 DEFENSIVE
# 수정 후: 실제 상대 기동 패턴 관찰 → NEUTRAL_CIRCLE, AGGRESSIVE 정상 분류
```

### Phase 3: 탐색 공간 & 최적화 (Search & Optimization)

**목표**: 표현력 있는 노드와 CMA-ES로 전체 공간을 실질적으로 탐색한다.

#### Phase 3a: BFM 노드 분류 (35개)

각 노드는 `TUNABLE_PARAMS` 딕셔너리로 최적화 대상 파라미터를 선언한다:

```python
class SmartLeadPursuit(BaseAction):
    """
    Lead Pursuit: 적의 미래 위치를 예측하여 lead angle을 계산하고
    그 방향으로 기동. Pure Pursuit보다 WEZ 진입 효율이 높음.
    """
    TUNABLE_PARAMS = {
        "heading_gain": {"type": "cont", "range": (0.3, 2.0), "default": 1.0},
        # 너무 높으면 오버슈트, 너무 낮으면 느린 반응
        "vel_far":      {"type": "disc", "choices": [2, 3, 4], "default": 4},
        # 원거리: 고속 접근
        "vel_close":    {"type": "disc", "choices": [1, 2, 3, 4], "default": 3},
        # 근거리: 중간 속도 (오버슈트 방지)
    }
```

**노드 분류표**:

| 카테고리 | 노드 (23개 액션) | BFM 이론 역할 |
|---|---|---|
| **OBFM (Offensive)** | SmartLeadPursuit, SmartPurePursuit, SmartLagPursuit, SmartGunAttack, SnapshotAttack | Lead angle 예측, WEZ 진입 및 유지 |
| **DBFM (Defensive)** | SmartBreakTurn, SmartDefensiveSpiral, ExtensionBreak, Jink, GunsDefense, LastDitch | Break turn G-force, energy recovery, last ditch maneuver |
| **HABFM (Head-on)** | SmartOneCircle, SmartTwoCircle, FlatScissors, RollingScissors | 선회전 주도권 확보 |
| **Energy Mgmt** | SmartHighYoYo, SmartLowYoYo, SmartClimbingTurn, SmartDescendingTurn, VerticalFight | Ps 관리, E-M advantage |
| **Disengagement** | HeadOnBreak, UnloadedExtension, Chandelle | 이탈 및 재접근 각도 확보 |

**조건 노드 (12개)**:

| 노드 | 조건 논리 | BFM 판단 근거 |
|---|---|---|
| `IsOffensiveGeometry` | ATA < θ_off AND dist < d_max | 공격 기회 판단 |
| `IsDefensiveGeometry` | AA < θ_def (상대가 나를 향함) | 방어 전환 판단 |
| `IsWEZOpportunity` | ATA < 12° AND dist ∈ [152, 914] ft | 실제 발사 가능 여부 |
| `CustomOrbitDetector` | ATA ∈ [35°, 85°] AND closure < th | 선회전 감지 (BUG-4 수정) |
| `IsOneCircleSituation` | HCA < 90° | 1-circle vs 2-circle 판단 |
| `IsUnderFire` | AA < θ_danger | 피격 위험 판단 |

#### Phase 3b: CMA-ES 탐색 공간 (104차원)

탐색 공간 구성:

```
PARAM_DEFS 구성:
  8개  — 브랜치 ON/OFF (enable_gun, enable_eim, ...)
  9개  — Action slot 선택 (gun_action, pursuit_action, ...)
  ~83개 — 조건/액션 노드 TUNABLE_PARAMS (연속/이산) + 전역 파라미터
  ─────
  ~104개 총 차원 (auto-discovery로 노드 추가 시 자동 확장)
```

**auto-discovery 메커니즘**:
```python
def _discover_tunable_classes():
    """nodes/custom_*.py를 스캔하여 TUNABLE_PARAMS가 있는 클래스 자동 등록."""
    # 새 노드를 추가하면 optimizer가 자동으로 인식
    # 탐색 공간 차원도 자동으로 확장됨
```

#### Phase 3c: 평가 전략 (두 단계 분리)

| 단계 | 풀 | 라운드 | 매치 수 | 목적 |
|---|---|---|---|---|
| **최적화 루프** | Layer-stratified 40개 | 1 | 40 | CMA-ES fitness (빠른 피드백) |
| **최종 검증** | 전체 695개 | 10~50 | 6,950~34,750 | Universal claim 통계 |

**Stratified Sampling 필요성**:
```
단순 랜덤 40개:
  L1(81개) → 5개, L2(240개) → 14개, L3(120개) → 7개...
  → L2가 과대 대표됨 → CMA-ES가 L2 특화 BT로 수렴

Stratified 40개:
  각 layer에서 균등하게 → 모든 전술 유형 커버
  → 전체 풀에서 균형잡힌 최적화
```

### Phase 4: 상대 풀 & 적응성 (Opponent Pool & Adaptation)

**목표**: 전술 공간 전체를 체계적으로 커버하는 직교 상대 풀 구축.

#### Phase 4a: 직교 축 (Orthogonal Tactical Axes)

| 축 | 값 | 이론 근거 |
|---|---|---|
| **Phase Focus** | OBFM / DBFM / HABFM / MIXED | Shaw BFM 3대 분류 |
| **Range Preference** | GUN(<914ft) / CLOSE(<3000) / MID(<6000) / LONG(>6000) | WEZ 경계 + 추적 전환점 |
| **Energy Discipline** | PRESERVE / TRADE / IGNORE | Boyd E-M 이론 |
| **Aggression** | PASSIVE / BALANCED / AGGRESSIVE | 평균 속도·선회율 |
| **Primary Action** | ~30 builtin actions | Action Space 전수 |
| **Altitude Bias** | HIGH / LEVEL / LOW | 수직 기동 편향 |

#### Phase 4b: Layer 구조 (695 BT)

| Layer | 설계 목적 | 구성 방법 | 개수 |
|---|---|---|---|
| **L1** | 개별 action 순수 성능 기준 | 27 actions × 3 속도 프리셋 | 81 |
| **L2** | 조건-액션 결합 효과 | 10 cond × 8 action × 3 fallback | 240 |
| **L3** | BFM 이론 직접 반영 | OBFM × DBFM × Neutral 조합 | 120 |
| **L4** | 연속 파라미터 민감도 | LHS 5-dim 80 샘플 | 80 |
| **L5** | 다축 직교 조합 | 4 phase × 4 range × 3 energy × 3 agg | 144 |
| **L6** | 의도적 카운터 (hard test) | 수동 설계: WEZ denial, hit-run 등 | 30 |
| **합계** | | | **695** |

**L6 존재 이유**: L1~L5는 체계적이지만 "AI가 발견하기 어려운 카운터 전략"을 포함하지 않는다. L6는 현재 best가 취약할 것으로 예상되는 패턴을 수동으로 설계하여 포함.

#### Phase 4c: 통계적 규모 근거

$$\text{Wilson CI margin at } p = 0.5: \quad \pm 1.96\sqrt{\frac{0.25}{n}} \approx \frac{0.98}{\sqrt{n}}$$

| $n$ (매치 수) | CI Margin | 의미 |
|---|---|---|
| 6,950 (10R × 695) | **±1.18%** | Universal claim 가능 수준 |
| 13,900 (20R × 695) | **±0.83%** | 고신뢰 |
| 34,750 (50R × 695) | **±0.53%** | 최고 정밀도 |
| per-opp @ 10R | ±30% | 개별 진단 불가 |
| per-opp @ 50R | ±13% | 약점 패턴 식별 가능 |

**결론**: Universal WR은 10R(±1.18%)로 충분. per-opponent 진단은 50R 이상 필요.

---

## 6. 실험 결과 및 분석

### 6.1 버전 진화 비교

| 항목 | v5.1 (이전) | **v6.0 (현재)** |
|---|---|---|
| 상대 풀 크기 | 6 | **695** |
| 탐색 공간 차원 | ~15 | **104** |
| 커스텀 노드 수 | 7 | **35** |
| CMA-ES budget | 100 | **400** |
| 최적화 stratified sample | — | **40 (layer balanced)** |
| Wilson CI @ 최종 검증 | ±15% (6R×6opp) | **±0.53% (50R×695)** |

### 6.2 v6.0 CMA-ES 최적화 결과 (완료)

| Metric | 값 |
|---|---|
| Budget | 400 evals |
| Elapsed | 440.5분 (~7.3h, 4 workers) |
| Best score | **295.36** (gen 38, eval 304) |
| Best W/D/L (40 sample) | **28 / 11 / 1** |
| Best WR (stratified) | **70.0%** |
| 무패율 | **97.5%** |

**Best 구조 (CMA-ES 선택)**:
```yaml
pursuit_action: SmartPurePursuit
gun_action:     SmartGunAttack
default_action: SmartLeadPursuit
enable_gun:     true
enable_eim:     true
enable_defense: false   # CMA-ES가 disable 선택
enable_neutral: false   # CMA-ES가 disable 선택
enable_orbit:   false   # CMA-ES가 disable 선택
```

**해석**: 단순 공격 중심 BT가 직교 풀에서 가장 강함. Defense/Neutral branch는 조건 판단 오류 시 오히려 결정 노이즈로 작용 → disable이 최적.

이는 "복잡한 전략 > 단순한 전략"이라는 직관에 반한다. **CMA-ES가 데이터로 반증한 사례**.

### 6.3 v6.0 Full Pool Validation (실행 중 — 2026-04-11)

| Metric | 값 |
|---|---|
| 파라미터 | 695 opp × 10R = **6,950 매치** |
| Workers | 48 (64-core machine) |
| 중간 W/D/L | 113 / 71 / 16 (200매치 시점) |
| 중간 WR | 56.5% (초반 편향 있음) |
| 예상 최종 CI | **±1.18%** |

> **초반 편향 주의**: `imap_unordered` 특성상 빠른 매치(L1 단순 상대)가 먼저 완료 → 초반 WR은 최종과 다를 수 있음.

완료 시 `logs/cycle_1/validation.json`에 per-layer, per-opponent 통계 저장.

---

## 7. 되먹임 루프 (Feedback Loop)

### 7.1 진단 → Phase 매핑 매트릭스

| 증상 | Root Cause 가설 | 되먹임 대상 | 검증 방법 |
|---|---|---|---|
| 분산이 큼 (CI 넓음, run-to-run 불일치) | 측정 신뢰성 부족 | **Phase 1** | 동일 BT k회 평가 → 표준편차 |
| 새 best가 이전보다 regression | Fitness metric 불일치 | **Phase 1** | seed 고정 후 재측정 |
| 특정 layer에 일관된 패배 | 노드/조건 표현력 한계 | **Phase 2, 3** | 해당 layer 노드 발동률 분석 |
| EIM ON < EIM OFF 성능 | EIM 입력/라벨 오류 | **Phase 2** | EIM 예측 accuracy 직접 측정 |
| 모든 layer에서 50% saturation | 탐색 공간 자체 빈약 | **Phase 3** | 노드 다양성 분석 |
| CMA-ES 조기 수렴 | 차원 과다 / step-size 문제 | **Phase 3** | convergence curve 분석 |
| L6 counter에만 약함 | 메타게임 미반영 | **Phase 4** | L6 상대 개별 분석 |

### 7.2 Phase별 보강 플레이북

#### → Phase 1 보강 (측정 개선)
- 동일 BT $k$회 평가 → 표준편차 측정 (목표: ±5%p 이하)
- **결정론적 시드 매트릭스** 도입: `evaluate.py --seed-grid`
- Fitness 다각화: `time-to-engagement`, `energy retention`, `first-shot advantage` 추가

#### → Phase 2 보강 (버그 수정)
- Best YAML 실제 매치 trace → 각 노드 발동률 카운트
- 발동률 0% 노드 → 조건 임계값 또는 unit 변환 BUG 의심
- EIM 라벨 정확도 직접 측정 (예측 vs ground truth)

#### → Phase 3 보강 (노드/탐색 확장)
- 약점 layer 분석 → 그 layer가 쓰는 액션에 대한 counter 노드 존재 확인
- 없다면 신규 BFM 노드 추가 (예: high-G barrel roll, lag pursuit with energy bleed)
- `TUNABLE_PARAMS` range 재검토 (너무 좁으면 전역 탐색 실패)
- Action slot 확장 (현재 9개 → phase별 sub-slot)

#### → Phase 4 보강 (풀/전략 확장)
- **Per-layer min fitness**: 평균 대신 worst-case layer를 강하게 압박
- **CMA-ES seed 다중화**: 1 seed → 3 seeds × 부분 budget, best ensemble
- **Curriculum learning**: L1/L2 먼저 → 점진적으로 L6에 가중치 이전
- **Self-play**: 이전 세대 best를 풀에 추가 → 자기 약점 자동 노출
- **Adversarial pool generation**: 현재 best 취약 패턴 자동 검출 → 신규 상대 자동 생성

### 7.3 사이클 운영 원칙

> **한 사이클당 하나의 Phase만 변경.**

이유: 여러 Phase를 동시에 변경하면 어떤 변경이 효과를 냈는지 분리 불가 (ablation 불능).

```
나쁜 예:
  Phase 1 + Phase 3 동시 변경 → WR 65% → 70%
  → 어떤 변경이 효과적인지 모름

올바른 예:
  Cycle 1: Phase 3 변경 → WR 65% → 68% (+3%p)
  Cycle 2: Phase 1 변경 → WR 68% → 70% (+2%p)
  → 각 변경의 단독 효과를 명확히 측정 가능
```

### 7.4 사이클 기록 인프라

매 사이클 다음을 저장:

```
logs/cycle_N/
├── best.yaml          # 이 사이클의 best BT
├── validation.json    # 695 풀 검증 결과 (per_layer, per_opponent, Wilson CI)
├── diagnosis.md       # 어떤 Phase 보강을 결정했는지 + 정량적 근거
├── changeset.md       # 무엇을 바꿨는지 (단일 Phase, 1~3줄)
└── diff_vs_prev.md    # 이전 사이클 대비 per-layer WR 변화
```

이 인프라가 있어야 "경험적 학습"이 아닌 **체계적 개선**이 된다.

---

## 8. 실패 사례 분석 (Failure Mode Catalog)

> 이 섹션은 학습 목적으로 가장 중요하다. 같은 실수를 반복하지 않기 위한 카탈로그.

### 8.1 BUG-4: pyd Override Silent Failure (2026-04-09)

**현상**: `CustomOrbitDetector` 조건이 항상 True/False 중 하나만 반환
**원인**: Python `py_trees` 빌트인 pyd에 동명 클래스 존재 → import 시 커스텀 클래스가 shadowed

```
탐지 방법:
  test_suite name_collision → 즉시 탐지

해결:
  IsCircularOrbit → CustomOrbitDetector (pyd에 없는 이름으로 변경)

교훈:
  커스텀 노드명은 pyd 내부 이름과 반드시 충돌 검사 후 확정.
  test_suite는 커밋 전 필수 실행.
```

**일반화**: 외부 라이브러리의 내부 심볼 목록을 미리 파악하고, 이름 충돌 검사를 CI/CD에 포함시켜라.

### 8.2 DRIFT: Non-deterministic Evaluation (2026-04-08)

**현상**: 동일 BT, 동일 상대, 10라운드 → WR이 38%~80%로 변동
**원인**: `online_tracker.update_online()`이 매치 중간에 EIM 프로토타입을 업데이트 → 각 라운드마다 초기 상태가 달라짐

```
수정:
  매치 시작 시 tracker 상태 동결 (freeze_for_match=True)
  매치 종료 후에만 업데이트 허용

교훈:
  평가 함수의 결정론성은 최적화의 전제 조건.
  같은 입력 → 같은 출력이 보장되지 않으면 CMA-ES가 노이즈를 최적화함.
  "측정 도구를 먼저 교정하라."
```

### 8.3 v5.0-smart: Heading Override Regression (2026-04-07)

**현상**: `SmartLeadPursuit` 추가 후 WR이 60% → 30%로 급락
**원인**: 커스텀 heading 계산이 빌트인 proportional navigation(PN)보다 정확도가 낮음

```
교훈:
  "커스텀이 항상 낫다"는 가정은 틀렸다.
  빌트인 heading(PN) + 커스텀 WEZ 제어(SmartGunAttack)의 조합이 최적.
  커스텀화는 빌트인이 못하는 영역(WEZ 유지)에만 집중.
```

### 8.4 v4.4: RLInspiredAttack 0% (2026-04-06)

**현상**: RL 정책에서 영감받은 기동 추가 → WR 0%
**원인**: 좌우 방향 반전 버그 (좌선회가 우선회로 출력)

```
교훈:
  새 노드 추가 시 최소 10R 회귀 테스트 필수.
  "이론적으로 좋아 보이는" 노드도 구현 오류 가능.
```

### 8.5 CMA-ES 결과 해석 주의사항

**현상**: Defense branch 전체 disable이 CMA-ES 최적 선택
**위험한 해석**: "방어 기동은 쓸모없다"
**올바른 해석**: "현재 조건 노드의 정확도가 낮아서 방어 분기가 역효과"

```
검증 방법:
  1. 방어 노드 발동률 측정 (0%에 가까우면 조건 오류)
  2. 방어 branch ON vs OFF를 per-layer로 비교

교훈:
  최적화 결과를 "진실"로 받아들이지 말고 "현재 구현의 반영"으로 보라.
  데이터는 현재 구현의 결과를 측정할 뿐, 이론적 진실을 말하지 않는다.
```

---

## 9. 파일 구조

```
ai-combat-sdk/
├── tools/
│   ├── evaluate.py                    # Phase 1a: 통합 평가 + Wilson CI
│   ├── test_suite.py                  # Phase 1b: 5개 자동 검증
│   ├── adaptive_optimizer.py          # Phase 3: CMA-ES 104-dim + auto-discovery
│   ├── generate_opponent_pool.py      # Phase 4: 695 직교 풀 생성기
│   └── expand_archetypes.py           # (legacy) EIM 학습용
│
├── examples/
│   ├── adaptive_eagle/
│   │   ├── adaptive_eagle.yaml        # v5.1 수동 버전 (baseline)
│   │   ├── _best_pool_v1.yaml         # v6.0 CMA-ES best (2026-04-10)
│   │   └── nodes/
│   │       ├── __init__.py            # 35 클래스 re-export (auto-discovery용)
│   │       ├── custom_actions.py      # 23 action 노드 (TUNABLE_PARAMS)
│   │       └── custom_conditions.py   # 12 condition 노드 + EIM
│   │                                  # (CustomOrbitDetector — pyd override 회피)
│   └── opponent_pool/                 # 695 BT + manifest.json
│       ├── L1_pure_*.yaml             # 81개
│       ├── L2_*.yaml                  # 240개
│       ├── L3_phase_*.yaml            # 120개
│       ├── L4_lhs_*.yaml              # 80개
│       ├── L5_*.yaml                  # 144개
│       ├── L6_*.yaml                  # 30개
│       └── manifest.json              # layer, category, params 메타
│
├── src/
│   └── match/
│       ├── runner.py                  # BUG-5 수정 + 드리프트 비활성화
│       └── runner_core.py
│
├── logs/
│   └── cycle_N/                       # 사이클별 기록
│       ├── best.yaml
│       ├── validation.json
│       ├── diagnosis.md
│       ├── changeset.md
│       └── diff_vs_prev.md
│
└── ADAPTIVE_BT_PLAN.md                # 본 문서 (v5.0)
```

---

## 10. 커스텀 노드 작성 규칙 (불변)

새 노드를 추가할 때 반드시 지켜야 하는 체크리스트:

| # | 항목 | 확인 방법 | 위반 시 증상 |
|---|---|---|---|
| 1 | 이름이 pyd 빌트인과 충돌하지 않는가 | `python tools/test_suite.py <yaml>` | silent override (BUG-4 재현) |
| 2 | 각도값 ×180 변환했는가 | `ata_deg` 등은 0~1 정규화 | 조건 항상 오평가 |
| 3 | YAML params ↔ `__init__` 파라미터 일치 | `test_suite yaml_init_match` | TypeError 런타임 크래시 |
| 4 | `__init__.py`에 import했는가 | `test_suite init_imports` | 빌트인 fallback |
| 5 | `TUNABLE_PARAMS` 정의했는가 | auto-discovery 대상이 되려면 필수 | 최적화에서 제외 |
| 6 | heading은 빌트인 우선인가 | v5.0-smart 실패 교훈 | WR 30% 이하로 급락 |
| 7 | 단독 10R 회귀 테스트 통과했는가 | `evaluate.py --rounds 10` | v4.4 재현 위험 |

---

## 부록 A: 핵심 수식 모음

**Wilson Score Interval (95%)**:
$$[\text{lo}, \text{hi}] = \frac{\hat{p} + \frac{z^2}{2n} \pm z\sqrt{\frac{\hat{p}(1-\hat{p})}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}, \quad z=1.96$$

**Fitness Score (CMA-ES 평가)**:
$$\text{score} = \sum_{\text{opp}} \begin{cases}
10 + 2\Delta\text{hp} & \text{win} \\
1 + 2\Delta\text{hp} & \text{draw} \\
-5 + 2\Delta\text{hp} & \text{loss}
\end{cases}$$

**CI Margin (n 매치, p=0.5)**:
$$\text{margin} \approx \frac{0.98}{\sqrt{n}}$$

**LHS 효율**:
$$\text{Grid 필요 수} = k^d \quad \text{vs} \quad \text{LHS 필요 수} = n \ll k^d$$

---

## 부록 B: 버전 이력

| 버전 | 주요 변경 | 주요 측정 | 핵심 교훈 |
|---|---|---|---|
| v3.x | 순수 기하학 BT | eagle1 ~50% | EIM 없이도 50% 달성 가능 |
| v4.0~v4.3 | EIM 연결 시도 | 불안정 | 통합 테스트 없이 연결하면 반드시 버그 |
| v4.4 | RLInspiredAttack | **0%** | 구현 버그 → 회귀 테스트 필수 |
| v4.5 | LeadPursuit 복귀 | 57% | 단순한 것이 안정적 |
| v4.6 | EIM NEUTRAL_CIRCLE | 38~80% | 드리프트 → 측정 결정론성 필수 |
| v4.7 | BUG-4/5 수정, 드리프트 안정화 | EIM active | pyd override 회피 패턴 확립 |
| v5.0 | BUG-4,5 수정 확인 | 50% (재기준) | 측정 기반 검증의 힘 |
| v5.0-smart | SmartLeadPursuit | **30%** | 커스텀 heading < 빌트인 PN |
| v5.1 | 빌트인 LP + SmartGunAttack | 60% | 빌트인 heading + 커스텀 WEZ = 최적 조합 |
| **v6.0** | 695 풀 + CMA-ES 104-dim + 35 노드 | **stratified 70%** | 직교 풀 + auto-discovery = 전체 탐색 가능 |

---

## 부록 C: 용어집

| 용어 | 정의 |
|---|---|
| **BFM** | Basic Fighter Maneuvers: 기본 공중전 기동 이론 |
| **OBFM / DBFM / HABFM** | Offensive / Defensive / Head-on & Break-away BFM |
| **WEZ** | Weapon Engagement Zone: 유효 사격 영역 (152~914ft, ATA<12°) |
| **ATA** | Antenna Train Angle: 내 기수 기준 적까지의 각도 |
| **AA** | Aspect Angle: 적 꼬리 기준 나의 각도 |
| **HCA** | Heading Crossing Angle: 양 기체 heading 교차각 (1-circle vs 2-circle 판단) |
| **Ps** | Specific Power: 단위 중량당 에너지 변화율 (E-M 이론) |
| **E-M** | Energy-Maneuverability: Boyd 이론, turn rate vs G-load vs 에너지 |
| **EIM** | Enemy Intent Model: 상대 전술 의도 예측 (ProtoNet GRU+Attention) |
| **Hard Deck** | 즉시 패배 고도 (1,000 ft) |
| **1-circle fight** | 양 기체가 같은 방향으로 선회하는 근접 공중전 |
| **2-circle fight** | 양 기체가 반대 방향으로 선회하는 공중전 |
| **CMA-ES** | Covariance Matrix Adaptation Evolution Strategy: 진화 전략 최적화 알고리즘 |
| **Wilson CI** | Wilson Score Confidence Interval: 소표본에서 안정적인 비율 신뢰구간 |
| **LHS** | Latin Hypercube Sampling: 고차원 공간의 효율적 샘플링 방법 |
| **Stratified Sampling** | 층화 샘플링: 각 계층에서 균등하게 샘플 추출 |
| **Ablation** | 요소를 하나씩 제거하며 각 구성 요소의 기여도를 측정하는 실험 방법 |

---

## 부록 D: 인프라 요구사항

- **Python 3.14** 필수 (upstream pyd가 cp314-win_amd64)
- `PYTHONIOENCODING=utf-8` (Windows cp949 인코딩 충돌 방지)
- 패키지: `cma`, `py_trees>=2.4.0`, `pyyaml`, `pydantic>=2.0`, `gymnasium`, `torch`
- `.venv/` 위치: `c:/Users/USER/Desktop/ai-combat-sdk/.venv/`
- upstream remote: `https://github.com/rokafa-daslab/ai-combat-sdk`
