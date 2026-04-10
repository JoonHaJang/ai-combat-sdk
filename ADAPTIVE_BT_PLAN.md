# Adaptive Combat BT — 설계 계획서 v3.0

> 최초 작성: 2026-04-05
> 최종 갱신: 2026-04-10 (Phase 3 완료, Phase 4 전체 파이프라인 + 되먹임 루프 정립)
> 목표: **"어떤 상대든 적응적으로 대응하여 항상 이기는 AI Pilot"**
> **통계적 정의: 전술 공간을 직교 분할한 상대 풀(695 BT)에서 측정 가능한 Universal Win Rate를 최대화한다.**

---

## 0. 개요 — 왜 이렇게 하는가 (SE 1차 원칙)

본 계획은 단일 버전의 BT를 만드는 것이 아니라, **"측정 → 진단 → 보강 → 재측정"** 이 자동화된 파이프라인을 구축하는 것이 목적이다.

### 0.1 핵심 원칙

1. **전체 영역 탐색**: 이론으로 축소된 일부만 보지 말고, CMA-ES로 파라미터·구조·노드 선택을 동시에 전 영역 탐색한다. 빌트인 고정값이 탐색 공간에 포함되므로 **결과 ≥ 빌트인 baseline**이 이론적으로 보장된다.
2. **통계적 유의성**: 소규모·경험적 평가 금지. 모든 판단은 Wilson 신뢰구간과 함께 제시한다.
3. **직교 분할**: 상대 풀은 임의 수집이 아니라 전술 공간을 직교 축으로 분할하여 체계적으로 생성한다.
4. **되먹임 기반 진화**: 단일 사이클이 아니라, 검증 결과로 Phase 1~4 중 어느 단계를 보강할지 진단하고 순환한다. **사이클 당 한 단계만 변경**하여 ablation 가능성을 보존한다.
5. **모든 변경은 자동 검증 통과**: `test_suite.py`가 구조적 정합성을 자동 검사한다.

### 0.2 이론적 근거

**왜 전체 영역 탐색이 베스트인가?**

- Search space $\mathcal{X}$에 빌트인 고정점 $x_0$이 포함되어 있다면, CMA-ES의 전역 최적 $x^*$는 정의상 $f(x^*) \geq f(x_0)$.
- 단, (1) 평가 노이즈가 있고, (2) budget이 유한하므로, 실제로는 "**전역 최적에 확률적으로 수렴**"이다.
- 따라서 이 파이프라인의 성패는 다음 세 가지에 달려있다:
  - (a) **평가 측정의 정확도** (Phase 1 — Wilson CI)
  - (b) **탐색 공간의 표현력** (Phase 2,3 — 노드 정의와 BUG 부재)
  - (c) **탐색의 효율성** (Phase 3 — CMA-ES + 병렬화 + 풀 샘플링)

**왜 695개 직교 풀인가?**

- 전술 공간을 6축(Phase, Range, Energy, Aggression, Primary Action, Altitude)으로 직교 분할하면 유한한 조합 공간이 된다.
- Layer 1~6은 이 공간의 서로 다른 밀도 영역을 채우도록 설계됨:
  - L1: 개별 action "원자" 성능 (sparse prior)
  - L2: 조건 × action 결합 (2-body interaction)
  - L3: Phase 분해 (BFM 이론 직접 반영)
  - L4: Latin Hypercube — 연속 파라미터의 공간 커버리지
  - L5: 4축 직교 곱 (테스트 매트릭스)
  - L6: 의도적 카운터 (하드 테스트 케이스)
- **통계적 의의**: $n = 695 \times 10 = 6950$ 매치일 때 Wilson $\text{CI}_{95\%}$ at 50% WR $\approx \pm 1.18\%$. Universal claim을 주장할 수 있는 수준.

---

## 1. 전체 파이프라인 아키텍처

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Adaptive BT Full Pipeline                      │
└──────────────────────────────────────────────────────────────────────┘

  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
  │   Phase 1   │   │   Phase 2   │   │   Phase 3   │   │   Phase 4   │
  │  측정 기반  │   │  표현력 &   │   │  탐색 공간  │   │  상대 풀 &  │
  │  (metric)   │   │  버그 수정  │   │  최적화     │   │  적응성     │
  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
         │                 │                 │                 │
         ▼                 ▼                 ▼                 ▼
    evaluate.py       test_suite.py   adaptive_optimizer.py  generate_opponent_pool.py
    Wilson CI         name_collision  CMA-ES (104-dim)       695 BT × 6 layers
    loss cause        init_match      TUNABLE_PARAMS         L1~L6 직교 분할
    hp tracking       dead_code       auto-discovery         manifest.json

         │                 │                 │                 │
         └─────────────────┴─────────┬───────┴─────────────────┘
                                     ▼
                         ┌──────────────────────┐
                         │   중심 루프 (Core)    │
                         │  1. 최적화 (샘플링)   │
                         │  2. Full 풀 검증     │
                         │  3. 진단 (analyze)   │
                         │  4. 단일 Phase 보강   │
                         │  5. 재최적화         │
                         └──────────┬───────────┘
                     ┌──────────────▼──────────────┐
                     │   되먹임 매트릭스 (Section 5)│
                     │   증상 → 진단 → 대상 Phase   │
                     └─────────────────────────────┘
```

### 1.1 파이프라인 데이터 흐름

1. **BT 생성**: `adaptive_optimizer.py`가 104차원 파라미터 벡터 → YAML BT로 디코딩
2. **매치 실행**: `src/match/runner.py` (`BehaviorTreeMatch`) — 결정론적 시드 매치
3. **평가**: `evaluate.py` — W/D/L + Wilson CI + loss cause 자동 분류
4. **최적화 피드백**: 평가 score를 CMA-ES에 전달 → 분포 업데이트
5. **검증 (수렴 후)**: `validate_on_full_pool` — 695 × N 라운드, 병렬 워커
6. **진단**: per-layer, per-opponent 분석 → 약점 패턴 식별
7. **되먹임**: 어느 Phase를 보강할지 결정 → 다음 사이클

---

## 2. Phase별 상세

### Phase 1: 측정 기반 (Measurement Infrastructure)

**목표**: 모든 판단이 노이즈가 아니라 통계에 기반하도록 만든다.

#### 1a. `tools/evaluate.py` — 통합 평가 함수

```python
evaluate(agent, opponents, rounds=50, max_steps=1500) -> dict {
    "win_rate": float,
    "ci_95": (lo, hi),                # Wilson score interval
    "per_opponent": {name: {W, D, L, win_rate, ci_95, avg_hp_diff}},
    "loss_causes": {hard_deck, hp_diff, timeout, draw},
    "matches": [...]
}
```

**Wilson Score Interval 공식** (소표본에서 정규근사보다 안정):
$$
\text{CI}_{95\%} = \frac{p + \frac{z^2}{2n} \pm z\sqrt{\frac{p(1-p) + \frac{z^2}{4n}}{n}}}{1 + \frac{z^2}{n}}, \quad z=1.96
$$

**왜 Wilson?** 정규근사 $\hat p \pm z\sqrt{p(1-p)/n}$는 $p$가 0 또는 1에 가까울 때 CI가 범위 밖으로 나가며, $n$이 작을 때 심하게 왜곡된다. Wilson은 boundary behavior가 올바르다.

#### 1b. `tools/test_suite.py` — 구조적 자동 검증

5개 정적 검사:

| 테스트 | 검증 대상 | 실패 시 영향 |
|---|---|---|
| `name_collision` | 커스텀 노드명이 pyd 빌트인과 충돌 | pyd가 우선해서 커스텀 로직이 silently 무시됨 |
| `yaml_init_match` | YAML `params` 키 ↔ `__init__` 파라미터 일치 | `unexpected keyword argument` 런타임 에러 |
| `init_imports` | YAML 참조 노드가 `nodes/__init__.py`에서 import | 로더가 못 찾아서 빌트인 fallback |
| `dead_code` | import되었으나 YAML에서 미사용 | 탐색 공간 오염 |
| `tree_structure` | 루트 Selector + 첫 branch HardDeck | Hard Deck 패배 위험 |

**실증:** BUG-4 (IsCircularOrbit 이름 충돌)를 `name_collision`이 자동 탐지 → 수동 디버깅 없이 즉시 발견.

### Phase 2: 표현력 & 버그 수정 (Representation & Correctness)

**목표**: 탐색 공간의 BT 표현이 모두 *실제로* 작동하도록 한다. 잘못된 BT를 최적화하는 것은 무의미하다.

#### 수정된 버그

| # | 위치 | 증상 | 원인 | 해결 |
|---|---|---|---|---|
| BUG-4 | `custom_conditions.py` | IsCircularOrbit이 무시됨 | pyd 빌트인과 이름 충돌 | `CustomOrbitDetector`로 개명 |
| BUG-5 | `src/match/runner.py` | EIM이 항상 DEFENSIVE 분류 | `tracker1.update(obs2)` — 상대 self-obs 입력 | `tracker1.update(obs1)` — 본인 obs로 상대 의도 추론 |
| DRIFT | `src/match/runner.py` | 10R 재현성 없음 (38→80% 변동) | mid-match `update_online()` 드리프트 | 매치 중 온라인 업데이트 비활성화 |
| DEAD | `custom_*.py` | 8개 클래스 import만, 사용 X | 이전 리팩토링 잔존물 | 삭제 (371줄 → 131줄) |

#### Observation 단위 규약

내부 관측은 0~1로 정규화되어 있어 커스텀 노드에서 반드시 변환해야 함:

| 키 | 범위 | 변환 |
|---|---|---|
| `ata_deg`, `aa_deg`, `hca_deg` | 0~1 | `×180 → 도` |
| `tau_deg`, `relative_bearing_deg` | -1~1 | `×180 → 도` |
| `distance_ft`, `closure_rate_kts`, `ego_altitude_ft` | raw | 변환 불필요 |

**이 규약을 지키지 않으면 모든 조건식이 잘못 평가됨** — BUG-4와 동등 수준의 silent failure.

### Phase 3: 탐색 공간 & 최적화 (Search & Optimization)

**목표**: 표현력 있는 노드와 CMA-ES로 전체 영역을 실질적으로 탐색한다.

#### 3a. 커스텀 BFM 노드 (35개)

각 노드는 `TUNABLE_PARAMS` 딕셔너리를 갖는다:

```python
class SmartLeadPursuit(BaseAction):
    TUNABLE_PARAMS = {
        "heading_gain":  {"type": "cont", "range": (0.3, 2.0), "default": 1.0},
        "vel_far":       {"type": "disc", "choices": [2, 3, 4], "default": 4},
        "vel_close":     {"type": "disc", "choices": [1, 2, 3, 4], "default": 3},
        ...
    }
```

**자동 발견(auto-discovery)**: `adaptive_optimizer.py`의 `_discover_tunable_classes()`가 `examples/adaptive_eagle/nodes/custom_*.py`를 스캔하여 `TUNABLE_PARAMS`가 있는 클래스를 자동 등록. 새 노드를 추가하면 optimizer가 자동으로 인식한다.

#### 3b. BFM 분류 (Shaw's Fighter Combat)

| 카테고리 | 노드 | 이론적 역할 |
|---|---|---|
| OBFM (Offensive) | SmartLeadPursuit, SmartPurePursuit, SmartLagPursuit, SmartGunAttack, SnapshotAttack | 공격 기동: lead angle 예측, WEZ 진입 |
| DBFM (Defensive) | SmartBreakTurn, SmartDefensiveSpiral, ExtensionBreak, Jink, GunsDefense, LastDitch | 방어: last ditch, gun defense, energy recovery |
| HABFM (Head-on/Neutral) | SmartOneCircle, SmartTwoCircle, FlatScissors, RollingScissors | 선회전: lift vector match, turn circle 경쟁 |
| Energy | SmartHighYoYo, SmartLowYoYo, SmartClimbingTurn, VerticalFight | Ps (Specific Power) 관리 |
| Disengagement | HeadOnBreak, UnloadedExtension, Chandelle | 이탈 및 재접근 |

#### 3c. CMA-ES 탐색 공간 (104차원)

**구성**:
- **Action slots** (9차원, discrete): 9개 tactical slot 각각에 할당할 액션 선택
  - `gun_action`, `pursuit_action`, `defense_action`, `orbit_action`, `energy_action`, `neutral_action`, `default_action`, `underfire_action`, `overshoot_action`
- **Enable flags** (7차원, binary): 각 branch 활성화 여부
  - `enable_gun`, `enable_defense`, `enable_orbit`, `enable_energy`, `enable_neutral`, `enable_overshoot`, `enable_underfire`, `enable_eim`
- **Tunable continuous params**: 커스텀 노드의 `TUNABLE_PARAMS` 연속값
- **Tunable discrete params**: 동일 - 선택형

이 104차원 벡터는 `vector_to_params()`로 디코딩되어 `generate_bt_yaml()`이 완전한 BT YAML을 조립한다.

**CMA-ES 선택 이유**:
- Derivative-free (평가 함수가 non-differentiable — 매치 시뮬레이션)
- Non-convex에 강함 (covariance adaptation으로 ill-conditioning 대응)
- Discrete + continuous mixed 지원 (반올림 후 mapping)
- 병렬 평가 친화적 (generation당 population을 병렬 처리)

#### 3d. 평가 전략 (두 단계 분리)

**왜 분리하는가**: 695 opp × 50R = 34,750 매치 per fitness는 불가능.

| 단계 | 풀 | 라운드 | 매치 수 | 시간 (4 worker) | 용도 |
|---|---|---|---|---|---|
| **최적화 루프** | Layer-stratified 40 | 1 | 40 | ~175s/eval | CMA-ES fitness |
| **최종 검증** | 전체 695 | 20~50 | 13,900~34,750 | ~5~12h | Universal claim 통계 |

**Stratified sampling**: `_stratified_sample_opponents(k=40, seed=0)`는 각 layer에서 균등하게 샘플링하여 편향을 방지한다. CMA-ES는 이 샘플 위에서 수렴하며, 샘플이 충분히 대표적이면 전체 풀에서도 최적에 가깝다.

### Phase 4: 상대 풀 & 적응성 (Opponent Pool & Adaptation)

**목표**: 전술 공간 전체가 실제로 탐색되도록 체계적 상대 풀을 구축한다. 단순히 개수를 늘리는 것이 아니라 **직교 커버리지**가 핵심.

#### 4a. 직교 축 (Orthogonal Tactical Axes)

| 축 | 값 | 근거 |
|---|---|---|
| **Phase Focus** | OBFM / DBFM / HABFM / MIXED | Shaw의 BFM 3대 분류 |
| **Range Preference** | GUN(<914ft) / CLOSE(<3000) / MID(<6000) / LONG(>6000) | WEZ 경계 + 추적 전환점 |
| **Energy Discipline** | PRESERVE / TRADE / IGNORE | E-M 이론 |
| **Aggression** | PASSIVE / BALANCED / AGGRESSIVE | 평균 속도·선회율 차이 |
| **Primary Action** | ~30 builtin actions | Action Space 전수 |
| **Altitude Bias** | HIGH / LEVEL / LOW | 수직 기동 편향 |

#### 4b. Layer 구조 (695 BT)

| Layer | 목적 | 구성 | 개수 |
|---|---|---|---|
| **L1** | Pure single-action | 27 actions × 3 속도 프리셋 | 81 |
| **L2** | Condition-gated 2-branch | 10 cond × 8 action × 3 fallback | 240 |
| **L3** | Phase-decomposed | 5 off × 4 def × 6 neu (122 실제 생성) | 120 |
| **L4** | LHS threshold sweep | 5 params × 80 샘플 (action cycle) | 80 |
| **L5** | 4-axis orthogonal | 4 phase × 4 range × 3 energy × 3 agg | 144 |
| **L6** | Counter-strategies | 수동 설계 (WEZ denial, hit-run, …) | 30 |
| **합계** | — | — | **695** |

#### 4c. Latin Hypercube Sampling (L4 설계 이유)

5개 연속 파라미터(gun_dist, gun_ata, close_dist, hard_deck, recover_alt)를 Grid로 스윕하면 $5^5 = 3125$개가 필요하지만, LHS는 80개로 동등한 *marginal* 커버리지를 달성한다. 각 차원의 구간을 $n$개로 나누고 모든 구간에 정확히 1개 샘플이 들어가도록 배치하면, 어떤 1차원 투영도 uniform에 가까워진다. 이는 광역 sensitivity scan 에 적합하다.

#### 4d. 통계적 규모

$$
\text{Wilson CI margin at } p = 0.5: \quad \pm 1.96 \sqrt{\frac{0.25}{n}}
$$

| $n$ (매치 수) | Margin |
|---|---|
| 6,950 (10R × 695) | ±1.18% |
| 13,900 (20R × 695) | ±0.83% |
| 34,750 (50R × 695) | ±0.53% |
| Per-opp @ 50R | ±13% |
| Per-opp @ 10R | ±30% (의미 없음) |

**결론**: Universal WR은 10R로 충분, per-opponent 진단은 50R 이상 필요.

---

## 3. 현재 상태 (2026-04-10)

### 3.1 버전 비교

| 항목 | v5.1 (이전) | **v6.0 (현재)** |
|---|---|---|
| 상대 풀 크기 | 6 | **695** |
| 탐색 공간 차원 | ~15 | **104** |
| 커스텀 노드 수 | 7 | **35** |
| CMA-ES budget | 100 | **400** |
| 최적화 stratified sample | — | **40 (layer balanced)** |
| Wilson CI @ 최종 검증 | 6R × 6opp ±15% | **50R × 695 ±0.53%** |

### 3.2 v6.0 CMA-ES 결과 (완료)

| Metric | 값 |
|---|---|
| Budget | 400 evals |
| Elapsed | 440.5분 (~7.3h, 4 worker) |
| Best score | **295.36** (gen 38, eval 304) |
| Best W/D/L (40 sample) | **28 / 11 / 1** |
| Best WR | **70.0%** |
| 무패율 | **97.5%** |
| Best YAML | [examples/adaptive_eagle/_best_pool_v1.yaml](examples/adaptive_eagle/_best_pool_v1.yaml) |

**Best 구조 선택 (CMA-ES)**:
- `pursuit_action`: SmartPurePursuit
- `gun_action`: SmartGunAttack
- `default_action`: SmartLeadPursuit
- `enable_gun`: ✅, `enable_eim`: ✅
- `enable_defense/neutral/orbit/overshoot/underfire`: ❌
- **해석**: 단순한 공격 중심 BT가 직교 풀에서 가장 강함. Defense/Neutral branch는 오히려 결정 noise로 작용하여 disable이 선택됨.

### 3.3 v6.0 Full Pool Validation (진행 중)

| Metric | 값 |
|---|---|
| 시작 | 2026-04-10 |
| 파라미터 | 695 opp × 50R = **34,750 매치**, 4 workers |
| ETA | **~13h** |
| 현재 진행 | ~1,400 / 34,750 (4%) |
| 중간 W/D/L | 600 / 729 / 71 (초반 편향, imap_unordered 순서 때문) |
| 관찰 | L=71이 200매치 동안 고정 → 패배가 **1~2개 상대에 집중**됨을 시사 |

완료 시 `logs/full_pool_validation.json`에 `per_opponent` 통계와 함께 저장. 이로부터 약점 BT를 자동 식별 가능.

---

## 4. 되먹임 루프 (Feedback Loop) — 결과 분석 시 적용

### 4.1 진단 → Phase 매핑 매트릭스

| 증상 | Root Cause | 되먹임 대상 |
|---|---|---|
| 분산이 큼 (CI 넓음, run-to-run 불일치) | 측정 신뢰성 부족 | **Phase 1** (측정) |
| 새 best가 이전 best보다 regression | Fitness metric 불일치, 시드 편향 | **Phase 1** (측정) |
| 특정 layer/opponent에 일관되게 패배 | 노드/조건 부족 (표현력 한계) | **Phase 2,3** (노드 정의) |
| EIM ON이 OFF보다 약함 | EIM 입력/라벨 오류 | **Phase 2** (BUG) |
| 모든 layer에서 50% 근처 saturation | 탐색 공간 자체가 빈약 | **Phase 3** (노드 확장) |
| CMA-ES 조기 수렴, 다양성 부족 | 차원 과다 / step-size 작음 | **Phase 3** (optimizer) |
| 개별 opp은 좋은데 평균 낮음 | 풀이 너무 발산 (outlier) | **Phase 4** (풀 재설계) |
| L6 counter에 약함 | 메타 게임 미반영 | **Phase 4** (적응성) |

### 4.2 Phase별 보강 플레이북

#### → Phase 1 보강
- 같은 BT를 $k$회 평가하여 분산 측정. 표준편차가 ±5%p 이상이면 측정이 부정확.
- **결정론적 시드 매트릭스** 도입 (round당 고정 seed).
- `evaluate.py`에 `--seed-grid` 옵션 추가.
- HP 차이 단일 metric이 아니라 *time-to-engagement*, *energy retention*, *first-shot advantage* 등 **다중 metric**으로 fitness 다각화 → 단일 metric overfit 방지.

#### → Phase 2 보강
- Best YAML을 실제 매치에서 trace → 각 노드 발동률 카운트.
- 발동률 0인 노드가 많다면 조건이 잘못 설계된 것 (관측 unit 변환 BUG 의심).
- **EIM 라벨 정확도**를 직접 측정 (예측 vs ground truth intent).
- BT 노드 trace logger 추가 (Phase 1 infra와 연결).

#### → Phase 3 보강
- "약점 layer" 분석 → 그 layer의 적이 쓰는 액션을 카운터하는 노드가 존재하는지 확인.
- 없다면 **신규 BFM 노드 추가** (예: high-G barrel for hard-evader, lag pursuit with energy bleed).
- `TUNABLE_PARAMS` range 재검토 (range가 너무 좁으면 전체영역 탐색 실패).
- **Action slot 확장** (현재 9개 → phase별 sub-slot 도입).

#### → Phase 4 보강
- **Layer별 fitness 균등화**: 현재는 평균 fitness로, outlier layer가 dominate. **per-layer min을 fitness에 반영**(worst-case optimization)하면 약한 layer 개선에 강한 압력.
- **CMA-ES seed 다중화**: 현재 1 seed → 3 seeds × 부분 budget, best ensemble.
- **Curriculum learning**: 쉬운 layer(L1,L2)부터 시작 → 점진적으로 hard layer(L6)에 가중치 이전.
- **Self-play**: 이전 세대의 best를 풀에 추가 → 자기 약점 자동 노출.
- **Adversarial pool generation**: 현재 best가 잘 못 이기는 패턴을 자동 검출 → 그 패턴을 강화한 신규 상대 자동 생성 (적대적 풀 확장).

### 4.3 사이클 운영 원칙

**한 사이클 당 하나의 Phase만 변경.** 동시에 여러 Phase를 변경하면 어떤 변경이 효과를 냈는지 분리 불가 (ablation 불능).

### 4.4 기록 인프라 (사이클을 가능하게 하는 것)

매 사이클 다음을 저장:

```
logs/cycle_N/
├── best.yaml              # 이 사이클의 best BT
├── validation.json        # 695 풀 검증 결과 (per_layer, per_opponent)
├── diagnosis.md           # 어떤 Phase 보강을 결정했는지 + 근거
├── changeset.md           # 무엇을 바꿨는지 (단일 Phase)
└── diff_vs_prev.md        # 이전 사이클 대비 per-layer WR 변화
```

이 인프라가 있어야 "경험적 학습"이 아니라 **체계적 개선**이 된다.

---

## 5. 검증 기준 (진화)

| 지표 | v4.6 | v5.1 | **v6.0 (현재)** | 최종 목표 |
|---|---|---|---|---|
| vs legacy 6 opp 평균 | 미측정 | 미측정 | **75%** (이전 측정) | 80%+ |
| Stratified 40 샘플 승률 | — | — | **70%** | 75%+ |
| **Full 695 풀 승률 (10R+)** | — | — | **진행 중** | 65%+ |
| 최악 layer WR | — | — | 진행 중 | 50%+ |
| 측정 CI 폭 | ±15% | ±10% | **±0.53%** | ±1% |
| test_suite | 없음 | 5/5 | **5/5** | 5/5 |

---

## 6. 파일 구조 (v6.0)

```
ai-combat-sdk/
├── tools/
│   ├── evaluate.py                    # Phase 1a: 통합 평가 + Wilson CI
│   ├── test_suite.py                  # Phase 1b: 5개 자동 검증
│   ├── adaptive_optimizer.py          # Phase 3: CMA-ES 104-dim + auto-discovery
│   ├── generate_opponent_pool.py      # Phase 4: 695 직교 풀 생성기
│   └── expand_archetypes.py           # (legacy) 168 EIM 학습용
│
├── examples/
│   ├── adaptive_eagle/
│   │   ├── adaptive_eagle.yaml        # v5.1 수동 버전
│   │   ├── _best_pool_v1.yaml         # v6.0 CMA-ES best (2026-04-10)
│   │   └── nodes/
│   │       ├── __init__.py            # 35 클래스 re-export
│   │       ├── custom_actions.py      # 22 action 노드 (TUNABLE_PARAMS)
│   │       └── custom_conditions.py   # 12 condition 노드 + EIM
│   │
│   └── opponent_pool/                 # 695 BT + manifest.json
│       ├── L1_pure_*.yaml             # 81
│       ├── L2_*.yaml                  # 240
│       ├── L3_phase_*.yaml            # 120
│       ├── L4_lhs_*.yaml              # 80
│       ├── L5_*.yaml                  # 144
│       ├── L6_*.yaml                  # 30
│       └── manifest.json              # layer, category, params 메타
│
├── src/
│   └── match/
│       ├── runner.py                  # BUG-5 수정 + 드리프트 비활성화
│       └── runner_core.py
│
├── logs/
│   ├── best_adaptive_20260410_002309.yaml  # CMA-ES raw output
│   ├── full_pool_validation.json      # Full pool 검증 결과
│   └── cycle_*/                       # (향후) 사이클별 기록
│
└── ADAPTIVE_BT_PLAN.md                # 본 문서 (v3.0)
```

---

## 7. 커스텀 노드 작성 규칙 (불변)

| # | 항목 | 확인 방법 |
|---|---|---|
| 1 | 이름 충돌 없는가 | `python tools/test_suite.py <agent>` |
| 2 | 각도 ×180 변환했는가 | `ata_deg` 등은 0~1 정규화됨 |
| 3 | YAML params ↔ `__init__` 일치 | `test_suite yaml_init_match` |
| 4 | `__init__.py`에 import | `test_suite init_imports` |
| 5 | `TUNABLE_PARAMS` 정의 | auto-discovery 대상이 되려면 필수 |
| 6 | heading은 빌트인 우선 | SmartLeadPursuit 실패 교훈: 커스텀 heading < 빌트인 PN |

---

## 8. 제어 루프 요약 (참조)

```
관측 (0.2초/tick) → BT 결정 (3-tuple) → JSBSim 물리 (12 substep @ 60Hz)
                                          ↓
액션: [alt_idx(0-4), hdg_idx(0-8), vel_idx(0-4)] = 225 조합
                                          ↓
제약: 22.5° 조향 단위, 0.2초 반응 지연, 적 기동 미예측
```

**핵심 한계**: 접근(closing)은 쉬우나 WEZ 유지(staying)가 어려움. → WEZ 내 정밀 추적 (SmartGunAttack PD 제어)이 가장 가치 있는 커스텀화.

**WEZ 조건** (검증된 값):
- Distance: 152~914 ft
- ATA: < 12°
- Base DPS: 25

**Hard Deck**: 1000 ft (305 m) 이하 즉시 패배.

---

## 9. 인프라 요구사항

- **Python 3.14** 필수 (upstream v0.5.5.9 pyd가 cp314)
- `PYTHONIOENCODING=utf-8` (Windows cp949 대응)
- `cma` 패키지 (`pip install cma`)
- upstream remote: `https://github.com/rokafa-daslab/ai-combat-sdk`

---

## 부록 A: 버전 이력

| 버전 | 주요 변경 | 주요 측정 | 교훈 |
|---|---|---|---|
| v3.x | 순수 기하학 BT | eagle1 ~50% | EIM 없어도 50% 가능 |
| v4.0-v4.3 | EIM 연결 시도 | 불안정 | 통합 테스트 없이 연결하면 버그 |
| v4.4 | RLInspiredAttack | **0%** | 좌우 반전 → 회귀 테스트 필요 |
| v4.5 | LeadPursuit 복귀 | 57% | 단순한 것이 안정적 |
| v4.6 | EIM NEUTRAL_CIRCLE | 38-80% | 온라인 드리프트 불안정 |
| v5.0 | BUG-4,5 수정 | 50% | 측정 기반 검증의 힘 |
| v5.0-smart | SmartLeadPursuit | 30% | heading은 빌트인이 우수 |
| v5.1 | 빌트인 LP + SmartGunAttack | 60% | heading 빌트인 + WEZ PD 커스텀 |
| **v6.0** | **전체 풀 + CMA-ES 104-dim + 35 커스텀 노드** | **stratified 70%** | **직교 풀 설계 + auto-discovery** |

## 부록 B: 핵심 수식 모음

**Wilson Score Interval (95%)**:
$$
\text{lo, hi} = \frac{p + \frac{z^2}{2n} \pm z\sqrt{\frac{p(1-p) + \frac{z^2}{4n}}{n}}}{1 + \frac{z^2}{n}}
$$

**Fitness score** (CMA-ES 평가):
$$
\text{score} = \sum_{\text{opp}} \begin{cases} W_{\text{base}} + \alpha \cdot \Delta \text{hp} & \text{if win} \\ D_{\text{base}} + \alpha \cdot \Delta \text{hp} & \text{if draw} \\ L_{\text{base}} + \alpha \cdot \Delta \text{hp} & \text{if loss} \end{cases}
$$
여기서 $W_{\text{base}}=10, D_{\text{base}}=1, L_{\text{base}}=-5, \alpha=2.0$.

**CI margin at $p=0.5$** (regression test 시 요구 정확도 계산):
$$
\text{margin} \approx \frac{z}{2\sqrt{n}} = \frac{0.98}{\sqrt{n}}
$$
예: $\pm 1\%$ 목표 $\Rightarrow n \geq 9604$ 매치.

## 부록 C: 용어집

- **BFM** (Basic Fighter Maneuvers): 기본 공중전 기동
- **OBFM / DBFM / HABFM**: Offensive / Defensive / Head-on BFM
- **WEZ** (Weapon Engagement Zone): 유효 사격 영역 (거리 152~914ft, ATA<12°)
- **ATA** (Antenna Train Angle): 내 기수 기준 적까지의 각도 (lead 예측용)
- **AA** (Aspect Angle): 적 꼬리 기준 나의 각도 (adbantage 판단)
- **AO** (Angle Off): 적의 heading과 나의 line-of-sight 사이 각
- **TA** (Track Angle): 적이 나를 보는 각도
- **HCA** (Heading Crossing Angle): 양 기체 heading의 교차각 (1-circle vs 2-circle 판단)
- **Ps** (Specific Power): 단위 중량당 에너지 변화율
- **E-M** (Energy-Maneuverability): Boyd의 이론, turn rate vs G-load vs 에너지 관계
- **EIM** (Enemy Intent Model): 상대 전술 의도 예측 (ProtoNet GRU+Attention)
- **Hard Deck**: 즉시 패배 고도 (1000 ft)
- **1-circle / 2-circle fight**: 선회전의 두 주요 패턴 (same turn direction vs opposite)
