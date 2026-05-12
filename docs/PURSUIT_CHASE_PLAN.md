# Pursuit_Chase_BT — Solver-First Design Plan

> **목적**: 1:1 F-16 도그파이트를 6D zero-sum differential game 으로 형식화하고
> Hamilton-Jacobi-Isaacs (HJI) 수치 solver 로 풀어, 그 결과를 BT 노드 lookup 으로
> 구현. Heuristic τ 함수 대신 수학적으로 정의된 saddle-point 전략 사용.
>
> **참조**:
> - [BFM_MATHEMATICAL_FOUNDATIONS.md](../examples/adaptive_eagle_v11_code/BFM_MATHEMATICAL_FOUNDATIONS.md) — 정리 1-8 출전
> - [open_access_references.csv](open_access_references.csv) — 18개 open-access 논문
> - [ACTION_LATENCY_REPORT.md](ACTION_LATENCY_REPORT.md) — HJI primitive 식별 완료
>
> **상태**: 2026-05-12 작성, Phase A-2.5 (action profiling) 완료. Phase A-1 (dynamics) 진행 중.

---

## 1. 문제 정의

### 1.1 1:1 도그파이트 = 6D Zero-Sum Differential Game

**플레이어**: pursuer P (우리), evader E (적). 양쪽 동등 스펙 F-16.

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

**A-1: F-16 6D Dynamics in JAX**

```
tools/basis/
├── __init__.py
└── dynamics_f16_6d.py
    - F-16 envelope 테이블 (JSBSim 매칭)
    - 6D dynamics ODE
    - 제어 한계 함수
    - 단위 테스트: canonical x₀ → dx/dt 계산 검증
```

이 후 A-2 (optimized_dp 통합) 로 진행.
