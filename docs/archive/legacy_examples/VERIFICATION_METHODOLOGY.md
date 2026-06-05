# Verification Methodology — `sim_dogfight_verify.py` 학술화 로드맵

> **목적**: 현재 `sim_dogfight_verify.py`는 "canonical 변형 11개 × 적 정책 5개 =
> 55 케이스에서 91% WIN" 같은 **경험적 측정**을 한다. 이를 **formal verification
> 도구**로 격상시키는 학술 방법론을 매핑한다.
>
> **핵심 제약**: 모든 시나리오는 `scripts/run_match.py`의 실제 JSBSim 매치
> 초기 조건(canonical: ATA=90°, dist=3297.6ft, spd=386.8kts, alt=15000ft, HCA=180°,
> cl=0)과 일치해야 한다.
>
> **참조**: 현재 측정 상태는 [`CURRENT_STATE_AND_DESIGN.md`](./CURRENT_STATE_AND_DESIGN.md),
> 수학적 BFM 출전은 [`BFM_MATHEMATICAL_FOUNDATIONS.md`](./BFM_MATHEMATICAL_FOUNDATIONS.md).

---

## 0. 현 상태의 한계 — 무엇이 학술적으로 부족한가

| 항목 | 현재 | 학술적 기준 |
|------|------|-------------|
| 시나리오 생성 | 11개 hand-crafted | 체계적 / DSL 기반 / 분포 sampling |
| 커버리지 주장 | 없음 | 상태공간 커버리지, mission 커버리지 정량화 |
| 속성 (property) 표현 | 자연어("WIN") | 형식 명세 (e.g., STL, dL) |
| 반례 탐색 | 무작위 | 적대적/falsification 기반 |
| 신뢰도 | 점추정 91% | 통계적 신뢰구간, 또는 reachability proof |
| 적 모델 | 5개 휴리스틱 | 게임 이론 분포, 적대적 RL |
| 결과 검증 | 단일 측정 | 재현성, 다중 random seed |

**학술적으로 빈 곳**: 우리는 "F-16 vs F-16, BFM 정리 기반 τ 연속 제어, canonical
초기 조건"이라는 **specific verification problem**에 대해 어떤 formal claim도
하지 못한다. 91% WIN은 11+5+1500틱이라는 매우 좁은 표본에 대한 진술.

---

## 1. Verification Problem 형식화

`sim_dogfight_verify.py`가 진짜로 검증하고자 하는 것을 명세로 풀어 쓰면:

### 1.1 Property P1 — τ 함수 정확성
> "τ_corner(obs) > 0.5 ⟹ 코너 진입 명령이 우세 가중치를 받는다"
> "정리 5+6의 entry condition (HCA>120 AND V>V_corner) 만족 시 τ_corner > 0.5"

→ **단위 테스트**로 즉시 검증 가능. 현재 미구현.

### 1.2 Property P2 — Capture Set 도달성
> "canonical 초기 상태 x₀에서, 어떤 적 정책 π_e ∈ Π_admissible에 대해서도
> ∃ T < 300s, ∃ control u(·): x(T; x₀, u, π_e) ∈ WEZ_set"

→ **HJI reachability** 또는 **falsification**으로 형식 검증.

### 1.3 Property P3 — 견고성 (Robustness)
> "canonical 초기 + δ 섭동 시, |WIN_rate(x₀+δ) - WIN_rate(x₀)| ≤ ε"
> 즉 초기 조건 미세 변동에 결과가 크게 바뀌지 않음.

→ **민감도 분석** + **STL robustness semantics**.

### 1.4 Property P4 — 커버리지
> "검증된 시나리오 집합 S가 canonical-neighborhood N(x₀, r)을 ε-망(ε-net)으로 덮음"

→ **Scenic-style scenario DSL** + **coverage metric**.

---

## 2. 적용 가능한 학술 방법론

### 2.1 Hamilton-Jacobi-Isaacs (HJI) Reachability — Property P2

**이론적 배경**: Mitchell, Bayen, Tomlin (2005) "A Time-Dependent Hamilton-Jacobi
Formulation of Reachable Sets for Continuous Dynamic Games", *IEEE TAC*[^mitchell2005].
Bansal, Tomlin (2017) "Hamilton-Jacobi Reachability: Some Recent Theoretical
Advances and Applications in Unmanned Airspace Management" *Annual Reviews in
Control*[^bansal2017].

**우리 문제 매핑**:
```
state x = (P_us, V_us, P_them, V_them) ∈ R¹²
ego control u ∈ U_F16 (turn rate, gamma rate, throttle bounded)
adversary control v ∈ V_F16 (same bounds, hostile)
WEZ_set W = { x : ATA<12°, 500<dist<3000, closure>0 }

Capture(W) = { x : ∃u(·) ∀v(·), ∃t≤T, x(t) ∈ W }
            ↑ Hamilton-Jacobi-Isaacs PDE의 sub-zero level set
```

**구체 산출**: HJI value function V(x, t) 를 grid 또는 level-set method로 계산.
canonical x₀에 대해 V(x₀, T) < 0 이면 capture 가능 = 우리 우세 증명.

**도구**:
- helperOC (MATLAB, Stanford) — https://github.com/HJReachability/helperOC
- BEACLS (C++/CUDA, GPU) — https://github.com/HJReachability/beacls
- ToolboxLS (level-set, MATLAB)
- 12D state space는 grid 한계 → **decomposition**(축소표현) 필요. Bansal 2017
  Section 4 참조.

**비용**: ★★★★ (계산량 큼, 단 한 번 계산이면 수학적 증명 획득)

### 2.2 Signal Temporal Logic (STL) + Falsification — Property P1, P2, P3

**이론적 배경**: Maler, Nickovic (2004) "Monitoring Temporal Properties of
Continuous Signals", FORMATS[^maler2004]. Donzé (2010) "Breach, A Toolbox for
Verification and Parameter Synthesis of Hybrid Systems"[^donze2010].

**우리 문제 매핑** — BFM theorem entry condition을 STL formula로:
```
φ_corner_correct = G[0,300] (HCA>120 ∧ V>V_corner ∧ |turn_rate|>5
                              ⟹ τ_corner > 0.5)
                            (Globally over [0, 300s])

φ_capture = F[0,300] WEZ
            (Eventually within 300s, reach WEZ)

φ_robust = G[0,300] (¬enemy_WEZ)   ← 적이 우리 사격 못 함
```

**falsification** = 위 STL 공식을 위반시키는 입력(초기 조건 perturbation, 적
정책 parameter)을 자동 탐색. **robust semantics**[^fainekos2009]는 단순 true/false가
아닌 "얼마나 만족/위반했는가"의 양적 거리를 부여하여 gradient-guided 탐색 가능.

**도구**:
- **Breach** (MATLAB, Donzé) — https://github.com/decyphir/breach
- **S-TaLiRo / PSY-TaLiRo** (Python) — https://psy-taliro.readthedocs.io/
- **RTAMT** (Python, 가벼움) — https://github.com/nickovic/rtamt

**비용**: ★★ (Python 라이브러리 활용 가능, 즉시 적용 가능)

### 2.3 Scenic — 시나리오 DSL — Property P4

**이론적 배경**: Fremont, Dreossi, Ghosh, Yue, Sangiovanni-Vincentelli, Seshia
(2019) "Scenic: A Language for Scenario Specification and Scene Generation",
PLDI[^fremont2019]. UC Berkeley Learn-Verify Lab의 자동주행 검증 표준.

**우리 문제 매핑**: canonical 초기 조건 + 분포 declaration:
```scenic
# 우리 problem의 Scenic-like DSL
scenario CanonicalDogfight:
    setup:
        ego_pos = (0, 0, 15000)
        ego_hdg = 0
        ego_spd = Normal(386.8, 5.0)        # ±5kts 산포
        enemy_pos_relative = OrientedVector(
            ata = 90 + Uniform(-3, 3),       # ±3° 산포
            dist = Normal(3297.6, 30.0),     # ±30ft 산포
        )
        enemy_hdg = 180 + Uniform(-2, 2)     # HCA ≈ 180° ±2°
        enemy_policy = Discrete([
            (0.4, "offensive"),               # 가중 sampling
            (0.2, "defensive"),
            (0.2, "evading"),
            (0.1, "orbiting"),
            (0.1, "passive"),
        ])
        enemy_init_speed = Normal(386.8, 10.0)
    require:
        verify(ego, enemy)
```

→ Scenic이 **분포에서 시나리오를 sampling** 하고, 우리 검증 함수에 입력. 통계적
보장 (e.g., 95% 신뢰구간으로 1000개 시나리오에 대해 WIN > 88%).

**도구**:
- **Scenic** — https://scenic-lang.org, https://github.com/BerkeleyLearnVerify/Scenic
- 자동주행/CARLA용으로 만들어졌으나 도그파이트로 확장 가능 (custom simulator backend)

**비용**: ★★★ (DSL 통합 작업 필요, 그 후 sampling은 거의 무료)

### 2.4 Metamorphic Testing — Property P1

**이론적 배경**: Chen, Kuo, Liu, Poon, Towey, Tse, Zhou (2018) "Metamorphic
Testing: A Review of Challenges and Opportunities", *ACM Computing Surveys*[^chen2018].

**핵심 아이디어**: 명시적 oracle (정답 라벨) 없이도 **입력 변환 ↔ 출력 변환의
관계**를 검증. 우리 τ 함수에 즉시 적용 가능.

**우리 문제 매핑** — τ 함수의 metamorphic relations (MR):
```python
# MR1 — 단조성 (HCA 증가 → τ_corner 감소 안 함)
def test_tau_corner_monotone_hca():
    obs1 = make_obs(hca=130, V=387, turn_rate=15)
    obs2 = make_obs(hca=170, V=387, turn_rate=15)
    assert tau_corner(obs2) >= tau_corner(obs1)

# MR2 — 대칭성 (좌선회/우선회 부호 무관)
def test_tau_yoyo_symmetric_turn():
    obs_left  = make_obs(turn_rate=+15)
    obs_right = make_obs(turn_rate=-15)
    assert abs(tau_yoyo(obs_left) - tau_yoyo(obs_right)) < 1e-6

# MR3 — 경계값 (canonical at corner → τ_corner 정확히 0)
def test_tau_corner_at_threshold():
    obs = make_obs(hca=180, V=350, turn_rate=21)
    assert 0.4 < tau_corner(obs) < 0.6   # 경계 영역에서 ~0.5

# MR4 — 보존 (적 정책 변화는 τ 직접 영향 X — obs만 영향)
# ... 등
```

**도구**:
- **Hypothesis** (Python property-based) — https://hypothesis.readthedocs.io/
- 기본 pytest로도 충분

**비용**: ★ (가장 가볍게, 즉시 시작 가능)

### 2.5 SMT-based Scenario Synthesis — Property P3, 반례 탐색

**이론적 배경**: Gao, Avigad, Clarke (2013) "δ-Complete Decision Procedures for
Satisfiability over the Reals", IJCAR[^gao2013] — dReal SMT solver. nonlinear
ODE까지 다룰 수 있는 delta-decision SMT.

**우리 문제 매핑**:
```
∃ x_0 ∈ canonical_neighborhood(δ),
∃ enemy_policy_param p ∈ Param_space,
∃ control_param q ∈ Q,
∀ t ∈ [0, 300s]:
    dynamics(x_0, p, q, t) ⊨ ¬φ_capture
                              ↑ "WEZ에 도달 못함"

→ SMT solver가 만족하는 (x_0, p, q) 를 찾으면 그게 반례 시나리오.
   못 찾으면 (또는 unsat 증명) → φ_capture 만족 형식 증명.
```

**도구**:
- **dReal** — https://github.com/dreal/dreal4 (delta-SMT, ODE 지원)
- **Z3** — 단순 polynomial constraint 만 (ODE 불가)
- **CVC5** — 비선형 nlsat 일부 지원

**비용**: ★★★★★ (12D state + 적 정책 parameter → 큰 SMT, decomposition 필요)

### 2.6 Adaptive Stress Testing (AST) — 적대적 시나리오 발굴

**이론적 배경**: Lee, Mengshoel, Saksena, Gardner, Genin, Brush, Kochenderfer
(2018) "Adaptive Stress Testing: Finding Likely Failure Events with Reinforcement
Learning", *Journal of Artificial Intelligence Research*[^lee2020].

**핵심**: RL agent가 적 정책 파라미터 공간에서 **우리를 깨뜨리는** 적 정책을
탐색. 우리의 5개 hand-crafted 적 정책의 한계를 메움.

**우리 문제 매핑**:
```
RL state = (current scenario state, history)
RL action = enemy policy parameter perturbation
RL reward = -log P(우리가 WIN)   ← 우리를 깨면 RL이 reward 받음
```

→ 학습 후 RL이 발견한 "우리가 자주 지는 적 정책"을 baseline 시나리오로 추가.

**도구**:
- AST 프레임워크 — https://github.com/sisl/AdaptiveStressTesting (Julia)
- Python 포팅: stable-baselines3 + custom env
- **NVIDIA Isaac Lab**의 randomization API

**비용**: ★★★★ (학습 시간 + RL 인프라)

### 2.7 Statistical Model Checking — Property P4 정량화

**이론적 배경**: Younes, Simmons (2002) "Probabilistic Verification of Discrete
Event Systems Using Acceptance Sampling"[^younes2002]. Legay, Delahaye, Bensalem
(2010) "Statistical Model Checking: An Overview", RV[^legay2010].

**우리 문제 매핑**:
```
H_0: P(WIN | canonical) ≥ 0.90
H_1: P(WIN | canonical) < 0.90

→ Sequential probability ratio test (SPRT) — Wald 1945
→ 표본 N개 sampling 후 H_0 / H_1 결정 (α, β 오류율 제어)

현재 측정: 11 시나리오 = 너무 작음. SPRT는 동적으로 표본 늘리며 결정.
```

**도구**:
- **PRISM-games** — http://www.prismmodelchecker.org/games/
- **UPPAAL-SMC** — https://uppaal.org/
- 또는 직접 Python으로 SPRT 구현 (수십 줄)

**비용**: ★★ (표본 수 늘리는 비용 외 거의 없음)

---

## 3. Phased Adoption Roadmap

| Phase | 방법론 | 기간 | 산출 | 우선순위 |
|-------|--------|------|------|----------|
| A | 2.4 Metamorphic testing | 1주 | τ 함수 단위 테스트 (~30 MR) | 🔴 즉시 |
| B | 2.7 Statistical Model Checking | 1주 | WIN rate 95% CI 산출 | 🔴 즉시 |
| C | 2.2 STL + Falsification | 2-3주 | BFM theorem entry condition 형식 명세, 반례 탐색 | 🟠 |
| D | 2.3 Scenic 시나리오 DSL | 3-4주 | 시나리오 분포 sampling, 자동 covering | 🟠 |
| E | 2.6 Adaptive Stress Testing | 4-6주 | 적대적 적 정책 발굴 → 5개 → 50개 | 🟡 |
| F | 2.1 HJI Reachability | 6-8주 | canonical capture set의 형식 증명 | 🟡 |
| G | 2.5 SMT-based synthesis | 8-12주 | 반례 자동 발견 또는 unsat 증명 | 🟢 |

**Phase A+B 즉시 시작 가능** (Python pytest + scipy.stats만으로). 이걸로
"91% WIN ± 4% (95% CI, N=200)" 같은 정량적 신뢰 진술 가능.

---

## 4. canonical-anchored 시나리오 생성 — 제약 만족

> **사용자 제약**: 모든 시나리오는 `scripts/run_match.py`의 초기 조건과 일치해야 함.

### 4.1 Canonical 초기 조건 명세 (run_match.py 추적)

`scripts/run_match.py:227` → `config_name = f"1v1/NoWeapon/{scenario}"` →
`src/simulation/envs/JSBSim/configs/1v1/NoWeapon/{scenario}.yaml` 의 초기 조건.

기존 분석 (대화 기록):
```
ego:    pos=(0, 0, 15000ft), hdg=0°,   gamma=0°, spd=386.8kts
enemy:  pos=(3297.6, 0, 15000ft), hdg=180°, gamma=0°, spd=386.8kts
→ ATA=90°, AA=90°, HCA=180°, dist=3297.6ft, closure=0
```

### 4.2 Perturbation Operator P(x_0; δ)

검증 시나리오는 canonical x_0의 **bounded perturbation**으로만 생성:
```
P(x_0; δ) = {
    pos_ego:    x_0.pos_ego + δ_pos,    |δ_pos| ≤ 50ft     (편대 산포)
    spd_ego:    x_0.spd_ego + δ_spd,    |δ_spd| ≤ 5kts     (속도 산포)
    hdg_ego:    x_0.hdg_ego + δ_hdg,    |δ_hdg| ≤ 1°       (헤딩 산포)
    pos_enemy:  ... 같은 bounds
    enemy_policy: π ∈ {휴리스틱 5종} ∪ {RL 발견 정책}
}
```

→ 모든 verification 방법론은 **이 P(x_0; δ) 안에서만 sampling/탐색**. 비현실
시나리오 (canonical_close 2000ft, canonical_enm_fast 420kts) 는 분명히 P 밖
이므로 **검증 대상에서 제외** 또는 별도 sensitivity 분석.

### 4.3 현재 11 시나리오의 위치
| 시나리오 | P(x_0; δ) 안인가? |
|----------|-------------------|
| canonical | ✅ δ=0 (정확) |
| canonical_close (dist=2000) | ❌ δ_pos=1297ft >> 50ft |
| canonical_far (dist=7000) | ❌ δ_pos=3702ft >> 50ft |
| canonical_e_deficit (e_diff=-3000) | ❌ 명시 perturbation 외 |
| canonical_enm_fast (V=420kts) | ❌ δ_spd=33kts >> 5kts |
| canonical_alt_low/high | ❌ |

→ **현재 91% WIN의 진짜 의미**: "canonical 정확점 1개 + 비현실 변형 10개" 평균.
Statistical 의미를 가지려면 P(x_0; δ) 안에서 sampling 필요.

---

## 5. Novelty Positioning — 학술적 기여 가능 영역

본 작업이 기존 문헌 대비 어디서 novel 한가:

### 5.1 BFM theorem ↔ continuous control 의 formal correspondence
- BFM 교과서(Shaw, Boyd, Stillion)는 정성적 / 사례 기반.
- HJI 도그파이트 연구(Pachter, Yavin, Merz)는 단순 dynamics (homicidal chauffeur, two cars).
- 우리: **F-16 JSBSim envelope + 8개 BFM 정리의 τ-blended 합성**의 formal correspondence는 신규 영역으로 보임 [Medium confidence].

### 5.2 Canonical-anchored differential game verification
- 자동주행 SUMO/Scenic은 random initial state.
- 우리: **fixed canonical initial state + bounded perturbation**의 verification problem은 specific하게 정의되지 않은 영역 [Medium].

### 5.3 Black-box adversary refinement via SMC + AST
- 일반 differential game 문헌은 minimax adversary 가정.
- 우리: **adversary policy class를 RL로 확장**하여 sub-optimality 활용. 이 접근의 도그파이트 specific application은 신규 [Low].

### 5.4 BFM theorem-driven τ blending — vs end-to-end RL
- 자동주행/도그파이트 RL (Pope et al 2021 "Hierarchical Reinforcement Learning
  for Air-to-Air Combat"[^pope2021]) 은 black-box neural policy.
- 우리: **명시적 BFM theorem 기반 + obs-direct τ 함수**. interpretability + robustness 강점 [High].

---

## 6. 즉시 시작 가능한 작업 (Phase A+B)

### 6.1 신규 파일 (제안)
```
examples/adaptive_eagle_v11_code/
├── verification/
│   ├── test_tau_metamorphic.py   — Phase A: τ 함수 metamorphic relations
│   ├── statistical_mc.py          — Phase B: SPRT WIN rate CI
│   ├── canonical_perturbation.py — P(x_0; δ) 정의 + sampling
│   └── README.md                  — 검증 폴더 안내
```

### 6.2 Phase A 의사 코드 (2.4 Metamorphic testing)
```python
# examples/adaptive_eagle_v11_code/verification/test_tau_metamorphic.py
import pytest
from sim_dogfight_verify import tau_corner, tau_yoyo, tau_ldt

def make_obs(hca=180, V=387, turn_rate=21, ata=90, closure=0,
             alt_gap=0, distance=3297.6, rel_bearing=90, ...):
    return { "hca_deg": hca/180, "ego_vc_kts": V, "turn_rate_degs": turn_rate, ... }

# MR1 — τ_corner monotone in HCA
@pytest.mark.parametrize("hca_low, hca_high", [(100, 130), (130, 160), (160, 175)])
def test_tau_corner_hca_monotone(hca_low, hca_high):
    obs_low  = make_obs(hca=hca_low)
    obs_high = make_obs(hca=hca_high)
    assert tau_corner(obs_high, obs_low_prev) >= tau_corner(obs_low, obs_low_prev)

# ... ~30 MR
```

### 6.3 Phase B 의사 코드 (2.7 SMC)
```python
# examples/adaptive_eagle_v11_code/verification/statistical_mc.py
from scipy import stats
from sim_dogfight_verify import run_scenario, SCENARIOS

def sprt_test(p0=0.90, p1=0.85, alpha=0.05, beta=0.05, max_n=500):
    """Wald SPRT for WIN rate."""
    log_a = np.log(beta / (1 - alpha))
    log_b = np.log((1 - beta) / alpha)
    cum_log_lr = 0; n_win = 0; n = 0
    for trial in canonical_perturbation_sampler():
        result = run_scenario(trial, ...)
        x = 1 if result["outcome"] == "WIN" else 0
        n_win += x; n += 1
        cum_log_lr += x * np.log(p1/p0) + (1-x) * np.log((1-p1)/(1-p0))
        if cum_log_lr <= log_a:  return "ACCEPT_H0", n_win/n, n
        if cum_log_lr >= log_b:  return "REJECT_H0", n_win/n, n
        if n >= max_n: return "INCONCLUSIVE", n_win/n, n
```

---

## 7. References (open access 우선)

[^mitchell2005]: Ian M. Mitchell, Alexandre M. Bayen, Claire J. Tomlin, "A Time-Dependent Hamilton-Jacobi Formulation of Reachable Sets for Continuous Dynamic Games", *IEEE Transactions on Automatic Control*, 50(7), 2005. Open: Stanford CS preprint https://web.stanford.edu/class/ee291e/papers/Mitchell-IEEE05.pdf
[^bansal2017]: Somil Bansal, Mo Chen, Sylvia Herbert, Claire J. Tomlin, "Hamilton-Jacobi Reachability: A Brief Overview and Recent Advances", arXiv:1709.07523. Open: https://arxiv.org/abs/1709.07523
[^maler2004]: Oded Maler, Dejan Nickovic, "Monitoring Temporal Properties of Continuous Signals", FORMATS 2004. Open: VERIMAG technical report TR-2004-15
[^donze2010]: Alexandre Donzé, "Breach, A Toolbox for Verification and Parameter Synthesis of Hybrid Systems", CAV 2010. Tool: https://github.com/decyphir/breach
[^fainekos2009]: Georgios E. Fainekos, George J. Pappas, "Robustness of Temporal Logic Specifications for Continuous-Time Signals", *Theoretical Computer Science*, 410(42), 2009. Open: https://georgepappas.org/papers/RobustSTL_TCS.pdf
[^fremont2019]: Daniel J. Fremont, Tommaso Dreossi, Shromona Ghosh, Xiangyu Yue, Alberto L. Sangiovanni-Vincentelli, Sanjit A. Seshia, "Scenic: A Language for Scenario Specification and Scene Generation", PLDI 2019. Open: https://arxiv.org/abs/1809.09310
[^chen2018]: T. Y. Chen, F.-C. Kuo, H. Liu, P.-L. Poon, D. Towey, T. H. Tse, Z. Q. Zhou, "Metamorphic Testing: A Review of Challenges and Opportunities", *ACM Computing Surveys*, 51(1), 2018. Open: https://arxiv.org/abs/1707.05475
[^gao2013]: Sicun Gao, Jeremy Avigad, Edmund M. Clarke, "δ-Complete Decision Procedures for Satisfiability over the Reals", IJCAR 2013. Open: https://www.cs.cmu.edu/~sicung/papers/IJCAR13.pdf — Tool dReal: https://github.com/dreal/dreal4
[^lee2020]: Ritchie Lee, Ole J. Mengshoel, Anshu Saksena, Ryan W. Gardner, Daniel Genin, Joshua Silbermann, Michael Owen, Mykel J. Kochenderfer, "Adaptive Stress Testing: Finding Likely Failure Events with Reinforcement Learning", *JAIR*, 69, 2020. Open: https://arxiv.org/abs/2004.04293
[^younes2002]: Håkan L. S. Younes, Reid G. Simmons, "Probabilistic Verification of Discrete Event Systems Using Acceptance Sampling", CAV 2002. Open via Springer.
[^legay2010]: Axel Legay, Benoît Delahaye, Saddek Bensalem, "Statistical Model Checking: An Overview", Runtime Verification 2010. Open: https://hal.inria.fr/inria-00591593
[^pope2021]: Adrian P. Pope, Jaime S. Ide, Daria Mićović, Henry Diaz, David Rosenbluth, Lee Ritholtz, Jason C. Twedt, Tyler T. Walker, Kevin Alcedo, Daniel Javorsek, "Hierarchical Reinforcement Learning for Air-to-Air Combat", *ICUAS 2021*. Open: https://arxiv.org/abs/2105.00990

추가 참고 (BFM 영역):
- Pachter, Miloh, Eisenstadt (2019) "Differential Games — Lions, Two Decades Later", Springer.
- Stillion (2015) "Trends in Air-to-Air Combat: Implications for Future Air Superiority", CSBA report. Open: https://csbaonline.org/research/publications/trends-in-air-to-air-combat-implications-for-future-air-superiority

검증 도구 GitHub:
- helperOC (HJI MATLAB): https://github.com/HJReachability/helperOC
- Breach (STL falsification MATLAB): https://github.com/decyphir/breach
- PSY-TaLiRo (STL Python): https://github.com/cpslab-asu/PSY-TaLiRo
- Scenic: https://github.com/BerkeleyLearnVerify/Scenic
- dReal4: https://github.com/dreal/dreal4
- Hypothesis (property-based test Python): https://github.com/HypothesisWorks/hypothesis
- AST: https://github.com/sisl/AdaptiveStressTesting

---

## 8. 미해결 / 사용자 결정 필요

1. **Phase A+B로 즉시 시작할까, full roadmap 계획 후 시작할까?**
2. **검증 시나리오의 P(x_0; δ) δ bound** — 50ft / 5kts / 1° 제안값이 적절한가? JSBSim 실 매치 변동성 측정 필요할 수 있음.
3. **현재 91% WIN의 11 시나리오 중 10개가 P 바깥**임을 어떻게 처리할까?
   - 옵션 A: 폐기 (canonical 단일점에서 N=200 sampling으로 대체)
   - 옵션 B: P_extended (변형된 perturbation bound)로 별도 트랙 유지
   - 옵션 C: Sensitivity analysis 트랙으로 별도 명명
4. **Adopt할 도구**: MATLAB(Breach, helperOC) vs Python(PSY-TaLiRo, dReal Python wrapper)? 우리 코드베이스가 Python이므로 Python 우선 추천.
