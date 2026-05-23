# Differentiable Scoring Behavior Tree (DSBT)
## — F-16 1v1 도그파이트 의사결정 방법론

> **본 문서의 위치**: BT 분기점을 수학적 함수화하여 "연속값이 흐르는 오토마타(continuous-valued automaton)"로 재구성하는 설계의 핵심 아이디어, 수학적 기반, 철학, 방법론적 한계, 그리고 보강 방안을 정리한다. 본 접근은 형식 검증(model checking), 하이브리드 시스템 이론, 최적제어/강화학습이 같은 수학적 객체에서 만나는 교차점에 위치한다.

---

## 0. Executive Summary

도그파이트 BT의 분기점을 **수학적 score function**으로 대체하면, 결과적으로 다음 동치들이 동시에 성립한다:

1. **Discrete predicate guard → smooth control function**으로의 변환 — guard 조건이 더 이상 indicator가 아니라 실수값 control signal이 됨
2. **Hybrid automaton의 미분가능화**(Differentiable Hybrid Automaton)
3. **Signal Temporal Logic(STL)의 quantitative semantics**와 algebra-isomorphic
4. **Entropy-regularized policy**(max-entropy RL)와 변분적 동치
5. **Trajectory-space scoring**과의 자연 결합 — 각 leaf score = horizon $H$ 동안의 expected payoff
6. **Game-theoretic Logit/Quantal Response Equilibrium**의 자연스러운 instantiation

**한 줄 요약**: *"의사결정을 논리 추론에서 부드러운 목적함수의 최적화로 옮기는 패러다임 전환."*

---

## 1. 배경 — 문제 설정

### 1.1 도그파이트 미분게임 (Differential Game)

- **시나리오**: F-16 vs F-16 1v1, 초기 mutual beam (ATA=AA=90°, HCA=180°), 동일 envelope (대칭)
- **상태**: $\mathbf{z} = (\mathbf{x}_B, \mathbf{x}_R) \in \mathbb{R}^{14}$ (3-DOF point-mass) 또는 $\mathbb{R}^{24}$ (6-DOF rigid body)
- **동역학**: 각 기체 $i$ 에 대해
  $$\dot{\mathbf{x}}_i = f(\mathbf{x}_i, \mathbf{u}_i),\quad \mathbf{u}_i = (T_i, \alpha_i, \mu_i)$$
- **페이오프** (Zero-sum):
  $$J[\mathbf{u}_B, \mathbf{u}_R] = \int_0^{T_f \wedge \tau} [r_B(\mathbf{z}) - r_R(\mathbf{z})]\,dt + \Phi(\mathbf{z}(T_f))$$
  WEZ 진입 시 $r = 25 \cdot w_{ATA}(\text{ATA}) \cdot w_{dist}(d)$ HP/s.

### 1.2 시뮬레이션 stack (갱신된 tick)

| 층 | 주기 | 비고 |
|---|---|---|
| sim (JSBSim 6-DOF) | 60 Hz (16.7 ms) | truth model |
| env.step | 20 Hz (50 ms) | observation refresh |
| BT decision | 10 Hz (100 ms) | tactical layer |
| condition subtick | 20 Hz (50 ms) | blackboard 갱신 |

핵심 관찰: **BT 결정 주기(100 ms)가 F-16 자세 동역학 시간상수(roll ~300 ms, short-period ~300 ms)보다 짧다.** 따라서 instant attitude 가정이 깨지고, 3-DOF는 분석용으로만, 실행은 3.5-DOF (bank를 상태로) 또는 4-DOF 권장.

### 1.3 표준 BT의 한계 — Threshold-based Chattering

```python
if ATA < 90: OFFENSIVE
elif AA < 60: DEFENSIVE
else: NEUTRAL
```

**문제 진단**:
- ATA = 89.5° ↔ 90.5° 사이를 측정 노이즈가 진동시키면 100 ms마다 phase flip
- 본질: piecewise constant policy $\pi : \mathcal{Z} \to A$는 **discontinuous map**
- Caratheodory 조건 위배 → ODE solution의 uniqueness 잃음
- Filippov sliding mode → **Zeno 현상**(유한 시간 무한 스위칭) 가능

수학적으로: BT는 hybrid automaton $\mathcal{H} = (Q, \mathcal{Z}, \text{Inv}, \mathcal{E}, \text{Reset}, f_q)$ 이며, guard $g_i(\mathbf{z}) > \theta_i$ 가 단순 indicator라 well-posedness가 깨진다.

---

## 2. 핵심 통찰 — 연속값 오토마타로서의 BT

### 2.1 패러다임 전환

| 표준 BT | DSBT |
|---|---|
| Discrete guard $g(\mathbf{z}) > \theta \in \{T, F\}$ | Smooth score $S_a(\mathbf{z}) \in \mathbb{R}$ |
| Selector → first success | Selector → $\max_i S_i$ (smoothed) |
| 출력: action $a \in A$ | 출력: distribution $\mu \in \Delta(A)$ |
| Reactive (threshold trigger) | Anticipatory (rollout-based score) |
| Threshold = constant 값 | "Threshold" = control function modulating action |
| Verification: model checking | Verification: quantitative robustness |

> **핵심 관찰**: guard 조건문이 제어 함수가 되면, BT는 더 이상 단순 *model checker* 가 아니라 *continuous controller* 가 된다. 검증과 합성이 같은 수학적 객체(robustness function)에서 만난다.

### 2.2 Signal Temporal Logic (STL) 연결 — 가장 깊은 동치

STL의 quantitative semantics는 BT operator algebra와 **isomorphic**:

| BT operator | STL operator | Quantitative semantics |
|---|---|---|
| Leaf 조건 $p$ | atomic predicate $p$ | $\rho(p, \mathbf{z}, t) = f_p(\mathbf{z}(t))$ |
| Selector | $\varphi_1 \lor \varphi_2 \lor \ldots$ | $\max_i \rho(\varphi_i, \mathbf{z}, t)$ |
| Sequence | $\varphi_1 \land \varphi_2 \land \ldots$ | $\min_i \rho(\varphi_i, \mathbf{z}, t)$ |
| Decorator (negate) | $\neg \varphi$ | $-\rho(\varphi, \mathbf{z}, t)$ |
| Temporal "until" | $\Box_{[0,H]} \varphi$ | $\min_{\tau \in [t, t+H]} \rho(\varphi, \mathbf{z}, \tau)$ |
| Temporal "eventually" | $\Diamond_{[0,H]} \varphi$ | $\max_{\tau \in [t, t+H]} \rho(\varphi, \mathbf{z}, \tau)$ |

→ **DSBT = Smooth STL-controlled hybrid system.**

Smooth STL은 min/max를 logsumexp로 대체:
$$\widetilde{\min}_\beta(x_1, \ldots, x_n) = -\frac{1}{\beta}\log\sum_i e^{-\beta x_i}$$
$$\widetilde{\max}_\beta(x_1, \ldots, x_n) = \frac{1}{\beta}\log\sum_i e^{\beta x_i}$$

이게 BT의 미분가능화와 정확히 같은 연산.

**문헌적 근거**:
- Donzé & Maler (2010) "Robust Satisfaction of Temporal Logic over Real-Valued Signals"
- Pant, Abbas, Mangharam (2017) "Smooth Operator: Control using the Smooth Robustness of Temporal Logic"
- Mehdipour et al. (2019) "Specifying and Synthesizing Hybrid Controllers via Smooth Boolean Composition"

### 2.3 미분가능 모델 체킹 — 검증과 합성의 이중성

- **전통 model checking**: "주어진 시스템이 spec을 만족하는가?" → 출력 $\{T, F\}$
- **Quantitative model checking**: robustness degree $\rho \in \mathbb{R}$ — 얼마나 robust하게 만족하는가
- **Inversion → Control synthesis**: $\max_{\mathbf{u}} \rho(\varphi, \mathbf{z}^{\mathbf{u}})$ — robustness를 최대화하는 제어 합성

> **DSBT는 검증/합성 이중성의 명시적 instantiation**: spec = WEZ dwell + survival, $\rho$ = score, control = primitive selection.

### 2.4 Entropy-regularized policy 동치

$$\pi(a|\mathbf{z}) = \frac{e^{\beta S_a(\mathbf{z})}}{\sum_b e^{\beta S_b(\mathbf{z})}}$$

는 변분문제
$$\pi^* = \arg\max_{\mu \in \Delta(A)} \mathbb{E}_{a \sim \mu}[S_a(\mathbf{z})] - \frac{1}{\beta}\mathcal{H}(\mu)$$
의 해. $\beta \to \infty$: hard argmax, $\beta \to 0$: uniform, 적절한 $\beta$: smooth + well-posed.

이는 **maximum-entropy RL** (Ziebart 2010, Soft Actor-Critic, Levine 2018)과 동치이며, 동시에 게임이론의 **Quantal Response Equilibrium**(McKelvey & Palfrey 1995)의 형태를 띤다. → Fictitious play, replicator dynamics로 수렴성 분석 가능.

---

## 3. 수학적 정형화

### 3.1 상태와 동역학 (3.5-DOF 권장)

$$\mathbf{x}_i = (x, y, h, V, \psi, \gamma, \mu)_i^\top \in \mathbb{R}^7$$

$$
\begin{aligned}
\dot{x} &= V\cos\gamma\cos\psi,\quad \dot{y} = V\cos\gamma\sin\psi,\quad \dot{h} = V\sin\gamma \\
\dot{V} &= (T-D)/m - g\sin\gamma \\
\dot{\gamma} &= [L\cos\mu - mg\cos\gamma]/(mV) \\
\dot{\psi} &= L\sin\mu/(mV\cos\gamma) \\
\dot{\mu} &= p,\quad |p| \leq p_{\max}(\alpha, V)\quad \text{(4-DOF에서만)}
\end{aligned}
$$

제약: $n_z \leq 9$ G, $V \in [160, 480]$ kts, $C_L \leq C_{L,\max}$, $h \geq h_{\text{deck}}$.

### 3.2 Score Function 빌딩블록

각 leaf $a$의 score:
$$S_a(\mathbf{z}) = \sum_k w_k^{(a)} \phi_k(\mathbf{z})$$

**기본 basis $\phi_k$**:

| Basis | 형태 | 용도 |
|---|---|---|
| Sigmoid | $\sigma\!\left(\dfrac{g(\mathbf{z}) - \theta}{w}\right)$ | soft threshold |
| Gaussian/RBF | $\exp\!\left(-\dfrac{(g(\mathbf{z}) - \mu)^2}{2w^2}\right)$ | sweet-spot (예: $d=1750$ ft) |
| Monotone polynomial | $\sum c_k g^k$, $c_k \geq 0$ | 단조 부드러움 |
| ReLU·MLP | $\max(0, Wg + b)$ + linear | universal approximator |

**설계 원칙**:
1. **단조성**: 더 유리한 상태 → 높은 $S$
2. **Lipschitz 유계**: $\|S(\mathbf{z}_1) - S(\mathbf{z}_2)\| \leq L\|\mathbf{z}_1 - \mathbf{z}_2\|$
3. **Compositionality**: sub-BT의 score를 윗단에서 그대로 합성

### 3.3 Trajectory-space scoring (anticipatory)

Leaf score를 **expected horizon payoff**로 정의:
$$S_a(\mathbf{z}_t) = \mathbb{E}_{\tau_a, \pi_R}\!\left[\int_t^{t+H} r(\mathbf{z}(s))\,ds + \gamma V(\mathbf{z}(t+H))\right]$$

- $\tau_a$: primitive $a$의 trajectory distribution (dynamics noise 포함)
- $\pi_R$: 적 정책 belief (GRU intent estimator로 추정)
- $V$: terminal value (NN learned, 또는 HJI distillation)

이 형태에서 score 자체가 **MPC objective**와 동치. BT는 primitive-level의 sampling-based MPC controller가 된다.

### 3.4 BT operator algebra (smoothed)

```
Leaf:       S = S_a(z)
Selector:   S = LogSumExp_β(S_1, ..., S_n)
Sequence:   S = -LogSumExp_β(-S_1, ..., -S_n)
Parallel:   S = Σ w_i S_i  
Decorator:  S → -S (negate), S → σ(S) (until-success) 등
```

최종 정책:
$$\pi(a|\mathbf{z}) = \text{softmax}_\beta(S_1(\mathbf{z}), \ldots, S_{|A|}(\mathbf{z}))$$

### 3.5 게임이론적 목적함수

대칭 envelope이지만 정보 비대칭 + 적 정책 belief 활용:
$$\pi_B^* = \arg\max_{\pi_B} \mathbb{E}_{\pi_R \sim p(\pi_R | \text{obs})}\!\left[\mathbb{E}[J(\pi_B, \pi_R)]\right]$$

→ **Bayesian best-response with belief over opponent**. 이게 DSBT의 게임이론적 정체성.

---

## 4. 세 관점의 통합

### 4.1 수학자 관점 — Variational well-posedness

- $\arg\max$ → entropy-regularized $\arg\max_{\mu \in \Delta(A)}$로 변환
- 변분문제로 well-posed, viscosity solution 존재
- Caratheodory 조건 회복 → ODE uniqueness 보장, Zeno 회피
- Lyapunov 분석 가능 (score function이 $\mathcal{C}^1$이라면)

### 4.2 수학적 모델링 관점 — Compositional score algebra

- BT operator → smooth score operator로 lift
- min/max → logsumexp로 smooth, $\beta$로 hard-soft 조절
- 합성성 보존 → learning theory 적용 가능 (예: PAC bound)
- STL과의 isomorphism → 형식 검증 도구 재사용 가능

### 4.3 비행제어 수치해석 관점 — Chattering 방지 실용 layer

수학적 regularization 위에 실용 layer 추가:

| 도구 | 목적 | 우리 권장값 (10 Hz BT) |
|---|---|---|
| **Hysteresis** | 진입/이탈 임계 분리 | 폭 5–10° (ATA 기준) |
| **Dwell-time** | 모드 변경 후 최소 유지 | $\tau_d \geq 300$ ms (자세 시간상수) |
| **LPF on score** | raw score 노이즈 흡수 | $\tau_f$ 100–200 ms |
| **Boundary layer (사격)** | $\text{sat}(\sigma/\epsilon)$ | $\epsilon \approx 1$–$2°$ |
| **Softmax $\beta$** | hard-soft 균형 | 5–20 |
| **Numerical guard** | softmax overflow 방지 | max-subtraction trick |

---

## 5. 철학과 방법론

### 5.1 패러다임 전환의 본질

| 측면 | 전통 BT | DSBT |
|---|---|---|
| 의사결정의 본질 | 논리 추론 | 목적함수 최적화 |
| 상태 분류 | 이산 phase 분할 | 연속 membership |
| 결정 시점 | event-triggered (threshold) | continuous (smooth blending) |
| 검증 방식 | discrete model checking | quantitative robustness |
| 학습 방식 | rule tuning (수동) | gradient-based (자동) |
| 게임이론 위치 | pure strategy | mixed strategy (logit response) |
| 적 모델 통합 | 어려움 (별도 모듈) | 자연 (rollout에 통합) |

### 5.2 설계 원칙 (헌장)

1. **모든 분기점은 함수**: predicate가 아니라 $\mathbb{R}$-valued score
2. **모든 score는 합성 가능**: smooth operator algebra (logsumexp)
3. **모든 score는 의미 있음**: 단조성 + 해석가능한 BFM 변수의 함수
4. **모든 결정은 anticipatory**: rollout-based, reactive 금지
5. **모든 전환은 부드러움**: hysteresis + dwell + LPF 3중 보호
6. **모든 weight는 학습 가능**: gradient + self-play
7. **모든 결정은 게임이론적**: 적 모델 belief 위에서 best-response

### 5.3 방법론의 교차점적 본질

DSBT는 세 분야의 **수학적 교집합**:
- **Hybrid systems theory**: smooth automaton, regularized switching
- **Formal methods**: quantitative STL, control synthesis from spec
- **Optimal control / RL**: entropy-regularized policy, trajectory scoring

이 셋이 같은 수학적 객체(**미분가능 합성 score functional**)에서 만난다는 것이 본 접근의 핵심 발견.

---

## 6. 방법론적 한계

### 6.1 이론적 한계

**(a) 대칭성 trap의 불완전 회피**
F-16 vs F-16 + symmetric initial condition에서는 mixed Nash가 일반적으로 자명(양측 동일 정책 → game value 0). DSBT 자체로는 대칭을 깨지 못한다. 진정한 비대칭은 다음 중 하나가 있어야:
- Information asymmetry (관측·반응 지연 차이)
- 적의 비최적 정책 exploitation
- 초기 perturbation
- Belief의 정확도 우위

**(b) Score function의 local optima**
Smooth approximation은 다항식+softmax 합성으로 non-convex. Gradient descent는 local minimum에 수렴 가능. Random restart, CMA-ES, evolutionary search 보완 필요.

**(c) Regularization parameter의 정당화 부재**
$\beta, \epsilon, \tau_d$ 의 최적값은 이론적으로 noise-to-signal에 의존하나, 실용적으론 heuristic. Calibration 절차가 정형화되어 있지 않음.

**(d) Smooth approximation의 부정확성**
logsumexp는 max의 over-approximation. $\beta$가 작으면 multiple maximizers가 결합되어 "compromise action"이 됨 — 결정적이어야 할 상황에서 indecisive해질 위험.

**(e) Lyapunov 안정성 증명의 어려움**
DSBT closed-loop의 stability proof가 자명하지 않음. score function이 sliding mode를 만들지 않음을 보이려면 별도 분석 필요.

### 6.2 실용적 한계

**(f) Rollout 비용**
Trajectory-space scoring은 매 BT tick(100 ms)마다 $N \times H$ rollout 필요. 6-DOF JSBSim은 sequential, GPU 병렬 불가. **Surrogate dynamics model 필수** — 정확도-속도 trade-off가 본질적 제약.

**(g) Reality gap (sim-to-sim-to-real)**
Surrogate dynamics ↔ JSBSim ↔ 실제 F-16 사이의 3중 gap. Surrogate에서 잘 작동하는 score가 JSBSim에서 같은 값을 주리란 보장 없음.

**(h) 형식 검증의 어려움**
Discrete BT는 finite-state model checking으로 검증 가능. DSBT는 continuous state space에서 reachability 검증이 본질적으로 더 어려움 — PDE 풀이 수준의 비용.

**(i) 해석가능성 저하**
모든 분기가 smooth blending이면 "왜 이 결정을 했는가" 답이 "score 차이가 0.07이라서" 수준이 됨. 운영자의 후행 분석, 사고 조사, 신뢰성 검증에 불리. 특히 군사 응용에선 *explainability*가 중요.

**(j) 학습 안정성 (Self-play)**
Self-play에서 mode collapse, oscillation, non-stationarity 문제. 단순 self-play는 발산 가능. League training, fictitious play, PSRO 같은 안정화 절차 필요.

**(k) 적 모델 의존성**
Trajectory rollout 시 적 정책 $\pi_R$ 가정 필요. GRU intent estimator의 정확도가 전체 성능 상한을 결정. Belief 갱신이 느리면 stale information으로 결정.

**(l) Envelope 위반 위험**
Smooth score는 envelope 한계(9G, $V_{\min}/V_{\max}$, hard deck)를 *soft penalty*로만 표현 가능. Hard constraint 보장이 score만으론 불가능 → 별도 safety filter 필요.

---

## 7. 보강 방안

### 7.1 이론적 보강

| 한계 | 보강 방안 |
|---|---|
| (a) 대칭 trap | 의도적 information asymmetry: 우리만 GRU intent estimator 활용, Bayesian belief 우위 확보; vertical maneuver primitive로 horizontal-only 정책 break |
| (b) Local optima | CMA-ES + gradient hybrid; 다중 random init; HJI oracle distillation으로 prior 제공 |
| (c) $\beta, \epsilon$ 정당화 | Cross-validation, Bayesian optimization on validation matches; sensitivity analysis |
| (d) Smooth over-approx | Adaptive $\beta$ scheduling — uncertain 영역엔 작은 $\beta$, 결정적 영역엔 큰 $\beta$ |
| (e) Stability proof | Lyapunov function $V(\mathbf{z})$ 구성, dwell-time + score monotonicity로 stability 증명; Filippov 해의 uniqueness 검증 |

### 7.2 실용적 보강

| 한계 | 보강 방안 |
|---|---|
| (f) Rollout 비용 | (i) Neural surrogate dynamics 학습 (JSBSim trajectory로 fit); (ii) GPU batch rollout; (iii) horizon-adaptive (긴급 상황엔 short horizon, 여유엔 long) |
| (g) Reality gap | Domain randomization (dynamics param 흔들기); JSBSim self-play로 surrogate 보정; sim-to-sim transfer 정량 평가 |
| (h) 형식 검증 | **Statistical Model Checking (SMC)**: STL spec 작성 후 Monte Carlo로 만족 확률 추정; **Reachability via level set**: 8-D 축소 상태에서 numerical HJI |
| (i) 해석가능성 | Score decomposition 시각화 (각 basis의 기여도); counterfactual analysis ("만약 ATA가 5° 작았다면?"); attention map |
| (j) 학습 안정성 | **PSRO** (Policy Space Response Oracle); AlphaStar-style league with main agent + exploiters; regularized self-play with KL penalty |
| (k) 적 모델 의존 | Bayesian belief over $\pi_R$ (Dirichlet 또는 GP); ensemble of intent estimators with diversity reward; worst-case robust DSBT |
| (l) Envelope 위반 | **Control Barrier Function (CBF)** 또는 **ECBF** safety filter: DSBT 출력 위에 safety layer로 hard constraint 강제 |

### 7.3 검증 layer (필수 추가 레이어)

DSBT를 단독으로 deploy하지 말고, 다음 두 layer로 감싸야 한다:

```
┌─────────────────────────────────────────┐
│  Safety Layer (ECBF)                    │ ← Hard envelope 보장
│  · 9G, V_min/max, hard deck             │
│  · Score 출력을 safe set으로 projection  │
├─────────────────────────────────────────┤
│  Verification Layer (SMC + STL)         │ ← 정량적 spec 검증
│  · "WEZ dwell ≥ 4s within 60s"         │
│  · Monte Carlo로 위반 확률 추정          │
├─────────────────────────────────────────┤
│  DSBT Core                              │ ← 본 문서의 주제
│  · Smooth score + trajectory rollout    │
│  · Softmax response + hysteresis        │
└─────────────────────────────────────────┘
```

- **SMC** (Statistical Model Checking): STL spec과 simulator로 위반 확률 통계적 추정 (Younes & Simmons)
- **Falsification testing**: adversarial scenario 자동 생성으로 DSBT 약점 탐색 (Annpureddy et al. S-TaLiRo)
- **Runtime monitor**: STL robustness $\rho$를 실시간 모니터링, 임계 이하 시 fallback 정책 전환

---

## 8. 구현 로드맵

### Phase 1 — Score function 라이브러리 (1–2주)
- BFM 변수(ATA, AA, HCA, d, $P_s$, $H_e$, alt_gap) → basis function 매핑 정의
- 각 phase별 score 정의 (MERGE / OFFENSIVE / DEFENSIVE / NEUTRAL / WEZ_EXPLOIT / RECOVERY)
- Unit test: 합성 BT score의 미분가능성, Lipschitz, 단조성 검증
- **Deliverable**: `score_lib.py`, score function 시각화 notebook

### Phase 2 — Surrogate dynamics (2–3주)
- 6-DOF 경량 모델 (point-mass + bank dynamics + actuator lag)
- Optional: JSBSim trajectory에 fitted neural ODE
- GPU batch rollout 가능 형태 (PyTorch/JAX)
- **Deliverable**: `surrogate_dynamics.py`, 정확도 평가 (JSBSim 대비 trajectory error)

### Phase 3 — Trajectory rollout scoring (1–2주)
- Primitive library 정의 (20–40개 BFM primitive: 1-circle×{L,R}×{flat, high-yo, low-yo}×duration×pursuit_type)
- MPPI-style scoring (10 Hz, $N \in [64, 256]$, $H \in [2, 3]$s)
- Softmax response with hysteresis/dwell/LPF
- **Deliverable**: `dsbt_runtime.py`, 단일 episode end-to-end 작동

### Phase 4 — Self-play 학습 (4–6주)
- PSRO 또는 fictitious play 알고리즘
- Score weight $w^{(a)}_k$ 학습
- 적 정책 분포 ensemble 구축
- **Deliverable**: 학습된 DSBT, vs baseline (rule-based BT) 승률

### Phase 5 — Verification + Sim-to-sim (3–4주)
- STL spec 작성, SMC 실행
- JSBSim 평가 vs surrogate score 일치도
- Adversarial falsification (DSBT의 weak corner 탐색)
- ECBF safety filter 추가
- **Deliverable**: verification report, falsification scenarios

### Phase 6 — Counter Table / Adaptive (4–6주)
- 적 정책 cluster 식별 (GRU/ProtoNet)
- Cluster별 best-response DSBT
- Online belief update with cluster posterior
- **Deliverable**: Adaptive DSBT, intent estimator integration

---

## 9. 핵심 수식 요약

**상태 (3.5-DOF, $i \in \{B, R\}$)**:
$$\mathbf{x}_i = (x, y, h, V, \psi, \gamma, \mu)_i^\top, \quad \mathbf{z} = (\mathbf{x}_B, \mathbf{x}_R) \in \mathbb{R}^{14}$$

**Leaf score (trajectory-space, anticipatory)**:
$$\boxed{S_a(\mathbf{z}_t) = \mathbb{E}_{\tau_a, \pi_R}\!\left[\int_t^{t+H} r(\mathbf{z}(s))\,ds + \gamma V(\mathbf{z}(t+H))\right]}$$

**Smooth composition (BT operator algebra)**:
$$S_{\text{Sel}}(\mathbf{z}) = \frac{1}{\beta}\log\sum_i e^{\beta S_{c_i}(\mathbf{z})},\quad S_{\text{Seq}}(\mathbf{z}) = -\frac{1}{\beta}\log\sum_i e^{-\beta S_{c_i}(\mathbf{z})}$$

**Policy (softmax with dwell-time)**:
$$\pi(a|\mathbf{z}, a_{\text{prev}}) = \begin{cases}
\delta_{a_{\text{prev}}} & \text{if } t - t_{\text{switch}} < \tau_d \\
\text{softmax}_\beta(S(\mathbf{z}) + h \cdot \mathbf{e}_{a_{\text{prev}}}) & \text{otherwise}
\end{cases}$$
($h$: hysteresis bonus for previous action)

**Variational characterization**:
$$\pi^*(\cdot|\mathbf{z}) = \arg\max_{\mu \in \Delta(A)} \left\{\mathbb{E}_{a \sim \mu}[S_a(\mathbf{z})] - \frac{1}{\beta}\mathcal{H}(\mu)\right\}$$

**Game-theoretic objective (Bayesian best-response)**:
$$\pi_B^* = \arg\max_{\pi_B} \mathbb{E}_{\pi_R \sim p(\pi_R | \text{obs})}\!\left[\mathbb{E}[J(\pi_B, \pi_R)]\right]$$

**STL spec example (운영 가능한 형태)**:
$$\varphi = \Diamond_{[0, 60]}\, \Box_{[0, 4]} (\text{ATA} < 12° \land 500 < d < 3000)$$
"60초 안에 어딘가에서 4초 연속으로 WEZ를 유지한다."

---

## 10. 용어집

| 약어 | Full Name | 의미 |
|---|---|---|
| DSBT | Differentiable Scoring Behavior Tree | 본 문서의 제안 구조 |
| STL | Signal Temporal Logic | 시간 논리, quantitative semantics 갖춤 |
| SMC | Statistical Model Checking | Monte Carlo 기반 spec 검증 |
| QRE | Quantal Response Equilibrium | softmax response의 게임이론 평형 |
| PSRO | Policy Space Response Oracle | self-play 학습 알고리즘 |
| ECBF | Exponential Control Barrier Function | 안전성 강제 제어 |
| MPPI | Model Predictive Path Integral | sampling-based MPC |
| HJI | Hamilton-Jacobi-Isaacs | 미분게임의 가치함수 PDE |
| PMP | Pontryagin's Maximum Principle | 최적제어 1차 필요조건 |
| BFM | Basic Fighter Maneuvers | 전투기 기본 기동 |
| WEZ | Weapon Engagement Zone | 사격 가능 영역 |
| ATA | Antenna Train Angle | 내 nose↔LOS 각 (0°=정조준) |
| AA | Aspect Angle | 적 nose↔LOS 각 (0°=stern, 180°=head-on) |
| HCA | Heading Crossing Angle | 두 heading 사이 각 |
| Ps | Specific Excess Power | $\dot{H}_e = V(T-D)/(mg)$ |
| He | Specific Energy | $h + V^2/(2g)$ |

---

## 11. 참고 문헌 (핵심)

### Hybrid Systems & Formal Methods
1. Henzinger, T. (1996). "The Theory of Hybrid Automata." *IEEE LICS*.
2. Donzé, A., Maler, O. (2010). "Robust Satisfaction of Temporal Logic over Real-Valued Signals." *FORMATS*.
3. Pant, Y., Abbas, H., Mangharam, R. (2017). "Smooth Operator: Control using the Smooth Robustness of Temporal Logic." *CCTA*.
4. Mehdipour, N., Vasile, C., Belta, C. (2019). "Specifying and Synthesizing Hybrid Controllers via Smooth Boolean Composition." *HSCC*.

### Behavior Trees
5. Colledanchise, M., Ögren, P. (2018). *Behavior Trees in Robotics and AI: An Introduction*. CRC Press.
6. Sprague, C., Ögren, P. (2018). "Adding Neural Network Controllers to Behavior Trees." *arXiv*.

### Optimal Control / RL
7. Ziebart, B. (2010). *Modeling Purposeful Adaptive Behavior with the Principle of Maximum Causal Entropy*. PhD thesis, CMU.
8. Levine, S. (2018). "Reinforcement Learning and Control as Probabilistic Inference." *arXiv 1805.00909*.
9. Williams, G., Drews, P., Goldfain, B., Rehg, J., Theodorou, E. (2017). "Information-theoretic MPC for model-based reinforcement learning." *ICRA*.

### Game Theory & Differential Games
10. Isaacs, R. (1965). *Differential Games*. Wiley.
11. McKelvey, R., Palfrey, T. (1995). "Quantal Response Equilibria for Normal Form Games." *Games and Economic Behavior*.
12. Mitchell, I., Bayen, A., Tomlin, C. (2005). "A time-dependent Hamilton-Jacobi formulation of reachable sets for continuous dynamic games." *IEEE TAC*.
13. Fridovich-Keil, D. et al. (2020). "Efficient iterative linear-quadratic approximations for nonlinear multi-player general-sum differential games." *ICRA*.
14. Lanctot, M. et al. (2017). "A Unified Game-Theoretic Approach to Multiagent Reinforcement Learning." *NeurIPS* (PSRO).

### Air Combat / BFM
15. Shaw, R. (1985). *Fighter Combat: Tactics and Maneuvering*. Naval Institute Press.
16. Burgin, G. H., Sidor, L. B. (1988). "Rule-based air combat simulation." *NASA CR-4160*.
17. Pope, A. P. et al. (2021). "Hierarchical Reinforcement Learning for Air-to-Air Combat." *ICUAS*.

### Verification / Safety
18. Younes, H., Simmons, R. (2002). "Probabilistic Verification of Discrete Event Systems Using Acceptance Sampling." *CAV*.
19. Ames, A. et al. (2019). "Control Barrier Functions: Theory and Applications." *ECC*.

---

## 12. 부록: 의사결정 흐름도 (개념)

```
       ┌────────────────────────────────────────────┐
       │ Observation (20 Hz)                        │
       │ z = (x_B, x_R) from JSBSim                 │
       └──────────────┬─────────────────────────────┘
                      │
       ┌──────────────▼─────────────────────────────┐
       │ Belief Update (GRU intent estimator)       │
       │ p(π_R | obs_history) ← Bayesian filter     │
       └──────────────┬─────────────────────────────┘
                      │
       ┌──────────────▼─────────────────────────────┐
       │ Trajectory Rollout (Surrogate, GPU batch)  │
       │ For each primitive a ∈ A:                  │
       │   τ_a ← surrogate_rollout(z, a, π_R, H)    │
       │   S_a ← E[∫r dt + γV(z_H)]                 │
       └──────────────┬─────────────────────────────┘
                      │
       ┌──────────────▼─────────────────────────────┐
       │ Smooth BT Composition                      │
       │ S_phase ← logsumexp_β(S_leaves)            │
       │ Hysteresis + dwell-time + LPF              │
       └──────────────┬─────────────────────────────┘
                      │
       ┌──────────────▼─────────────────────────────┐
       │ Softmax Policy                             │
       │ π(a|z) = softmax_β(S_a)                    │
       │ Sample or argmax                           │
       └──────────────┬─────────────────────────────┘
                      │
       ┌──────────────▼─────────────────────────────┐
       │ Safety Filter (ECBF)                       │
       │ Project to safe set if envelope violated   │
       └──────────────┬─────────────────────────────┘
                      │
       ┌──────────────▼─────────────────────────────┐
       │ Inner-loop MPC (20 Hz)                     │
       │ Realize primitive as control input         │
       │ u = (T, α, μ) → JSBSim                     │
       └────────────────────────────────────────────┘
```

---

## 13. 마치며 — 본 접근의 위치

DSBT는 새로운 알고리즘이 아니라, **기존 4개 분야가 같은 수학적 객체를 가리키고 있었음을 깨닫는 통합 프레임워크**다:

> *"BT의 분기점이 수학적 식이 되는 순간, 그것은 동시에 hybrid automaton의 smooth regularization이며, STL의 quantitative semantics이며, entropy-regularized policy이며, sampling-based MPC의 score function이다. 이 네 관점은 같은 수학을 다른 언어로 말한다."*

따라서 DSBT 구현자가 잡아야 할 핵심은:

1. **합성성**(compositionality)을 깨지 않는 score algebra
2. **anticipation**을 보장하는 trajectory rollout (reactive 금지)
3. **regularization**의 다층 보호 (수학적 + 수치적)
4. **검증·안전 layer**의 분리 — DSBT 단독 deploy 금지
5. **적 모델 belief**를 명시적으로 통합 (game-theoretic identity)

방법론적 한계는 분명히 존재하지만(특히 reality gap, verification, explainability), 각 한계에 대응되는 보강 도구가 기존 문헌에 이미 있다. 본 문서는 그 매핑을 명시화한다.

---

*문서 버전*: v1.0
*작성 맥락*: F-16 1v1 도그파이트 의사결정, JSBSim 6-DOF + 10 Hz BT, mutual beam initial condition
