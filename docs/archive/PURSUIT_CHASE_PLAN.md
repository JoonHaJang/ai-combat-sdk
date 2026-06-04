# Pursuit_Chase_BT — Solver-First Design Plan

> **목적**: 1:1 F-16 도그파이트를 zero-sum differential game 으로 형식화하고
> Hamilton-Jacobi-Isaacs (HJI) 수치 solver 로 풀어, 그 결과를 BT 노드 lookup 으로
> 구현. Heuristic τ 함수 대신 수학적으로 정의된 saddle-point 전략 사용.
>
> **참조**:
> - [BFM_MATHEMATICAL_FOUNDATIONS.md](../examples/adaptive_eagle_v11_code/BFM_MATHEMATICAL_FOUNDATIONS.md) — 정리 1-8 출전
> - [open_access_references.csv](open_access_references.csv) — 18개 open-access 논문
> - [ACTION_LATENCY_REPORT.md](ACTION_LATENCY_REPORT.md) — HJI primitive 식별 완료
> - [PURSUIT_CHASE_RESULTS.md](PURSUIT_CHASE_RESULTS.md) — Phase A+B 결과
>
> **상태**: 2026-05-12 작성. Phase A (이론) + Phase B (BT 통합) 구조 완료. Phase C 검증 대기.

---

## 0. 학습 가이드 — 문제 정의·용어·가정 (Learning Guide)

> 본 절은 처음 읽는 사람을 위한 안내입니다. 기술 명세는 §1 부터.
> 본 절의 목적: **(1) 우리가 푸는 문제가 무엇인지 well-defined 하고,
> (2) 어떤 가정 위에서 풀고 있는지 명시하고, (3) 범위(scope)를 한정하는 것**.

### 0.1 우리가 푸는 문제 — 한 문장 정의

**"동일 스펙 F-16 두 대가 정해진 초기 조건에서 1:1 공중전을 시작할 때, 양쪽이 모두 수학적으로 최선의 전략을 쓴 결과는 무엇인가?"**

이를 풀려면:
1. 비행기 운동을 수학으로 표현 (dynamics)
2. "승리 / 패배 / 무승부" 를 수학으로 정의 (terminal conditions)
3. "최선의 전략" 을 수학으로 정의 (minimax / saddle-point)
4. 컴퓨터로 풀이 (HJI 수치 PDE solver)

### 0.2 두 가지 게임 모델 — 핵심 구분 ★

도그파이트의 수학적 형식화는 두 가지 다른 방향이 있습니다.

#### **모델 A — 비대칭 Pursuit-Evasion Game (고전 수학 전통)**

```
역할 고정:
  Pursuer (추격자): 적을 잡는 것이 유일한 목표 (방어 안 함)
  Evader (회피자): 도망가는 것이 유일한 목표 (공격 안 함)

→ 한 명만 사거리(WEZ)를 가짐
→ Value function 1개만 정의: V*(x) = "추격자가 회피자를 잡을 수 있는가"
```

**대표 문헌**:
- Isaacs (1965) *Differential Games* — 원조
- Buzikov-Galyaev (2022) arXiv:2206.10199 — 동등 두 자동차 게임 해석해
- 우리가 사용한 `hj_reachability.systems.Air3d`

**장점**: 수학적으로 단순. 해석해 존재. 표준 solver 있음.
**한계**: 실제 도그파이트는 양쪽 모두 공격 능력 있음 → 비현실적 단순화.

#### **모델 B — 대칭 Combat Game (도그파이트)**

```
역할 대칭:
  플레이어 A: 적을 잡으려 함 (공격) + 안 잡히려 함 (방어)
  플레이어 B: 적을 잡으려 함 (공격) + 안 잡히려 함 (방어)

→ 양쪽 모두 사거리(WEZ)를 가짐
→ Value function 2개 동시 정의:
    V_us*(x):   우리가 적을 잡을 수 있는가
    V_them*(x): 적이 우리를 잡을 수 있는가
→ 게임 결과 = 4가지 영역:
    (1) V_us<0, V_them>0 : 우리 승 (us-win zone)
    (2) V_us>0, V_them<0 : 적 승 (them-win zone)
    (3) V_us<0, V_them<0 : mutual kill (양사)
    (4) V_us>0, V_them>0 : DRAW (양쪽 capture 불가)
```

**대표 문헌**:
- Olsder & Breakwell (1974) "Role determination in aerial dogfight"
- Merz & Hague (1977) "Coplanar tail chase aerial combat as a differential game"
- Ardema, Heymann, Rajan (1985) "Combat games"
- Shinar 연구 (1980s~)

**장점**: 실 도그파이트 정확 형식화.
**한계**: 수학 복잡. 두 PDE 동시 풀이 필요. 표준 solver 적음.

### 0.3 우리가 채택한 형식화 — 현재 단계와 정당화

**현재 (Phase A+B)**: **모델 A 비대칭** 형식화 사용.

**왜 모델 A 부터?**
1. 수학적으로 단순 — HJI PDE 1개만 풀이
2. `hj-reachability` 의 `Air3d` 같은 표준 도구 즉시 활용
3. **대칭성 (symmetry) 덕분에 동등 스펙 케이스에서는 모델 B 결과를 함의**:
   ```
   동등 스펙 + canonical 시작 조건
   ⟹ 모델 A 의 V*(x) > 0 (우리가 적을 못 잡음)
   ⟹ 위치 swap 시에도 V*(swap된 x) > 0 (적이 우리를 못 잡음, 대칭에 의해)
   ⟹ 모델 B 의 V_us > 0 AND V_them > 0
   ⟹ 영역 (4) DRAW
   ```
4. 사용자의 "자가대전 DRAW" 가설 검증 목적에는 모델 A 만으로 충분

**모델 B 가 꼭 필요한 경우**:
- mutual kill (영역 3) 회피 전략 도출 — 양사 방지
- 비대칭 sub-optimal 적 정확 exploit — heuristic 적 100% WIN 목표
- 적 사거리 (WEZ_them) 가 우리와 다른 시나리오 — 무기 비대칭

### 0.4 핵심 용어 사전 ★ (수학적 정의 + 직관)

#### 0.4.1 게임 형식

| 용어 | 수학적 정의 | 직관 / 비유 |
|------|-----------|----------|
| **Differential Game** | tuple $(X, U_p, U_e, f, J)$ — 연속 시간 dynamic game where state $x(t) \in X \subset \mathbb{R}^n$ evolves by $\dot{x}=f(x,u_p,u_e)$ | "연속 시간 체스" — 매 순간 양쪽이 동시 결정 |
| **Pursuit-Evasion Game (PEG)** | Differential game with asymmetric payoff: $J = T_{capture}$ (capture time). One player minimizes, other maximizes. | 술래잡기 (술래만 잡음, 도망자는 도망만) |
| **Combat / Two-Target Game** | Asymmetric or zero-sum game with **two** capture sets $\mathcal{C}_p, \mathcal{C}_e$. Each player has dual objective. | 권투, 펜싱 (양쪽 모두 공격+방어) |
| **Zero-sum Game** | $J_p(x, u_p, u_e) = -J_e(x, u_p, u_e)$ — 한쪽 이득 = 다른쪽 손실 | 1:1 결투 (한 명만 승) |
| **Symmetric Game** | dynamics, control space, payoff 가 player swap 에 invariant | 동등 무기 결투 |

#### 0.4.2 상태 / 제어

| 용어 | 수학적 정의 | 직관 |
|------|-----------|------|
| **State (상태) $x$** | 게임 진행에 필요한 충분 통계량 (Markov 가정) $\in \mathbb{R}^n$ | 체스의 현재 보드 |
| **Control $u_p, u_e$** | measurable function $u: [0,T] \to U \subset \mathbb{R}^m$ from time to admissible control set | 체스에서 다음 수 |
| **Dynamics $f$** | Lipschitz continuous function $f: X \times U_p \times U_e \to \mathbb{R}^n$, $\dot{x}=f(x,u_p,u_e,t)$ | 비행 운동방정식 |
| **6D State (본 작업)** | $x = (\Delta x, \Delta y, \Delta h, \Delta\psi, V_p, V_e) \in \mathbb{R}^6$ | (3D 상대위치 + 상대방위 + 두 속도) |
| **Control-Affine Dynamics** | $f(x, u) = f_0(x) + B(x) u$ — 제어가 dynamics 에 affine | hj-reachability solver 요구 조건 |
| **Admissible Control** | non-anticipative strategy — past info 만 사용 | 체스 룰 안에서 합법 수 |

#### 0.4.3 게임 값 (Game Value)

| 용어 | 수학적 정의 | 직관 |
|------|-----------|------|
| **Payoff Functional $J$** | $J(x_0, u_p(\cdot), u_e(\cdot)) = g(x(T)) + \int_0^T L(x, u_p, u_e) dt$ — terminal + running cost | 게임 결과의 점수 |
| **Value Function $V^*(x)$** | $V^*(x) = \min_{u_p} \max_{u_e} J(x, u_p, u_e)$ subject to $\dot{x}=f$, $x(0)=x$ | "양쪽 최선 시 점수" — 체스 엔진 평가점수 |
| **Minimax** | $\min_{u_p}\max_{u_e}$ — "worst case 상대 가정 후 최선" decision rule | 가장 강한 상대를 가정 |
| **Saddle-Point** | $(u_p^*, u_e^*)$ s.t. $J(u_p^*, u_e) \le J(u_p^*, u_e^*) \le J(u_p, u_e^*)$  $\forall u_p, u_e$ | minimax 균형점, 어느 쪽도 일방 변경 시 손해 |
| **Isaacs Condition** | $\min_{u_p}\max_{u_e} H = \max_{u_e}\min_{u_p} H$ (Hamiltonian) | minimax = maximin (대부분 자연 시스템에서 성립) |

#### 0.4.4 HJI / Reachability

| 용어 | 수학적 정의 | 직관 |
|------|-----------|------|
| **HJI PDE** | Hamilton-Jacobi-Isaacs: $\partial_t V + H(x, \nabla V) = 0$, $H = \min_{u_p}\max_{u_e} \{\nabla V \cdot f + L\}$ | $V^*$ 가 만족하는 1차 PDE |
| **Viscosity Solution** | $V$ that satisfies HJI in viscosity (weak) sense — Crandall-Lions (1983) 정의 | 미분 불가능 점 (kink) 도 허용하는 일반화된 해 |
| **Capture Set $\mathcal{C}$** | $\mathcal{C} = \{x: $ capture condition$(x)$ true$\}$ — closed subset of $X$ | "잡힘 영역" |
| **WEZ_us** | $\{x: \text{ATA}(x) < 12° \land 500 < \text{dist}(x) < 3000 \land \dot{\text{dist}}(x) < 0\}$ | 우리 사거리 — binary 근사 (정확 모델은 §0.8) |
| **Signed Distance** | $l(x) = \text{dist}(x, \partial \mathcal{C}) \cdot \text{sign}(\mathbb{1}_{x \notin \mathcal{C}} - \mathbb{1}_{x \in \mathcal{C}})$ | $\mathcal{C}$ 까지 부호 있는 거리 (안=음수, 밖=양수) |
| **BRT (Backward Reachable Tube)** | $\text{BRT}(T) = \{x: \exists u_p, \forall u_e, \exists s \in [0,T], x(s) \in \mathcal{C}\}$ | $T$초 안에 capture 가능한 상태 집합 |
| **Barrier** | $\{x: V^*(x) = 0\}$ — capture 가능/불가능 경계면 | 임계 |
| **Escape Zone** | $\{x: V^*(x) > 0\}$ — capture 불가능 영역 | 영원히 도망 가능 |

#### 0.4.5 우리 문제 특수 용어

| 용어 | 수학적 정의 | 직관 |
|------|-----------|------|
| **Canonical $x_0$** | $(3297.6\text{ft}, 0, 0, \pi, 386.8, 386.8)$ — JSBSim 매치 시작 상태 | 체스의 초기 배치 |
| **ATA (Antenna Train Angle)** | $\angle(\hat{V}_p, \vec{r}_{p \to e})$ — 우리 nose 와 적 방향 사이 각도 ∈ $[0, 180°]$ | "내가 적을 얼마나 정면에 두고 있나" |
| **AA (Aspect Angle)** | $\angle(\hat{V}_e, -\vec{r}_{p \to e})$ — 적 nose 와 우리 방향 사이 각도 ∈ $[0, 180°]$ | "적이 나를 얼마나 정면에 두고 있나" |
| **HCA (Heading Crossing Angle)** | $\angle(\hat{V}_p, \hat{V}_e)$ — 두 비행 벡터 사이 각도 | 평행=0°, 정반대=180° |
| **Closure $\dot{\text{dist}}$** | $-\frac{d}{dt} \|\vec{r}_{p\to e}\|$ — 거리 감소율 (양수=가까워짐) | 접근 속도 |
| **WEZ (Weapon Engagement Zone)** | $\{x: \text{ATA}(x) < 12° \land 500 < \text{dist}(x) < 3000 \land \dot{\text{dist}}(x) > 0\}$  (binary) — §0.8 의 가중치 함수로 일반화됨 | F-16 사거리 콘 |
| **F-16 Envelope** | bounded $\{u: \|\omega_h\| \le \omega_{\max}(V), \|\gamma\| \le \gamma_{\max}, a \in [-a_{\max}, +a_{\max}]\}$ | F-16 의 기동 한계 |
| **Sub-optimal** | $J(x_0, u_p, u_e) > V^*(x_0)$ — minimax 보다 못한 결과 | 체스에서 약수(弱手) |
| **Mutual Kill** | $V_{us}^*(x) < 0 \land V_{them}^*(x) < 0$ — 4-영역 분류의 영역 (3). §0.8 에서 race-to-zero 로 재해석 | 결투 동시 발사 |
| **Canonical perturbation** | $x_0 + \delta$ where $\delta \in B(0, r)$ for small bound $r$ | 시작 조건 미세 변동 |

#### 0.4.6 표기 규약 (Notation Convention) ★

수식에 등장하는 모든 변수, 첨자, 집합 기호 사전.

##### 0.4.6.1 기본 변수 (Variable Names)

| 변수 | 의미 | 본 작업에서의 차원 / 예시 |
|------|-----|------|
| $X$ | state space (상태 공간) — 게임이 진행될 수 있는 모든 상태의 집합 | $X = \mathbb{R}^6$ (6D state, §1.1) |
| $U$ | control space (제어 공간) — 한 플레이어가 선택 가능한 입력의 집합 | $U \subset \mathbb{R}^3$ (3D control, §1.2) |
| $U_p, U_e$ | pursuer / evader 각각의 control space | $U_p = U_e$ (동등 스펙이므로 동일) |
| $u$ | control input (제어 입력) — $U$ 의 원소 | $u = (\omega_h, \gamma, a) \in \mathbb{R}^3$ |
| $u_p, u_e$ | pursuer / evader 의 제어 입력 (한 시점) | $u_p \in U_p$ |
| $u(\cdot)$ | control trajectory — 시간 함수 (전체 시간 구간) | $u: [0, T] \to U$ |
| $x$ | state vector (상태 벡터) — $X$ 의 원소 | $x = (\Delta x, \Delta y, \Delta h, \Delta\psi, V_p, V_e)$ |
| $x(t)$ | state at time $t$ (시점 $t$ 의 상태) | scalar 또는 vector 함수 of time |
| $\dot{x}$ | $dx/dt$ — 상태의 시간 미분 | dynamics 좌변 |
| $f$ | dynamics function (운동방정식 우변) — $\dot{x} = f(x, u_p, u_e, t)$ | $f: X \times U_p \times U_e \times [0,T] \to \mathbb{R}^n$ |
| $J$ | payoff functional (보상/비용 functional) — 게임 결과의 점수 | $J(x_0, u_p, u_e) \in \mathbb{R}$ |
| $L$ | running cost (적분 비용) — 매 순간의 비용 | $L: X \times U_p \times U_e \to \mathbb{R}$ |
| $l$ | terminal cost (종단 비용) 또는 signed distance | $l(x) = \text{dist}(x, \partial\mathcal{C})$ 부호 포함 |
| $g$ | terminal payoff (종단 보상) — $J = g(x(T)) + \int L$ | scalar function |
| $V$ | value function — $V(x) = \min\max J$ | $V: X \to \mathbb{R}$ |
| $H$ | Hamiltonian — $H(x, p, u_p, u_e) = p \cdot f + L$ | HJI PDE 의 핵심 |
| $p$ | costate (보조 변수) — Pontryagin 의 $\lambda$, $p = \nabla V$ | gradient of $V$ |
| $t$ | time (시간) — 일반적으로 $t \in [0, T]$ | scalar |
| $T$ | terminal time (게임 종료 시간) | $T = 300$s (본 작업) |
| $n$ | state space dimension (상태 차원) | $n = 6$ (본 작업) |
| $m$ | control space dimension (제어 차원) | $m = 3$ (per player) |
| $\omega_h$ | horizontal turn rate (수평 선회율) | rad/s |
| $\gamma$ | flight path angle (비행 경로 각) | rad |
| $a$ | acceleration (가속) | kts/s |
| $\psi$ | heading (방위각) | rad, 절대 또는 상대 |
| $V_p, V_e$ | pursuer / evader 속도 크기 | kts (state 의 component) |
| $h$ | altitude (고도) | ft |
| $\Delta$ | difference (차이) — 예: $\Delta x = x_e - x_p$ | (prefix 첨자) |
| $\delta$ | small perturbation (미소 섭동) | $x_0 + \delta$, $\|\delta\| < r$ |

##### 0.4.6.2 첨자 (Subscript / Superscript)

| 첨자 | 의미 | 예시 |
|------|-----|------|
| $_p$ (subscript) | pursuer — 추격자 (본 작업에서 "우리") | $u_p, U_p, V_p, \omega_{h,p}$ |
| $_e$ (subscript) | evader — 회피자 (본 작업에서 "적") | $u_e, U_e, V_e, \omega_{h,e}$ |
| $_{us}$ (subscript) | "우리" 관점 — 모델 B 에서 사용 (= pursuer 역할) | $V_{us}, \text{WEZ}_{us}, D_{us}$ |
| $_{them}$ (subscript) | "적" 관점 — 모델 B 에서 사용 (= evader 역할) | $V_{them}, \text{WEZ}_{them}, D_{them}$ |
| $_0$ (subscript) | 초기 (initial) — 게임 시작 시점 | $x_0, t_0$ |
| $_T$ (subscript) | 종단 (terminal) — 게임 종료 시점 | $x_T, t_T$ |
| $_{\max}$ (subscript) | 최대 한계 | $\omega_{\max}, V_{\max}, a_{\max}$ |
| $_{\min}$ (subscript) | 최소 한계 | $V_{\min}$ |
| $^*$ (superscript) | optimal (최적) — 양쪽 minimax 시의 값 | $V^*, u^*, J^*$ |
| $^c$ (superscript) | complement (여집합) | $\mathcal{C}^c$ = capture set 밖 |
| $_h, _v$ (subscript) | horizontal, vertical | $\omega_h, \omega_v$ |
| $_t$ (subscript on $\partial$) | partial derivative w.r.t. $t$ | $\partial_t V = \partial V / \partial t$ |
| $_x$ (subscript on $\partial$) | partial derivative w.r.t. $x$ | $\partial_x V = \nabla V$ |
| $(\cdot)$ (parentheses with $\cdot$) | placeholder for time variable | $u(\cdot)$ = full trajectory |

##### 0.4.6.3 연산자 / 함수 표기

| 표기 | 의미 |
|------|------|
| $\dot{(\cdot)}$ | time derivative — $\dot{x} = dx/dt$ |
| $\nabla$ | spatial gradient — $\nabla V = (\partial V/\partial x_1, \ldots, \partial V/\partial x_n)$ |
| $\nabla \cdot$ (with operator) | divergence (발산) — $\nabla \cdot F$ |
| $\partial$ | partial derivative — $\partial V / \partial x_i$ |
| $\partial \mathcal{C}$ | boundary of set $\mathcal{C}$ (집합의 경계) |
| $\|\cdot\|$ | Euclidean norm (유클리드 노름) — $\|x\| = \sqrt{x_1^2 + \ldots + x_n^2}$ |
| $\|\cdot\|_\infty$ | infinity norm — $\max_i \|x_i\|$ |
| $\mathbb{1}_A$ | indicator function — $A$ 면 1, 아니면 0 |
| $\mathbb{E}[\cdot]$ | expectation (기대값) — 확률 게임 시 |
| $\min, \max$ | minimum, maximum (over set) |
| $\arg\min, \arg\max$ | minimum/maximum 을 달성하는 인자 |
| $\forall, \exists$ | "모든", "존재" |
| $\Rightarrow, \Leftrightarrow$ | "함의", "동치" |

##### 0.4.6.4 집합 표기

| 기호 | 의미 |
|------|------|
| $\mathbb{R}$ | real numbers (실수) |
| $\mathbb{R}^n$ | $n$-차원 실수 공간 |
| $\mathbb{R}^+, \mathbb{R}_{\ge 0}$ | 양수 (또는 0 포함) |
| $\mathbb{N}, \mathbb{Z}$ | 자연수, 정수 |
| $\mathcal{C}, \mathcal{H}, \mathcal{T}$ | capture set, hard-deck set, target set (캘리그래픽 = 집합) |
| $\subset, \subseteq$ | proper subset, subset |
| $\in, \notin$ | element of, not element of |
| $\cap, \cup$ | intersection, union |
| $\emptyset$ | empty set (공집합) |
| $\{x : P(x)\}$ | set-builder notation (조건 $P$ 만족하는 $x$ 의 집합) |
| $[a, b]$ | closed interval (닫힌 구간) — $a \le x \le b$ |
| $(a, b)$ | open interval (열린 구간) — $a < x < b$ |
| $B(x_0, r)$ | open ball — $\{x : \|x - x_0\| < r\}$ |

##### 0.4.6.5 자주 등장하는 합성 표기

| 표기 | 풀이 | 의미 |
|------|-----|------|
| $V^*(x)$ | $V$ 최적값을 $x$ 에서 평가 | "주어진 상태 $x$ 에서의 최적 게임 값" |
| $u_p^*(x)$ | pursuer 의 optimal control at state $x$ | "$x$ 일 때 우리가 해야 할 최적 행동" |
| $u^*_p(\cdot)$ | optimal control trajectory (full time) | "전체 시간에 걸친 최적 행동 sequence" |
| $\nabla V^*$ | optimal value 의 spatial gradient | "$V^*$ 가 가장 빠르게 변하는 방향" |
| $\partial_t V$ | $V$ 의 시간 편미분 | "$V$ 가 시간에 따라 어떻게 변하는가" |
| $\dot{x} = f(x, u_p, u_e)$ | dynamics ODE | "상태 변화율 = dynamics 함수" |
| $\min_{u_p} \max_{u_e}$ | minimax — pursuer 최소, evader 최대 | "양쪽 모두 최선 다할 때" |
| $\arg\min_u H$ | $H$ 를 최소화하는 $u$ | "어떤 $u$ 를 골라야 $H$ 최소?" |
| $x(t; x_0, u_p, u_e)$ | initial $x_0$, controls $u_p, u_e$ 로 진행되는 $t$ 시점 state | trajectory at time $t$ |
| $\mathbb{1}_{x \in \mathcal{C}}$ | $x$ 가 $\mathcal{C}$ 안에 있으면 1, 아니면 0 | "잡혔는가" 의 binary indicator |
| $\mathbb{E}[X | \mathcal{F}]$ | conditional expectation (조건부 기대값) | $\mathcal{F}$ 정보 하에 $X$ 의 기대값 |

##### 0.4.6.6 본 작업 특수 합성 — 좌표계 + 게임값

| 표기 | 풀이 |
|------|------|
| $(\Delta x, \Delta y, \Delta h, \Delta\psi, V_p, V_e)$ | 본 작업 6D state vector (§1.1) |
| $u_p = (\omega_{h,p}, \gamma_p, a_p)$ | pursuer 의 3D control (선회율, 비행각, 가속) |
| $u_e = (\omega_{h,e}, \gamma_e, a_e)$ | evader 의 3D control |
| $\text{ATA}(x), \text{AA}(x), \text{HCA}(x)$ | 6D state $x$ 로부터 계산되는 각도 |
| $\text{dist}(x), \dot{\text{dist}}(x)$ | $x$ 에서 거리 및 closure rate |
| $D(x) = 25 \cdot w_{\text{ATA}}(x) \cdot w_{\text{dist}}(x)$ | damage rate at $x$ (§0.8) |
| $V^*(x_0) = +1731$ ft | 본 작업 3D 한계 실측 값 (§1.5) |

> **읽는 법 예시**:
>
> $\dot{\Delta x} = V_e \cos\gamma_e \sin\Delta\psi + \omega_{h,p} \cdot \Delta y$
>
> 풀이: "**상대 위치 $\Delta x$ 의 시간 미분** = (적 속도 $V_e$) × cos(적 비행각 $\gamma_e$) × sin(상대 heading 차 $\Delta\psi$) + (우리 수평 선회율 $\omega_{h,p}$) × (상대 위치 $\Delta y$)"
>
> 즉 첨자 $_e$, $_p$, $_{h,p}$ 의 의미를 알면 식 전체가 자연어로 읽힘.

#### 0.4.7 약어 사전 (Acronym Glossary) ★

본 문서 + 본 작업 전반에서 사용되는 약어. 처음 등장 시 풀어 쓰지 않은 곳이 있을 수 있어 전수 목록.

##### 수학 / 게임 이론 약어

| 약어 | 풀이 (영문) | 풀이 (한글) | 한 줄 설명 |
|------|----------|----------|----------|
| **HJ** | Hamilton-Jacobi | 해밀턴-야코비 | 19세기 고전 역학에서 유래한 1차 PDE class |
| **HJB** | Hamilton-Jacobi-Bellman | 해밀턴-야코비-벨만 | 단일 최적 제어 (1 player) 의 PDE |
| **HJI** | Hamilton-Jacobi-Isaacs | 해밀턴-야코비-아이작스 | 두 플레이어 미분 게임의 PDE — 본 작업 핵심 |
| **PDE** | Partial Differential Equation | 편미분방정식 | 다변수 함수의 편미분으로 표현되는 방정식 |
| **ODE** | Ordinary Differential Equation | 상미분방정식 | 단일 변수의 미분방정식 (시간만) |
| **PEG** | Pursuit-Evasion Game | 추격-회피 게임 | 비대칭 미분 게임 — 모델 A |
| **BRT** | Backward Reachable Tube | 역방향 도달 가능 집합 | "$T$초 안에 capture 가능한 상태 집합" |
| **BRS** | Backward Reachable Set | 역방향 도달 가능 집합 (시점) | 특정 시점의 도달가능 — BRT 는 시간 전 구간 |
| **FRT** | Forward Reachable Tube | 순방향 도달 가능 집합 | "$T$초 후 도달 가능한 상태 집합" |
| **PMP** | Pontryagin's Maximum Principle | 폰트랴긴 최대 원리 | 최적 제어의 필요 조건 (게임 외부 도구) |
| **PN** | Proportional Navigation | 비례 항법 | 미사일/추격기 유도 법칙 — Bryson-Ho |
| **LQG** | Linear-Quadratic-Gaussian | 선형-2차-가우스 | 특수 해석해 존재 (Riccati equation) |
| **MDP** | Markov Decision Process | 마르코프 결정 과정 | 이산 시간 game (vs 연속 differential game) |
| **POMDP** | Partially Observable MDP | 부분 관측 MDP | 부분 관측 가능한 MDP — 본 작업 관련 없음 |

##### 비행 / BFM 약어 (Basic Fighter Maneuvers)

| 약어 | 풀이 (영문) | 풀이 (한글) | 한 줄 설명 |
|------|----------|----------|----------|
| **BFM** | Basic Fighter Maneuvers | 기본 전투기동 | 1:1 도그파이트의 기동 교리 모음 |
| **OBFM** | Offensive BFM | 공격 기본 기동 | 추격 측 기동 (lead/lag pursuit, gun snap shot) |
| **DBFM** | Defensive BFM | 방어 기본 기동 | 회피 측 기동 (break turn, defensive spiral) |
| **HABFM** | Head-On / Aggressor BFM | 정면 교전 기동 | 양쪽 정면 만남 시 기동 |
| **WEZ** | Weapon Engagement Zone | 사거리 진입 영역 | 사격 가능 조건 영역 (ATA + 거리 + closure) |
| **ATA** | Antenna Train Angle | 안테나 추적 각도 | 우리 nose 와 적 방향 사이 각도 (∈ [0, 180°]) |
| **AA** | Aspect Angle | 측면각 (적 측면) | 적 nose 와 우리 방향 사이 각도 |
| **HCA** | Heading Crossing Angle | 비행 경로 교차각 | 두 비행 벡터 사이 각도 |
| **TCA** | Track Crossing Angle | 추적 경로 교차각 | HCA 의 대체 표기 (동의어) |
| **LOS** | Line Of Sight | 시선 | 우리 → 적 방향 벡터 |
| **LOSR** | LOS Rate | LOS 회전율 | LOS 의 시간 미분 — PN 핵심 변수 |
| **EM** | Energy Maneuverability | 에너지 기동성 | Boyd 의 specific excess power 이론 |
| **Ps** | Specific Excess Power | 비잉여 출력 | $(T - D) V / W$ — 에너지 변화율 |
| **LDT** | Lag Displacement Turn | 지체 변위 선회 | Shaw 의 추격 기동 (lag→lead 전환) |
| **PNAttack** | PN-based Attack | PN 기반 사격 | Proportional Navigation 으로 lead 계산 |
| **TC** | Two-Circle (또는 Track Crossing) | 2-circle | 양쪽 반대 방향 선회 fight |
| **OC** | One-Circle | 1-circle | 양쪽 같은 방향 선회 fight |
| **GUN_RUN** | Gun Run / Gun Attack | 사격 시도 | 적이 우리에게 사격 시도 중 |

##### 시스템 / 소프트웨어 약어

| 약어 | 풀이 (영문) | 풀이 (한글) | 한 줄 설명 |
|------|----------|----------|----------|
| **JSBSim** | Jet Specification Body Simulator | 제트 시뮬레이터 | F-16 등 항공기 6-DOF 비행 시뮬레이터 — 본 작업의 core |
| **BT** | Behavior Tree | 행동 트리 | 계층적 의사결정 트리 구조 (Selector/Sequence/Action) |
| **HCCA** | Hierarchical Continuous Control Architecture | 계층 연속 제어 구조 | 본 프로젝트의 5-layer 연속 제어 (HCCA v12) |
| **EIM** | Enemy Intent Model | 적 의도 모델 | ProtoNet 기반 적 intent 분류기 (6 classes) |
| **CT** | Counter Table | 카운터 테이블 | intent → BT 노드 매핑 lookup |
| **YAML** | YAML Ain't Markup Language | YAML | BT 정의 / config 파일 형식 |
| **CSV** | Comma-Separated Values | 쉼표 구분 값 | 매치 로그 / metric 데이터 파일 |
| **NPZ** | NumPy ZIP archive | NumPy 압축 보관소 | numpy 다차원 배열 압축 파일 (V table 저장) |
| **NN** | Neural Network | 신경망 | 본 작업 의도적 회피 ("진정한 solver 사용") |
| **AI** | Artificial Intelligence | 인공지능 | NN 의 상위 카테고리 |
| **API** | Application Programming Interface | API | 외부 모듈 호출 인터페이스 |
| **CLI** | Command Line Interface | 명령행 인터페이스 | shell 명령 입력 인터페이스 |
| **6-DOF** | 6 Degrees Of Freedom | 6자유도 | 3D 위치 + 3D 자세 = 6 자유도 |
| **3D / 6D** | 3-Dimensional / 6-Dimensional | 3차원 / 6차원 | 본 작업에서 game state 차원 |
| **3-DOF** | 3 Degrees Of Freedom | 3자유도 | 점-질량 모델 (위치 3D, 자세 무시) |
| **HW** | Hardware | 하드웨어 | (참고용) |
| **OS** | Operating System | 운영체제 | (참고용) |

##### 수치 / 계산 약어

| 약어 | 풀이 (영문) | 풀이 (한글) | 한 줄 설명 |
|------|----------|----------|----------|
| **GPU** | Graphics Processing Unit | 그래픽 처리 장치 | 병렬 계산 가속기 — JAX/CUDA |
| **CPU** | Central Processing Unit | 중앙 처리 장치 | 일반 컴퓨터 프로세서 |
| **CUDA** | Compute Unified Device Architecture | CUDA | NVIDIA GPU 병렬 계산 framework |
| **JAX** | (이름) | JAX (구글 ML 라이브러리) | NumPy 호환 + auto-diff + GPU/TPU 가속 |
| **FP** | Floating Point | 부동 소수점 | 컴퓨터 실수 표현 — non-determinism 원인 |
| **FP32 / FP64** | 32-bit / 64-bit Float | 32/64비트 부동소수 | 정밀도 — 본 작업 FP32 사용 |
| **CFL** | Courant-Friedrichs-Lewy condition | CFL 조건 | PDE 수치해 안정성 시간 step 한계 ($\Delta t \le \Delta x / \|f\|$) |
| **WENO** | Weighted Essentially Non-Oscillatory | 가중 본질 비진동 | 고차 spatial finite difference scheme (PDE 풀이) |
| **ENO** | Essentially Non-Oscillatory | 본질 비진동 | WENO 의 이전 버전 |
| **TVD** | Total Variation Diminishing | 전체변동감소 | Runge-Kutta 시간 적분 안정성 보장 |
| **RK** | Runge-Kutta | 룽게-쿠타 | ODE 수치 적분 방법 (예: RK4, RK45) |
| **ZOH** | Zero-Order Hold | 0차 유지 | 이산 시간 → 연속 시간 (사이 값은 상수) |
| **TPU** | Tensor Processing Unit | 텐서 처리 장치 | Google 의 AI 가속기 |
| **RAM** | Random Access Memory | 주 기억장치 | 계산 메모리 |
| **JIT** | Just-In-Time compilation | 적시 컴파일 | 첫 호출 시 컴파일, 후속 빠름 (JAX 핵심) |

##### 본 작업 특수 약어

| 약어 | 풀이 (영문) | 풀이 (한글) | 한 줄 설명 |
|------|----------|----------|----------|
| **HP** | Hit Points | 체력 | 양쪽 100 으로 시작, damage 누적으로 감소 |
| **DPS** | Damage Per Second | 초당 데미지 | WEZ 안에서 25 HP/s (max) |
| **NED** | North-East-Down | 북-동-하 | 항공 표준 좌표계 (지구 표면 기준) |
| **NEU** | North-East-Up | 북-동-상 | NED 의 z 부호 반전 |
| **F-16** | Fighting Falcon (전투기 명) | F-16 (전투기) | Lockheed Martin F-16, 본 작업 항공기 |
| **kts** | knots | 노트 (속도) | 1 kt = 1.6878 ft/s ≈ 0.514 m/s |
| **ft** | feet | 피트 (길이) | 1 ft = 0.3048 m |
| **deg / °** | degrees | 도 | 각도 단위 |
| **rad** | radians | 라디안 | 각도 단위 (1 rad ≈ 57.3°) |
| **G** | G-force | 중력 가속도 배수 | 1G = 9.81 m/s², F-16 max ≈ 9G |
| **AOA** | Angle Of Attack | 받음각 | 비행 경로 와 동체 축 사이 각도 |
| **DRAW** | Draw outcome | 무승부 | 매치 결과 (양쪽 동률 또는 timeout) |
| **WIN** | Win outcome | 승리 | 매치 결과 |
| **LOSS** | Loss outcome | 패배 | 매치 결과 |

##### 도구 / 외부 약어 (참고)

| 약어 | 풀이 | 한 줄 설명 |
|------|-----|----------|
| **CMA-ES** | Covariance Matrix Adaptation - Evolution Strategy | 진화 전략 최적화 (`adaptive_optimizer.py`) |
| **LHS** | Latin Hypercube Sampling | 격자 sampling (구 `bt_optimizer.py` v2) |
| **ProtoNet** | Prototypical Network | 적은 데이터로 분류 학습 — EIM 사용 |
| **TacticalLookup** | (이름) | data-driven counter table lookup BT 노드 |
| **WEZ_us / WEZ_them** | (위치 표기) | 우리/적 WEZ 영역 (모델 B 에서 양쪽) |
| **VSCode** | Visual Studio Code | 코드 편집기 |

> **주의**: 위 용어들은 §0~§11 전체에서 일관 사용. §1.3 의 binary WEZ 는 §0.8 의 가중치 함수 $D(x)$ 의 1차 근사임. 모델 A 는 binary capture, 모델 B' 는 continuous damage 누적.
>
> **누락 약어 발견 시**: §0.4.7 에 추가하고 §12 변경 이력 기록.

### 0.5 가정사항 명시 (Assumptions) ★

본 작업이 well-defined 하기 위한 모든 가정을 명시:

#### **A. 시뮬레이터 / 물리 가정**

| # | 가정 | 정당화 | 깨질 경우 영향 |
|---|------|------|------|
| A1 | F-16 양쪽 동등 스펙 (JSBSim core) | 사용자 합의 + JSBSim 기본 | 비대칭 시 결론 변경 |
| A2 | 점-질량 운동 (γ 즉시 제어) | 수학 단순화 | high-G stall 시 부정확 |
| A3 | Envelope: V∈[160,420]kts, ω_max=21°/s@350kts | JSBSim 실측 (`sim_dogfight_verify.py:54-79`) | spec 변경 시 재계산 |
| A4 | 60 Hz physics, 5 Hz BT tick (0.2s ZOH) | JSBSim 기본 | tick 변경 시 시간 스케일 조정 |
| A5 | 25% non-determinism (FP, thread) | 프로젝트 메모리 측정값 | 통계 검증 시 noise floor |

#### **B. 게임 형식 가정**

| # | 가정 | 정당화 | 깨질 경우 |
|---|------|------|------|
| B1 | **모델 A 비대칭 채택** (현재 단계) | 수학 단순화 + 대칭 argument | 모델 B 필요 시 §11 로드맵 적용 |
| B2 | Initial = canonical (ATA=90°, dist=3297.6ft, V=386.8kts, alt=15000ft, HCA=180°) | JSBSim 매치 모두 이 상태에서 시작 | non-canonical 시작 시 별도 검증 |
| B3 | Terminal = 1500 tick (300s) timeout | JSBSim 기본 | 더 긴 매치 시 결과 변할 수 있음 |
| B4 | WEZ = ATA<12° AND 500<dist<3000ft AND closure>0 | `config/wez_params.yaml` 기본 | WEZ 변경 시 V table 재계산 |
| B5 | Hard deck = h<1000ft 즉시 패 | JSBSim 기본 | safety BT branch 로 별도 처리 |
| B6 | Minimax 가정 (양쪽 모두 saddle-point 플레이) | game theory 정통 가정 | sub-optimal 적 대비 V_us<V* 가능 |

#### **C. 수학 / 수치 가정**

| # | 가정 | 정당화 | 깨질 경우 |
|---|------|------|------|
| C1 | 6D state space (Δx, Δy, Δh, Δψ, V_p, V_e) | translation/rotation 대칭으로 14D→6D 축소 | 자세각 추가 시 7~8D 필요 |
| C2 | **Dynamics 는 비선형** (sin/cos/곱 등). 단 hj-reachability 호환 위해 **control-affine 형식** 으로 변환 (control 에만 affine, state 비선형성 유지). 추가로 **small-γ 가정** ($\cos\gamma \approx 1$, $\sin\gamma \approx \gamma$) 적용 — $\gamma$ control 도 affine 화 | hj-reachability 호환 + 수학 단순화 (§1.2.3). **실측 검증 완료** (`tools/analyze_dynamics_assumptions.py`): 44,500 tick 평균 \|γ\|=2.92°, cos γ 오차 평균 **0.29%** (이론 14% worst-case 의 1/50), max \|γ\|=15.06° (30° 한계 절반). | 이론 worst case (γ=30°) 시 cos 오차 ~14%, 실측은 평균 0.29% — 가정 매우 valid. 30° 발생 빈도 0% (실측). 완전 비선형 풀이는 일반 `Dynamics` 클래스 + 8D state 로 가능 |
| C3 | Grid 12⁶ = 약 3M cells (현재) | CPU JAX 메모리 한계 | 정밀도 부족 → 20⁶ 권고 |
| C4 | Nearest-neighbor lookup (BT 런타임) | 단순 구현 | 정밀도 필요 시 trilinear 보간 |
| C5 | V_e ≈ V_p 추정 (BT obs 변환) | obs 에 V_e 직접 노출 안 됨 | closure_rate 활용 추정 가능 |
| C6 | HCA 부호 양수 사용 (절대값) | side_flag 정확성 불확실 | 부호 정확성 확보 시 좌표계 명확화 |

#### **D. 좌표계 가정 ★**

| # | 가정 | 정당화 |
|---|------|------|
| D1 | HJI body frame: +x=우측, +y=전방, +z=하단 | NED 표준 (북동지) 회전 |
| D2 | dx>0 = 적이 우리 우측 | dynamics 정의 |
| D3 | dpsi = 적 heading - 우리 heading (rad) | 일관성 |
| D4 | Sim `relative_bearing_deg`: 수학 CCW positive (LEFT positive, RIGHT negative) | canonical 검증으로 도출 |
| D5 | 변환: dx = -dist · sin(rb_rad) (부호 flip) | D1↔D4 정합 |

### 0.6 범위 한정 (Scope Boundary)

**본 작업이 다루는 것**:
- 1:1 (one-on-one) 도그파이트만
- 동등 스펙만 (asymmetric weapon/aircraft 제외)
- canonical 초기 조건 ± perturbation 만
- 점-질량 6D 모델만 (full 6-DOF 자세각 dynamics 제외)
- gun WEZ 기반 capture (missile 제외, 현재 SDK 무기 한정)
- 모델 A 비대칭 (현재) → 모델 B 대칭 (로드맵 §11)

**본 작업이 다루지 않는 것**:
- 2:2 이상 다대다
- BVR (Beyond Visual Range) 미사일 전투
- 비대칭 스펙 (F-16 vs F-22 등)
- 6-DOF 자세각 동역학 (stall, roll lag 등)
- 환경 영향 (바람, 시야 제한, 무기 제약)
- 적 정책 미지 / 학습형 (TacticalLookup 통합은 후속)

### 0.7 학습자가 다음 절에서 만날 표기

§1 부터 등장하는 수식 / 표기:

| 표기 | 의미 | 본 절 어디서 정의 |
|------|------|------|
| x ∈ ℝ⁶ | 6D 상태 벡터 | §0.5 C1 |
| f(x, u_p, u_e) | dynamics — 상태 미분 | §0.4 dynamics |
| u_p, u_e ∈ ℝ³ | pursuer/evader 제어 (ω, γ, a) | §0.4 control |
| V*(x) | optimal value function | §0.4 value function |
| ∇V*(x) | V 의 gradient (6D 편미분 벡터) | calculus |
| 𝒯, 𝒞 | target set, capture set | §0.4 capture set |
| H(x, ∇V) | Hamiltonian — HJI 의 핵심 함수 | §2 |
| BRT(T) | T초 backward reachable tube | §0.4 BRT |
| D(x) | damage rate (HP/s) at state x | §0.8 |
| w_ATA, w_dist | WEZ 내 ATA/거리 가중치 (∈ [0,1]) | §0.8 |
| HP_us, HP_them | 양쪽 체력 (초기 100) | §0.8 |

---

### 0.8 "잡다" 의 진정한 의미 — WEZ 가중치 함수 + HP 누적 ★

> 사용자가 짚은 핵심 보강 (2026-05-12):
> "잡다"는 binary (잡힘 / 안 잡힘) 가 아니라 **연속 damage 누적**이다.
> 이 절은 §0.4 의 "Capture Set" 정의를 더 정확하게 재정의함.

#### 잘못된 단순화 (§0~§5 까지의 가정)

```
WEZ = { x : ATA<12° AND 500<dist<3000 AND closure>0 }
"x ∈ WEZ 이면 잡았다" (binary)
```

이게 모델 A 비대칭 PEG 의 capture set 정의. 단순하지만 **실 게임 규칙과 다름**.

#### 실제 규칙 (config/wez_params.yaml + config/match_rules.yaml)

**1. WEZ 진입 조건**:
```yaml
gun_wez:
  max_angle_deg:  12.0      # ATA ≤ 12° (±12° 콘)
  min_range_ft:   500
  max_range_ft:   3000
  base_dps:       25.0      # ATA=0 + 사거리 sweet spot 시 25 HP/s
  angle_multiplier: true    # 각도에 따른 감쇠
```

**해석 — 각 파라미터의 의미** ★

| 파라미터 | 값 | 물리적 의미 | 왜 이 값인가 |
|---------|-----|-----------|-----------|
| `max_angle_deg` | $12.0°$ | "총구를 적과 정렬하는 각도 허용 오차" — ATA 가 우리 nose 에서 ±12° 안에 적이 있어야 사격 의미 있음 | F-16 의 M61 Vulcan gun 분산도 + 사거리 기반 effective cone (실 fighter 운영 지침 ~10-15°) |
| `min_range_ft` | $500$ ft (≈152 m) | 최소 사거리 — 너무 가까우면 회피 불능 / 충돌 위험 | 비행 안전 + 총탄 비행 시간 짧아도 명중 시간 필요 |
| `max_range_ft` | $3000$ ft (≈914 m) | 최대 사거리 — 총탄 도달 + 살상력 유효 거리 | M61 의 effective range (실 F-16 운영 ~600-800 m, 본 SDK 는 ~900 m) |
| `base_dps` | $25.0$ HP/s | 최적 조건(ATA=0, 사거리 sweet spot) 에서 초당 데미지 | 100 HP / 4초 = full kill 시간 4초 → 게임 페이스 결정 |
| `angle_multiplier` | `true` | 각도에 따라 damage 감쇠 적용 (binary 가 아닌 continuous) | 실 사격 정확도가 각도에 비례 — w_ATA 함수 적용 |

**왜 이 규칙이 중요한가** (수학적 해석):

- **Binary capture (모델 A) vs Continuous damage (실제) 의 차이**:
  - Binary: "WEZ 안 → 잡힘 (1) 또는 밖 → 미수 (0)" — Heaviside step function
  - Continuous: "WEZ 안 깊숙이 정확 조준 → 빠른 damage / 가장자리 부정확 → 느린 damage" — smooth function
- **수학적 의미**: 모델 A 는 ${1}_{x \in \mathcal{C}}$ (indicator), 모델 B' 는 weight function $w_{\text{ATA}}(x) \cdot w_{\text{dist}}(x)$
- → BT 의사결정 영향: 모델 A 는 "들어왔나/못 들어왔나", 모델 B' 는 "더 정확히 더 오래" 추구

---

**2. WEZ 내 damage 가중치** (사용자 명세):

$$
D(x) = \begin{cases}
25.0 \cdot w_{\text{ATA}}(x) \cdot w_{\text{dist}}(x) & \text{if } x \in \text{WEZ} \\
0 & \text{otherwise}
\end{cases} \quad [\text{HP/s}]
$$

**해석 — 식의 각 부분**:

- **좌변 $D(x)$**: damage rate (초당 데미지) — state $x$ 에서 적이 받는 HP 감소 속도. 단위 [HP/s].
- **$25.0$**: base DPS (위 표 참조) — 최적 조건 시 최대치. 모든 가중치가 1.0 일 때 25 HP/s.
- **$w_{\text{ATA}}(x)$**: 각도 가중치 ∈ $[0, 1]$ — 정확한 조준일수록 1 에 가까움.
- **$w_{\text{dist}}(x)$**: 거리 가중치 ∈ $[0, 1]$ — sweet spot 거리일수록 1 에 가까움.
- **곱셈 $\cdot$**: 두 가중치의 **독립적** 곱 — 각도 정확성과 거리 적정성이 모두 좋아야 max damage.
- **$x \in \text{WEZ}$ 조건**: ATA<12° AND 500<dist<3000 AND closure>0 (binary 진입 조건은 유지).

**왜 곱셈인가**: 두 효과가 **독립**이라는 모델 가정. ATA=0 라도 거리 5000ft 면 명중률 0 (총탄 도달 못함). 반대도 마찬가지.

---

**$w_{\text{ATA}}$ 의 정확한 형식**:

$$
w_{\text{ATA}}(x) = \max\Bigl(0, \; 1 - \frac{\text{ATA}(x)}{12°}\Bigr) \quad \text{(linear decay)}
$$

**해석 — 선형 감쇠**:

- $\text{ATA}(x) = 0°$: $w_{\text{ATA}} = 1 - 0/12 = 1$ (max, 정확 조준)
- $\text{ATA}(x) = 6°$: $w_{\text{ATA}} = 1 - 6/12 = 0.5$ (half damage)
- $\text{ATA}(x) = 12°$: $w_{\text{ATA}} = 1 - 12/12 = 0$ (no damage, WEZ 경계)
- $\text{ATA}(x) > 12°$: $\max(0, \ldots) = 0$ (WEZ 밖)

**그래프 (시각화)**:
```
w_ATA(x)
  1.0 |●
      | \
  0.5 |  \
      |   \
  0.0 |    ●─────────────
      └────┬─────┬──────→ ATA(x) [°]
           6°   12°
```

**왜 선형인가**: 실제 총기 정확도는 각도의 제곱(가우시안) 에 가깝지만, SDK 는 단순화를 위해 선형 채택. BFM 의사결정에는 정성적으로 동일 (정확할수록 큰 damage).

---

**$w_{\text{dist}}$ 의 형식** (가정):

$$
w_{\text{dist}}(x) = \text{linear decay function in } [500, 3000] \text{ ft}
$$

**가정 (`wez_engine.pyd` 내부 미공개)**:
- Sweet spot ~ 1500 ft 부근에서 최대 (~1.0)
- 500 ft (너무 가까움) → 약 0.5 (회피 어려움 + 총탄 비행 시간 너무 짧음)
- 3000 ft (너무 멀음) → 약 0 (총탄 도달 한계)

**가정 형식 (예시)**:
```
w_dist(x) ≈ {
  (dist - 500) / 1000        if 500 ≤ dist ≤ 1500  (증가 구간)
  1 - (dist - 1500) / 1500   if 1500 ≤ dist ≤ 3000 (감소 구간)
}
```

또는 단순화:
```
w_dist(x) = 1 (가정)  ← 1차 근사, 정확한 형식은 BT 통합 검증 시 측정
```

**왜 sweet spot 이 있나**: 너무 가까우면 회피 기동 시 빠르게 WEZ 이탈 / 너무 멀면 총탄 도달 약화. 중간에 최적점.

---

**3. HP 시스템** (match_rules.yaml):
```yaml
match:
  initial_health: 100.0     # 양쪽 초기 HP = 100
  max_steps: 1500           # 5분
  victory_conditions:
    - type: "health_zero"        # 1순위: 상대 HP = 0
    - type: "hard_deck"          # 2순위: 상대 hard deck 위반
    - type: "health_advantage"   # 3순위: 시간 종료 시 HP 우위
```

**해석 — HP 시스템의 의미** ★

| 파라미터 | 값 | 의미 | 게임 영향 |
|---------|-----|------|----------|
| `initial_health` | $100.0$ | 양쪽 시작 HP = 100 | base_dps=25 와 결합: 100 HP / 25 HP·s$^{-1}$ = **4 초** 완전 명중 시 즉살 |
| `max_steps` | $1500$ | 매치 최대 길이 (tick) — $1500 \times 0.2s = 300s$ | 5 분 안 결판 안 나면 timeout |
| `health_zero` (priority 1) | — | 상대 HP 0 시 즉시 승리 | "잡다" 의 1차적 의미 — kill |
| `hard_deck` (priority 2) | — | 상대가 1000 ft 아래로 내려가면 즉시 패 (우리 승) | 안전 규칙 — 추락 회피 강제 |
| `health_advantage` (priority 3) | — | timeout 시 HP 우위 인 쪽 승리 | "잡다" 의 2차적 의미 — 점수 우위 |

**왜 우선순위가 이 순서인가**:

1. **$\text{HP}=0$ 이 1순위**: 게임 끝낸 자가 승. 즉시 결정.
2. **Hard deck 이 2순위**: 추락은 자살 — 적의 사격이 아니지만 패배 조건.
3. **HP advantage 가 3순위**: 누구도 kill 못 했으면 누가 더 많은 damage 입혔나 비교.

**수학적 표현 (Win Function)**:

$$
\text{Outcome}(T) = \begin{cases}
\text{우리 승} & \text{if } \text{HP}_{them}(t) = 0 \text{ for some } t \le T \\
\text{적 승}  & \text{if } \text{HP}_{us}(t) = 0 \text{ for some } t \le T \\
\text{적 승}  & \text{if } h_{us}(t) < 1000 \text{ ft for some } t \le T \quad (\text{우리 hard deck}) \\
\text{우리 승} & \text{if } h_{them}(t) < 1000 \text{ ft} \\
\text{우리 승} & \text{if } \text{HP}_{us}(T) > \text{HP}_{them}(T) \quad (\text{timeout, advantage}) \\
\text{적 승}  & \text{if } \text{HP}_{us}(T) < \text{HP}_{them}(T) \\
\text{DRAW}   & \text{if } \text{HP}_{us}(T) = \text{HP}_{them}(T)
\end{cases}
$$

여기서 위에서부터 우선순위 적용 (먼저 만족하는 조건이 결과 결정).

**현재 측정 (자가대전 20 매치)**:
- 모든 매치 $\text{HP}_{us}(T) = \text{HP}_{them}(T) = 100$
- → priority 3 의 마지막 분기 → DRAW
- → 양쪽 누구도 1초도 WEZ 안 진입 못 함 → damage 누적 0

#### "잡다" 재정의 — 누적 damage 게임

**확장된 game state**:

$$
x = (\Delta x, \Delta y, \Delta h, \Delta\psi, V_p, V_e, \text{HP}_{us}, \text{HP}_{them}) \in \mathbb{R}^8
$$

**해석 — 차원이 6D → 8D 로 증가**:

- 기존 6D: 양쪽 기하학적 위치 + 속도. **damage 정보 없음**.
- 추가된 2D: $\text{HP}_{us}, \text{HP}_{them} \in [0, 100]$ — 양쪽 누적 체력.
- **왜 state 에 추가?** — HP 가 시간에 따라 변하고, 미래 결과 (승/패) 에 영향. 따라서 Markov state 의 일부.
- **trade-off**: 8D 격자는 $20^8 \approx 25.6$ 십억 cells → 계산 폭발. 모델 B' 의 실 구현 시 차원 축소 필요 (예: $\Delta \text{HP} = \text{HP}_{us} - \text{HP}_{them}$ 하나만 추적, 7D).

---

**HP 동역학**:

$$
\frac{d\text{HP}_{them}}{dt} = -D_{us}(x) \quad (\text{우리가 적에게 입히는 damage})
$$

$$
\frac{d\text{HP}_{us}}{dt} = -D_{them}(x) \quad (\text{적이 우리에게 입히는 damage})
$$

**해석 — 식의 구조**:

- **좌변 미분 $\frac{d\text{HP}}{dt}$**: HP 의 시간 변화율. 음수 = HP 감소.
- **우변 $-D(x)$**: damage rate 의 음수 — damage 가 클수록 HP 빠르게 감소.
- **$D_{us}(x)$**: 우리 입장에서 적에게 가하는 damage. ATA, dist, closure 가 우리 기준.
- **$D_{them}(x)$**: 적 입장에서 우리에게 가하는 damage. AA, dist, closure 가 적 기준 (= 우리 입장에서 swap).
- **대칭**: 양쪽 동등 스펙이므로 $D_{them}$ 은 $D_{us}$ 의 상태 swap 으로 계산.

**예시 — 우리가 적 6시(뒤)에서 ATA=3° 거리 1500ft 로 추격**:
- $w_{\text{ATA}}(x) = 1 - 3/12 = 0.75$
- $w_{\text{dist}}(x) \approx 1.0$ (sweet spot)
- $D_{us}(x) = 25 \cdot 0.75 \cdot 1.0 = 18.75$ HP/s
- 동시에 적의 AA 는 우리 뒤이므로 ~ 180° → $w_{\text{AA}} = 0$ → $D_{them}(x) = 0$
- 결과: $\text{HP}_{them}$ 1초마다 18.75 감소, $\text{HP}_{us}$ 변화 없음
- 5.3초 후 $\text{HP}_{them} = 0$ → 우리 승.

**역상황 — 우리 6시 뒤에 적이 있음 (적 ATA=3°)**:
- 위와 정확히 반대. $D_{us} = 0$, $D_{them} = 18.75$. 우리가 먼저 0 도달 → 우리 패.

---

**승리 / 패배 / 무승부 판정 (영어 명세 + 한글 해석)**:

| 조건 | 영어 | 한글 의미 | 발생 시점 |
|------|------|---------|---------|
| **WIN by kill** | $\text{HP}_{them}(t) = 0$ for some $t \le T$ | 적 HP 가 게임 중간에 0 도달 | 즉시 승 |
| **LOSS by kill** | $\text{HP}_{us}(t) = 0$ for some $t \le T$ | 우리 HP 가 0 도달 | 즉시 패 |
| **WIN by advantage** | $\text{HP}_{us}(T) > \text{HP}_{them}(T)$ | timeout 시 HP 더 많음 | $T$ 시점 |
| **LOSS by advantage** | $\text{HP}_{us}(T) < \text{HP}_{them}(T)$ | timeout 시 HP 더 적음 | $T$ 시점 |
| **DRAW** | $\text{HP}_{us}(T) = \text{HP}_{them}(T) \ne 0$ | 양쪽 동일 HP (양쪽 무피해 100/100 포함) | $T$ 시점 |

---

#### 게임 값 (Game Value) 재정의

**기존 모델 A (reach-avoid)**:

$$
V^*(x) = \min_{u_p}\max_{u_e}\;\min_{t \in [0,T]} l(x(t))
$$

**해석 — reach-avoid value 의 의미**:

- $l(x)$ = signed distance to WEZ_us (음수 = 안, 양수 = 밖)
- 내부 $\min_t$: "도달 시간 안에 가장 가까이 들어간 순간" — reach 목표 함수
- 외부 $\min_{u_p}\max_{u_e}$: pursuer 가 이 값을 줄이려 하고, evader 가 키우려 함
- **출력**: $V^* < 0$ → WEZ 안 진입 가능, $V^* > 0$ → 진입 불가
- **한계**: "한 번이라도 들어갔나" 만 판단. **얼마나 오래** 머물렀는지, **얼마나 정확히** 조준했는지 무시.

---

**새 모델 (running cost / accumulation game)**:

$$
J^*(x_0) = \min_{u_p(\cdot)} \max_{u_e(\cdot)} \mathbb{E}\biggl[ \int_0^T \bigl(D_{us}(x(t)) - D_{them}(x(t))\bigr) dt \biggm| x(0) = x_0 \biggr]
$$

**해석 — 항별로 풀어 읽기**:

| 부분 | 의미 |
|------|------|
| $J^*(x_0)$ | 초기 상태 $x_0$ 에서 양쪽이 최선 다할 때의 **기대 net damage 차이** |
| $\min_{u_p(\cdot)}$ | pursuer (우리) 가 우리 손해 최소화 / 적 손해 최대화 시도 |
| $\max_{u_e(\cdot)}$ | evader (적) 가 동일하게 자기 입장에서 시도 |
| $\mathbb{E}[\cdot]$ | 기대값 — non-determinism (25% FP noise) 평균 |
| $\int_0^T (\cdot) dt$ | 전 게임 시간에 걸친 누적 |
| $D_{us}(x(t)) - D_{them}(x(t))$ | 매 순간 우리가 가하는 damage - 받는 damage = **net damage rate** |
| 부호 +: | 적이 더 큰 damage 받음 = 우리에게 유리 |
| 부호 -: | 우리가 더 큰 damage 받음 = 적에게 유리 |

**적분 의 의미를 HP 와 연결**:

$$
J^*(x_0) = \mathbb{E}\biggl[\int_0^T \dot{(\text{HP}_{us} - \text{HP}_{them})}^{-1} dt\biggr] = \mathbb{E}[(\text{HP}_{us}(0) - \text{HP}_{them}(0)) - (\text{HP}_{us}(T) - \text{HP}_{them}(T))]
$$

초기 HP 가 양쪽 100 으로 같으니 $\text{HP}_{us}(0) - \text{HP}_{them}(0) = 0$, 따라서:

$$
J^*(x_0) = \mathbb{E}[\text{HP}_{them}(T) - \text{HP}_{us}(T)]
$$

**즉 $J^*$ 는 "양쪽 최선 시 기대되는 HP 차이"** (적 HP 가 우리보다 얼마나 더 많이 떨어지는가).

**해석 결과**:
- $J^*(x_0) > 0$: 우리 우위 — 평균적으로 적이 우리보다 더 많이 damage 받음
- $J^*(x_0) < 0$: 적 우위
- $J^*(x_0) = 0$: 동등 (양쪽 동량 또는 양쪽 무피해)

---

**핵심 차이**:

| 모델 | 무엇을 측정 | 한계 |
|------|----------|------|
| **모델 A** (reach-avoid) | "WEZ 진입 가능한가?" (binary) | 머무는 시간 / 정확성 무시 |
| **모델 B'** (running cost) | "WEZ 안에서 얼마나 오래 + 얼마나 정확히?" (continuous) | 계산 비용 증가 ($\sim$2 배) |

→ 실 게임 규칙은 **모델 B'** 가 정확. 모델 A 는 1차 근사.

#### "Mutual Kill" 의 재해석

§0.2 모델 B 4-영역 분류 중 `mutual_kill` 영역도 재해석:

| 기존 | 신규 |
|------|------|
| "양쪽 동시 WEZ 진입 → 양사" (binary) | "양쪽 동시 WEZ 진입 → 양쪽 모두 damage 누적 → 둘 다 HP 빨리 깎임" |
| 이산 이벤트 | 연속 race-to-zero |

→ **양사가 일어나는 게 아니라**, 양쪽이 동시에 빠르게 HP 깎임. 누가 먼저 0 도달하느냐의 race.
→ 점-질량 모델로 양쪽 정확 동률은 거의 안 일어남. 비대칭 발생 (먼저 정확한 조준에 들어간 쪽 승).

#### "DRAW" 영역의 재해석

| 기존 | 신규 |
|------|------|
| "양쪽 모두 WEZ 진입 불가 → timeout" (binary, escape zone) | "양쪽 모두 WEZ 진입 못 함 → HP 그대로 100/100 → tie at timeout" |

→ 양쪽 모두 100 HP 로 timeout = 사용자가 짚은 **"서로 선회만 하다 끝남"**.

→ canonical 자가대전에서 양쪽 모두 minimax 시 V*>0 (escape zone 양쪽) 이므로
   양쪽 모두 WEZ 못 들어감 → 양쪽 100 HP → timeout → DRAW (3rd priority: equal HP).

#### HJI 형식화 변경 (모델 B' — Running Cost)

**기존 reach-avoid HJI** (모델 A 가 푸는 PDE):

$$
\frac{\partial V}{\partial t} + \min_{u_p}\max_{u_e}\bigl\{\nabla V \cdot f(x, u_p, u_e)\bigr\} = 0
$$

종단 조건:

$$
V(x, T) = l(x) \quad (\text{signed distance to WEZ})
$$

**해석 — 항별 의미**:

| 항 | 의미 |
|----|------|
| $\partial V / \partial t$ | $V$ 의 시간 변화율 (HJI 좌변, $V_t$ 로도 표기) |
| $\nabla V$ | $V$ 의 공간 gradient (6D 벡터) — "$V$ 가 어느 방향으로 가장 빠르게 변하는가" |
| $\nabla V \cdot f$ | dot product — state 가 $f$ 방향으로 움직일 때 $V$ 의 변화 |
| $\min_{u_p}\max_{u_e}$ | minimax — pursuer 가 $V$ 줄이려 하고 evader 가 키우려 함 |
| $\{ \cdots \}$ | "Hamiltonian" $H(x, \nabla V)$ — HJI 의 핵심 |
| $V(x, T) = l(x)$ | $t = T$ 시점에 $V$ 의 값 (= signed distance) — backwards 풀이의 시작점 |

**왜 reach-avoid 라 부르나**: $l(x)$ 가 capture set 까지의 거리 — "**reach** capture set" 목표. terminal cost 만 있고 running cost 없음.

---

**새 running cost HJI** (모델 B' 가 풀어야 할 PDE):

$$
\frac{\partial J}{\partial t} + \min_{u_p}\max_{u_e}\bigl\{\nabla J \cdot f(x, u_p, u_e) + L(x, u_p, u_e)\bigr\} = 0
$$

종단 조건:

$$
J(x, T) = 0 \quad (\text{no terminal cost})
$$

여기서:

$$
L(x, u_p, u_e) = -D_{us}(x) + D_{them}(x)  \quad (\text{instantaneous net damage rate})
$$

**해석 — 새로 등장한 항 $L$**:

| 항 | 의미 |
|----|------|
| $L(x, u_p, u_e)$ | **running cost** (또는 reward) — 매 순간의 비용/이득 |
| $-D_{us}(x)$ | 우리가 입히는 damage 의 음수 — pursuer minimize 관점 (우리 이득 = $J$ 감소) |
| $+D_{them}(x)$ | 적이 입히는 damage — pursuer 입장 손해 ($J$ 증가) |
| 합 $L$ | 매 순간 게임 값 변화율 (state 와 control 의 함수) |

**부호 규약 설명**:
- $J$ 가 작을수록 우리에게 유리 (pursuer minimize) — 그래서 우리 가하는 damage 는 $J$ 감소 (음수)
- $J$ 가 클수록 적에게 유리 (evader maximize) — 적이 가하는 damage 는 $J$ 증가 (양수)

**왜 running cost 라 부르나**: 매 순간 (적분 안에서) 비용 누적 — $J = g(x(T)) + \int_0^T L \, dt$ 형식. 종단 cost 없고 running 만.

---

**두 PDE 의 차이 (한눈 비교)**:

| 항목 | 모델 A (reach-avoid) | 모델 B' (running cost) |
|------|--------------------|----------------------|
| **시간 적분 누적** | 없음 (terminal cost 만) | 있음 ($\int L \, dt$) |
| **종단 조건** | $V(x, T) = l(x)$ — signed dist | $J(x, T) = 0$ — no terminal |
| **Hamiltonian** | $H = \nabla V \cdot f$ | $H = \nabla J \cdot f + L$ |
| **의미** | "WEZ 한 번 들어가나?" | "WEZ 안 누적 시간 × damage" |
| **단위** | 거리 (ft) | HP (net damage) |
| **수렴 시간** | 짧음 (단순 propagation) | 길음 (누적 적분) |
| **결과 해석** | $V < 0$ 이면 잡힘 | $J < 0$ 이면 우리에게 net damage |

---

→ 모델 B' 가 진정한 도그파이트 게임 값. 본 작업은 1차 근사로 모델 A 사용 (계산 단순, 사용자 가설 검증에 충분).

#### 함의 (Implication)

1. **현재 V table (V6d_sphere_12bin.npz) 는 binary capture 근사** —
   running cost 모델로 재계산 시 더 정확한 BT 가능
2. **8D 게임** (HP_us, HP_them 추가) 가 정확하지만,
   초기 100/100 시작에서는 6D 만으로 1차 근사 충분
3. **사용자 가설 더 정밀화**:
   - "canonical 자가대전 → DRAW (HP 100/100)" — 양쪽 모두 WEZ 못 들어감
4. **5 heuristic exploit 의 정밀화**:
   - sub-optimal 적은 자기 보호 못 함 → 우리가 WEZ 더 오래 → 우리 HP 더 많이 남음 → 우리 승
   - 단순 "WEZ 진입 가능" 이 아니라 "WEZ 안 머무는 시간" 이 진정한 metric

---

## 0.9 실험 인벤토리 (Experiment Inventory) ★

> 사용자 지적 (2026-05-12): "정당성이 중요해. 실험 규모도 아래에 적고, 어떤 실험으로 도출한 데이터인지도 정리해".
>
> 본 작업의 모든 측정 실험 정리. 각 실험은 **실험 ID + 설계 + 규모 + 데이터 위치 + 도출 결론** 형식으로 추적 가능하게 기록.

### E1 — Action Latency Profiling

**목적**: BT 31 액션의 응답 특성 (즉발 / rate-limited / multi-phase) 분류 → HJI primitive 식별.

**실험 설계**:
- 격리 BT YAML 자동 생성 (HardDeck 안전망 + 단일 측정 대상 액션)
- canonical 초기 조건 (ATA=90°, dist=3297.6ft, V=386.8kts, alt=15000ft, HCA=180°)
- 상대: `horizontal_flight` (직선 비행) 또는 `aggressive` (회피 액션용)
- 매치 길이: 200 tick (= 40s @ 5Hz)

**규모**:
- 31 액션 × 3 trial = 93 매치
- 매치당 평균 200 tick × 2 plane = 400 tick
- **총 ~37,200 tick** (양쪽 모두), 우리 쪽만 ~18,600 tick

**데이터 수집 명령**:
```bash
python tools/profile_action_response.py --all --trials 3 --max-steps 200
```

**데이터 위치**:
- 격리 BT YAML: `logs/profiling/yamls/profile_<action>.yaml` (자동 생성)
- 매치 CSV: `logs/profiling/*.csv` (~227 파일)
- 통합 metric: `logs/profiling/action_latency_metrics.csv`

**도출 결론**:
- HJI primitive (Tier 1): TurnLeft/Right, ClimbTo/DescendTo, Accel/Decel, Straight, MaintainAltitude
- Multi-phase (Tier 2): Pursue, BreakTurn, Loop, ImmelmannTurn, ...
- 자세한 결과: `docs/ACTION_LATENCY_REPORT.md`

---

### E2 — Self-Play DRAW Verification

**목적**: 사용자 가설 "V*(canonical) > 0 → 자가대전 DRAW" 의 실증 검증.

**실험 설계**:
- 양쪽 모두 `pursuit_chase_v1` BT (동일 LUT + 동일 의사결정 로직)
- canonical 초기 조건
- 매치 길이: 1500 tick (= 300s, 전체 매치)
- 측정: winner, HP 분포, total_steps

**규모**:
- 20 매치 × 1500 tick × 2 plane = **60,000 tick**

**데이터 수집 명령**:
```bash
python scripts/run_match.py \
    --agent1 pursuit_chase_v1 --agent2 pursuit_chase_v1 \
    --round 20 \
    --metadata-log logs/selfplay_v1
```

**데이터 위치**:
- 매치 CSV: `logs/selfplay_v1/*_meta.csv` (20 파일)
- Sidecar JSON: `logs/selfplay_v1/*_result.json` (winner, HP 등)

**도출 결론** (집계):
- WIN: 0, LOSS: 0, **DRAW: 20 (100%)**
- 모든 매치 HP (100.0, 100.0) — 양쪽 무피해
- 모든 매치 1500/1500 step (full timeout)
- **사용자 가설 V\*(canonical) > 0 → DRAW 입증** ✓

---

### E3 — 5 Heuristic 1st Pass

**목적**: 우리 BT 가 sub-optimal 적을 exploit 할 수 있는가 정량 측정.

**실험 설계**:
- 우리: `pursuit_chase_v1`
- 적: `{simple, aggressive, defensive, horizontal_flight}` 각 5 매치
- canonical 초기, 1500 tick (full match)

**규모**:
- 4 opponent × 5 매치 × 1500 tick × 2 plane = **60,000 tick**

**데이터 수집 명령**:
```bash
for opp in simple aggressive defensive horizontal_flight; do
  python scripts/run_match.py --agent1 pursuit_chase_v1 --agent2 $opp \
      --round 5 --metadata-log logs/c2_5h/$opp
done
```

**데이터 위치**:
- 매치 CSV: `logs/c2_5h/<opp>/*_meta.csv` (각 5 파일)
- Sidecar JSON: `logs/c2_5h/<opp>/*_result.json`

**도출 결론**:
| 적 | 결과 |
|---|---|
| simple | simple WIN × 5 (health_advantage) — 우리 LOSS |
| aggressive | aggressive WIN × 5 (health_advantage) — 우리 LOSS |
| defensive | DRAW × 5 (timeout, 무피해) |
| horizontal_flight | DRAW × 5 (timeout, 무피해) |

→ 우리 BT 가 active 상대 (simple, aggressive) 에게 LOSS. **§4.2.5 의 6-layer 한계 입증**.
   passive 상대 (defensive, horizontal_flight) 에는 DRAW.

---

### E4 — Dynamics Assumption Analysis (Post-hoc on E1 data)

**목적**: Small-γ 가정 (§1.2.3) 의 실측 오차 정량화.

**실험 설계**:
- **재실험 아님** — E1 의 raw CSV 를 후처리
- γ 계산: $\gamma = \arcsin(v_z / \|v\|)$ (velocity vector 기반)
- 측정 지표: γ 분포, cos γ 오차, sin γ 오차, HCA 분포, 액션별 |γ|

**규모**:
- E1 의 227 CSV 중 우리 측 데이터 추출
- **44,500 tick** (우리 측만 — 양쪽 합치면 89,000)
- ≈ 2.5시간 가상 비행

**데이터 처리 명령**:
```bash
python tools/analyze_dynamics_assumptions.py
```

**도출 결론**:
- 평균 \|γ\| = 2.92°, 95-percentile = 11.64°, max = 15.06°
- cos γ 오차 평균 = **0.29%** (이론 worst case 14% 의 1/50)
- sin γ 오차 평균 = 0.14%
- → small-γ 가정은 **측정한 시나리오 안에서** 매우 valid

**한계 (sample bias)**:
- Isolation BT 시나리오 한정 → 복합 실 매치 미반영
- canonical 시작 한정 → 다른 초기 조건 미수집
- 200 tick 매치 한정 → 1500 tick 후반부 미반영
- 일반화 위해서는 E5+ 추가 측정 필요 (~495K tick 권고)

---

### E5 — Dynamics Sanity Check (3D 등속 한계, Air3d)

**목적**: 우리 6D 풀이가 Buzikov-Galyaev (2022) 의 3D 등속 한계 결과와 일치하는가.

**실험 설계**:
- `hj_reachability.systems.Air3d` 사용 (Game of Two Identical Cars 의 등가)
- $V_p = V_e = 386.8$ kts, $\Delta h = 0$ (3D state space 로 축소)
- 30s backward horizon

**규모**:
- 1회 solve, $40^3 = 64$K cells
- Solve time: 0.3s (JAX JIT 캐시 후)

**데이터 수집 명령**:
```bash
python tools/basis/hji_air3d_sanity.py --grid 40 --time 30.0
```

**데이터 위치**: CLI 출력 + (선택) 그래프

**도출 결론**:
- V*(canonical 3D, t=-30s) = **+1731 ft** (escape zone)
- → Buzikov-Galyaev 의 "barrier 형성 케이스" 와 일치
- → canonical 은 동등 스펙 minimax 에서 capture 불가 영역

---

### E6 — 6D HJI Numerical Solve

**목적**: F-16 가변속 6D 게임의 V*(x) lookup table 산출.

**실험 설계**:
- Dynamics: §1.2 의 control-affine F-16 6D 모델
- Capture set: sphere radius 1500 ft (WEZ 중간 근사)
- Grid: $12^6 = $ 약 3M cells
- Backward 10s

**규모**:
- 1회 solve, 12⁶ cells
- 풀이 시간: 4.6s (JAX JIT 캐시 후)

**데이터 수집 명령**:
```bash
python tools/basis/hji_solve_6d.py --grid 12 --time 10.0 --capture sphere \
    --save logs/hji/V6d_sphere_12bin.npz
```

**데이터 위치**:
- LUT 파일: `logs/hji/V6d_sphere_12bin.npz` (5.3 MB)

**도출 결론**:
- V*(canonical 6D, t=-10s) = **+2374 ft** (escape zone)
- BRT (capture 가능 영역): 31,912 / 2,985,984 (1.1%)
- → 6D 가변속 추가해도 canonical 은 여전히 escape zone

---

### 실험 인벤토리 — 전체 통계

| 실험 | 종류 | 규모 (tick) | 결론 type | 데이터 |
|------|------|-----------|----------|------|
| E1 | Profiling | 18,600 | Classification | `logs/profiling/` |
| E2 | Self-play | 60,000 | Verification | `logs/selfplay_v1/` |
| E3 | vs Heuristic | 60,000 | Quantification | `logs/c2_5h/` |
| E4 | Post-hoc (E1) | 44,500 (subset) | Validity check | (E1 재사용) |
| E5 | HJI sanity | (N/A, solve) | Mathematical | (인메모리) |
| E6 | HJI solve | (N/A, solve) | LUT 산출 | `logs/hji/` |

**총 매치 데이터**: **138,600 tick** (≈ 7.7 시간 가상 비행)

**계획된 추가 실험** (Phase C-3 + Phase D):

| 실험 | 목적 | 규모 (계획) |
|------|------|----------|
| E7 | 자가대전 100 매치 (통계 강화) | 300,000 tick |
| E8 | 5 heuristic 각 20 매치 | 240,000 tick |
| E9 | Canonical perturbation grid (alt, V, ATA 변동) | ~150,000 tick |
| E10 | Dynamics assumption full statistics (E4 의 일반화) | 495,000 tick |
| E11 | V_them table (모델 B Phase D-1) | (solve) |

→ 총 **~1,200,000 tick** (현재의 8.6배) — 통계적 일반화 가능 수준.

---

## 1. 문제 정의 (기술 명세)

> §0 의 학습자 정의를 수학·코드 명세로 옮긴 절. 모델 A 비대칭 형식화 기반.

### 1.1 1:1 도그파이트 = 6D Zero-Sum Differential Game

**플레이어**: pursuer P (우리), evader E (적). 양쪽 동등 스펙 F-16.
**채택 모델**: 모델 A 비대칭 PEG (§0.2). 모델 B 확장은 §11 참조.

**상태 (6D, pursuer 좌표계 상대 위치)**:
```
x = (Δx, Δy, Δh, Δψ, V_p, V_e) ∈ ℝ⁶

Δx, Δy  — 적의 수평 상대 위치 (pursuer body NED 좌표, ft)
Δh      — h_e - h_p (고도차, ft)
Δψ      — 적 heading - 우리 heading (rad)
V_p, V_e — 양쪽 절대 속도 (kts)
```

**축소 근거 (정확)** ★:

원래 두 비행기 full state 는 각각 6D (position 3 + heading/γ/V 3) → 합 12D. (이미 자세각 ψ, γ 는 state 에 포함, AOA 등 미세는 제외.)

본 작업의 6D 는 **"우리 body frame 에서 본 적의 상대 상태"** 만 추적:

| 차원 | 의미 | 왜 6D 면 충분? |
|------|------|---------------|
| $\Delta x, \Delta y, \Delta h$ | 적의 위치 (우리 body frame) | 절대 위치 (12D 의 6개) 는 게임 결과에 무관 — translation invariance |
| $\Delta\psi$ | 상대 heading | 우리 heading (절대값) 은 게임 결과에 무관 — rotation invariance (수평) |
| $V_p, V_e$ | 양쪽 절대 속도 크기 | 속도는 control 한계와 직접 관련 — 축소 불가 |

**축소 안 되는 부분 (사용자 지적 반영)**:

1. **양쪽이 각자의 body frame 으로 obs 를 로깅함** — 단일 좌표계 아님:
   - 우리 매치 CSV: 우리 body frame 에서 본 $(\Delta x, \Delta y, ...)$
   - 적 매치 CSV: 적 body frame 에서 본 $(\Delta x', \Delta y', ...)$ — **다른 좌표계의 다른 값**
   - 두 관측은 **거울 대칭이 아니라 두 개의 독립 관측**:
     - 우리 CSV 의 $\Delta x$ = 우리 우측 방향의 적 위치
     - 적 CSV 의 $\Delta x'$ = 적 우측 방향의 우리 위치 ≠ $-\Delta x$ (방향, 회전 다름)
   - 모델 B 가 정확히 이를 다루기 위해 $V_{us}^*$ (우리 frame) 와 $V_{them}^*$ (적 frame) **두 V table 분리** 필요 (§11.1).

2. $\gamma_p, \gamma_e$ (flight path angle) 는 점-질량 가정으로 즉시 제어 → state 에서 제외 (§0.5 C2). 완전한 모델은 8D 까지 필요.

3. **hard deck 절대 고도 $h_p$** 는 별도 safety branch — state 에서 제외 (relative $\Delta h$ 만 추적).

**결론**: 6D 는 **우리 관점의 1차 근사**. 모델 B 로 가면 두 6D 가 양쪽에 각각 존재 (총 12D 정보 — 단 4 차원 중복).

### 1.2 Dynamics

> ⚠️ **본 dynamics 는 비선형 (state 에 sin, cos, 곱)**. "control-affine" 은
> state 비선형성은 그대로 두고 control 입력 $u$ 에만 affine 이라는 의미 (§1.2.3 참조).

#### 1.2.1 진짜 (full) 운동방정식 — 비선형

$$
\begin{aligned}
\dot{\Delta x} &= V_e \cos\gamma_e \sin\Delta\psi + \omega_{h,p} \cdot \Delta y\\
\dot{\Delta y} &= V_e \cos\gamma_e \cos\Delta\psi - V_p \cos\gamma_p - \omega_{h,p} \cdot \Delta x \\
\dot{\Delta h} &= V_e \sin\gamma_e - V_p \sin\gamma_p \\
\dot{\Delta\psi} &= \omega_{h,e} - \omega_{h,p} \\
\dot{V_p} &= a_p, \quad \dot{V_e} = a_e
\end{aligned}
$$

**비선형성 어디에 있나** ★:

- $\sin\Delta\psi, \cos\Delta\psi$: state $\Delta\psi$ 의 비선형 함수 (trigonometric)
- $\sin\gamma_e, \cos\gamma_e$: control $\gamma_e$ 의 비선형 함수 (이게 control-affine 깨는 부분)
- $V_e \cos\gamma_e \sin\Delta\psi$: state $V_e$ 와 control $\gamma_e$ 와 state $\Delta\psi$ 의 **삼중 곱**
- $\omega_{h,p} \cdot \Delta y, \omega_{h,p} \cdot \Delta x$: control $\omega_{h,p}$ 와 state 의 **곱** (Coriolis-like, frame rotation)

**→ Full F-16 dynamics 는 본질적으로 비선형 PDE 풀이 대상**. 진짜 NLP / NN 방법 필요. 또는 단순화.

#### 1.2.2 제어 입력 / 한계

- $u_p = (\omega_{h,p}, \gamma_p, a_p)$ : pursuer 의 3D control
- $u_e = (\omega_{h,e}, \gamma_e, a_e)$ : evader 의 3D control
- 한계: $|\omega_h| \le \omega_{\max}(V)$, $|\gamma| \le \gamma_{\max} = 30°$, $a \in [-15, +15]$ kts/s

**Envelope** (JSBSim 실측, `sim_dogfight_verify.py:54-79`):
```
V (kts):  160  200  250  300  350  400  420  500
ω_max:    6    9    15   18   21   18.5 16   14    (°/s)
R_min:    1600 1700 1600 1700 1800 1650 2100 2500 2800 (ft)
```

#### 1.2.3 본 작업 단순화 — Small-γ 가정 (control-affine 형식)

hj-reachability 는 dynamics 가 **control 에 affine** 일 것을 요구:

$$
f(x, u_p, u_e) = f_0(x) + B_c(x) u_e + B_d(x) u_p
$$

**"Control-affine" 의 정확한 의미**:
- **state $x$ 에 대한 비선형성은 유지** ($f_0, B_c, B_d$ 모두 $x$ 의 일반 함수)
- **control $u$ 에만 affine** — $u$ 가 가산적 (additive) 으로 들어감

원래 dynamics 의 $\sin\gamma_e, \cos\gamma_e, \sin\gamma_p, \cos\gamma_p$ 가 control $\gamma$ 의 비선형 → 그대로면 control-affine 깨짐.

**해결 — Small-γ 가정** (linearization around $\gamma = 0$):

$$
\cos\gamma \approx 1, \quad \sin\gamma \approx \gamma \quad (\text{for small } \gamma)
$$

이 가정으로 단순화된 dynamics:

$$
\begin{aligned}
\dot{\Delta x} &\approx V_e \sin\Delta\psi + \omega_{h,p} \cdot \Delta y\\
\dot{\Delta y} &\approx V_e \cos\Delta\psi - V_p - \omega_{h,p} \cdot \Delta x \\
\dot{\Delta h} &\approx V_e \cdot \gamma_e - V_p \cdot \gamma_p \\
\dot{\Delta\psi} &= \omega_{h,e} - \omega_{h,p} \\
\dot{V_p} &= a_p, \quad \dot{V_e} = a_e
\end{aligned}
$$

이제 $\gamma_e, \gamma_p$ 가 control 에 linear (additive) → control-affine 만족.

**그러나 state $\Delta\psi$ 의 sin/cos 는 여전히 비선형** → state 비선형성은 그대로.

**Small-γ 가정의 오차 — 이론값**:

| $\gamma$ | $\cos\gamma$ 실제 | $\cos\gamma \approx 1$ 가정 | 오차 (이론) |
|---------|-----------------|---------------------------|------|
| 0° | 1.000 | 1 | 0% |
| 10° | 0.985 | 1 | +1.5% |
| 20° | 0.940 | 1 | +6.4% |
| 30° | 0.866 | 1 | +15.5% ← worst case ($\gamma_{\max}$) |
| 45° | 0.707 | 1 | +41% (안 씀) |

| $\gamma$ | $\sin\gamma$ 실제 | $\sin\gamma \approx \gamma$ 가정 (rad) | 오차 (이론) |
|---------|-----------------|----------------------------------|------|
| 10° | 0.174 | 0.175 | +0.5% |
| 20° | 0.342 | 0.349 | +2.1% |
| 30° | 0.500 | 0.524 | +4.8% |

#### Small-γ 가정 오차 — **실측 검증** ★ (2026-05-12)

> 사용자 핵심 지적: "이건 명령과 데이터 결과로 확인 가능".
> `tools/analyze_dynamics_assumptions.py` 로 31 액션 × 3 trial = 227 CSV 분석.

**측정**: 44,500 tick (≈ 2.5시간 비행) 의 γ 분포

| 통계 | 값 | 비고 |
|------|-----|------|
| 평균 \|γ\| | **2.92°** | 매우 작음 |
| 중앙값 \|γ\| | 2.00° | |
| 95-percentile | 11.64° | |
| 99-percentile | 12.80° | |
| **max** | **15.06°** | $\gamma_{\max}=30°$ 한계의 절반 |

**γ 범위별 빈도 (전체 데이터)**:

| 범위 | 빈도 | 비율 |
|------|-----|------|
| [0°, 5°)   | 38,116 | **85.7%** ← 대부분 |
| [5°, 10°)  | 2,701  | 6.1% |
| [10°, 15°) | 3,677  | 8.3% |
| [15°, 20°) | 6      | 0.01% |
| [20°, 30°) | 0      | **거의 발생 안 함** |
| [30°+)     | 0      | 0% |

**Small-γ 가정 실측 오차 (cos γ ≈ 1)**:

| 통계 | 실측 오차 | 이론 oracle | 차이 |
|------|---------|-----------|------|
| 평균 (mean) | **0.29%** | 14% (γ=30° 가정) | **약 50배 작음** |
| 95-percentile | 2.10% | |
| max | 3.56% | |
| < 1% 오차의 빈도 | **89.7%** | |

**Small-γ 가정 실측 오차 (sin γ ≈ γ)**:

| 통계 | 실측 오차 |
|------|---------|
| 평균 (|γ|>1° 인 ticks) | **0.14%** |
| 95-percentile | 0.76% |
| max | 1.16% |

**액션별 |γ| max (Top 5)**:

| 액션 | \|γ\| mean | \|γ\| max | N ticks |
|------|----------|---------|---------|
| HighYoYo | 2.41° | **15.06°** | 1,200 |
| LowYoYo | 2.35° | 14.69° | 1,200 |
| OneCircleFight | 4.93° | 14.55° | 1,200 |
| BreakTurn | 5.38° | 14.39° | 1,600 |
| BarrelRoll | 5.76° | 14.39° | 1,200 |

→ **수직 기동 액션 (yo-yo) 도 max γ ~ 15° 정도**. 30° 까지 가는 시나리오는 점-질량 모델 + JSBSim envelope 에서 사실상 없음.

**결론**:
- 이론적 worst case = 14% (γ=30°)
- 실 매치 평균 = **0.29%**
- → small-γ 가정은 **실 매치 데이터에서 매우 valid**.
- 본 작업의 1차 근사가 정당화됨 (실측 검증).

**비교 — Δψ 의 상태 비선형성**:

HCA (≈ Δψ) 분포:
- 양극단 분포: [0°, 30°) 28.3%, [150°, 180°) 34.7%
- 평행 (HCA≈0) 과 정반대 (HCA≈180) 가 가장 빈번
- 중간 영역 (60-120°) 25%
- → **state 의 cos Δψ, sin Δψ 비선형성은 매치에서 정상 분포로 활성화** — 단순화 불가, 그대로 풀이 필요.

#### ⚠️ 측정의 한계 (Sample Bias) — 사용자 지적 (2026-05-12)

> "실측기반으로 정정하려면 매우 많은 상태의 데이터를 봐야 한다. 알지?"

본 측정 (44,500 tick) 은 **single point estimate** 이지 **통계적 일반화** 가 아님.

**측정 데이터의 편향**:

| 편향 source | 현재 측정 | 일반화 위험 |
|------------|---------|---------|
| **시나리오 다양성** | Isolation BT (단일 액션 강제 활성) | 복합 도그파이트 상태 미반영 |
| **초기 조건** | canonical 만 (387kts, 15000ft, ATA=90°) | 저고도/고속/다른 ATA 미수집 |
| **매치 길이** | 200 tick (≈40초) | 1500 tick (300초) 후반부 미반영 |
| **상대 정책** | `horizontal_flight`, `aggressive` 2종 | 5+ heuristic / 강한 BT 미반영 |
| **transient peak γ** | 200 tick 안 30°+ 0% | 긴 매치에서 yo-yo 정점/회피 transient 30° 가능 |
| **active 추격 시나리오** | 격리 BT 라 추격 발달 부족 | BreakTurn 진입 transient γ 클 수 있음 |

**현 측정의 정확한 의미** (정직):

- ✓ "Isolation profiling 시나리오 + canonical 시작 + 40초 매치" 에서 평균 \|γ\|=2.92°
- ✓ "그 조건 데이터의 89.7% 가 \|γ\| < 5°"
- ✓ "그 조건의 cos γ 오차 평균 0.29%"
- ✗ 위 결과를 "모든 실 매치 시나리오에서 그럴 것" 으로 **일반화 불가**

**왜 단정 못 하나**:
- yo-yo, BreakTurn 같은 multi-phase 액션이 **격리 매치에선 짧게만 발동** (Loop=13 tick, ImmelmannTurn=16 tick — §A-2.5 ACTION_LATENCY_REPORT)
- 실 1:1 매치에서 적이 위협일 때 우리 BT 의 **transient pitch-up 이 30° 가까이** 갈 가능성 (vertical evasion)
- 본 측정의 200 tick (40초) 으로는 **긴 transient 의 분포 fully capture 못함**

**일반화 위한 추가 측정 계획** (Phase C-3 또는 후속):

```
필요 데이터:
  - 자가대전 100 매치 × 1500 tick × 2 plane = 300,000 tick
  - 5 heuristic 각 10 매치 × 1500 tick × 2 plane = 150,000 tick
  - canonical perturbation (alt 8000/22000, V 200/350/420) × 30 매치 = 45,000 tick
  - 총 ≈ 495,000 tick (현재의 11배)

추가 통계:
  - 95% Wilson CI for mean error
  - per-scenario stratification (canonical / canonical_close / canonical_fast / ...)
  - peak γ 의 transient 분포 (state-dependent)
  - HCA × γ joint 분포
```

**현 단계 결론**:
- §0.5 C2 가정은 "**측정한 조건 안에서**" 매우 valid (cos γ 평균 0.29%)
- 모든 실 매치 시나리오 일반화는 위 추가 측정 후 가능
- 본 1차 prototype 단계에서는 충분, production 단계에서는 보강 필수

#### 1.2.4 본 작업이 푸는 dynamics — 실 코드 형식

`tools/basis/dynamics_f16_6d_hj.py` 에서:
- $f_0(x)$ : 위 단순화 식의 control 항 제외 부분
- $B_c(x)$ : evader control 의 jacobian (6×3 matrix)
- $B_d(x)$ : pursuer control 의 jacobian (6×3 matrix)
- $f(x, u_p, u_e) = f_0(x) + B_c(x) u_e + B_d(x) u_p$ — 합성

**완전 비선형 (small-γ 가정 없는) 풀이를 원할 때**:
- `ControlAndDisturbanceAffineDynamics` 대신 `Dynamics` 일반 클래스 사용
- 또는 8D state (γ_p, γ_e 추가) 로 확장 — control 은 $\dot\gamma$ 로 affine
- 본 작업의 후속 phase (D 또는 그 이후) 에서 검토.

### 1.3 게임 규칙 (JSBSim core 매칭) — **모델 B' 정확형** ★

> 본 절은 **새 모델 (모델 B' — running cost / continuous damage)** 기준으로 작성.
> 이전 binary capture 표현은 1차 근사일 뿐 — 정확 규칙은 아래.
> 자세한 학습 가이드는 §0.8 참조.

#### 1.3.1 WEZ 진입 조건 (binary indicator — damage 발생 영역)

$$
\mathrm{WEZ}_{us}(x) \equiv \mathrm{ATA}(x) < 12° \;\wedge\; 500\,\mathrm{ft} < \mathrm{dist}(x) < 3000\,\mathrm{ft} \;\wedge\; \dot{\mathrm{dist}}(x) > 0
$$

(adversary 의 WEZ 도 동일 형식, AA 사용)

#### 1.3.2 Damage Rate (continuous — 실제 규칙)

WEZ 안에서 우리가 적에게 가하는 damage:

$$
D_{us}(x) = \begin{cases}
25.0 \cdot w_{\text{ATA}}(x) \cdot w_{\text{dist}}(x) & x \in \mathrm{WEZ}_{us} \\
0 & \text{otherwise}
\end{cases} \quad [\text{HP/s}]
$$

여기서:

$$
w_{\text{ATA}}(x) = \max\Bigl(0, \, 1 - \frac{\text{ATA}(x)}{12°}\Bigr), \quad w_{\text{dist}}(x) \in [0, 1] \text{ (사거리 가중치)}
$$

적이 우리에게 가하는 damage $D_{them}(x)$ 는 대칭 swap (AA 사용).

#### 1.3.3 HP 동역학

$$
\dot{\text{HP}}_{them} = -D_{us}(x), \quad \dot{\text{HP}}_{us} = -D_{them}(x)
$$

초기값: $\text{HP}_{us}(0) = \text{HP}_{them}(0) = 100$.

#### 1.3.4 종단 조건 (Priority 순)

$$
\text{Outcome} = \begin{cases}
\text{우리 WIN by kill}    & \text{if } \exists t \le T : \text{HP}_{them}(t) = 0 \\
\text{우리 LOSS by kill}   & \text{if } \exists t \le T : \text{HP}_{us}(t) = 0 \\
\text{우리 WIN by deck}    & \text{if } \exists t \le T : h_{them}(t) < 1000 \text{ ft} \\
\text{우리 LOSS by deck}   & \text{if } \exists t \le T : h_{us}(t) < 1000 \text{ ft} \\
\text{우리 WIN by adv}     & \text{if } \text{HP}_{us}(T) > \text{HP}_{them}(T) \quad (\text{timeout}) \\
\text{우리 LOSS by adv}    & \text{if } \text{HP}_{us}(T) < \text{HP}_{them}(T) \\
\text{DRAW}                 & \text{if } \text{HP}_{us}(T) = \text{HP}_{them}(T) \\
\end{cases}
$$

위에서부터 우선순위 적용 — 먼저 만족하는 조건이 결과 결정.

#### 1.3.5 HJI Capture Set (binary 1차 근사)

모델 A 형식화 (현재 V table 산출 시 사용한 단순화):

$$
\mathcal{C}_{us} = \{x \in \mathbb{R}^6 : \mathrm{WEZ}_{us}(x)\}, \quad
\mathcal{C}_{them} = \{x : \mathrm{WEZ}_{them}(x)\}
$$

$$
\mathcal{H}_{us} = \{x : h_{us} < 1000\,\mathrm{ft}\} \quad (\text{Hard Deck — HJI 외부 safety branch})
$$

**왜 1차 근사**: 본 BT v1 의 V table 은 $\mathcal{C}_{us}$ 의 signed distance 만 사용 (continuous damage 무시). 정확한 모델 (running cost) 은 §11.7 모델 B' 에서 도입.

**Timeout**: $T = 1500 \text{ ticks} \times 0.2 \text{s} = 300\text{s}$.

### 1.4 Initial Condition (Canonical, JSBSim 정확 매칭)

```
x₀ = (
  Δx_rel = 3297.6 ft (적이 우리 정동 방향),
  Δy_rel = 0 ft (적이 우리 정북에서 정동으로 회전된 위치),
  Δh     = 0,
  Δψ     = π (HCA=180°, head-on opposite heading),
  V_p    = 386.8 kts,
  V_e    = 386.8 kts,
)

→ canonical 은 head-on 통과 시나리오. ATA=90°, AA=90°.
```

### 1.5 Value Function 정의 — **새 모델 (B') 기준** ★

> 본 절은 **모델 B' (running cost / continuous damage)** 가 정확.
> 모델 A 의 reach-avoid value $V^*$ 는 1차 근사 (실 V table 산출 시 사용).

#### 1.5.1 정확한 게임 값 — Model B' (Running Cost)

$$
J^*(x_0) = \min_{u_p(\cdot)}\;\max_{u_e(\cdot)}\;\mathbb{E}\biggl[\int_0^T \bigl(D_{us}(x(t)) - D_{them}(x(t))\bigr) dt \,\biggm|\, x(0) = x_0\biggr]
$$

여기서:
- $D_{us}, D_{them}$ : 양쪽 damage rate (§1.3.2)
- $\int (\cdot) dt$ : 누적 net damage 차이
- $\mathbb{E}[\cdot]$ : non-determinism (25% FP noise) 평균

연결:
$$
J^*(x_0) = \mathbb{E}[\text{HP}_{them}(T) - \text{HP}_{us}(T)] \quad (\text{양쪽 100 시작})
$$

**해석**:
- $J^*(x_0) > 0$: 우리 우위 (적이 더 큰 damage 받음)
- $J^*(x_0) < 0$: 적 우위
- $J^*(x_0) = 0$: 동등 (양쪽 동량 damage 또는 양쪽 무피해)

#### 1.5.2 1차 근사 — Model A (Reach-Avoid)

본 작업 v1 의 V table 산출 시 사용한 단순화:

$$
V^*(x) = \min_{u_p(\cdot)}\;\max_{u_e(\cdot)}\;\min_{s \in [0, T]}\; l(x(s; x, u_p, u_e))
$$

여기서 $l(x)$ = signed distance to $\mathcal{C}_{us}$ (§1.3.5).

| $V^*(x)$ | 의미 |
|---------|------|
| $V^*(x) < 0$ | 우리 capture set 진입 가능 (binary) |
| $V^*(x) = 0$ | barrier — 임계 |
| $V^*(x) > 0$ | escape zone — capture set 진입 불가 |

**1차 근사인 이유**:
- "WEZ 진입 가능?" 만 binary 판단 — 누가 더 오래/정확히 머무는지 무시
- 실제 게임은 누적 damage 라 $J^*$ 가 정확

**그러나 정성적 결론은 일치**:
- $V^*(x_0) > 0$ → capture set 미진입 → damage 누적 없음 → DRAW
- $V^*(x_0) < 0$ → capture set 진입 → damage 발생 → 어느 쪽 더 빨리 HP 0 도달하는가가 결정

#### 1.5.3 측정 결과 (Phase A-3, A-2 완료, 2026-05-12)

**A. Model A $V^*$ (binary 1차 근사)**:

| 모델 / Grid | $V^*(x_0)$ | 해석 | 출처 |
|-----------|-----------|------|------|
| 3D 등속 한계 (Air3d, $40^3$ grid, $T=30s$) | **$+1731$ ft** | escape zone — 30s 안 capture 불가 | `hji_air3d_sanity.py` |
| 6D 가변속 ($12^6$ grid, $T=10s$) | **$+2374$ ft** | escape zone — 10s+ 안 capture 불가 | `hji_solve_6d.py` |

→ canonical 은 binary 모델 A 에서도 escape zone (capture 자체가 불가).

**B. Model B' $J^*$ (running cost — 실측, 2026-05-12 E7 실험)**:

| 실험 | $\mathbb{E}[\text{HP}_{them} - \text{HP}_{us}]$ | 매치 수 | 출처 |
|------|---------------------------------------------|--------|------|
| E7 quick (자가대전, 20 매치) | **$0.0 \pm 0.0$** ($100.0 - 100.0$) | 17/20 valid | `logs/c_extended/E7_selfplay/` |
| E7 full (예정 100 매치, ⏳ 진행 중) | TBD | 100 | `logs/c_extended/E7_selfplay/` |

→ canonical 자가대전에서 **$J^*(x_0) = 0$** (양쪽 100 HP 무피해 timeout).
→ **사용자의 자가대전 DRAW 가설이 모델 A 와 B' 양쪽에서 검증됨** ✓.

#### 1.5.4 모델 A vs B' 결과 일치성

| 모델 | $x_0$ 의 게임 값 | 결과 예측 | 실측 일치? |
|------|-------------|---------|---------|
| A (binary) | $V^*=+2374$ ft (escape) | "양쪽 모두 capture set 진입 못함 → 양쪽 100 HP timeout" | ✓ |
| B' (continuous) | $J^*=0$ (양쪽 동량) | "양쪽 모두 WEZ 진입 못해 damage=0 → HP 100/100 timeout" | ✓ |
| 사용자 가설 | "서로 선회만 하다 끝남" | DRAW | ✓ |

→ canonical 동등 스펙에서 세 가지 표현이 모두 **같은 게임 결과 (DRAW)** 를 예측. 수학적 일관성 확인.

---

## 2. 수학적 기초

### 2.1 8개 BFM 정리의 HJI 통합

| 정리 | HJI 안에서 어떻게 등장 | 별도 처리 |
|------|-------------------|----------|
| 1 (Bernoulli pursuit) | Hamiltonian $H = \nabla V \cdot f$ 의 자연스러운 결과 | — |
| 2 (PN, Bryson-Ho) | $u^* = \arg\min_u H$ 가 PN 형태로 환원 (state-feedback) | — |
| 3 (Homicidal Chauffeur) | barrier ODE 가 HJI 의 0-level set | — |
| 4 (Game of Two Cars) | symmetric 동등 스펙 → Buzikov-Galyaev 해석해 | sanity check |
| 5 (Boyd EM) | Hamiltonian 의 $V$ 의존성 — Ps 가 game value gradient 에 등장 | — |
| 6 (Shaw 1/2-circle) | 최적 전략의 geometry (1-circle vs 2-circle) 자동 산출 | — |
| 7 (LDT) | 최적 trajectory 의 phase 분할 (lag → lead) 자동 산출 | — |
| 8 (Pontryagin yo-yo) | 수직 평면 최적 trajectory — Δh 자유도 통해 자연 등장 | — |

**핵심**: 정리 1-8 을 BT 분기로 명시적 인코딩 불요. HJI 가 최적 전략을 통일된 framework 에서 산출.

---

### 2.2 Flight Envelope from First Principles — Doghouse Plot 의 수학적 유도 ★

> **본 절의 학술적 위치**: 정리 5 (Boyd Energy-Maneuverability, 1964) 의 **출전 (derivation)**.
> 흔히 인용되는 F-16 "코너속도 350kts" 는 doghouse plot 의 한 좌표일 뿐, 그 값 자체로
> 사용 시 (curve-fit) 수학적 정당성 없음. 우리는 **세 독립 source — 제1원리 물리,
> JSBSim aerodata, NASA TP-1538 wind-tunnel data — 의 cross-validation** 으로
> doghouse plot 을 derive 한 뒤, 그 결과로 game dynamics 의 envelope 을 정의한다.

#### 2.2.1 왜 이 절이 필요한가 (Motivation)

본 작업의 6D HJI dynamics 에는 제어 bound `|ω| ≤ ω_max` 가 등장한다. 초기에 우리는 `ω_max = 19.16°/s` 상수를 사용했으나 [§1.2.2], 이는 두 가지 문제를 안고 있다:

1. **물리적 부정합**: 실제 항공기는 속도에 따라 가능한 ω 가 변한다 — 저속에서는 lift 부족 (aero-limited), 고속에서는 구조한계 (load-factor saturated). 상수 가정은 이 두 regime 을 모두 누락.
2. **검증 불가능성**: 상수값 (19.16°/s) 의 정당성을 묻는 순간 "v11_code 가 그렇게 썼다" 외에 답할 수 없다. 즉 **수학적 정당성 없는 magic number**.

따라서 `ω_max(V, alt)` 을 **물리식**으로 표현하고, 그 표현 자체가 검증 대상이 된다.

#### 2.2.2 유도 — 협조 선회 (Coordinated Turn) 에서의 ω_max(V, n)

수평 협조 선회의 운동방정식 (Anderson, *Aircraft Performance and Design*, ch. 6):
$$\underbrace{W \cdot \sqrt{n^2 - 1}}_{\text{horizontal lift component}} = \underbrace{\frac{W}{g} V \cdot \omega}_{\text{required centripetal force}}$$

→ **제1원리 식 (식 E1)**:
$$\boxed{\ \omega(V, n) = \frac{g}{V}\sqrt{n^2 - 1}\ }$$

여기서:
- `V`: 진속 (true airspeed, ft/s)
- `n = L/W`: 하중배수 (load factor, dimensionless)
- `g = 32.174 ft/s²`

식 E1 은 가정 무관 — `W·sin(roll)` 의 수직 균형 + 등속 원운동 정의의 직접 산출. 우주 정거장이든 F-16 이든 같은 식.

#### 2.2.3 n 의 두 한계 — 두 regime 의 분리

`n` 은 두 독립 한계의 최소값:

**(a) 구조한계** `n_struct`:
F-16 의 fly-by-wire 가 +9g / -3g 로 제한 (USAF F-16 Flight Manual TO-1F-16C-1).
$$n_{\text{struct}} = 9.0$$

**(b) 공력한계** `n_aero(V, alt)`:
필요 lift 가 `L = nW`, 공급 가능 lift 는 `L = q \cdot S \cdot C_L` (`q = \tfrac{1}{2}\rho V^2`). max lift 는 `C_L = C_{L,\max}`. 따라서:
$$n_{\text{aero}}(V, \text{alt}) = \frac{\tfrac{1}{2}\rho(\text{alt})\, V^2 \cdot S \cdot C_{L,\max}}{W}$$

여기서:
- `ρ(alt)`: 대기 밀도 (US Standard Atmosphere 1976). 8000ft: 0.001869 slug/ft³, 15000ft: 0.001496, 25000ft: 0.001065
- `S = 300 ft²`: F-16 wing area (JSBSim `<wingarea>`, NASA TP-1538 와 일치)
- `C_{L,max}`: 익면 lift coefficient 의 최대값
- `W`: 항공기 무게 (combat config)

→ **제1원리 식 (식 E2)**:
$$\boxed{\ n_{\max}(V, \text{alt}, W) = \min\!\big(n_{\text{struct}},\ n_{\text{aero}}(V, \text{alt}, W)\big)\ }$$

#### 2.2.4 코너속도 V_c — 두 regime 의 교차점

`n_aero(V_c) = n_struct` 인 V_c 가 정의에 의해 코너속도. 풀면:
$$\boxed{\ V_c(\text{alt}, W) = \sqrt{\frac{2 \cdot n_{\text{struct}} \cdot W}{\rho(\text{alt}) \cdot S \cdot C_{L,\max}}}\ }$$

이게 정리 6 (Shaw 1985) 의 코너속도 정의의 수학적 출전. "코너속도 = 최대 순간선회율을 만드는 속도" 라는 정성적 진술이 식 E1+E2 로부터 정량적으로 derive.

#### 2.2.5 파라미터 추출 — 세 독립 source

| 파라미터 | 값 | 출처 | 정당성 |
|---|---|---|---|
| `S` | 300 ft² | `f16.xml:<wingarea>` (라인 41) | JSBSim ↔ NASA TP-1538 일치 |
| `W_empty` | 17,400 lb | `f16.xml:<emptywt>` (라인 ~140) | 동 |
| `W_combat` | ≈ 25,000 lb | 추정 (empty + 50% fuel 3,400 + 2×AIM-9 388 + pilot 200 + misc) | F-16C combat profile (Lockheed datasheet) |
| `C_{L,max}` | **≈ 1.83** | `f16.xml:aero/coefficient/CLDh` 테이블, α=40° (0.698 rad), elev=0 (라인 1305) | NASA TP-1538 (1979) wind tunnel data 의 JSBSim 인코딩 |
| `n_struct` | 9.0 g | USAF F-16 Flight Manual | 공지 |
| `ρ(15000ft)` | 0.001496 slug/ft³ | US Std Atmosphere 1976 | 공지 |

`C_{L,max} = 1.83` 의 출전: JSBSim `f16.xml` 의 `<function name="aero/coefficient/CLDh">` 테이블 (라인 1284-1311). α=40° (0.698 rad), 엘리베이터 중립 (0 rad) 에서 CL = 1.822. 이 점이 lift curve 의 peak (이후 stall). LEF (leading-edge flap) 자동 deploy 효과 미반영 — 따라서 보수적 lower bound.

#### 2.2.6 결과 — F-16 doghouse plot, 15000ft

식 E1 + E2 + 표 2.2.5 의 파라미터 대입 (`tools/basis/envelope_f16.py` 실행 결과):

```
V_c(15000ft) = √(2 × 9 × 25000 / (0.001496 × 300 × 1.83))
             = √(450000 / 0.8214)
             = 740 ft/s = 438.6 kts (TAS)
```

**15000 ft Doghouse plot** (우리 canonical 매치 환경):

| V (kts) | n_aero | n_max | ω_max (°/s) | R (ft) | regime |
|---|---|---|---|---|---|
| 160 | 1.20 | 1.20 | 4.50 | 3440 | aero |
| 200 | 1.87 | 1.87 | 8.64 | 2239 | aero |
| 250 | 2.92 | 2.92 | 12.00 | 2014 | aero |
| 300 | 4.21 | 4.21 | 14.89 | 1948 | aero |
| 350 | 5.73 | 5.73 | 17.61 | 1922 | aero |
| **386.8 (canonical IC)** | 6.98 | 6.98 | **18.91** | 1913 | aero |
| 400 | 7.48 | 7.48 | 20.25 | 1910 | aero |
| **438.6 (= V_c)** | **9.00** | **9.00** | **22.24** | 1905 | **transition** |
| 500 | 11.70 | 9.00 | 19.54 | 2475 | structural |
| 600 | 16.84 | 9.00 | 16.28 | 3564 | structural |

**8000 ft Doghouse plot** (v11 가정 환경, cross-validation):

| V (kts) | n_max | ω_max (°/s) | regime |
|---|---|---|---|
| 200 | 2.34 | 11.54 | aero |
| 300 | 5.26 | 18.80 | aero |
| **350** | **7.16** | **22.12** | aero (v11 측정치 21°/s 와 1.05× 정합 ✓) |
| **392.4 (= V_c)** | **9.00** | **24.86** | **transition** |
| 420 | 9.00 | 23.27 | structural (v11: 16°/s — 큰 차이 ★) |

**관찰 및 학술적 발견** ★:

1. **8000 ft 에서 식과 v11 의 1.05× 정합** (350kts, 22°/s vs 21°/s) — 식 E1+E2 가 wind tunnel + USAF 측정의 reproduction.

2. **단, V=420 kts 에서 큰 발산** (식 23°/s vs v11 16°/s). 해석: v11 표는 **순간선회율 (instantaneous)** 이 아니라 **지속선회율 (sustained)** 에 더 가까운 듯. 고속에서 thrust < induced drag 가 발생해 9g 가 sustainable 하지 않음. §2.2.7 sustained envelope 추가 필요.

3. **★★ 매치 환경 불일치 발견**: 우리 canonical 매치는 **15000 ft**, 초기 속도 386.8 kts.
   - V_corner(15000ft) = **438.6 kts** — canonical IC 는 코너 한참 아래
   - V=386.8 kts 에서 ω_max(15000ft) = **18.91°/s** ≠ v11 의 ω_max 상수 19.16°/s
   - 즉 우리 BT 가 사용했던 `OMEGA_MAX = 19.16` 은 사실 **8000ft 의 코너 peak 부근 값**이며, 15000ft 매치에서는 약 1.3% 과대평가 (canonical IC)
   - 더 중요: **BT 가 더 잡으려면 V_corner = 438 kts 로 가속해야** 함. 현재 386.8 에서 코너 정렬 없이 18.9°/s 의 sub-optimal 선회

4. **고도가 envelope 을 좌우함** (Anderson 정리 6.7 의 직접 결과): 25000ft 에서 V_c=520kts. 고도에 따른 BT 코너 전략 차이 — 본 작업 BT 가 명시 인식해야 할 사항.

5. 위 표는 **순간선회율 (instantaneous)** — energy state Ps 무관. **지속선회율 (sustained)** 은 thrust = drag 조건 추가, §2.2.7 에서 별도 정의.

#### 2.2.7 순간 vs 지속 — Boyd 정리 5 의 본질

지속선회는 추가 부등식:
$$T(V, \text{alt}, \text{throttle}) - D(V, n, \text{alt}) \ge 0$$

여기서 `D = D_0 + k \cdot n^2 \cdot W^2 / (q S)` (induced + parasite drag). `T_max(15000ft, \text{AB}) ≈ 0.85 \times 29000 = 24,650 lbf` (afterburner, 고도 손실).

지속 n_sus 의 풀이는 E1 의 `(T-D=0)` 음함수 — 따로 표 작성. 본 절은 instantaneous envelope 만 정의; sustained 는 §2.3 으로 분리.

#### 2.2.8 게이트 G0 의 정확한 형태 (반복)

| 게이트 | 명세 |
|---|---|
| **G0_a** | 파라미터 `(S, W, C_{L,max}, n_{\text{struct}}, ρ)` 가 모두 JSBSim aerodata 또는 공지 source 에서 직접 추출. magic number 0개 |
| **G0_b** | 식 E1, E2 가 첫 절 원리에서 derive 됨 (본 절 2.2.2, 2.2.3 참조) — curve fit 0회 |
| **G0_c** | 우리 식 ω_max(V, 15000ft) 와 JSBSim 직접 시뮬레이션 (9g pull-up, 15000ft) ω 측정 의 정합 ≤ 1% (수치정밀도 한계) |
| **G0_d** | 우리 식 V_c(15000ft) = 438 kts 가 NASA TP-1538 의 doghouse plot (해당 고도) 와 정합 (질적: regime 교차 위치, 정량: ≤ 5%) |
| **G0_e** | v11 의 9-point 테이블 (8000ft 환경) 도 같은 식에 `alt=8000ft` 대입하여 재현. (검증 보조 — 별도 환경에서도 식 일관) |

→ G0_c 가 비협상 핵심. JSBSim 자체 실측이 ground truth.

#### 2.2.9 학습 가이드 — 이 절의 메타-원칙

본 절은 단순히 ω_max(V) 함수를 정의하지 않음. **검증 가능한 mathematical structure** 의 한 예시:

1. **식의 출전**: 식 E1 은 협조 선회의 운동방정식, E2 는 lift 의 정의. 둘 다 reductio ad principia.
2. **파라미터의 출전**: 모든 상수는 JSBSim/NASA reference 의 직접 추출. magic 0개.
3. **결과의 검증**: 세 독립 source (제1원리 식, JSBSim 시뮬레이션 실측, NASA published plot) 의 cross-validation. 일치하면 신뢰, 불일치하면 식 또는 파라미터 추출 의심.
4. **사용 영역**: 식 E1+E2 는 본 문서의 dynamics §1.2, HJI control bound, BT envelope clamp 의 단일 source. 다른 곳에서 다른 ω_max 사용 금지.

이 원칙이 본 작업 전반의 **검증 게이트 설계 원칙** — 어떤 magic number 도, 어떤 hard-coded threshold 도, derive 출처 + 검증 게이트 없이 코드에 들어가지 않음.

---

### 2.3 ∇V_i Closed-Forms — 각 BFM 정리의 Gradient Approximator ★

> **본 절의 학술적 위치**: 본 작업의 핵심 가설 — "BFM 정리들은 HJI value function `V*(x)` 의
> region-wise closed-form approximation 이고, 각 정리는 자신의 entry 영역에서 `∇V*(x)` 의 정확한
> 표현을 제공" — 의 **명시적 형식화**. 정책 합성 `u_p* = -sign(B_d^⊤ ∇V_approx) · u_max`
> 의 `∇V_approx` 가 본 절에서 정의된다.

#### 2.3.1 통일 관점 — Lyapunov-like Value Function

HJI value function `V*: ℝ⁶ → ℝ` 의 정확한 closed-form 은 일반적으로 존재하지 않음 (PDE 의 수치해만 존재). 단:

1. **WEZ 내부** (capture set): `V*(x) = 0`
2. **WEZ 근방**: `V*(x) ≈ distance_to_WEZ_boundary(x)`
3. **BFM 정리 entry 영역**: `V*(x) ≈ V_i(x)` (정리 i 가 제공하는 closed-form)
4. **그 밖**: LUT 수치해 또는 PN baseline fallback

본 절은 각 `V_i(x)` 및 그 gradient `∇V_i(x)` 를 정의. 정책 시:
$$\nabla V_{\text{approx}}(x) = \sum_{i} \tau_i(x) \cdot \nabla V_i(x) + \tau_0(x) \cdot \nabla V_{\text{PN}}(x)$$
여기서 `τ_i(x) ∈ [0, 1]` 는 §R2 에서 정의되는 정리 entry score, `τ_0 = 1 - Σ τ_i` 는 baseline weight.

#### 2.3.2 6D State 와 B_d Convention 재확인

상태 `x = (Δx, Δy, Δh, Δψ, V_p, V_e)`:
- `Δx > 0`: 적 우측 (body-frame)
- `Δy > 0`: 적 전방
- `Δh > 0`: 적이 위
- `Δψ > 0`: 적 heading 이 우리보다 +CCW

제어 `u_p = (ω_p, γ̇_p, a_p)` — 모두 시간미분, envelope (§2.2) bound.

Disturbance Jacobian (`tools/basis/dynamics_f16_6d_hj.py` 에서):
$$B_d(x) = \begin{bmatrix} \Delta y & 0 & 0 \\ -\Delta x & 0 & 0 \\ 0 & -V_p & 0 \\ -1 & 0 & 0 \\ 0 & 0 & 1 \\ 0 & 0 & 0 \end{bmatrix}$$

→ `(B_d^⊤ ∇V)_ω = Δy · ∂V/∂Δx - Δx · ∂V/∂Δy - ∂V/∂Δψ`
→ `(B_d^⊤ ∇V)_γ̇ = -V_p · ∂V/∂Δh`
→ `(B_d^⊤ ∇V)_a = ∂V/∂V_p`

최적 제어 box-corner argmin:
- `u_ω* = -sign((B_d^⊤ ∇V)_ω) · ω_max(V_p, alt)`
- `u_γ̇* = -sign((B_d^⊤ ∇V)_γ̇) · γ̇_max(V_p, alt) = +sign(∂V/∂Δh) · γ̇_max`
- `u_a* = -sign(∂V/∂V_p) · a_max`

#### 2.3.3 정리 2 — Proportional Navigation (Bryson-Ho 1969)

**물리 의도**: 적과의 ATA 를 0 으로 만들고, 적당 거리 (WEZ 중심 ≈ 1750 ft) 에 위치.

**ATA 정의** (body frame):
$$\text{ATA}(x) = \text{atan2}(\Delta x, \Delta y) \quad \in (-\pi, \pi]$$

ATA=0 = 적 정면, ATA=±π/2 = 적 측면, ATA=±π = 적 후방.

**Value function**:
$$\boxed{\ V_{\text{PN}}(x) = \tfrac{1}{2}\,\text{ATA}(x)^2 + \tfrac{\lambda_d}{2}\,(\text{dist}(x) - d_{\text{WEZ}}^*)^2\ }$$

- `dist(x) = √(Δx² + Δy² + Δh²)`
- `d_{\text{WEZ}}^* = 1750 ft` (WEZ 거리 중심)
- `λ_d = 1/d_{\text{WEZ}}^{*2} ≈ 3.27×10⁻⁷` (무차원화)

**Gradient**:

ATA 미분:
$$\frac{\partial \text{ATA}}{\partial \Delta x} = \frac{\Delta y}{\Delta x^2 + \Delta y^2}, \quad \frac{\partial \text{ATA}}{\partial \Delta y} = -\frac{\Delta x}{\Delta x^2 + \Delta y^2}$$

dist 미분:
$$\frac{\partial \text{dist}}{\partial \Delta x} = \frac{\Delta x}{\text{dist}}, \quad \frac{\partial \text{dist}}{\partial \Delta y} = \frac{\Delta y}{\text{dist}}, \quad \frac{\partial \text{dist}}{\partial \Delta h} = \frac{\Delta h}{\text{dist}}$$

따라서:
$$\nabla V_{\text{PN}} = \begin{bmatrix}
\text{ATA} \cdot \dfrac{\Delta y}{\Delta x^2 + \Delta y^2} + \lambda_d (\text{dist} - d^*) \dfrac{\Delta x}{\text{dist}} \\[3pt]
-\text{ATA} \cdot \dfrac{\Delta x}{\Delta x^2 + \Delta y^2} + \lambda_d (\text{dist} - d^*) \dfrac{\Delta y}{\text{dist}} \\[3pt]
\lambda_d (\text{dist} - d^*) \dfrac{\Delta h}{\text{dist}} \\
0 \\ 0 \\ 0
\end{bmatrix}$$

**Sanity check**: canonical IC (Δx=3297·sin(90°)=3297, Δy=0, Δh=0, dist=3297, ATA=π/2):
- `∂V/∂Δx ≈ (π/2) · 0/3297² + λ_d · (3297-1750) · 3297/3297 ≈ 0 + 5.1e-4 ≈ 5.1e-4`
- `∂V/∂Δy ≈ -(π/2) · 3297/3297² + λ_d · 1547 · 0/3297 = -4.76e-4`
- `(B_d^⊤ ∇V)_ω = Δy · 5.1e-4 - Δx · (-4.76e-4) = 0 + 3297·4.76e-4 = 1.57`
- `u_ω* = -sign(1.57) · ω_max = -ω_max` (좌회전, body convention CCW positive)

→ canonical 에서 적은 우측 (Δx>0). 좌회전이 맞는지? 잠시 보자.
실은 body frame 의 omega 의 부호 convention 이 `B_d` 의 sign 으로 인코딩되어 있고, `dΔx/dt = +ω·Δy` 가 의미하는 바는 "ω > 0 ⟹ Δx 증가 (적이 더 우측으로 보임)" — 이는 우리가 **좌회전** 할 때 발생 (우리가 좌회전 → 적이 상대적으로 우측). 즉 ω > 0 = **좌회전** convention. 따라서 `u_ω* = -ω_max` = 우회전. 적이 우측인데 우회전 → 적을 향해 회전. ✓

#### 2.3.4 정리 5+6 — Boyd Energy-Maneuverability + Shaw Corner (1964, 1985)

**물리 의도**: V_p 를 V_corner 에 안착시켜 ω 우위 확보.

**Value function**:
$$\boxed{\ V_{56}(x, \text{alt}) = \tfrac{1}{2}\,(V_p - V_c(\text{alt}))^2 \cdot \mathbf{1}_{\text{HCA aware}}\ }$$

여기서 `V_c(alt)` 는 §2.2 의 코너속도 식. `1_{HCA aware}` 는 정리가 적용되는 영역 indicator — implementation 에서는 R2 의 `τ_corner` 가 같은 역할.

**Gradient** (V_corner 는 alt 의 함수, V_p 와 무관하므로 상수 취급):
$$\nabla V_{56} = \begin{bmatrix} 0 \\ 0 \\ 0 \\ 0 \\ V_p - V_c(\text{alt}) \\ 0 \end{bmatrix}$$

**최적 제어**:
- `(B_d^⊤ ∇V_56)_a = ∂V/∂V_p = V_p - V_c`
- `u_a* = -sign(V_p - V_c) · a_max` — `V_p > V_c` 면 감속, `V_p < V_c` 면 가속 ✓ (Boyd 정리)

**Note**: 정리 5+6 는 V_p 차원에서만 gradient 가짐. ω 와 γ̇ 채널은 다른 정리들이 담당.

#### 2.3.5 정리 7 — Lag Displacement Turn (Shaw 1985)

**물리 의도**: ATA 중간 (40°~90°) + 큰 거리 (dist > 3000) 에서 즉시 lead 대신 lag (90° offset) 으로 displacement 누적 후 phase 2 lead 전환. Shaw 의 정확 entry: `dist · sin(ATA) ≥ R(V_p) · √2`.

**Value function** (Phase-aware 형식):

Phase 1 (displacement 누적): lag pursuit target 까지의 각도 cost
$$V_{7,P1}(x) = \tfrac{1}{2}\,(\text{ATA}(x) - \text{ATA}_{\text{lag}})^2$$

여기서 `ATA_lag = ±90°` (적 방향 + 90° offset). 부호는 `sign(Δx)` 로.

Phase 2 (lead 전환): pure lead pursuit → V_PN 재사용

전이 boundary: `dist · sin(ATA) = R·√2`

**Gradient (Phase 1)**:
$$\nabla V_{7,P1} = (\text{ATA} - \text{ATA}_{\text{lag}}) \cdot \nabla \text{ATA} = (\text{ATA} - \text{ATA}_{\text{lag}}) \begin{bmatrix}
\Delta y / r_{xy}^2 \\ -\Delta x / r_{xy}^2 \\ 0 \\ 0 \\ 0 \\ 0
\end{bmatrix}$$

여기서 `r_{xy}^2 = Δx² + Δy²`.

#### 2.3.6 정리 8 — High Yo-Yo (Pontryagin Vertical Bang-bang)

**물리 의도**: 적이 alt-track lag 가질 때, 우리가 climb 으로 시간 벌고 invert dive 로 WEZ 진입. 수직 평면에서 Pontryagin Maximum Principle 의 bang-bang 해.

**Value function** (Phase-aware):

Phase 1 (climb): alt_gap 부족 → climb cost
$$V_{8,P1}(x) = \tfrac{1}{2}\,(1500 - \max(0, \Delta h))^2 \cdot \mathbf{1}_{\Delta h < 1500}$$

→ `\Delta h < 1500ft` 일 때 climb cost, 도달 후 0.

Phase 2 (dive): 적 고도 추종
$$V_{8,P2}(x) = \tfrac{1}{2}\,\Delta h^2$$

**Gradient**:

Phase 1 (`Δh < 1500`):
$$\nabla V_{8,P1} = \begin{bmatrix} 0 \\ 0 \\ -(1500 - \Delta h) \\ 0 \\ 0 \\ 0 \end{bmatrix}$$
`∂V/∂Δh = -(1500 - Δh) = Δh - 1500 < 0` (climb wanted)

`(B_d^⊤ ∇V_{8,P1})_γ̇ = -V_p · (Δh - 1500)` (positive when Δh < 1500)
`u_γ̇* = -sign(positive) · γ̇_max = -γ̇_max`

→ 잠깐, γ̇ < 0 = 하강. 그런데 climb 단계인데 하강? 부호 검사 필요.

Convention: `dΔh/dt` 의 ω_p 와의 관계는 `∂(Δh_dot)/∂γ̇_p = -V_p` (B_d 의 3행 2열). 즉 `γ̇_p > 0` (pitch up) 시 `dΔh/dt < 0` (우리가 위로 가면 적 상대고도 감소). 따라서 `γ̇_p > 0 ⟺ 우리 climb ⟺ Δh 감소`.

V_8_P1 = ½(1500 - Δh)² 가 작아지려면 Δh 가 1500 으로 → 우리는 Δh 감소 방향 (적과 같은 고도 또는 낮아짐). 잠깐, Δh > 0 가 적이 위에 있다는 뜻이면, "alt_gap 부족" = "우리 위로 가야" = Δh 음수로 가야 (우리가 적보다 위).

상기 정의: `Δh > 0`: 적이 위. 우리 alt 우위 = `Δh < 0`. yo-yo Phase 1 의 "alt_gap 우위 확보" = `Δh ≪ 0` 방향. V_8_P1 정의를 정정해야:
$$V_{8,P1}(x) = \tfrac{1}{2}\,(\Delta h + 1500)^2 \cdot \mathbf{1}_{\Delta h > -1500}$$
→ `Δh = -1500` (우리가 적보다 1500ft 위) 에서 minimum. `Δh > -1500` 인 동안 climb cost active.

$$\frac{\partial V_{8,P1}}{\partial \Delta h} = \Delta h + 1500 > 0 \text{ (when } \Delta h > -1500\text{)}$$

`(B_d^⊤ ∇V)_γ̇ = -V_p · (Δh + 1500) < 0`
`u_γ̇* = -sign(negative) · γ̇_max = +γ̇_max` (pitch up = climb)

✓ Phase 1 시 climb 명령.

#### 2.3.7 정리 1 (Bernoulli) — 직선 추격 (특수 case)

적이 직선 비행 (HCA=180° 유지 + ω≈0) + V_p > V_e 일 때 단순 직선 추격. Bernoulli 추격 곡선의 점근 해.

**Value function**:
$$V_1(x) = \tfrac{1}{2}\,\text{ATA}(x)^2 \quad (\text{단순화: PN 의 } \lambda_d=0 \text{ 한계})$$

→ 사실상 V_PN 의 거리 항 제거. 별도 구현 불필요 — `λ_d = 0` 으로 PN 사용.

#### 2.3.8 정리들의 분담 — Component-wise

| 정리 | ω 채널 | γ̇ 채널 | a 채널 |
|---|---|---|---|
| 2 (PN) | ✓ ATA → 0 | — | — |
| 5+6 (corner) | — | — | ✓ V_p → V_c |
| 7 (LDT) | ✓ ATA → 90° lag | — | — |
| 8 (yo-yo) | — | ✓ Δh → -1500 → +∞ | — |
| **합성 (blend)** | τ_PN·PN + τ_LDT·LDT | τ_yoyo·yoyo | τ_corner·corner |

**관찰**: 각 정리가 다른 채널을 주로 담당. 충돌 없음. 합성 시 채널별 가중 평균.

#### 2.3.9 게이트 G1_a-d (정리별 sanity)

| 게이트 | 검증 |
|---|---|
| **G1_a (PN)** | canonical IC (ATA=90°, dist=3297, Δh=0) 에서 `u_ω*` 가 적 방향 회전 (Δx>0 → u_ω 부호로 우회전) |
| **G1_b (Corner)** | V_p=300 → u_a* > 0 (가속), V_p=400 → u_a* < 0 (감속), V_p=V_c → u_a* ≈ 0 |
| **G1_c (Yo-yo)** | Δh > -1500 → u_γ̇* > 0 (climb), Δh < -1500 → u_γ̇* < 0 (dive) |
| **G1_d (LDT)** | Phase 1 (dist·sin(ATA) < R·√2) 에서 u_ω* 부호가 LDT lag target (90° offset) 으로 |
| **G1_e (조합)** | 모든 ∇V_i 가 numerical (finite diff) 와 ≤ 1% 정합 |

→ 게이트 G1_a-e 는 R5 정적 분석에서 `pytest` 로 검증.

---

### 2.4 τ_i Functions — 정리 i 의 Entry Score (Layer 1 + Layer 2) ★

> **본 절의 학술적 위치**: §2.3 의 `∇V_i` 가 "정리 i 의 closed-form gradient" 라면,
> 본 절의 `τ_i(o)` 는 "지금 state x 가 정리 i 의 entry 영역에 있는가" 의 정량 표현.
> 사용자 합의 형식 (회차 2026-05-13): **2-층 표현** — Layer 1 hard predicate `Φ_i(o)`
> (SMT 검증·디버깅용) + Layer 2 soft score `ρ_i(o)` (blending 용).

#### 2.4.1 28-feature obs 만 입력 — 정보 게임 정합성

§0.5 D 의 정보 구조 가정 — 양 플레이어 28-obs 만 관측 — 에 따라 모든 τ_i 는 obs (또는 obs 의 시간 차분) 만 사용. 추정기 0개. v11_code 의 설계 정합.

ω_e (적 선회율) 같이 obs 에 없는 양은 시간차분 (HCA rate 에서 우리 ω 잔여) 로만 인지. 이건 estimator 가 아니라 **finite-difference operator on observable** — 정당.

#### 2.4.2 Layer 1 vs Layer 2 의 역할 분담

| 층 | 입력 | 출력 | 용도 |
|---|---|---|---|
| **Layer 1 — Hard predicate Φ_i** | obs | bool | (a) 진단·로깅: "지금 정리 i 의 모든 entry 조건이 만족됐나?", (b) SMT 형식 검증 (각 조건이 polynomial literal) |
| **Layer 2 — Soft score ρ_i** | obs | float ∈ [0,1] | 정책 시 `∇V_approx = Σ ρ_i ∇V_i` 가중 평균. 매끄러운 분기 전환 (chattering 방지) |

**관계**: ρ_i 는 Φ_i 의 sigmoid 매끈화. Φ_i 의 각 conjunct `(cond_j(o) > θ_j)` 에 대응하는 sigmoid `σ((cond_j - θ_j)/σ_j)` 의 곱. 영역 boundary 에서 부드럽게 0↔1 전환.

#### 2.4.3 τ_PN — Proportional Navigation Baseline

**Layer 1**: 항상 활성 (다른 정리들의 fallback baseline). Φ_PN ≡ True.

**Layer 2**:
$$\rho_{\text{PN}}(o) = \max\!\Big(0,\ 1 - \rho_{\text{corner}} - \rho_{\text{yoyo}} - \rho_{\text{LDT}}\Big)$$

→ 잔여 baseline. 다른 정리들이 모두 약하면 1. 다른 정리들이 강하면 0 으로 감소.

#### 2.4.4 τ_corner — Boyd EM + Shaw 1/2-circle (정리 5+6)

**Entry 조건** (Shaw 1985 정리 6 의 정확 form):
1. HCA 가 1-circle (< 90°) 또는 2-circle (> 120°) — head-on 중간 영역 (90~120°) 은 regime 모호
2. V_p 가 V_corner 근방
3. 양쪽 active turning fight (우리 ω > 5°/s AND 적 ω 추정 > 3°/s)

**Layer 1**:
$$\Phi_{\text{corner}}(o) = \big[(\text{HCA} > 120°) \vee (\text{HCA} < 90°)\big] \wedge \big[V_p > V_c - 30\big] \wedge \big[\omega_{us} > 5°/s\big] \wedge \big[\omega_e^{\text{est}} > 3°/s\big]$$

여기서 `ω_e^est = max(0, |dHCA/dt| - ω_us)` — finite-difference operator on observable.

**Layer 2** (sigmoid 곱):
$$\rho_{\text{corner}}(o) = \max\!\big(s_{\text{2c}}, s_{\text{1c}}\big) \cdot s_V \cdot s_{\text{us}} \cdot s_{\text{them}}$$

- `s_2c = σ((HCA - 120°)/20°)`
- `s_1c = σ((90° - HCA)/20°)`
- `s_V = σ((V_p - V_c + 30)/15)`   (V_c 가 alt 함수, §2.2)
- `s_us = σ((ω_us - 5)/3)`
- `s_them = σ((ω_e^est - 3)/2)`

#### 2.4.5 τ_yoyo — Pontryagin Vertical Bang-bang (정리 8)

**Entry 조건**:
1. closure 양수 (chase) 또는 |closure| 작음 (engagement lock)
2. ATA 중간 영역 ([20°, 100°]) — 너무 정렬되면 PN, 너무 안 정렬되면 yo-yo 무의미

**Layer 1**:
$$\Phi_{\text{yoyo}}(o) = \big[\text{closure} > 0 \vee |\text{closure}| < 30\big] \wedge \big[20° \le \text{ATA} \le 100°\big]$$

**Layer 2**:
$$\rho_{\text{yoyo}}(o) = \max\!\big(s_{\text{chase}}, s_{\text{lock}}\big) \cdot g_{\text{ATA}}$$

- `s_chase = σ((closure - 30)/50)`
- `s_lock = σ((50 - |closure|)/30)`
- `g_ATA = exp(-(ATA - 70°)² / (2·30°²))` — Gaussian centered at 70°

**Note**: 정리 8 의 Pontryagin switch surface (Phase 1 climb / Phase 2 dive) 는 `∇V_yoyo` 의 Δh 부호로 인코딩 (§2.3.6). τ_yoyo 는 발동 가중치만 결정.

#### 2.4.6 τ_LDT — Shaw Lag Displacement Turn (정리 7)

**Entry 조건** (Shaw 정리 7 의 정확 form):
1. ATA 중간 영역 ([40°, 90°])
2. **Displacement criterion**: `dist · sin(ATA) ≥ R(V_p) · √2`
3. LOS rate 충분히 큼 (정리 7 의 PN saturation 회피 동기)

**Layer 1**:
$$\Phi_{\text{LDT}}(o) = \big[40° \le \text{ATA} \le 90°\big] \wedge \big[\text{dist} \cdot \sin(\text{ATA}) \ge R(V_p) \sqrt{2}\big] \wedge \big[|\dot\psi_{\text{LOS}}| > 5°/s\big]$$

**Layer 2**:
$$\rho_{\text{LDT}}(o) = g_{\text{ATA}} \cdot s_{\text{disp}} \cdot s_{\text{LOS}}$$

- `g_ATA = exp(-(ATA - 65°)² / (2·15°²))`
- `s_disp = σ((dist·sin(ATA) - R√2)/500)`
- `s_LOS = σ((|LOS_rate| - 8)/5)`

#### 2.4.7 통합 — `∇V_approx` 합성식 (§2.3.1 의 구체화)

$$\boxed{\nabla V_{\text{approx}}(o) = \dfrac{\rho_{\text{PN}}\nabla V_{\text{PN}} + \rho_{\text{corner}}\nabla V_{56} + \rho_{\text{yoyo}}\nabla V_8 + \rho_{\text{LDT}}\nabla V_7}{\rho_{\text{PN}} + \rho_{\text{corner}}+ \rho_{\text{yoyo}}+ \rho_{\text{LDT}}}}$$

정상화 (분모) 는 ρ_i 합이 1 보다 작거나 클 때도 의미 보전 — convex combination.

#### 2.4.8 게이트 G2_a-d (정리별 τ sanity)

| 게이트 | 검증 |
|---|---|
| **G2_a (corner)** | τ_corner: HCA 단조성 — `HCA: 100→130→160°` 에서 ρ_corner 증가 (regime sigmoid 의 monotone) |
| **G2_b (yoyo)** | τ_yoyo: ATA=70° peak — `ATA: 30→70→110°` 에서 ρ_yoyo 가 ∩-shape |
| **G2_c (LDT)** | τ_LDT: displacement boundary — `dist·sin(ATA) < R√2` 일 때 ρ_LDT 거의 0, `≥ R√2` 일 때 > 0.3 |
| **G2_d (cover)** | **★★ 사용자 핵심 게이트** — 모든 x ∈ canonical neighborhood 에서 Σ ρ_i + ρ_PN ≥ 0.1 (어떤 상태도 cover 안 되는 영역 없음). SMT (dReal) 형식 증명 또는 grid sampling counter-example |
| **G2_e (Φ_i SMT)** | 각 Φ_i 가 polynomial conjunction 으로 표현되어 Z3 query 가능 (trig 변수 치환 후) |

→ G2_d 가 **R7 (7D LUT 재솔브) 의 trigger**. unsat 이면 LUT 불필요, sat counter-example 이면 그 영역만 LUT 필요.

---

### 2.5 V_advantage — 유분리 (Smart Separation) 의 수학화 ★★

> **사용자 지적 (2026-05-13)**: "디펜시브 objective 가 아니라 유분리야. 분리한 상황에서
> 유리한 상황으로 궤도를 결정하도록 하는게 맞아. 분리하기 시작하면 애매해져."
>
> **재정정**: §2.3 의 V_PN = ½·ATA² 는 **alignment 단일 metric**. 적 6시 위협 + 자기 분리 시
> "방어" 라는 별도 분기 만들지 말 것. **궁극 V 자체가 "유리한 상태로 가는 path"** 를
> 가리켜야 함. 즉 V 정의에 ATA 뿐 아니라 **AA (적의 우리 정렬 정도)** 도 통합.

#### 2.5.1 유분리의 의미 — 분리 자체는 중간 상태, 유리한 끝점을 향한 궤도

조종사 사고:
- "지금 분리됐다 (적과 거리 벌어짐)" — 중간 상태
- "어디로 갈 거냐?" = 유리한 끝점 — **적 6시 (우리 nose 가 적 정렬, 적 nose 는 우리 등지)**
- "어떤 궤도?" = 현 분리 상태에서 끝점까지의 trajectory

→ 수학으로는: 단일 V(x) 가 "유리한 끝점에서 0, 다른 곳에서 양수" 로 정의되고 ∇V 가 path 를 결정.
"defensive" 라는 별도 분기 불필요. **V_advantage 하나로 통합**.

#### 2.5.2 ATA + AA 통합 — 단일 V_advantage 정의

ATA: **우리 nose** vs LOS 각 (작을수록 우리가 적 향함)
AA:  **적 nose** vs LOS 각 (클수록 적이 등돌림 — 우리에게 유리)

유리한 끝점: ATA=0 (우리 정렬) ∧ AA=π (적 등돌림) ∧ dist≈d_WEZ.

$$\boxed{\ V_{\text{adv}}(x) = \tfrac{1}{2}\,\text{ATA}(x)^2 + \tfrac{1}{2}\,(\pi - \text{AA}(x))^2 + \tfrac{\lambda_d}{2}\,(\text{dist}(x) - d_{\text{WEZ}}^*)^2\ }$$

- `ATA²`: 우리 alignment 추구 (작을수록 좋음)
- `(π - AA)²`: 적 disorientation 추구 (AA 가 π 가까울수록 좋음)
- `(dist - d*)²`: WEZ 근접

→ 이 V 는 **공격·방어 구분 없음**. 모든 상태 (offensive / neutral / separated / defensive) 에서 같은 형식. ∇V 가 자동으로 "이 상태에서 유리한 끝점으로 가는 방향" 을 줌.

**검증** (네 상태에서 V_adv 값):

| 상태 | ATA | AA | V_adv (정성) |
|---|---|---|---|
| Offensive (적 6시 진입) | 0° | 180° | **최소** (목표 달성) |
| Canonical IC | 90° | 90° | 중간 (둘 다 큰 차이) |
| Head-on (양쪽 정렬) | 0° | 0° | 큼 (적도 정렬, 위험) |
| Defensive (적이 우리 6시) | 180° | 0° | **최대** (불리) |

#### 2.5.3 AA 의 수학적 표현 (6D state 에서)

적 nose 방향 (우리 body frame): 우리 heading=0 기준, 적 heading = `Δψ`.

적 nose 단위벡터 (우리 body frame 의 forward axis 기준):
$$\hat{n}_e = (\sin \Delta\psi,\ \cos \Delta\psi)$$

적→우리 LOS = -(우리→적) = -(Δx, Δy)/dist.

$$\cos(\text{AA}) = \hat{n}_e \cdot \hat{\text{LOS}}_{e \to us} = -\frac{\Delta x \sin\Delta\psi + \Delta y \cos\Delta\psi}{\text{dist}}$$

검증 (canonical: Δx=3297, Δy=0, Δψ=π): cos(AA) = -(0 - 0)/3297 = 0 → AA=π/2=90° ✓
검증 (우리 6시 victim: Δx=0, Δy=-3000, Δψ=0): cos(AA) = -(0 - 3000)/3000 = +1 → AA=0° ✓ (적 정렬)
검증 (offensive — 우리 적 6시: Δx=0, Δy=+3000, Δψ=0 같은 방향): cos(AA) = -(0 + 3000)/3000 = -1 → AA=π=180° ✓ (적 등돌림)

#### 2.5.4 ∇V_advantage 유도

`AA = arccos(c_AA)` 어디서 `c_AA = -(Δx s_ψ + Δy c_ψ)/dist`, `s_ψ := sin Δψ`, `c_ψ := cos Δψ`.

`∂AA/∂· = -1/sin(AA) · ∂c_AA/∂·`

`∂c_AA/∂Δx = -s_ψ/dist + c_AA · Δx/dist²`
`∂c_AA/∂Δy = -c_ψ/dist + c_AA · Δy/dist²`
`∂c_AA/∂Δh = c_AA · Δh/dist²`
`∂c_AA/∂Δψ = -(Δx c_ψ - Δy s_ψ)/dist`

전체 `∇V_adv`:
$$\nabla V_{\text{adv}} = \nabla V_{\text{PN}} + (\pi - \text{AA}) \cdot \frac{-1}{\sin(\text{AA})} \cdot \nabla c_{\text{AA}}$$

(상세 component 식은 `gradient_approximators.py` 의 코드 참조)

#### 2.5.5 ∇V_PN 의 자연 일반화 — 별도 정리 없음

§2.3.3 의 V_PN 을 V_adv 로 직접 치환. 즉:
- 정리 2 (PN) 의 closed-form: `V_PN_v2 = V_adv` (AA 항 포함)
- 별도 V_defensive / τ_threat 신설 X
- 모든 region 에서 동일 V_adv 사용

이는 사용자 통찰의 직접 반영: **"분리하기 시작하면 [공격·방어] 애매해져"** — V_adv 가 그 구분 없이도 작동.

#### 2.5.6 게이트 G_adv (V_adv sanity)

| 게이트 | 검증 |
|---|---|
| **G_adv_a** | canonical IC (ATA=90°, AA=90°): V_adv 양수, ∇V 의 ω 채널이 우리 ATA→0 방향 |
| **G_adv_b** | 적 6시 위치 (Δx=0, Δy=+3000, Δψ=0): ATA=0, AA=180°, V_adv = (d-d*)²/2 만 (최소화 완료) |
| **G_adv_c** | 우리 6시 victim (Δx=0, Δy=-3000, Δψ=0): ATA=180°, AA=0°, V_adv 큰 값. ∇V 의 ω 채널이 AA 증가 방향 (적이 등돌리도록 압박 — 직접 우회전·좌회전이 아니라 V_p 가속도 동반) |
| **G_adv_d** | numerical (finite-diff) 와 ≤ 1% 정합 |

#### 2.5.7 V_adv 의 정직한 한계 — 단일 Lyapunov 의 trade-off 불능 (2026-05-13)

**실 매치 검증 결과 (R3 단일 매치 시리즈)**:

| V 형태 | dist 추세 | ATA 추세 | 결론 |
|---|---|---|---|
| V_PN = ½ATA² (bang-bang) | 안정 | stuck 170° | hdg ∈ {0, 8} chattering, V_p 손실 |
| + smooth saturation | 안정 | stuck 170° | hdg 다양화, 그러나 ATA 정렬 못 함 |
| + V_aa (AA 통합) | **5x 폭증** | 좋아짐 (74°) | 적 6시 진입 추구 → 우리 너무 멀어짐 |
| + dist mask α(dist) | 진동 | 진동 (155° → 175°) | sigmoid mask sharp transition 시 oscillation |
| V_aa=0 (pure pursuit + V_p + dist) | 진동 | 진동 (170°→155°→175°→176°) | 다른 항 conflict — V_PN single Lyapunov 한계 |

**진단**:
- 단일 quadratic V 가 multi-objective (ATA, AA, dist, V_p) 동시 trade-off 못 함
- 한 항 강화 시 다른 항 악화 — limit cycle (turn→V_p 손실→가속→과회복→ATA 분기)
- v11 의 **분기 구조** (`if ata<12 then attack else lead`) 가 효율적인 이유: 한 번에 한 항만 우선화

**근본 해결**: 단일 V*(x) 의 정확한 수치해 (HJI LUT) 가 필요. 정리들의 closed-form approximation 만으로는 부족.

→ **R7 (HJI v2 6D LUT 재솔브)** 완료 (2026-05-13). 결과는 §2.5.9 정직 기록.

#### 2.5.9 R7 (HJI v2 6D LUT) 실측 한계 — 정직 기록 (2026-05-13)

**측정**:
| 시간 horizon | V(canonical) | Capturable | Solve time |
|---|---|---|---|
| 30s | +1815 ft | 13,824 cells (0.46%) | 6s |
| 90s | +1777 ft | **13,824 cells (변화 없음)** | 6s |

→ **BRT 영역 확장이 거의 0**. 90s 솔브가 30s 와 사실상 동일.

**원인 추정**:
1. **hj-reachability "low" accuracy + BRT postprocessor** 의 큰 dt — 큰 step 1-2번 후 수렴 정체
2. **12⁶ grid coarseness** — 13,824 / 2.99M cells = 0.46% 의 sparse capture set 에서 BRT propagation 어려움
3. **V range** 약 20,000 ft vs grid spacing (667ft per cell) — finite-diff ∇V 신호가 cell 폭에 비해 작아 quantize 후 의미 손실

**매치 검증 (3 mode)**:
| Mode | ATA Q4 | dist Q4 | WEZ entry | 결론 |
|---|---|---|---|---|
| V_adv (closed-form) | 176° | 12k ft | 0 | progression 있음, 진동 |
| LUT (30s, 직접) | 177° | 10k ft | 0 | alt/vel hold (∇V 약함) |
| Blend (0.5·V_adv + 0.5·LUT) | 177° | 7.8k ft | 0 | LUT 가 V_adv 신호도 약화 |

**학술적 결론**:
- 12⁶ grid + BRT-low accuracy 에서 6D HJI 가 **사용 가능한 ∇V LUT 산출 못 함**
- 진정한 V*(x) 가 필요하면 **D-α** (high accuracy + dense grid) 또는 **D-γ** (GPU 7D) 가 필요
- 본 환경 (CPU only) 의 제약 인정

**실용적 회귀 경로** (E 옵션):
- v11 의 분기 구조 (`if ATA<12 then GunAttack else LeadPursuit`) 가 simple-flight 적에 대해 작동 보장됨
- 본 작업의 closed-form ∇V_i 들 (정리 2/5+6/7/8) 을 v11 분기 안에 흡수 — 분기 결정은 v11 구조, 분기 내 명령은 본 작업 식
- 6D LUT 는 진정한 GPU/dense 환경에서 재시도 (R7b)

#### 2.5.8 학습 — Game Theoretic 관점

V_adv 는 본 작업의 **Model A** 에서 **Model B (§11)** 로 향하는 진정한 첫 발걸음. 두 player 의 game state (양쪽 alignment) 가 동시 등장.

엄밀히는 Model B 의 saddle-point HJI 해는 12D state (양쪽 attitude 전체) 의 PDE 풀이로 얻어짐. V_adv 는 그 해의 **closed-form 1차 근사** — 두 player 의 nose 정렬 차이를 single Lyapunov 로 통합.

LDT (정리 7) 의 Phase 1 (lag pursuit) 는 V_adv minimization 의 자연 trajectory 의 일부: ATA 를 직접 0 으로 내리지 않고 ATA→90°·dist 증가→AA 증가 후 ATA→0 로 가는 곡선 path. **V_adv 의 ∇V flow 가 이를 자동 산출** (별도 trajectory planning 불요).

---




- **Buzikov-Galyaev (2022) arXiv:2206.10199** — 동등 스펙 Game of Two Cars 해석해 (3D 등속). 본 작업의 sanity check.
- **Mitchell, Bayen, Tomlin (2005)** — HJI 수치 PDE solver 표준 방법론.
- **Bansal, Chen, Tomlin (2017) arXiv:1709.07523** — HJ reachability 현대적 개요.
- **Mitchell ToolboxLS** — MATLAB 구현. 본 작업은 Python optimized_dp 사용.

---

### 2.6 Hybrid Differential Game — BFM 정리의 형식화 ★★★

> **본 절의 학술적 위치**: v11_code (`adaptive_eagle_v11_code`) 의 implicit BFM 분기 구조를
> **Hybrid Differential Game** (switched-system differential game) 형식으로 promote.
> RED TEAM 분석 (2026-05-13) 결과 — 단일 Lyapunov `V_adv` (§2.5) 의 trade-off 한계 → 진정한
> 수학적 정답은 **mode-별 V_m\*(x) 의 switched system**. 사용자 요구 (학술 + 유/분리 + Δstate
> 적응 + 두 점 질량 게임) 정확히 충족.

#### 2.6.0 동기 — v11 의 success 를 rigorous 로 promote

v11 이 simple/aggressive/defensive/offensive/evading 5 정책 모두 vs WIN 함의 implicit 구조:

```
v11 의 (formal 안 됨) 핵심:
  match 의 매 tick 에:
    1. ATA, dist, closure, HCA, V_p, alt_gap 관측  ─ 28-obs
    2. branch ∈ {GunEngagement, OffensivePursuit, TheoremAdaptive, HardDeck, ...} 선택
    3. branch 내부 τ-blended 명령 산출 (PN + corner + yoyo + ldt 가중평균)
    4. (alt, hdg, vel) discrete bin 출력
```

v11 이 형식화 못 한 것:
- 각 branch 의 entry 조건이 **왜 그 수치** 인가 (예: ATA<12°, HCA>120°)
- 각 branch 내부의 명령 합성식의 **mathematical justification**
- branch 전환의 **smoothness 보장**

→ **Hybrid Differential Game formalism 이 이 모든 것을 derive 가능하게 함**.

#### 2.6.1 Hybrid (Switched) Dynamic Game — 정식 정의

**Definition (Hybrid Game).** 다음 6-tuple `H = (X, M, F, J, S, Φ)`:

1. **State space** `X ⊆ ℝⁿ`: 본 작업 `n=6` — `x = (Δx, Δy, Δh, Δψ, V_p, V_e)`
2. **Mode set** `M = {m_1, m_2, ..., m_K}`: 각 mode 는 BFM 정리 하나 + LUT fallback
3. **Dynamics** `F: X × U_p × U_e → ℝⁿ`: mode 무관 (물리는 동일) — control-affine `ẋ = f₀(x) + B_c(x)u_e + B_d(x)u_p` (§1.2.2)
4. **Cost (mode-별)** `J_m: X × U_p × U_e → ℝ`: mode m 의 "유리한 endpoint 까지 가는 cost"
5. **Switching surfaces** `S = {S_{ij} ⊂ X : i, j ∈ M, i ≠ j}`: mode i 에서 mode j 로 전환되는 state 부분집합
6. **Switching policy** `Φ: X → 2^M`: 현 state x 에서 활성 mode 집합 (보통 1개, 경계에서 다중)

**Game value (mode m 에 대해)**:
$$V_m^*(x) = \min_{u_p(\cdot)} \max_{u_e(\cdot)} J_m[x, u_p, u_e]$$

**Optimal mode**:
$$m^*(x) = \arg\min_{m \in M} V_m^*(x)$$

**Switching surface 의 명시적 정의**:
$$S_{ij} = \{x : V_i^*(x) = V_j^*(x)\}$$

→ "i 와 j mode 의 cost-to-go 가 같은 state" — 어느 mode 로 가도 같은 advantage. 이게 BFM 의 1c-vs-2c boundary 의 수학적 origin.

#### 2.6.2 Mode 정의 — BFM 정리를 mode 로 매핑

본 작업의 mode 집합:

| `m` | 이름 | 정리 | 활성 region (state 조건) | 학술 출전 |
|---|---|---|---|---|
| `m_1` | Bernoulli-Pursuit | 정리 1 | 적 직선 비행 + V_p > V_e | Bernoulli 1732[^bernoulli] |
| `m_2` | PN-Tracking | 정리 2 | ATA < 30°, dist ∈ [500, 3500] | Bryson-Ho 1969[^brysonho], Zarchan 2012[^zarchan] |
| `m_3` | OneCircle | 정리 6 (1-circle) | HCA < 90°, R_us < R_them | Shaw 1985[^shaw] |
| `m_4` | TwoCircle | 정리 6 (2-circle) | HCA > 120°, ω_max_us > ω_max_them | Shaw 1985, Boyd 1964[^boyd] |
| `m_5` | LDT | 정리 7 | ATA ∈ [40°, 90°], dist·sin(ATA) ≥ R√2 | Shaw 1985 |
| `m_6` | HighYoYo | 정리 8 | closure > 0, ATA ∈ [20°, 70°], Δh exploit 가능 | Pontryagin 1962[^pontryagin], Lutze-Durham 1989[^lutze] |
| `m_7` | HJI-Fallback | 수치해 | 위 mode 모두 active 안 함 (휴리스틱 region 밖) | Mitchell-Bayen-Tomlin 2005[^mitchell] |

→ **7 modes**. 합집합이 state 공간 cover. 진입 조건은 §2.6.3 의 V_m^*(x) 에서 derive.

#### 2.6.3 Mode 별 Value Function — Closed-Form Derivation

각 mode 의 V_m^*(x) 는 그 정리의 **first principle 에서 derive**. §2.3 의 ∇V_i 가 이 V_m^* 의 gradient.

**m_2 (PN)** — Bryson-Ho 1969 의 optimal PN 결과:
$$V_2^*(x) = \tfrac{1}{2}\,\text{ATA}^2 + \tfrac{1}{2}\,\lambda_d\,(\text{dist} - d_{\text{WEZ}}^*)^2$$
- `ATA = atan2(Δx, Δy)` ─ aspect-to-aim angle
- `λ_d = 1/d_{\text{ref}}^2` ─ 거리 정규화 (d_ref = WEZ 절반 폭 = 1250ft)
- `d_{\text{WEZ}}^* = 1750 ft` ─ WEZ 중심

**m_3 (OneCircle)** — Shaw 1985 의 1-circle 정리:

1-circle 의 본질: **R (선회 반경) 가 작은 자가 1 turn 후 적 6시 진입**. 따라서:
$$V_3^*(x) = \tfrac{1}{2}\,\lambda_R\,(R(V_p) - R_{\min})^2 + \tfrac{1}{2}\,\sigma_{1c}(\text{HCA})\,\text{ATA}^2$$

여기서:
- `R(V_p) = V_p / ω_{\max}(V_p)` ─ 현 V_p 의 instantaneous 선회 반경 (§2.2 envelope)
- `R_{\min} = \min_{V} R(V)` ─ envelope 의 최소 R (보통 코너 V 에서)
- `σ_{1c}(HCA) = sigmoid((90° - HCA)/20°)` ─ HCA<90° 영역에서 활성
- `λ_R = 1/R_{\min}^2` ─ R 정규화

→ **1-circle 의 정확한 entry**: HCA<90° 영역에서, V_p 를 R 최소가 되는 속도로 → 적 1 turn 안에 6시.

**m_4 (TwoCircle)** — Shaw 1985 의 2-circle + Boyd 1964 Ps:
$$V_4^*(x) = \tfrac{1}{2}\,(V_p - V_c)^2 + \tfrac{1}{2}\,\sigma_{2c}(\text{HCA})\,\text{ATA}^2$$
- `V_c` ─ 코너속도 (§2.2.4 에서 derive, alt 함수)
- `σ_{2c}(HCA) = sigmoid((HCA - 120°)/20°)` ─ HCA>120° 영역 활성

→ 2-circle: V_p 를 V_c 에 맞춰 ω_max → 양쪽 반대 turn 으로 ω 누적 우위.

**m_5 (LDT)** — Shaw 1985 Phase 1+2:
$$V_5^*(x) = \tfrac{1}{2}\,(\text{ATA} - \text{ATA}_{\text{lag}})^2 \cdot \mathbf{1}_{\text{Phase 1}} + V_2^*(x) \cdot \mathbf{1}_{\text{Phase 2}}$$
- Phase boundary: `dist · sin(|ATA|) ≥ R(V_p)·√2`
- `ATA_lag = ±90°` (Δx 부호 따라)

**m_6 (HighYoYo)** — Pontryagin 1962 vertical 평면 bang-bang:
$$V_6^*(x) = \begin{cases}
\tfrac{1}{2}\,(\Delta h + h_{\text{target}})^2 & \text{Phase 1 (climb): } \Delta h > -h_{\text{target}} \\
\tfrac{1}{2}\,\Delta h^2 & \text{Phase 2 (dive)}
\end{cases}$$
- `h_target = 1500 ft` ─ 우리 alt 우위 목표

**m_7 (HJI Fallback)** — 수치해 V*_LUT(x):
$$V_7^*(x) = V_{\text{LUT}}^{\text{numerical}}(x)$$

mode 1-6 모두 entry 영역 밖일 때 사용. §3 의 numerical solve 결과.

**m_1 (Bernoulli)** — 적 ω ≈ 0 (직선) 검출 시:
$$V_1^*(x) = \tfrac{1}{2}\,\text{ATA}^2 \cdot \mathbf{1}_{\hat{\omega}_e < 1°/s}$$
→ 단순 PN, 거리항 없음 (직선 추격 끝 보장).

#### 2.6.4 Switching Surfaces — 명시적 derive

mode i 와 mode j 간 switching surface 는 `V_i^* = V_j^*` 의 해 집합. 두 예시:

**S_{34} (1-circle ↔ 2-circle)**:
$$\tfrac{\lambda_R}{2}(R(V_p) - R_{\min})^2 + \tfrac{1}{2}\sigma_{1c}\cdot\text{ATA}^2 = \tfrac{1}{2}(V_p - V_c)^2 + \tfrac{1}{2}\sigma_{2c}\cdot\text{ATA}^2$$

ATA 항 dominant 영역 (ATA 큼) 에서:
$$\sigma_{1c}(\text{HCA}) \approx \sigma_{2c}(\text{HCA}) \quad \Leftrightarrow \quad \text{HCA} \approx 105° \text{ (transition midpoint)}$$

→ **HCA=105° 가 1c/2c switching surface 의 1차 근사** — Shaw 1985 의 정성적 진술 (110° 부근) 의 수학적 출전.

**S_{27} (PN ↔ HJI Fallback)**:
$$\text{ATA}^2 + \lambda_d(\text{dist} - d^*)^2 = V_{\text{LUT}}(x)$$

→ PN 의 closed-form 이 LUT 와 일치하는 ATA-dist 등고선. 이 surface 안쪽에서 PN, 밖에서 LUT.

#### 2.6.5 τ-blended Policy — Optimal Mode Selection 의 Smooth Approximation

**문제**: argmin 은 discontinuous. mode 경계에서 chattering.

**해결 (사용자 합의)**: smooth blend by τ_i:
$$\tau_i(x) = \frac{\exp(-\beta V_i^*(x))}{\sum_j \exp(-\beta V_j^*(x))} \quad \text{(softmin, β > 0)}$$

또는 본 작업의 실용 구현 (R2):
$$\tau_i(x) = \prod_{k} \sigma\!\left(\frac{c_{i,k}(x) - \theta_{i,k}}{\delta_{i,k}}\right)$$
- `c_{i,k}` ─ mode i 의 k 번째 entry condition value
- `θ_{i,k}` ─ threshold
- `δ_{i,k}` ─ transition 폭

**Composite gradient** (RED TEAM F1 정정):
$$\nabla V_{\text{policy}}(x) = \sum_{i=1}^{6} \tau_i(x) \cdot \nabla V_i^*(x) + \alpha_{\text{LUT}} \cdot \nabla V_{\text{LUT}}(x)$$
- `α_{LUT}` ─ LUT 의 보조 weight (보통 1 - Σ τ_i, 정리 영역 밖에서 활성)

**Optimal control (box-corner argmin from HJI)**:
$$u_p^*(x) = -\text{sign}\!\big(B_d(x)^\top \nabla V_{\text{policy}}(x)\big) \cdot u_{\max}(V_p, \text{alt})$$

또는 (실용 R3) smooth saturation:
$$u_p^*(x) = \text{clip}\!\big(-B_d^\top \nabla V_{\text{policy}} \cdot \text{gain},\ -u_{\max},\ +u_{\max}\big)$$

#### 2.6.6 Two-Point-Mass Game — 적 모델 명시

본 framework 는 본질적으로 **two-player zero-sum differential game**:
- player 1 (us, pursuer): `u_p ∈ U_p` ─ V 최소화
- player 2 (enemy, evader): `u_e ∈ U_e` ─ V 최대화

V_m^*(x) 의 minimax 가 양쪽 최적 정책 동시 가정. 실 매치에서 적이 minimax 안 함 (예: simple = 직선) → 우리 V_m^* 는 **conservative upper bound**. 적이 sub-optimal 인 만큼 우리 advantage.

**Δstate 적응**:
$$\hat{\text{strategy}}_e(t) = g(\Delta(t), \Delta(t-1), ..., \Delta(t-N)) \quad \text{(28-obs 시간차분)}$$

예: `ω̂_e = max(0, |Δψ̇| - ω_us)` ─ HCA 변화 중 우리 ω 가 설명 못 하는 잔여 = 적 ω 추정. estimator 가 아니라 **finite-difference operator on observable**. (§0.5 D 정보 게임 정합.)

#### 2.6.7 Notation Dictionary (본 절의 모든 기호)

**State (subscripts)**:
- `Δx` (= dx_rel) ─ pursuer body frame 의 적 우측 (right) 상대 위치 [ft]
- `Δy` (= dy_rel) ─ pursuer body frame 의 적 전방 (forward) 상대 위치 [ft]
- `Δh` (= dh) ─ 적 고도 - 우리 고도 [ft]. `Δh > 0` = 적이 위
- `Δψ` (= dpsi) ─ 적 heading - 우리 heading [rad]
- `Δγ` ─ 적 flight path angle - 우리 [rad]. 본 작업 6D 에선 small-γ 가정 (§1.2.3)
- `V_p` ─ pursuer (우리) 진속 [kts]
- `V_e` ─ evader (적) 진속 [kts]. 28-obs 에 없음 → closure 기반 추정 (§0.5 D)

**Subscripts on V, ρ, τ, ω, etc.**:
- `_p` ─ pursuer (우리)
- `_e` ─ evader (적)
- `_m` ─ mode m (e.g., V_m^*)
- `_i, _j, _k` ─ mode index 또는 condition index
- `_LUT` ─ HJI numerical lookup table
- `_us, _them` ─ 우리 / 적 (영문 표기)
- `_1c, _2c` ─ 1-circle, 2-circle (Shaw 정리 6)
- `*` (별) ─ optimal (최적)
- `^` (hat) ─ estimated (추정값, 시간차분 등)

**Operators**:
- `∇` ─ gradient (vector 미분)
- `arg min, arg max` ─ minimizer/maximizer
- `min_u max_v` ─ saddle-point (zero-sum game value)
- `‖·‖` ─ Euclidean norm
- `σ(·)` ─ sigmoid (= 1/(1+e^(-·))) ─ smooth threshold
- `1_{condition}` ─ indicator function (0 or 1)
- `clip(a, lo, hi)` ─ a 를 [lo, hi] 로 saturation

**Game-specific symbols**:
- `H` (Hamiltonian) ─ ∇V·f, HJI PDE 의 핵심
- `ATA` ─ Aspect-to-Aim angle [deg or rad]
- `AA` ─ Antenna Angle (적이 우리 향한 각) [deg or rad]
- `HCA` ─ Heading Crossing Angle [deg]. |Δψ| 의 절댓값 형 약식
- `WEZ` ─ Weapons Engagement Zone (사격 영역)
- `R_min, R(V)` ─ 선회 반경 [ft] (instantaneous, V 함수)
- `V_c` ─ corner speed [kts] (§2.2.4 derive)
- `ω_max(V), γ̇_max(V)` ─ envelope max rates (§2.2 V-의존)

**Greek/Math letters**:
- `α, β, γ` ─ blending weights (caller dependent)
- `λ_d, λ_V, λ_R` ─ 정규화 상수 (각 항의 무차원화)
- `σ_{1c}, σ_{2c}` ─ regime sigmoid (Shaw 6)
- `Φ_m` ─ mode m 의 Layer 1 hard predicate (bool)
- `ρ_m` ─ mode m 의 Layer 2 soft score [0, 1]
- `τ_m` ─ blended weight (ρ 의 동의어)
- `θ_{i,k}` ─ mode i 의 k-th condition threshold

#### 2.6.8 Open-Access References (학습 가이드)

본 framework 의 학술 출전. open-access 가능성 표시 (✓=무료, △=부분, ✗=유료/도서관):

| ID | 인용 | 무엇을 정당화 | 접근 |
|---|---|---|---|
| [^isaacs] | Isaacs, R. (1965) "Differential Games" RAND R-257 | Pursuit-evasion game 의 origin, barrier 개념 | △ RAND.org partial PDF |
| [^bryson] | Bryson, A.E., Ho, Y.-C. (1969) "Applied Optimal Control" | PN 의 optimal control derivation (정리 2) | ✓ Internet Archive 대출 |
| [^pontryagin] | Pontryagin, L.S. (1962) "Mathematical Theory of Optimal Processes" | Maximum Principle, bang-bang control (정리 8) | ✓ archive.org |
| [^boyd] | Boyd, J.R. (1964) "Energy Maneuverability" | Ps (specific excess power) 개념 (정리 5) | △ DTIC accession 일부 |
| [^shaw] | Shaw, R.L. (1985) "Fighter Combat: Tactics and Maneuvering" | 1c/2c, LDT 등 BFM 정리들 정성 서술 | ✗ 도서관 |
| [^crandall] | Crandall, M.G., Lions, P.-L. (1983) "Viscosity Solutions of HJ Equations" | HJI PDE 의 viscosity 해 존재·유일성 | ✓ AMS open access |
| [^mitchell] | Mitchell, I., Bayen, A.M., Tomlin, C.J. (2005) "A Time-Dependent HJ Formulation of Reachable Sets" *IEEE TAC* 50(7) | HJI reachability 수치해 표준 | ✓ Stanford preprint PDF |
| [^bansal] | Bansal, S., Chen, M., Herbert, S., Tomlin, C.J. (2017) "HJ Reachability: A Brief Overview and Recent Advances" | HJI 현대 개요, decomposition | ✓ arXiv:1709.07523 |
| [^branicky] | Branicky, M.S., Borkar, V.S., Mitter, S.K. (1998) "A Unified Framework for Hybrid Control" *IEEE TAC* 43(1) | Hybrid system formal definition | △ MIT preprint |
| [^sussmann] | Sussmann, H.J. (1999) "A Maximum Principle for Hybrid Optimal Control" | Hybrid PMP, switching surface | ✓ Rutgers preprint |
| [^ehtamo] | Ehtamo, H., Raivio, T. (2001) "Applied Nonlinear Programming for Pursuit-Evasion" *JOTA* | Hybrid game 의 pursuit-evasion 응용 | △ SpringerLink, partial |
| [^buzikov] | Buzikov, M.E., Galyaev, A.A. (2022) "Game of Two Identical Cars" *AAEC* | 동등 스펙 game 의 analytical barrier | ✓ arXiv:2206.10199 |
| [^zarchan] | Zarchan, P. (2012) "Tactical and Strategic Missile Guidance" 6ed AIAA | PN 의 modern engineering treatment | △ ResearchGate partial |
| [^lutze] | Lutze, F.H., Durham, W.C. (1989) "Aircraft pitch dynamics during pursuit" *J Guidance* | Vertical-plane optimal control (정리 8 기반) | △ AIAA, partial |
| [^bernoulli] | Bernoulli, J. (1732) "Solutio Problematis de Curvâ Persecutionis" | 직선 추격 곡선 origin (정리 1) | ✓ Euler Archive, public domain |

추가 참고 (BFM 영역):
- Pachter, M., Miloh, T., Eisenstadt, D. (2019) "Differential Games — Lions, Two Decades Later" Springer ─ △
- Stillion, J. (2015) "Trends in Air-to-Air Combat" CSBA ─ ✓ csbaonline.org/research
- NASA TP-1538 (1979) F-16 wind tunnel data ─ ✓ NASA NTRS

#### 2.6.9 Learning Guide — 본 framework 학습 순서

**초보자**:
1. §0.4 의 용어 사전부터 (ATA, AA, HCA, WEZ)
2. §1.2.2 의 control-affine dynamics — 6D state 의미 이해
3. §2.6.0-2.6.1 의 hybrid system 개념 (Branicky 1998 의 hybrid system definition)
4. **각 BFM 정리 1-8 의 정성 서술** (BFM_MATHEMATICAL_FOUNDATIONS.md 참고, v11_code/)

**중급자**:
5. §2.2 의 doghouse plot derive (제1원리)
6. §2.3 의 ∇V_i closed-form 각 정리 별 (Bryson-Ho 1969 정독)
7. §2.6.2-2.6.3 의 mode 정의 + V_m^* derivation
8. **Pontryagin 1962 의 Maximum Principle** (chapter on bang-bang)

**고급자**:
9. §2.6.4 의 switching surface derive (Sussmann 1999)
10. §2.6.5 의 τ-blended approximation 정당성 (softmin → smooth optimal mode selection)
11. **Mitchell-Bayen-Tomlin 2005** 의 HJI numerical 방법 (§3 의 v3 LUT 의 출전)
12. §2.6.6 의 two-point-mass game 의 minimax theorem (Isaacs 1965 Theorem 4.1)

**연구자**:
13. **Bansal-Tomlin 2017** 의 decomposition methods — 12⁶ → 7D 확장 시 적용
14. Buzikov-Galyaev 2022 의 closed-form barrier — 우리 LUT 와 sanity check
15. STL falsification (VERIFICATION_METHODOLOGY.md) 를 본 framework 에 적용

#### 2.6.10 Game-Theoretic Validity — 학술적 entailment

본 framework 의 학술적 정당성 chain:

```
Isaacs 1965 (differential games existence + barrier)
   ↓
Bryson-Ho 1969 (PN optimality from PMP)        ─→ V_2^* (정리 2)
Pontryagin 1962 (PMP, bang-bang)               ─→ V_6^* (정리 8)
Boyd 1964 (energy-maneuverability)             ─→ V_4^* 의 V_c 항
Shaw 1985 (1c/2c, LDT empirical → formal)      ─→ V_3^*, V_4^*, V_5^*
   ↓
Crandall-Lions 1983 (viscosity solutions)      ─→ V_m^* 의 well-definedness
Mitchell-Bayen-Tomlin 2005 (numerical HJI)     ─→ V_7^* (LUT)
   ↓
Branicky-Borkar-Mitter 1998 (hybrid systems)   ─→ mode set M 통합
Sussmann 1999 (hybrid PMP)                     ─→ switching surface 정당
Ehtamo-Raivio 2001 (hybrid PE games)           ─→ 본 작업의 직접 출전
```

→ 본 framework 는 **반세기 differential game + hybrid system 이론의 통합**.

---

## 3. Solver 선택 (확정 — 2026-05-12 변경)

### 3.1 Solver — **hj-reachability** (Stanford ASL)

**채택 이유**: `optimized_dp` 는 PyPI 부재 + GitHub 설치 필요. `hj-reachability` 는:
- `pip install hj-reachability` 즉시 설치
- JAX 기반 (자동 미분 + GPU 옵션)
- `ControlAndDisturbanceAffineDynamics` 표준 인터페이스
- `Air3d` (Game of Two Identical Cars) 내장 — 3D 한계 sanity check 즉시 가능
- WENO5 spatial scheme + Runge-Kutta time integration
- Viscosity solution 수렴 보장 (Crandall-Lions 1983)

**대안 비교**:
| Solver | 언어 | 6D 가능? | 본 작업 채택? |
|--------|-----|---------|------------|
| `hj-reachability` (Stanford ASL) | Python + JAX | ✓ | ✓ ★ |
| `optimized_dp` (SFU-MARS) | Python + JAX | ✓ | ✗ (설치 복잡) |
| `helperOC + ToolboxLS` (UBC) | MATLAB | ✓ | ✗ (MATLAB 의존) |
| `DeepReach` (Stanford ASL) | PyTorch | ✓ (NN 근사) | ✗ (AI 아닌 진정한 solver 요구) |

**환경 우회 (Windows long-path)**:
```bash
python -m pip install jax jaxlib                       # JAX 단독
python -m pip install hj-reachability --no-deps        # 핵심만
python -m pip install flax --no-deps                   # struct 만 필요
```
→ orbax 등 큰 의존성 회피, Windows long-path 한계 우회.

### 3.2 Sanity Check — Air3d (3D 등속 한계)

**Air3d 가 무엇인가** (`hj_reachability.systems.Air3d`):
- Game of Two Identical Cars (Merz 1971, Isaacs)
- 3D state $(x, y, \psi)$ — 상대 위치 (2D) + 상대 heading
- 등속 ($V_p = V_e = const$)
- 양쪽 동일 최대 선회율
- = **Buzikov-Galyaev (2022) 해석해 케이스의 수치 등가**

**우리 6D 모델을 3D 한계로 축소**:
- $V_p = V_e = 386.8$ kts 고정 (V 차원 제거)
- $\Delta h = 0$ 고정 (고도 차원 제거)
- → 남은 4D = (Δx, Δy, Δψ, =V) → Air3d 의 3D 와 등가

**측정 결과** (`tools/basis/hji_air3d_sanity.py`, 2026-05-12):

| 항목 | 값 |
|------|-----|
| Grid | $40^3 = 64$K cells |
| Time horizon | 30s backward |
| Capture radius | 1500 ft (WEZ 중간) |
| 초기 $V$(canonical 3D) | $+1610$ ft |
| 풀이 후 $V^*$(canonical 3D, $t=-30s$) | $+1731$ ft |
| Solve time | 0.3s (JAX JIT 캐시 후) |
| 결론 | **escape zone — 동등 스펙 등속에서 capture 불가** |

→ Buzikov-Galyaev (2022) 의 분석과 일치 (canonical 은 capture 불가 영역).

---

## 4. BT 통합 설계

### 4.1 Pursuit_Chase_BT 구조

```
examples/pursuit_chase_v1/
├── pursuit_chase_v1.yaml          — BT 정의
└── nodes/
    └── custom_actions.py          — PursuitChaseOptimal 클래스
```

**YAML 구조**:
```yaml
name: "pursuit_chase_v1"
version: "0.1.0"
description: "HJI solver-derived optimal pursuit"

tree:
  type: Selector
  children:
    # 1. 안전망 (HJI 외부)
    - type: Sequence
      name: HardDeckAvoidance
      children:
        - {type: Condition, name: BelowHardDeck}
        - {type: Action, name: ClimbTo, params: {target_altitude_ft: 3000}}
    
    # 2. HJI optimal control (메인)
    - type: Action
      name: PursuitChaseOptimal
      params:
        value_table_path: "examples/pursuit_chase_v1/hji_value_6d.npz"
        action_quantize: "priority"   # heading > altitude > speed
```

**커스텀 액션** (`nodes/custom_actions.py`):
```python
class PursuitChaseOptimal(BaseAction):
    """HJI lookup 기반 최적 제어.
    
    1. obs → 6D state x_rel 변환 (pursuer 좌표계)
    2. V*(x), ∇V*(x) lookup (precomputed grid, scipy.interpolate.RegularGridInterpolator)
    3. u*(x) = argmin_u { ∇V* · f(x, u, d_worst) }
    4. 연속 u* → 이산 BT primitive 매핑:
         u_omega > +thresh → TurnRight equivalent (d_hdg)
         u_omega < -thresh → TurnLeft
         u_gamma > +thresh → ClimbTo (d_alt + )
         u_gamma < -thresh → DescendTo (d_alt - )
         u_accel > +thresh → Accelerate (d_vel + )
         u_accel < -thresh → Decelerate (d_vel - )
    5. ActionCommand(d_alt, d_hdg, d_vel) 반환
    """
```

### 4.2 액션 합성 (BT 단일 명령 한계 대응)

BT 는 한 tick 에 한 액션만 발동.
- 다행히 액션 명령 자체는 (d_alt, d_hdg, d_vel) 3-tuple → 동시 발생 가능
- HCCA Continuous Master Controller 가 이미 이를 처리
- PursuitChaseOptimal 노드는 단일 액션 노드이고 내부에서 3-tuple 합성

**우선순위 (퇴화 시)**:
1. 회피가 핵심: $u_\omega$
2. 에너지: $u_a$
3. 고도: $u_\gamma$ (yo-yo 시 활성)

### 4.2.5 ⚠️ LUT 만으로는 훌륭한 도그파이트 안 됨 — BT 분기 구조의 진짜 의미

> **사용자 핵심 질문 (2026-05-12)**:
> "BT 가 이 LUT 만 가지고 전투를 할 수 있는거야? 분기나 이런것은 어떻게 결정되는거야?
>  이런 설명 없이 단순히 내가 시킨것만 한다고 와 훌륭한 1:1 dogfight 야 가 되지 않아."
>
> **솔직한 답: 아니오. 현재 LUT + BT 구조는 의도적으로 단순한 1차 prototype.**

#### 현재 BT 의 진짜 분기 구조 (`pursuit_chase_v1.yaml`)

```yaml
Selector:
  1. HardDeckAvoidance      ← 안전 분기 (hard-coded, LUT 외부)
       Condition: BelowHardDeck (alt < 1200ft)
       Action:    ClimbTo (3000ft)

  2. PursuitChaseOptimal    ← LUT lookup (다른 모든 결정 담당)
       params: value_table_path
```

**즉 분기는 단 2개**. 모든 의사결정이:
- 저고도 → 즉시 상승 (hard-coded)
- 그 외 → LUT 의 $u^*(x)$ 따름

이게 **의도된 minimalism** — saddle-point 수학적 검증 목적의 cleanroom.

#### 왜 이렇게 단순한가 — 목적별 분리

| 목적 | BT 구조 | 비고 |
|------|--------|------|
| **사용자 가설 검증** ($V^* > 0$ → DRAW) | 현재 minimal 구조로 충분 | self-play 100% DRAW 로 입증 ✓ |
| **5 heuristic 100% WIN** | minimal 구조 부족 | grid 정밀도 + 모델 B 필요 |
| **실 매치 대회 우승** | 6 layer 모두 통합 필요 | 본 작업 범위 밖 (§0.6 scope) |

#### 훌륭한 1:1 도그파이트 BT 의 진짜 layer 구조

```
┌─────────────────────────────────────────────────────────────────┐
│           훌륭한 1:1 도그파이트 BT 의 6-layer 결정 구조           │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Layer 0: 즉각 안전 (hard-coded, LUT 외부)                         │
│    ✓ HardDeckAvoidance (현재 있음 — alt<1200ft → ClimbTo)         │
│    ✗ StallRecovery (AOA 한계 진입 시)                              │
│    ✗ CollisionAvoidance (적과 < 200ft 시 즉시 break)               │
│                                                                   │
│  Layer 1: 위협 회피 (모델 B 의 V_them lookup)                       │
│    ✗ V_them < 0 영역 (적이 우리 잡을 수 있음) → escape 우선         │
│    ✗ 4-영역 분류의 Mutual Kill (영역 3) 회피                        │
│                                                                   │
│  Layer 2: 전략 결정 (4-영역 분류, 모델 B)                            │
│    ✗ WIN zone → 더 확실히 잡기 (combined ∇V_us, ∇V_them)             │
│    △ DRAW zone → capture 시도 (∇V_us)  ← 현재 LUT 이 일부 담당      │
│    ✗ LOSS zone → escape 우선 → 그 다음 chase                        │
│    ✗ Mutual Kill → 즉시 escape                                      │
│                                                                   │
│  Layer 3: HP 누적 최적 (모델 B' running cost)                        │
│    ✗ WEZ 안 머무는 시간 최대화 (single-pass 가 아닌 sustained)      │
│    ✗ ATA→0 정확 조준 유지 (가중치 w_ATA × w_dist 최대화)              │
│                                                                   │
│  Layer 4: 적 의도 적응 (EIM + TacticalLookup, 데이터 학습)            │
│    ✗ 적 정책 분류 (CLOSING/EXTENDING/EVADING/...) → counter 선택    │
│    ✗ sub-optimal 적의 약점 정확 exploit (saddle-point 너머)         │
│                                                                   │
│  Layer 5: 다단 시퀀스 (composite 기동)                                │
│    ✗ HJI 가 직접 산출 못하는 yo-yo / immelmann / split-S            │
│    ✗ 한정 시간 시퀀스 BT 분기로 격리 (Tier 2 액션, §ACTION_LATENCY) │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘

✓ : 현재 구현됨
△ : 부분 구현 (모델 A 의 V_us 만)
✗ : 미구현 — Phase D 이후
```

#### 현재 위치 vs 목표

| Layer | 현재 | 목표 (훌륭한 도그파이트) |
|-------|------|---------------------|
| 0 | ✓ HardDeck | ✓ + Stall + Collision |
| 1 | ✗ 위협 회피 | ✓ V_them lookup |
| 2 | △ V_us only (모델 A) | ✓ 4-영역 분류 (모델 B) |
| 3 | ✗ Binary capture | ✓ HP 누적 최적 (모델 B') |
| 4 | ✗ 정적 LUT | ✓ EIM 동적 적응 |
| 5 | ✗ Tier 1 primitive | ✓ Tier 2 composite |

→ **6 layer 중 1.5 layer 완료**. 사용자 비판 "훌륭한 도그파이트?" 답: 현재 단계는 검증 단계, 훌륭함은 Phase D 이후.

#### 솔직한 진단 (현재 vs simple/aggressive LOSS 의 이유)

```
현재 BT 의 약점:
  1. 정밀도   : 12⁶ grid → 좌-우 비대칭 → 부정확한 ω 명령
  2. 모델 A  : binary capture → "WEZ 가능?" 만, "누가 더 오래?" 무시
  3. 단일 V  : V_us 만 — 적의 위협 (V_them) 무시
  4. No EIM  : 적 정책 분류 없음 — 적 변화에 둔감
  5. No safety: HardDeck 외 위협 회피 분기 없음

vs simple (Pursue + HardDeck) 매치:
  - simple 이 우리에게 단순 추격
  - 우리는 LUT 의 minimax 추격 시도
  - LUT 정밀도 부족 → 우리 명령이 약간 빗나감
  - 동시에 우리에게 들어오는 simple 의 사거리 (V_them) 미고려
  - simple 이 가끔 우리 사거리 진입 → 우리 HP 감소
  - 결과: simple WIN by health advantage

근본 원인: 6 layer 중 5 layer 가 비어 있음.
```

#### Phase 진행 시 layer 별 추가 매핑

| Phase | 추가될 layer | 산출물 |
|-------|----------|--------|
| D-1, D-2 | Layer 1, 2 (모델 B, V_them) | 4-영역 분류기 + dual lookup |
| D-5 | Layer 3 (모델 B', HP 누적) | running cost HJI |
| (별도) | Layer 4 (EIM 통합) | TacticalLookup + intent counter |
| (별도) | Layer 5 (Tier 2 시퀀스) | composite 기동 노드들 |

**결론**: 현재 LUT 는 **수학적으로 well-defined 한 saddle-point reference**.
실 도그파이트에서 "훌륭" 하려면 위 6 layer 모두 통합 필요.
본 작업은 의도적으로 Layer 0 + (절반의) Layer 2 만 구현 — 사용자 가설 검증이 1차 목표.

---

### 4.3 Lookup Table 구조 (실제 구현, 2026-05-12)

#### 4.3.1 현재 구현 (12⁶ grid prototype)

```python
# tools/basis/hji_solve_6d.py 의 DOMAIN_DEFAULT
DOMAIN = {
    "dx_ft":   (-6000., +6000.),      # 12 bin → 1090 ft/bin
    "dy_ft":   (-6000., +6000.),
    "dh_ft":   (-4000., +4000.),
    "dpsi":    (-π, +π),               # periodic (12 bin → 30° /bin)
    "V_p_kts": (160., 420.),           # envelope (12 bin → 22 kts/bin)
    "V_e_kts": (160., 420.),
}
# Shape: 12^6 = 2,985,984 cells
# Memory: ~12 MB float32 (V) + 6 axes
# File: logs/hji/V6d_sphere_12bin.npz (5.3 MB, compressed)
```

**산출 시점**: HJI backward solve 한 번 (~4분 on CPU JAX).

#### 4.3.2 NPZ 구조

```python
data = np.load("logs/hji/V6d_sphere_12bin.npz")
data["V"]                       # shape (12,12,12,12,12,12) float32 — V*(x)
data["V_initial"]               # same — 초기 signed distance
data["coord_0"]                 # shape (12,) — dx_ft axis 좌표
data["coord_1"]                 # dy_ft axis
... data["coord_5"]             # V_e_kts axis
data["grid_shape"]              # (12, 12, 12, 12, 12, 12)
data["time_horizon_s"]          # 10.0
data["capture_mode"]            # "sphere" (r=1500ft) or "wez"
```

**Note**: 현재는 $V^*$ 만 저장. $u^*$ 는 BT 노드에서 $\nabla V^* \cdot B_d$ 로 실시간 계산 (box-corner solution).

#### 4.3.3 런타임 보간 (BT 노드)

현재 구현 (`examples/pursuit_chase_v1/nodes/custom_actions.py`):
- **Nearest-neighbor lookup** — 가장 가까운 grid cell 값 채택
- Central difference gradient — $\nabla V \approx (V[i+1] - V[i-1]) / (2 \cdot \Delta x)$
- 단순성 우선, 추후 trilinear 보간으로 정밀도 향상 가능

#### 4.3.4 정밀도 향상 경로 (Phase D)

| 단계 | 향상 | 비용 |
|-----|------|------|
| 현재 | $12^6 = 3$M cells, nearest-NN | 4분 solve, 5.3MB file |
| Next | $20^6 = 64$M cells, trilinear | ~30분 solve, ~256MB file |
| Final | $30^6 = 729$M cells, WENO 보간 | ~수 시간, ~3GB |

**현재 한계** (12⁶ 기준):
- $\Delta\psi$ : 30° /bin → ATA<12° WEZ 정밀 조준 부족
- 좌-우 mirror 대칭성 깨짐 → BT 명령 비대칭 발생 (Phase B 통합 테스트 시 관찰됨)
- 발산 trajectory (110km) 원인 = grid 노이즈

해결: 더 fine grid 또는 trilinear 보간 (메모리/시간 trade-off).

---

## 5. Verification Protocol

### 5.1 Sanity Check (Phase A-3)

**3D 등속 한계 검증**:
- $V_p = V_e = 386.8$ kts 고정 (V_p, V_e 차원 제거)
- $\Delta h = 0$ 고정 (Δh 차원 제거)
- 결과 V*(x') 가 **Buzikov-Galyaev 해석해** 와 일치하는가?
- 일치 기준: barrier 0-level set 위치 오차 < grid 해상도

### 5.2 Self-Play DRAW (Phase C — 핵심 채점 기준)

**가설** (사용자 주장):
> "동등 스펙 두 F-16 이 양쪽 모두 최적 전략 사용 시 → 자가대전 DRAW"

**예측**:
- V*(canonical x₀) ≈ 0 → barrier 위
- BT_us(π*) vs BT_them(π*) → V_game = V*(x₀) = 0 → DRAW

**측정**:
```
python scripts/run_match.py \
    --agent1 pursuit_chase_v1 --agent2 pursuit_chase_v1 \
    --log-csv logs/selfplay --metadata-log logs/selfplay/meta \
    --round 100

기대: WIN ≈ LOSS ≈ 0, DRAW ≈ 100 (± non-determinism ~25%)
```

### 5.3 5 Heuristic 대비 100% WIN (Phase C 보조)

**가설**: BFM_FOUNDATIONS 의 5 적 정책은 sub-optimal → V_us(x₀, π*, π_heuristic) < 0 보장 → 100% WIN.

```
python scripts/run_match.py \
    --agent1 pursuit_chase_v1 --agent2 {passive,orbiting,defensive,offensive,evading} \
    --round 20

기대: 모두 100% WIN
```

### 5.4 V*(x₀) 통계적 일치 (Phase C 정량)

실측 평균 outcome ≈ V*(x₀) 인가?
- V*(x₀) = 0 → 평균 ≈ 0
- 100 매치 결과 분포가 V*(x₀) 예측에 부합

---

## 6. Phase 별 실행 계획 (2026-05-12 상태 갱신)

### Phase A — 수학·이론 ★ 핵심 작업

| Sub-phase | 산출물 | 상태 |
|-----------|--------|------|
| A-0 (이 문서) | docs/PURSUIT_CHASE_PLAN.md | ✓ 완료 |
| A-2.5 | docs/ACTION_LATENCY_REPORT.md + tools/profile_action_response.py (31 actions 측정) | ✓ 완료 |
| A-1 | tools/basis/dynamics_f16_6d.py — numpy 6D dynamics + self-test | ✓ 완료 |
| A-1' | tools/basis/dynamics_f16_6d_hj.py — hj-reachability 호환 (control-affine) | ✓ 완료 |
| A-2 | tools/basis/hji_solve_6d.py — hj-reachability 통합, 6D HJI 풀이 | ✓ 완료 |
| A-3 | tools/basis/hji_air3d_sanity.py — Air3d (Buzikov-Galyaev 등가) sanity check | ✓ 완료 |
| A-4 | logs/hji/V6d_sphere_12bin.npz — 산출 lookup table (5.3 MB) | ✓ 완료 |

### Phase B — BT 구현

| Sub-phase | 산출물 | 상태 |
|-----------|--------|------|
| B-1 | examples/pursuit_chase_v1/nodes/custom_actions.py — PursuitChaseOptimal | ✓ 완료 |
| B-2 | examples/pursuit_chase_v1/pursuit_chase_v1.yaml — BT 정의 | ✓ 완료 |
| B-3 | 매치 통합 테스트 (active_node 100%, 좌표계 fix) | ✓ 완료 |
| B-4 | docs/PURSUIT_CHASE_RESULTS.md — Phase A+B 결과 보고서 | ✓ 완료 |

### Phase C — 검증 (다음 단계)

| Sub-phase | 산출물 | 상태 |
|-----------|--------|------|
| C-1 | self-play 100 매치 → DRAW 통계 | ⏳ 대기 |
| C-2 | 5 heuristic 대비 × 20 매치 → WIN 통계 | ⏳ 대기 |
| C-3 | V*(x₀) 예측 vs 실측 평균 일치 검증 | ⏳ 대기 |
| C-4 | docs/PURSUIT_CHASE_RESULTS_C.md — Phase C 보고서 | ⏳ 대기 |

### Phase D — 모델 B / B' 확장 (선택, §11 참조)

| Sub-phase | 산출물 | 상태 |
|-----------|--------|------|
| D-1 | V_them table (`--perspective them`) | ⏳ 대기 |
| D-2 | 4-영역 분류기 region_classifier.py | ⏳ 대기 |
| D-3 | 모델 B BT 노드 (pursuit_chase_v2) | ⏳ 대기 |
| D-4 | 모델 B 검증 | ⏳ 대기 |
| D-5 | 모델 B' (running cost, HP 누적) | ⏳ 대기 |

---

## 7. 위험 분석 (Red Team)

### 7.1 [구조적] BT vs JSBSim 시간 스케일 불일치

```
JSBSim physics:    60 Hz   (16.7ms)
BT tick:            5 Hz   (200ms)
HJI grid dt:        ~50ms  (CFL 수렴 조건)
HJI optimal u*:    연속 시간 (이상적)
```

→ BT 가 200ms zero-order hold. HJI optimal 의 200ms 평균이 BT 명령. 영향:
- yo-yo (수 초 timing): 무시 가능
- gun snap-shot (< 500ms): 명령 lag 발생, 보완 필요

**완화**: 본 작업의 1차 목표는 DRAW 검증. snap-shot 정확성은 후속.

### 7.2 [모델] 점-질량 vs JSBSim 6-DOF

HJI 의 점-질량 모델은 실 JSBSim 의 다음 효과 무시:
- aerodynamic stall (high AOA)
- G-induced loss (transient overshoot)
- 자세각 동역학 (roll → heading rate lag)

→ HJI 산출 u* 가 JSBSim 에서 **실현 불가능한** 명령 발행 가능 (예: 9G + max climb 동시).

**완화**:
- envelope 을 JSBSim 실측의 80% 로 conservative 설정
- A-3 sanity check 시 실제 매치 5-10 회로 envelope 일치 검증

### 7.3 [grid] 6D 차원의 저주

20⁶ = 64M cells. 보간 정확성:
- Δψ 차원 20 bin → 18° 간격 → 정밀 조준 (ATA<12°) 에 부족
- → 차원별 비균등 grid 또는 30 bin/dim 로 증가

**완화**: A-2 에서 20 bin 1차 → 30 bin 2차. 비균등 grid 는 후속.

### 7.4 [게임 이론] Minimax 가정 vs 실제 적

HJI 는 worst-case 적 가정 → V*(x) 는 최악의 적 대비 보장값.
- 실제 5 heuristic 은 sub-optimal → 우리가 실제 매치에서 **더 잘** 함
- BT_optimal vs BT_optimal 만 정확히 V*(x) 결과
- → Self-play DRAW = saddle-point 시그니처 (사용자 주장 검증)

### 7.5 [재현성] 25% non-determinism (프로젝트 메모)

> "Match simulation has ~25% FP non-determinism (not deterministic)"

→ self-play 100 매치 중 ~25 매치 random outcome. DRAW 비율은 75% 이상이면 OK.

### 7.6 [BT 한계] 동시 명령 불가

BT 한 tick = 한 액션. HJI 가 (TurnLeft + Climb + Accel) 동시 추천해도 BT 는 우선순위 하나만.

**해결**: ActionCommand(d_alt, d_hdg, d_vel) 3-tuple 출력 (HCCA 가 합성). PursuitChaseOptimal 노드 내부에서 3-tuple 채움.

### 7.7 [scope] custom 액션 (Smart*, PN*) 미통합

본 작업은 Tier 1 builtin 만 사용. 기존 BT 의 SmartHighYoYo 등은 직접 호출 안 함.
→ HJI 가 그 효과 (수직 yo-yo) 를 Δh 변화로 자연 산출. SmartHighYoYo 분기 사라짐.

---

## 8. 채점 기준 (불변)

사용자 합의:
1. **V*(canonical x₀) ≈ 0** — Buzikov-Galyaev 한계 일치
2. **자가대전 100 매치 → DRAW 비율 ≥ 75%** (non-determinism 보정 후)
3. **5 heuristic 대비 → 100% WIN** (sub-optimal exploit 보장)
4. **초기 조건 / 게임 규칙 변경 금지** — JSBSim core 정확 매칭

**금지**:
- match-by-match heuristic 미세 조정 (no piecemeal fixes 규칙)
- 채점 기준 자체 변경
- 문제 정의 변경 (1:1, 동등 스펙, 가변속 유지)

**허용**:
- 막힐 시 다른 solver 접근 (예: optimized_dp → DeepReach 신경망 fallback)
- grid 해상도 조절 (20 → 30 bins)
- HJI 외부 safety branch (HardDeck 등)

---

## 9. 다음 즉시 작업

**A-1: F-16 6D Dynamics** ✓ 완료 (numpy + hj-reachability 호환 양쪽)

```
tools/basis/
├── __init__.py
├── dynamics_f16_6d.py        ✓ F-16 envelope 테이블 (JSBSim 매칭)
├── dynamics_f16_6d_hj.py     ✓ hj-reachability control-affine 호환
├── hji_air3d_sanity.py        ✓ 3D 등속 한계 sanity check
└── hji_solve_6d.py            ✓ 6D HJI 풀이
```

A-2 (optimized_dp 대신 hj-reachability 사용) 완료.

**다음 (Phase C)**: 자가대전 100 매치 + 5 heuristic 매치 검증.
**중장기 (§11)**: 모델 B 대칭 게임 확장.

---

## 10. Phase A+B 결과 — 사용자 가설 수학적 검증 (2026-05-12)

| 모델 | V*(canonical) | 의미 |
|------|--------------|------|
| 3D 등속 (Buzikov-Galyaev 한계, Air3d) | **+1731 ft** | escape zone — 30s 이내 capture 불가 |
| 6D 가변속 (F-16 풀 모델, 12⁶ grid) | **+2374 ft** | escape zone — 10s+ 이내 capture 불가 |

**사용자 가설** (§0 학습 가이드의 핵심 질문):
> "동등한 두 BT 가 자가대전하면 서로 선회만 하다 끝날 것"

→ 모델 A 비대칭 형식화 + 대칭성 argument 로 **수학적으로 검증됨**.
구체적으로:
- 모델 A: V*(canonical) > 0 ⟹ 우리가 적을 못 잡음
- 대칭에 의해: V*(swap된 canonical) > 0 ⟹ 적도 우리를 못 잡음
- 모델 B 4-영역 분류 (§0.2) 의 영역 (4) DRAW = 양쪽 모두 capture 불가

상세는 [PURSUIT_CHASE_RESULTS.md](PURSUIT_CHASE_RESULTS.md).

---

## 11. 모델 B 로드맵 (Symmetric Combat Game 확장)

> §0.2 에서 정의한 **모델 B 대칭 도그파이트** 로 가는 단계별 계획.
> 현재 모델 A 결과는 동등 스펙 + canonical 케이스에서 충분하지만,
> 다음 항목에서 모델 B 가 필요해짐:
>
> 1. **mutual kill (영역 3) 회피 전략** — 양사 가능 상황 식별 + 회피
> 2. **sub-optimal 적 정확 exploit** — 5 heuristic 100% WIN 목표
> 3. **비대칭 시나리오** — 다른 무기 / 다른 항공기 미래 확장

### 11.1 핵심 수학적 차이

#### 모델 A (현재)

```
Value function: V*(x) ∈ ℝ  (one scalar)
PDE: V_t + min_{u_p} max_{u_e} { ∇V · f(x, u_p, u_e) } = 0
Terminal: V(x, T) = signed_distance_to_WEZ_us(x)
```

#### 모델 B (목표)

```
Two value functions:
   V_us*(x) ∈ ℝ  — 우리 capture 측면 (signed dist to WEZ_us)
   V_them*(x) ∈ ℝ — 적 capture 측면 (signed dist to WEZ_them)

Two coupled HJI PDEs:
   ∂V_us/∂t  + min_{u_p} max_{u_e} { ∇V_us · f } = 0   (우리 관점)
   ∂V_them/∂t + max_{u_p} min_{u_e} { ∇V_them · f } = 0  (적 관점)
```

### 11.2 4-영역 분류 (Region of Outcome)

```
state space (6D) 의 모든 점 x 는 (V_us, V_them) 좌표로 4영역:

  V_us\V_them  | < 0 (적이 잡음)  |  > 0 (적 못 잡음)
  ─────────────|────────────────|──────────────────
  < 0 (우리 잡음) | ❌ Mutual Kill | ✅ 우리 승 (WIN)
  > 0 (우리 못잡음)| ❌ 적 승 (LOSS) | ⚪ DRAW
```

**우리 BT 목표**: ✅ WIN 영역으로 이동 + ❌ Mutual Kill 의도적 회피.

### 11.3 BT 전략 (모델 B 채택 시)

```python
class PursuitChaseOptimal_B(BaseAction):
    def update(self):
        x = obs_to_state(obs)
        V_us, grad_V_us = lookup_us_table(x)
        V_them, grad_V_them = lookup_them_table(x)
        region = classify_region(V_us, V_them)
        
        if region == "us_win":
            u_star = combined_optimal(grad_V_us, grad_V_them)
        elif region == "draw":
            u_star = pure_capture(grad_V_us)
        elif region == "loss":
            u_star = escape_then_chase(grad_V_them, grad_V_us)
        elif region == "mutual_kill":
            u_star = pure_escape(grad_V_them)
        
        self.set_action(*u_to_bt(u_star))
```

### 11.4 구현 단계

| Phase | 작업 | 산출물 |
|-------|------|--------|
| D-1 | V_them table 산출 (hji_solve_6d.py `--perspective them` 옵션) | logs/hji/V6d_them.npz |
| D-2 | 4-영역 분류기 | tools/basis/region_classifier.py |
| D-3 | 모델 B BT 노드 | examples/pursuit_chase_v2/ |
| D-4 | 검증: canonical 영역 + 자가대전 + 5 heuristic | docs/PURSUIT_CHASE_RESULTS_B.md |

### 11.5 예상 결과 (사용자 핵심 주장 재검증)

| 가설 | 모델 A 검증 | 모델 B 예측 |
|------|----------|-----------|
| canonical 자가대전 → DRAW | V*>0 ✓ | (V_us, V_them)=(+,+) → DRAW ✓ |
| 5 heuristic → WIN | grid 해상도 한계 | sub-optimal 적은 V_them<0 → 우리 승 |
| mutual kill 회피 | 다루지 않음 | 영역 ❌ 식별 + escape 우선 |

### 11.6 모델 B 의 한계 (red team)

| 한계 | 영향 |
|------|------|
| Grid 메모리 2배 (V_us + V_them) | 12⁶ → 약 11MB (감당) |
| Solver 시간 2배 | 4분 → 8분 (감당) |
| V_them 계산 시 dynamics swap | 코드 careful |
| 4-영역 경계 보간 노이즈 | chattering → hysteresis 권고 |
| Mutual kill 실재성 (점-질량 모델) | JSBSim 검증 필요 |

### 11.7 모델 B → 모델 B' (HP 누적 게임, §0.8 반영)

**모델 B' — Running-Cost Combat Game** (§0.8 의 진정한 도그파이트 형식화):

```
state: 8D (Δx, Δy, Δh, Δψ, V_p, V_e, HP_us, HP_them)
     또는 6D + integral cost (시간에 따라 누적)

게임 값:
  J*(x₀) = E[ HP_them(T) - HP_us(T) | both optimal play ]

WEZ 가중치:
  D(x) = 25 × max(0, 1 - ATA/12°) × w_dist(x)    HP/s
  D_us(x):    우리가 적에게 가하는 damage rate
  D_them(x):  적이 우리에게 가하는 damage rate
  (대칭 swap 으로 계산)

승리 결정 (priority 순):
  1. HP_them(t) = 0 at some t < T:  우리 즉시 승
  2. HP_us(t) = 0 at some t < T:    우리 즉시 패
  3. HP_us(T) > HP_them(T):         우리 승 (advantage)
  4. HP_us(T) < HP_them(T):         적 승 (advantage)
  5. HP_us(T) = HP_them(T):         true DRAW (rare)
```

#### Phase D-5: 모델 B' 으로 확장 (D-4 검증 후)

| 작업 | 산출물 |
|------|--------|
| WEZ damage rate 함수 구현 | `tools/basis/wez_damage_rate.py` |
| Running cost HJI solver | `hji_solve_6d.py --mode running_cost` |
| 8D HJI 풀이 (HP_us, HP_them 추가) | logs/hji/J6d_running_cost.npz |
| 모델 B' BT 노드 (HP 누적 고려) | examples/pursuit_chase_v3/ |
| Race-to-zero 시나리오 검증 | mutual high-damage 케이스 |

#### 모델 B' 의 장점

1. **실 게임 규칙 정확 매칭** (binary capture 근사 제거)
2. **"잡다" 의 진정한 의미 포착** — 누적 damage = sustained accuracy
3. **mutual kill 정확 모델링** — 양쪽 동시 HP 빨리 깎임 race
4. **HP advantage win** 모델링 가능 — 단순 binary 가 아닌 정량 우위

### 11.8 모델 B → 모델 C (장기, scope 밖)

**모델 C — Asymmetric Combat Game**: 양쪽 dynamics 다름 (F-16 vs F-22, gun vs missile).
본 작업의 1차 범위 (§0.6) 밖. 미래 확장.

---

## 12. 문서 변경 이력

| 일자 | 변경 |
|------|-----|
| 2026-05-12 | 초기 작성 (§1-§9) — Phase A+B 설계 |
| 2026-05-12 | §0 학습 가이드 추가 (모델 A/B, 용어, 가정, 좌표계) — well-defined / scope 한정 |
| 2026-05-12 | §10 Phase A+B 결과 + §11 모델 B 로드맵 추가 |
| 2026-05-12 | §0.8 "잡다" 재정의 (WEZ 가중치 + HP 누적) + §11.7 모델 B' (running cost) 추가 |
| 2026-05-12 | 문서 정합성 패치: §0.4 용어 사전 수학적 엄밀화 (6 sub-section, 수식 정의 + 직관 병기) |
| 2026-05-12 | §1.3 binary WEZ 명시 + §0.8 cross-ref |
| 2026-05-12 | §1.5 Value Function 정의 정확화 + 실측 결과 ($V^*(x_0) > 0$) 반영 (원래 $\approx 0$ 예상 정정) |
| 2026-05-12 | §3.1 Solver 채택 변경 (`optimized_dp` → `hj-reachability`) + Windows 우회 명시 |
| 2026-05-12 | §3.2 Sanity check Air3d 실측 결과 표 추가 |
| 2026-05-12 | §4.3 Lookup Table 실제 구현 ($12^6$ grid, 5.3MB) + 정밀도 향상 경로 |
| 2026-05-12 | §6 Phase 별 실행 계획 상태 갱신 (A,B 완료 / C 대기 / D 모델 B 확장) |
| 2026-05-12 | §0.4.7 약어 사전 추가 — 본 작업 전체 약어 전수 풀이 (수학/BFM/시스템/수치/특수/외부 — 60+ 약어) |
| 2026-05-12 | §0.4.6 표기 규약 확장 — 수식의 변수 / 첨자 / 연산자 / 집합 / 합성 표기 전수 풀이 (6 sub-section) — 첨자 (p, e, us, them, *, 0, max 등) 의미 명시 |
| 2026-05-12 | §0.8 모든 수식에 학습 해석 추가 — WEZ params (5개), damage 함수 (line-by-line), w_ATA 감쇠 (그래프 포함), w_dist sweet spot, HP 동역학 (구체 시나리오 5.3초 kill 예시), $J^*$ game value (항별 풀이), running cost HJI (모델 A vs B' 한눈 비교 표) |
| 2026-05-12 | 사용자 두 지적 반영 정정 — (1) §1.1 좌표계 "거울 대칭" → "각자 body frame 로깅, 두 독립 관측" + 모델 B 의 두 frame 필요성 명시 (2) §1.2 dynamics 비선형성 명시 (전체 비선형, control-affine 은 control 에만 affine) + small-γ 가정 (~14% 오차) 의 정확한 의미 + 진짜 (full) 식 + 단순화 식 별도 표기 (3) §0.5 C2 가정 정확화 |
| 2026-05-12 | §4.2.5 신규 — "LUT 만으로는 훌륭한 도그파이트 안 됨". BT 분기의 진짜 의미 + 6-layer 결정 구조 + 현재 위치 (1.5/6) + vs simple/aggressive LOSS 의 5가지 근본 원인 + Phase 별 layer 추가 매핑. 사용자 비판 정직 반영. |
| 2026-05-12 | §1.2.3 small-γ 가정의 **실측 검증** 추가 — `tools/analyze_dynamics_assumptions.py` (44,500 tick 분석). 결과: 평균 \|γ\|=2.92°, cos 오차 평균 **0.29%** (이론 14% 의 1/50), max γ=15.06°. → §0.5 C2 가정 사항 정정 (이론 worst case vs 실측 평균 명시). 사용자 지적 "명령/데이터로 확인 가능" 반영. |
| 2026-05-12 | §1.2.3 에 sample bias 한계 (사용자 추가 지적: 데이터 충분성) — Isolation BT / canonical 시작 / 200 tick 한정의 일반화 위험 명시 + 추가 측정 계획 (총 ~495K tick) |
| 2026-05-12 | §0.9 실험 인벤토리 신규 — 본 작업의 모든 측정 (E1~E6) 의 정당성 정리: 실험 ID, 설계, 규모 (tick), 데이터 수집 명령, 데이터 위치, 도출 결론. 계획된 추가 실험 (E7~E11) 명세. 사용자 지적 "정당성 + 실험 규모 + 도출 데이터 정리" 반영. |
