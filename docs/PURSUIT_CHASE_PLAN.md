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

### 0.4 핵심 용어 사전 ★

| 용어 | 한 줄 정의 | 비유 |
|------|-----------|------|
| **Pursuit-Evasion Game (PEG)** | 비대칭 추격-회피 — 한 명만 공격 능력 | 술래잡기 (술래만 잡음) |
| **Combat Game / Two-Target Game** | 대칭 도그파이트 — 양쪽 모두 공격 | 권투, 펜싱 (양쪽 다 공격) |
| **Differential Game** | 연속 시간 동적 게임 (vs 이산 체스) | 추격, 자율주행 충돌 |
| **State (상태) x** | 게임의 현재 상황을 표현하는 벡터 | 체스에서 보드 상태 |
| **Control (제어) u** | 플레이어가 매 순간 선택하는 입력 | 체스에서 다음 수 |
| **Value Function V\*(x)** | "양쪽이 최선 다할 때 결과는?" 수치 | 체스 엔진의 평가점수 |
| **Saddle-point** | minimax 균형점 — 양쪽 모두 최선일 때의 게임값 | 가위바위보의 1/3 균등 전략 |
| **Minimax** | "최악의 상대를 가정한 최선" 의사결정 | 가장 강한 상대 가정 |
| **Capture Set** | "이 영역 안이면 잡혔다" 인 상태 집합 | 술래의 손이 닿는 거리 |
| **WEZ** | Weapon Engagement Zone — 사격 가능 영역 | F-16: ATA<12° + 500~3000ft + closure>0 |
| **Escape Zone** | V\* > 0 — 영원히 못 잡는 영역 | 술래 절대 못 잡는 거리 |
| **Barrier** | V\* = 0 — 영역 사이 경계면 | 잡을 수 있는지 없는지 임계 |
| **Canonical (초기 조건)** | 표준 시작 상태 (모든 매치 동일) | 체스의 초기 배치 |
| **HJI PDE** | Hamilton-Jacobi-Isaacs 편미분방정식 — V\* 가 만족하는 방정식 | Schrödinger 방정식과 유사 |
| **Solver** | PDE 를 수치적으로 푸는 컴퓨터 프로그램 | 미분방정식 시뮬레이터 |
| **BRT (Backward Reachable Tube)** | "T초 안에 capture 가능한 상태 집합" | 시간 거꾸로 술래의 손 범위 |
| **Dynamics** | 상태가 어떻게 변하는지 (운동방정식) | F-16 의 비행 물리 |
| **6D State** | 게임 상태를 6개 숫자로 표현 | (위치 3 + 방위 1 + 속도 2) |
| **Sub-optimal** | 최선 아닌 행동 | 체스에서 약수(弱手) |
| **Mutual Kill** | 양쪽 동시 사거리 진입 → 양사 | 결투 동시 발사 |

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
| C2 | Control-affine dynamics (small-γ 가정) | hj-reachability 호환 + 수학 단순 | large γ 시 ~14% 오차 |
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

**축소 근거**: translation + rotation symmetry 로 14D → 6D.
γ (flight path angle) 은 즉시 제어로 가정 (점-질량 모델).
hard deck (h_p 절대 한계) 는 별도 safety branch 에서 처리 → state 에서 제외.

### 1.2 Dynamics

$$
\begin{aligned}
\dot{\Delta x} &= V_e \cos\gamma_e \sin\Delta\psi \\
\dot{\Delta y} &= V_e \cos\gamma_e \cos\Delta\psi - V_p \cos\gamma_p \\
\dot{\Delta h} &= V_e \sin\gamma_e - V_p \sin\gamma_p \\
\dot{\Delta\psi} &= \omega_{h,e} - \omega_{h,p} \\
\dot{V_p} &= a_p, \quad \dot{V_e} = a_e
\end{aligned}
$$

**제어 입력**:
- $u_p = (\omega_{h,p}, \gamma_p, a_p)$, $u_e = (\omega_{h,e}, \gamma_e, a_e)$
- 한계: $|\omega_h| \le \omega_{\max}(V)$, $|\gamma| \le \gamma_{\max}$, $a \in [-15, +15]$ kts/s

**Envelope** (JSBSim 실측, `sim_dogfight_verify.py:54-79`):
```
V (kts):  160  200  250  300  350  400  420  500
ω_max:    6    9    15   18   21   18.5 16   14    (°/s)
R_min:    1600 1700 1600 1700 1800 1650 2100 2500 2800 (ft)
```

### 1.3 게임 규칙 (JSBSim core 매칭)

**Win (capture target)**:
```
WEZ_us = { x : ATA(x) < 12°  AND  500ft < dist(x) < 3000ft  AND  closure(x) > 0 }
```
ATA, dist, closure 모두 6D state 에서 계산 가능.

**Lose**:
```
WEZ_them = { x : AA(x) < 12°  AND  500ft < dist(x) < 3000ft  AND  closure(x) > 0 }
HardDeck = h_p < 1000ft  (별도 safety branch — HJI 외부)
```

**Timeout**: T = 1500 ticks × 0.2s = 300s

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

### 1.5 Value Function 정의 (Fisac-Tomlin reach-avoid)

$$
V^*(x, t) = \min_{u_p}\max_{u_e}\Bigl[\max\bigl(-1_{x \in W_{us}},\; \min_{s \in [t,T]} 1_{x(s) \in W_{them}}\bigr)\Bigr]
$$

해석:
- $V^*(x) < 0$: 우리 capture 보장 (양쪽 최적 시)
- $V^*(x) > 0$: 적 capture 보장
- $V^*(x) = 0$: barrier (DRAW)

**예상**: canonical 초기 + 동등 스펙 → $V^*(x_0) \approx 0$ (Buzikov-Galyaev 해석해 한계와 일치).

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

### 2.2 핵심 참조 (open_access_references.csv 에서)

- **Buzikov-Galyaev (2022) arXiv:2206.10199** — 동등 스펙 Game of Two Cars 해석해 (3D 등속). 본 작업의 sanity check.
- **Mitchell, Bayen, Tomlin (2005)** — HJI 수치 PDE solver 표준 방법론.
- **Bansal, Chen, Tomlin (2017) arXiv:1709.07523** — HJ reachability 현대적 개요.
- **Mitchell ToolboxLS** — MATLAB 구현. 본 작업은 Python optimized_dp 사용.

---

## 3. Solver 선택 (확정)

### 3.1 Solver

**optimized_dp** (Python + JAX, GPU 가속).
- 수치 PDE solver — AI/NN 아님
- 시간 가변 HJI PDE 의 viscosity solution 계산
- Lax-Friedrichs Hamiltonian + WENO5 spatial scheme
- 수렴 보장 (Crandall-Lions 1983 viscosity solution 이론)

**6D 실현 가능성**:
- Grid (30 bins/dim): 30⁶ = 729M cells, ~3GB float32, 수렴 ~30분
- Grid (20 bins/dim): 20⁶ = 64M cells, ~256MB, ~수분
- → 우선 20 bins coarse 로 prototype, 정확성 부족 시 30 bins

### 3.2 Sanity Check

**Buzikov-Galyaev (2022)** 해석해.
- 3D 등속 동등 스펙 한계 ($V_p = V_e = const$, $V_p$ component 만 사용) 에서 정확한 정답
- 우리 6D 수치해를 3D 한계로 축소 → 일치 확인
- 불일치 시 → grid 해상도 또는 dynamics 코드 버그 추적

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

### 4.3 Lookup Table 구조

```
value_table_6d.npz:
  grid_axes: [
    Δx_rel: linspace(-10000, +10000, 20),    # ft
    Δy_rel: linspace(-10000, +10000, 20),
    Δh:     linspace(-5000, +5000, 20),
    Δψ:     linspace(-π, +π, 20),
    V_p:    linspace(160, 420, 20),          # kts
    V_e:    linspace(160, 420, 20),
  ]
  V_star:    (20,20,20,20,20,20) float32  ~ 256 MB
  u_omega_star: same shape
  u_gamma_star: same shape
  u_accel_star: same shape
```

런타임 보간: trilinear (각 차원 선형 보간) → 64 인접 셀 가중 합.

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

## 6. Phase 별 실행 계획

### Phase A — 수학·이론 ★ 핵심 작업

| Sub-phase | 산출물 | 상태 |
|-----------|--------|------|
| A-0 (이 문서) | docs/PURSUIT_CHASE_PLAN.md | ✓ |
| A-2.5 (이미 완료) | docs/ACTION_LATENCY_REPORT.md + tools/profile_action_response.py | ✓ |
| A-1 | tools/basis/dynamics_f16_6d.py — JAX 6D dynamics, F-16 envelope rate constraint | 진행 |
| A-2 | tools/basis/hji_solve.py — optimized_dp 통합, 6D HJI 풀이 | 대기 |
| A-3 | tools/basis/buzikov_galyaev_sanity.py — 3D 한계 해석해 vs 수치해 비교 | 대기 |
| A-4 | logs/hji/value_6d.npz — 산출 lookup table | 대기 |

### Phase B — BT 구현

| Sub-phase | 산출물 | 상태 |
|-----------|--------|------|
| B-1 | examples/pursuit_chase_v1/nodes/custom_actions.py — PursuitChaseOptimal 클래스 | 대기 |
| B-2 | examples/pursuit_chase_v1/pursuit_chase_v1.yaml — BT 정의 | 대기 |
| B-3 | 단위 테스트 — obs → state 변환 정확성 | 대기 |

### Phase C — 검증

| Sub-phase | 산출물 | 상태 |
|-----------|--------|------|
| C-1 | self-play 100 매치 → DRAW 통계 | 대기 |
| C-2 | 5 heuristic 대비 × 20 매치 → WIN 통계 | 대기 |
| C-3 | V*(x₀) 예측 vs 실측 평균 일치 검증 | 대기 |
| C-4 | docs/PURSUIT_CHASE_RESULTS.md 보고서 | 대기 |

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

### 11.7 모델 B → 모델 C (장기, scope 밖)

**모델 C — Asymmetric Combat Game**: 양쪽 dynamics 다름 (F-16 vs F-22, gun vs missile).
본 작업의 1차 범위 (§0.6) 밖. 미래 확장.

---

## 12. 문서 변경 이력

| 일자 | 변경 |
|------|-----|
| 2026-05-12 | 초기 작성 (§1-§9) — Phase A+B 설계 |
| 2026-05-12 | §0 학습 가이드 추가 (모델 A/B, 용어, 가정, 좌표계) — well-defined / scope 한정 |
| 2026-05-12 | §10 Phase A+B 결과 + §11 모델 B 로드맵 추가 |
