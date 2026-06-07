# 12장. 오프라인 정책 도출 방법론

## 학습 목표
이 장을 마치면 다음을 할 수 있다.
- 경기 중이 아니라 경기 전에 무겁게 계산하는 이유를 안다.
- 데이터 수집, 라벨링, 회귀 학습, 배포의 네 단계를 설명한다.
- 상황 군집(KMeans)과 forward-sim 라벨링이 무엇인지 안다.
- 학습된 정책이 policy_value.pkl 로 어떻게 배포되는지 안다.


> 1:1 WVR 공중전 AI 파일럿을, 투명·인용가능·결정론 스택으로 재구축하고,
> 오프라인 solver(데이터 기반) 로 전술 정책을 도출하는 시스템의 전체 설명서.
> 작성: 2026-06-03 (진행 중)

---

## 0. 한 줄 요약

```
RNN 블랙박스 저수준 제어  →  LQR 투명 제어 (인용가능)
온라인 if-then/cost 튜닝  →  오프라인 solver 가 데이터로 정책 도출
단일 글로벌 cost          →  물리 기반 상호배타 상황 + 상황별 전술
손 포팅 적 4종            →  generic yaml 인터프리터로 legacy 970 적 자동
```

핵심 명제: dogfight 는 상황의 조합이다. 모든 상황을 하나의 두뇌로 처리하지 않고,
상황을 (물리로) 분리하고 각 상황의 최적 전술을 (결정론 시뮬 데이터로) 도출한다.

---

## 0.5 주요 가정 (연구 논의의 출발점)

> 연구는 항상 가정을 먼저 밝혀야 합니다. 아래가 무너지면 결론도 다시 봐야 합니다.
> 각 가정에 왜 두는지와 무너지면 무엇이 바뀌는지를 함께 적습니다.

| # | 가정 | 왜 (근거) | 무너지면 |
|---|---|---|---|
| A1 | 1v1 · WVR · 기총만 (미사일·다수기 없음) | 문제를 BFM 핵심으로 한정 (judge: WEZ gun) | 다대다·BVR이면 전술 체계 전면 재설계 |
| A2 | 완전관측 (적 상태 정확) — 위치·속도·자세·선회율 직접 | new_engine은 sim 내부값 직접 관측(노이즈/센서 모델 없음) | 부분관측이면 적 의도추정(EIM)·필터 필요 |
| A3 | 결정론 (RNG 없음) — 같은 IC → 같은 결과 | JSBSim 결정론 + side-switch 없음 → 1회 시뮬=참값 | 확률적이면 MC 다회·기댓값 라벨 필요 |
| A4 | 적 = 고정 정책 (.yaml BT, 학습 중 안 변함) | 평가·라벨이 재현가능 (적이 우리에 맞춰 진화 안 함) | 적응적 적이면 self-play·minimax 필요 |
| A5 | 평가 초기조건 = canonical beam (90° anti-parallel 3000ft) | 누구도 안 유리한 공정 시작 → 정책 실력만 평가 | 다른 spawn은 유불리가 결과 오염 (∴ 데이터生成 전용) |
| A6 | 게임 규칙 = judge가 closed-form (WEZ: ATA<12°·500–3000ft·25HP/s, Hard Deck 1000ft) | cost/라벨에 *추측 없이* 그대로 박음 (Oracle 불필요) | 규칙 바뀌면 라벨·shaping 재계산 |
| A7 | 상황은 물리로 상호배타 분리 가능 (지배 물리량이 다름) | 추격=속도, 선회=선회율 → 최적 전술 정반대(§3.1) | 분리 안 되면 단일 cost 자기모순 회귀(실측 §5.7) |
| A8 | JSBSim 6-DOF = 충분히 충실한 물리 | rollout 라벨이 실제 비행과 일치한다고 가정 | sim-to-real gap이면 대리모델 fidelity가 블로커 |
| A9 | 저수준 제어(LQR)는 setpoint를 잘 추종 | 의사결정층이 기동(어떻게)을 신뢰 | 추종 실패면 전술 무의미 — 단 측정상 제어는 물리한계(4.8G)까지 씀 |

→ 본 문서의 모든 수치·전술은 A1–A9 하에서의 결과입니다. 특히 A4(고정 적)·A5(beam)·A6(closed-form
규칙)이 "오프라인 결정론 solver로 정책을 도출" 한다는 방법론 전체를 떠받칩니다.

---

## 1. 전체 아키텍처

### 1.1 계층 (무엇이 있나)

데이터가 위→아래로 흐릅니다. 위는 "무엇을 할지(전략)", 아래로 갈수록 "어떻게(물리)".

```
┌─────────────────────────────────────────────────────────────┐
│ [의사결정]  obs → 상황분류 → 전술(Tactic) 선택                  │
│   · 온라인:  RealRollout (실엔진 rollout)  — baseline          │
│   · 오프라인: 학습된 value 정책 (RandomForest) ← 본 문서 핵심   │
├─────────────────────────────────────────────────────────────┤
│ [유도]  Tactic → Setpoint(ψ*, h*, v*)        guidance.py      │
│   연속 setpoint (이산 bin 아님). 14종 BFM tactic.             │
├─────────────────────────────────────────────────────────────┤
│ [제어]  Setpoint → u[thr,elev,ail,rud]       autopilot.py     │
│   Outer PI(고도·속도) + Outer P(협조선회) + Inner LQR          │
├─────────────────────────────────────────────────────────────┤
│ [물리]  JSBSim F-16 6-DOF (native FLCS)      plant.py         │
├─────────────────────────────────────────────────────────────┤
│ [판정]  WEZ 데미지 + Hard Deck                judge.py         │
│   ATA<12° ∧ 500~3000ft → 25HP/s. HardDeck<1000ft 패배        │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 동작 흐름 — 매 틱 무엇이 도나? (multi-rate)

전체가 매 틱 다 도는 게 아닙니다. 계층마다 다른 주파수로 돕니다 (legacy 동일):

| 계층 | 주파수 | 주기 | 무엇이 반복 |
|---|---|---|---|
| 물리 (JSBSim) | 120 Hz | 8.3ms | 6-DOF 적분 (가장 촘촘) |
| 제어 (autopilot LQR) | 20 Hz | 50ms | setpoint → 조종면 u |
| 의사결정 (상황→전술) | 10 Hz | 100ms | 정책이 도는 곳 (가장 드묾) |

왜 다른 주파수? 물리는 정확도(촘촘)·제어는 안정(중간)·의사결정은 BFM 시간척도
(전술은 초 단위라 0.1초마다면 충분 + 비싼 계산을 덜 돌림). 의사결정을 더 빨리 돌려도
거동은 같고 연산만 늚(측정 확인).

한 제어틱(50ms) 안의 순서 (sequential):
```
1. obs 계산        compute_obs(우리,적) + compute_obs(적,우리)  (양방향)
2. [10Hz 틱일 때만] 상황분류 → 전술 선택  (+ dwell: 0.3초 내 전환 거부 = chatter 방지)
3. 유도            전술 → setpoint(ψ*,h*,v*)
4. 제어            setpoint → u  (LQR: u = u₀ − K·(x−x*))
5. u 적용 → 물리 6 substep 전진 (120Hz)
6. WEZ 데미지 적분 + judge (hard deck / health=0 / timeout)
```
→ 매 50ms마다 1~6 반복, 단 2(의사결정)는 100ms마다만. 의사결정 1회 비용:
온라인 rollout=수백 ms(그래서 1초 캐싱), 배포 정책=μs(feature→RF→argmax, 시뮬無).

### 1.3 왜 이 스택인가 (3대 약속과 연결)
- LQR (RNN 대체): 인용가능·투명(게인 해석)·결정론(오프라인 solver 전제).
- 연속 setpoint (이산 bin 대체): WEZ 정밀 조준(ATA<12°) 분해능.
- 결정론 (RNG 없음): "같은 상태=같은 결과" → §5 오프라인 학습의 핵심 전제.

### 1.4 유도(Guidance) 상세 — Tactic을 목표값(setpoint)으로

역할: 전술(예 PURE_PURSUIT)을 받아 목표 방위 ψ\*, 목표 고도 h\*, 목표 속도 v\* 로 번역.
입력은 obs(상대 기하), 출력은 setpoint 세 값. 14종 tactic이 각자 다른 공식을 씀.

(a) 방위 ψ\* — "코를 어디로 둘까" (대표 tactic)

먼저 `rel_b`(적 상대방위) — 적이 우리 기수에서 몇 도 틀어져 있나:
```
              우리 기수 = 0°
                    ↑
        좌(−) ◀──  △  ──▶ 우(+)        rel_b = +60° → "적이 내 오른쪽 60°"
                  우리                   ψ* 공식의 +rel_b = 그쪽으로 코를 돌려라
```

세 가지 추격(pursuit) — 적 비행경로의 어디를 겨누나:
```
                      적 진행 방향 ──────────────▶
            ◌ ─────────── ● ─────────── ◌
         (적 뒤·과거)   (적 현위치)   (적 앞·미래)
            LAG           PURE          LEAD
             ↖             ↑             ↗
              ╲            │            ╱
               ╲           │           ╱        ← 우리 "코(nose)"를 어디로?
                ╲          │          ╱
                 ╲         │         ╱
                  ╲        │        ╱
                   ╲       │       ╱
                    ╲      │      ╱
                     ◤───  △  ───◢
                          우리
```

| Tactic | 겨냥점 | ψ\* 공식 | 효과 |
|---|---|---|---|
| LEAD_PURSUIT | 적 앞 | `heading + rel_b + k·ata·sign(rel_b)` | 적 갈 곳 선점 → 거리 빨리 좁힘, gun 준비 (과하면 overshoot) |
| PURE_PURSUIT | 적 현위치 | `heading + rel_b` | 적을 직접 추격 (기본) |
| LAG_PURSUIT | 적 뒤 | `heading + 0.5·rel_b` | 선회 안쪽 유지 → overshoot 방지·에너지 보존 |

핵심 직관 — "얼마나 도느냐"가 lead/pure/lag를 가른다

먼저 용어: `ata` = 우리 코에서 적까지의 각도 = 조준 오차 (= `|rel_b|`, §3.0).
`sign(rel_b)` = 적이 좌/우 어느 쪽인지(부호). `k` = 계수.

PURE는 적 방위(rel_b)만큼 딱 맞게 돕니다. 여기서 덜 돌면 lag, 더 돌면 lead:
```
  적이 우리 오른쪽 60°에 있다 (rel_b = +60°)

   적 ●                         "코를 어디로 돌리나?"
      ＼ 60°
        ＼ ┄┄ LEAD: 60°보다 더(예 +75°) → 적 '앞'을 겨냥 (갈 곳 선점)
           ＼
            ● PURE: 딱 60° → 적 '현위치' 정조준
           ╱
          ╱ ┄┄ LAG: 절반인 30°(=0.5×60)만 → 적에 30° '못 미침' = 적 '뒤'·선회 안쪽
         ╱
        △  우리 (기수 0° = ↑)
```
- LAG = under-turn(덜 돔): `0.5·rel_b` → 적 방위의 절반만 도니 코가 적에 못 미쳐
  적 꼬리쪽/선회 안쪽을 향함. 안쪽이라 반경 작고 에너지 덜 쓰고 overshoot 안 남.
- LEAD = over-turn(더 돔): `rel_b + (양수)` → 적 방위보다 더 도니 적이 갈 자리를 겨냥.
- (LEAD 식의 `k·ata·sign(rel_b)`: ata=|rel_b|라 결국 rel_b 방향으로 *추가* 회전 = over-turn.)

GUN_TRACK = PURE + 적 선회 예측 보정 (정밀 사격):
```
  적이 선회 중 ↻ 이면, 총알 도착 시점엔 적이 더 가 있음
  → ω_opp·τ·k 만큼 더 당겨 겨냥 (적이 갈 자리에 미리)
      ω_opp = 적 선회율,  τ = 총알 비행시간,  k = 계수
  ψ* = heading + ata·sign(rel_b) + ω_opp·τ·k
            └ PURE 조준 ┘    └ 선회 리드 ┘
```

ONE/TWO_CIRCLE = merge 후 rel_b 기반 선회 (적이 뒤로 돌면 자동 반전) → 선회전.

(b) 속도 v\* — 3-phase chase PID (BFM 교리 구현)

추격 속도는 단일값이 아니라 3국면으로 제어 (§4.3 E-M 측정 반영):
```
① 진행방향 크게 다름 (|rel_b| > 35°):
     v* = 220 kts (저속)           → 반경 R∝V² 이므로 저속=좁은 반경 → 즉시 tight 선회
② 정렬됨 (거리 멀음):
     목표접근속도 = clamp(Kp·(dist − WEZ중심), min, max)   # 멀수록 빨리 접근
     v* = ego_vc + Kv·(목표접근속도 − 현재접근속도)         # 접근속도 추종 → burst
③ WEZ 근접 (dist → 목표):
     목표접근속도 → 0  →  v* 감속  →  overshoot 없이 안착
```
→ "방향 다르면 저속 좁은선회 → 정렬되면 가속 추격 → 가까워지면 감속" = 조종사 교리 그대로.

(c) 고도 h\* — tactic별 (pursuit는 적 고도 추종, HIGH_YOYO는 +상승, CLIMB는 안전고도).
최종 setpoint는 물리한계로 clamp: `v*∈[V_MIN,V_MAX]`, `h*∈[H_MIN,H_MAX]`.

### 1.5 제어(LQR Autopilot) 상세 — setpoint을 조종면으로

역할: 목표값(ψ\*,h\*,v\*)과 현재 상태 x의 오차를 줄이는 조종면 입력 u 계산.
구조 = 외측 루프(물리 명령 생성) + 내측 LQR(최적 안정화) 의 cascade.

(a) 상태 벡터 x — "비행기가 지금 어떤 자세/운동 상태인가" (10개)

비행기 상태는 세 묶음으로 나뉩니다 (제어 설계의 표준 분해):

| 묶음 | 기호 | 이름 | 의미 (직관) | 단위 |
|---|---|---|---|---|
| 종(수직면)<br>오르내림·가속 | `V` | 속도 | 진대기속도 (얼마나 빠른가) | fps |
| | `α` (alpha) | 받음각 | 날개와 들어오는 기류 사이 각 → 양력 결정 | rad |
| | `θ` (theta) | 피치각 | 기수가 수평선 위(+)/아래(−) | rad |
| | `q` | 피치 각속도 | θ가 변하는 속도 (기수 들리는 빠르기) | rad/s |
| 횡(수평면)<br>좌우·선회 | `β` (beta) | 옆미끄럼각 | 기수와 기류의 좌우 어긋남 (옆으로 미끄러짐) | rad |
| | `φ` (phi) | 롤/뱅크각 | 좌우로 기운 정도 → 선회의 핵심 | rad |
| | `p` | 롤 각속도 | φ가 변하는 속도 (구르는 빠르기) | rad/s |
| | `r` | 요 각속도 | 기수가 좌우로 도는 빠르기 | rad/s |
| 항법 | `h` | 고도 | 해면 위 높이 | ft |
| | `ψ` (psi) | 방위각 | 어느 쪽을 향하나 (북=0, 시계방향) | rad |

→ 핵심 직관: 선회 = φ(뱅크)로 기울이면 → ψ(방위)가 변한다. 고도는 θ(피치),
속도는 throttle. 받음각 α는 양력(=급선회 시 G)을 좌우. 이 결합을 LQR이 한꺼번에 다룸.

(b) 입력 벡터 u — "조종면을 얼마나 움직이나" (4개)

| 기호 | 조종면 | 무엇을 바꾸나 | 범위 |
|---|---|---|---|
| `throttle` | 스로틀(추력) | 속도 V | [0, 1] |
| `elevator` | 승강타 | 피치 θ (기수 상/하) → 고도·G | [−1, 1] |
| `aileron` | 보조날개 | 롤 φ (뱅크) → 선회 | [−1, 1] |
| `rudder` | 방향타 | 요 (기수 좌우) → 협조선회 보조·β 제거 | [−1, 1] |

※ JSBSim F-16 관례 주의: aileron 양수 = 좌롤(−φ), 음수 = 우롤 (일반 항공 반대). 부호 측정 검증함.

(a') LQR이 어떤 제어인가 — 피드백 루프 관점

LQR = Linear Quadratic Regulator = "선형 시스템을 2차 비용으로 최적 제어하는
전상태 되먹임(state-feedback) 제어기". 한 마디로 모든 상태를 측정해 한꺼번에 되먹임.

전체 폐루프(closed-loop) 그림 — cascade:
```
  ψ*,h*,v*        ┌──────────────┐   x*(목표상태)        ┌─────────┐   u        ┌────────┐
 (전술의 목표) ──▶│ 외측 루프     │──────────────▶ (+)──▶│ LQR     │──────────▶│ F-16   │──┐
                  │ PI+협조선회   │                ▲ −e   │ u=u₀−Ke │           │ 물리    │  │ x
                  └──────────────┘                │       └─────────┘           └────────┘  │
                                                  │                                          │
                                                  └────────── 상태 피드백 x ─────────────────┘
```
- 오차 `e = x − x*` (지금 상태와 목표상태의 차이)를 만들고,
- LQR 게인 K 가 그 오차를 줄이는 조종면 `u = u₀ − K·e` 를 즉시 계산,
- 비행기(plant)가 움직여 새 상태 x → 다시 측정해 되먹임(feedback) → 반복.

PID와 뭐가 다른가?
| | PID | LQR |
|---|---|---|
| 되먹임 | 출력 1개씩(루프별) | 상태 전체(MIMO 동시) |
| 게인 | 손으로 튜닝 | 비용 최소화로 한 번에 계산(최적) |
| 결합 처리 | 약함(루프 간섭) | 강함(고도↔속도↔선회 동시 고려) |
| 보장 | 없음 | 안정성·강건성 마진 이론 보장 (gain margin ∞, phase 60°) |

→ 즉 LQR은 "여러 조종면을 *동시에* 최적으로 놀려 비행기를 목표상태로 끌고 가는,
수학적으로 보장된 되먹임 제어". 그래서 투명(게인 해석)·결정론·강건.

(b) 외측 루프 — 물리 명령 생성 (PI / 협조선회)

- 고도 PI → 피치 명령: `θ_cmd = −(K_Ph·h_err + K_Ih·∫h_err)`, 포화 `|θ_cmd|≤15°`
- 속도 PI → 스로틀 보정: `Δthr = −(K_Pv·V_err + K_Iv·∫V_err)`
- 방위 P + 협조선회(coordinated turn) → 뱅크 명령:
  ```
  협조선회 물리:  ψ̇ = g·tan(φ) / V        (뱅크 φ로 돌면 방위가 ψ̇로 변함)
  역산:          φ_cmd = atan( ψ̇_cmd · V / g )
  여기서        ψ̇_cmd = clamp( K_Pψ · ψ_err , ±ψ̇_max )    # 방위오차→목표 선회율
  포화:          |φ_cmd| ≤ 78°  (= 4.8G, BFM 하드선회)
  ```
  → "방위 오차가 크면 → 목표 선회율 → 그걸 내는 뱅크각"을 물리식으로 정확히 계산.
  (단순 P가 아니라 물리 기반 feedforward — 그래서 속도 변해도 정확히 돎.)

(c) 내측 루프 — LQR (조종면 최적 안정화)

외측이 만든 명령(θ_cmd, φ_cmd, V_cmd)을 목표상태 x\*로 삼고, 조종면을 LQR로:
```
u = u₀ − K · (x − x*)
```
- `u₀` = trim feedforward (정상비행 유지 입력), `K` = 최적 게인 행렬, `x*` = 목표상태.

LQR 게인 K는 어떻게 나오나 (수식):
```
선형 모델:   ẋ = A·x + B·u        (trim점서 유한차분으로 A,B 측정)
비용:        J = ∫ (xᵀQx + uᵀRu) dt     (Q=상태오차 벌점, R=입력 벌점)
                                          Bryson 법칙: Q_ii=1/x_max², R_jj=1/u_max²
최적해:      Riccati 방정식  AᵀP + PA − PBR⁻¹BᵀP + Q = 0   (scipy solve_continuous_are)
게인:        K = R⁻¹ Bᵀ P
```
→ "상태오차와 조종량을 동시에 최소화하는 수학적 최적 제어". Q를 키우면 빠른 추종,
R을 키우면 부드러운 조작. 게인 K를 읽으면 *어떤 오차에 어떤 조종면이 얼마나 반응하는지*
해석 가능(투명성). 예: `K[ail,φ] < 0` → 좌뱅크 오차 → 우에일러론 (부호 측정 검증).

(d) Gain Scheduling — 비행영역별 게인 보간
A,B는 속도·고도에 따라 변함 → trim점 격자 [5000·15000·25000ft] × [250·350·450kts] 에서
각각 K를 미리 풀어두고, 현재 상태에 맞춰 보간. (한 K로 전 영역 못 덮음.)

(e) Structured LQR — 종·횡 교차결합 제거
full-state K는 `K[ail,θ]`(피치오차→에일러론) 같은 교차항이 커서 진동 유발 →
Riccati 후 종↔횡 교차 게인을 0으로 강제 (K[ail, 종상태]=0, K[elev, 횡상태]=0).

> 유도·제어 한 줄: *유도는 "전술→목표값"(연속, BFM 공식), 제어는 "목표값→조종면"
> (외측 물리명령 + 내측 LQR 최적). 전부 수식으로 정의돼 결정론·해석가능.*

---

## 2. 관측 (obs) — 적 무관 relational feature

`compute_obs(ego, enm)` → `Observation`. 의사결정·라벨링이 쓰는 상태 기술자:

| feature | 의미 | 부호/단위 |
|---|---|---|
| `ata_deg` | 우리 nose → 적 (조준 오차) | [0,180]° |
| `aa_deg` | aspect — 우리가 적 꼬리쪽에 얼마나 | [0,180]° (0=적6시) |
| `hca` | 두 속도벡터 교차각 = \|ψ_us−ψ_opp\| | [0,180]° |
| `distance_ft` | 거리 | ft |
| `closure_kts` | 접근속도 | +접근/−이격 |
| `es_diff` | 에너지차 Es_us−Es_opp (Es=h+V²/2g) | ft |
| `ego_omega`,`opp_omega` | 선회율 (body yaw rate) | °/s |

모두 relational/물리 (적 정체성 무관) → 정책이 특정 적에 overfit 안 됨.

---

## 3. 상황 매핑 — 물리 기반 상호배타 분류

### 3.0 먼저, 각도 세 개를 구분하자 (ATA / AA / HCA)

dogfight 기하를 말하려면 "각도"가 세 종류 나옵니다. 헷갈리기 쉬우니 먼저 정리:

```
        ATA (내 조준 오차)              AA (내가 적 어디에 있나)         HCA (기수 방향 차이)
     "내 코가 적을 향하나?"          "내가 적 꼬리쪽이냐 정면이냐?"      "두 비행기가 얼마나 엇갈려 나나?"

        나 →→→●                         적 ↗                          나 ↑      적 ↑   (HCA=0, 나란히)
            ＼ ata                      ／ aa=0 (내가 적 6시)
             적                       나                               나 ↑      적 ↓   (HCA=180, 정반대)
```

| 각도 | 정의 | 0°일 때 | 180°일 때 |
|---|---|---|---|
| ATA | 내 기수 → 적 (조준 오차) | 적을 정조준 (쏠 수 있음) | 적이 내 정반대 (등 뒤) |
| AA (aspect) | 적의 꼬리 기준 내 위치 | 내가 적 6시(뒤) = 유리 | 내가 적 12시(정면) = 위험 |
| HCA | 두 기수(속도벡터) 방향 차이 | 둘 다 같은 방향 = 나란히 | 정반대 방향 = 마주봄 |


ATA (Antenna Train Angle): 안테나 지향각
AA (Aspect Angle): 아스펙트 앵글 (상대 방위각)
HCA (Heading Crossing Angle): 헤딩 교차각 (기수 교차각)

HCA가 핵심 판별자인 이유: HCA는 "교전의 *형태*"를 결정합니다.
- HCA 작음(정렬) → 한 대가 다른 대 뒤를 따라가는 추격. 누가 빠르냐(속도)가 승부.
- HCA 큼(교차) → 서로 돌면서 각도를 따는 선회전. 누가 잘 도냐(선회율)가 승부.

즉 ATA·AA는 "누가 유리한가"를, HCA는 "어떤 종류의 싸움인가" 를 말해줍니다.

### 3.1 왜 물리로 나누나 (측정 근거)

손으로 "이 상황엔 이 전술"을 정하기 전에, 상황을 어떻게 나눌지부터 물리로 정당화합니다.

E-M(에너지-기동성) 곡선 측정 — 최대 뱅크로 정상 선회시 속도별 선회율 ω, 반경 R:

| 속도 | 선회율 ω | 반경 R |
|---|---|---|
| 226 kts | 9.1°/s | 0.49 nm |
| 327 kts | 12.7°/s | 0.50 nm |
| 363 kts (corner) | 13.7°/s (최대) | 0.52 nm |
| 401 kts | 13.6°/s ↓ | 0.57 nm |

→ 선회율은 corner speed(~360kts)에서 최대, 그 이상 빨라지면 오히려 감소.
- 추격(정렬): 거리를 좁히려면 빠를수록 좋음 → 최대 속도 선호 (단조).
- 선회전(교차): 각도를 따려면 잘 돌아야 함 → corner speed 선호 (비단조).
- 두 상황의 최적 속도가 정반대 → 한 잣대(cost)로 둘 다 담으면 자기모순 →
  반드시 분리해야 함이 물리로 증명됨.

### 3.2 상황 dispatch (런타임) — 기하 기반 우선순위 캐스케이드

배포된 런타임의 실제 결정은 "기하로 상황을 판별 → 그 상황 전용 tactic을 dispatch" 하는
우선순위 캐스케이드입니다 (BT Selector 구조 — 위에서부터, 처음 맞는 하나 = 상호배타).
이것이 우리 BT의 실제 동작이며, 상세 표·파훼 원리는 §5.6에 있습니다
([tree_policy.py](../../new_match_engine/bt/tree_policy.py) `select`):

```python
def select(obs):                       # 요약 (전체·근거는 §5.6)
    if alt < 2500:        return CLIMB            # ① 안전 (Hard Deck) — 최우선
    if head_on(첫5s):     return ADAPTIVE         # ② 정면 merge → τ-블렌딩 yoyo perch
    if evasive_extend:    return VERTICAL_PURSUIT # ③ 도주 zoom → 적 고도 추종
    if close_unaligned:   return GUN_TRACK        # ④ 근접 미완 → 예측 lead 락
    return RF.predict(features)                   # ⑤ 그 외 → 학습 정책(offline solver)
```

왜 단순 3-class(CHASE/CIRCLE/DEFENSIVE)가 아니라 dispatch인가? — 측정 결과(§5.7) 단일
분류 하나로는 일부 상황(정면 merge·도주 extend·근접 미완)이 안 풀렸고, 단일 글로벌 수정은 늘
다른 상황을 회귀시켰습니다. 그래서 *지배 물리가 다른 상황을 기하로 분리해 독립 대책*을 붙였습니다
(= §3.1 물리 분리 원칙의 실현, 사용자 비전 "상황별 복합·독립 접근").

- 물리 기반 3-class 분류기 [situation.py](../../new_match_engine/bt/situation.py)(CHASE/CIRCLE/
  DEFENSIVE, HCA 기준)는 여전히 baseline·real_rollout 입력으로 쓰이나, 배포 결정은 위 기하
  dispatch + RF입니다.
- 상황 후보는 데이터(§3.3 클러스터링)가 가리킨 것 — HEAD_ON·CHASE(도주 포함)·근접 킬존 —
  중 *측정으로 파훼책이 확인된 것*을 dispatch에 올립니다. 즉 "이론상 N개 분류"가 아니라
  "실측으로 대책이 검증된 상황"만 독립 처리.

### 3.2b 분류된 상황 — 각각 무엇인가 (직관)

각도 3개(§3.0)로 상황을 읽습니다: ATA=내 코가 적에서 얼마나 벗어났나(0=정조준),
AA=내가 적의 어디에 있나(0=적 꼬리/6시, 180=적 정면), HCA=두 기수의 교차각(0=같은 방향,
180=정반대). 아래가 우리가 실제로 다루는 상황들의 "그림":

| 상황 | 한 컷 그림 | 기하 (대략) | 위험/기회 | 우리 대책 |
|---|---|---|---|---|
| Hard Deck | 내가 지면에 너무 가까움 | alt<2500ft | 충돌·자멸 | 무조건 상승(CLIMB) |
| Head-on merge (정면) | 서로 코 맞대고 빠르게 스쳐 지나감 | HCA~180·ata↓·aa↑·closure 큼 | 스치며 상호 한발 → 평면 scissors로 둘 다 deck 추락 | 수직 perch(ADAPTIVE) — 나만 떠 있고 적은 추락 |
| Chase (추격) | 적이 내 앞, 내 코가 적 꼬리를 향함 | ata↓·aa↓(적 후방반구) | 뒤만 잡으면 킬존 | 속도로 따라잡기(pursuit/RF) |
| Evasive extend (도주) | 적이 멀어지며 특히 위로 빼며(zoom) 도망 | dist 큼·안 닫힘·적 고도↑ | 수직으로 놓치면 영영 못 잡음 | 적 고도 추종(VERTICAL_PURSUIT) |
| Close finish (근접 마무리) | 사거리 안인데 코가 살짝 빗나감 | dist<3000ft·ata 어중간 | 한 발 직전, overshoot로 놓침 | 적 선회예측 lead로 각 락(GUN_TRACK) |
| Circle fight (선회전) | 서로 빙글빙글 돌며 각 다툼 | HCA 중간·교차 | 잘 도는 쪽이 먼저 뒤잡음 | one/two-circle (선회율 지배) |
| Defensive (피추격) | 적이 내 6시, 내가 쫓김 | aa↑(적이 내 후방) | 피격 위험 | break/회피 (생존 우선) |

> 직관 한 줄: dogfight는 *"정면으로 만나(merge) → 누군가 뒤를 잡고(chase/circle) → 사거리에서
> 마무리(finish), 잡히면 피한다(defensive)"* 의 반복입니다. 각 국면이 요구하는 물리가 달라
> (정면=수직 에너지, 추격=속도, 선회=선회율, 마무리=조준 정밀) 한 잣대로 못 풉니다 → 상황별 분리.

### 3.3 데이터 검증 — 손정의가 맞나? (클러스터링)

손으로 정한 분류가 실제 데이터의 자연스러운 군집과 맞는지 검증합니다 (측정 먼저).
도구: `cluster_situations.py` — sklearn KMeans(군집화) + silhouette(군집 품질) + PCA(시각화).

(1) 몇 개가 자연스러운가? — silhouette
silhouette 점수 = "각 점이 자기 군집엔 가깝고 남의 군집엔 먼 정도" [−1~+1, 높을수록 잘 분리].
k(군집 수)를 2~8로 바꿔가며 측정 → k=8까지 점수가 계속 증가(0.31). → 3개론 부족, 더 많은 상황이 자연스러움.

(2) 그 군집들이 무엇인가? — centroid 해석 (실측, 8군집 중 대표):

| 군집 | 평균 특징 | = BFM 상황 |
|---|---|---|
| 1 | ata13·aa13·HCA9, 우리wez 0.74 | CHASE (적 뒤 정조준 — 킬존) |
| 3 | ata168·aa165, 적wez 0.72 | CHASED (적이 우리 6시 — 피추격) |
| 2 | HCA152·closure493, 양쪽 wez | HEAD_ON (정면 상호조준) |
| 5 | HCA105, es+1896(에너지↑) | CIRCLE-에너지우위 |
| 6 | HCA124, 중간 aspect | CIRCLE-중립 |
| 4 | HCA135, es−496(에너지↓) | CIRCLE-에너지열세 |

→ 손정의(CHASE/CIRCLE/DEFENSIVE) 중 CIRCLE이 너무 거칢이 드러남: 데이터는
HEAD_ON·CHASED·CIRCLE(에너지 3변형)을 따로 봄 → ~6 상황.

(3) "6개"가 확실한가? — 정직한 한계
확실하지 않습니다. ~6은 근사입니다. 이유: silhouette가 0.31로 중간값(1에 한참 못 미침).
즉 군집들이 딱 떨어지지 않고 서로 겹칩니다. 뚜렷이 분리된 건 CHASE(군집1)뿐.

(4) "연속 manifold"의 의미
PCA로 펼쳐보면 점들이 별개 덩어리가 아니라, 이어진 연속 곡면(manifold)을 이룹니다.
- 비유: dogfight 상태는 "추격↔선회↔정면↔방어"가 무지개처럼 연속으로 번지는 풍경.
  명확한 국경이 있는 나라들이 아니라, 색이 서서히 변하는 그라데이션.
- 그래서 "상황 6개"는 자연의 발견이 아니라, 연속체를 유용하게 자른 이산화입니다.
  CHASE만 풍경에서 튀어나온 섬처럼 뚜렷 분리(우리 킬존이라 물리적으로 특이).

→ 결론: 손정의 taxonomy는 연속 상태공간의 *유용한 근사*. 데이터로 "3은 부족, ~6이 더
적절"을 확인했고, 경계는 부드러움(soft). 이 점이 §5에서 상황 라벨에만 의존하지 않고
정책을 데이터로 직접 학습하는 또 하나의 이유 (이산 경계의 모호함을 학습이 흡수).

---

## 4. 적 BT 동작 — generic .yaml 인터프리터

### 4.0 Behavior Tree(행동트리)란? — 자연어로

적(상대 조종사)은 행동트리(BT) 로 행동합니다. BT는 "if-then 규칙을 우선순위로
배열한 의사결정 트리"이며, 매 BT틱(10Hz)마다 위에서부터 평가해 할 행동을 정합니다.
구성 노드는 4종류뿐:

| 노드 | 자연어 의미 | 비유 |
|---|---|---|
| Selector (선택자) | 자식을 위→아래로 시도, 처음 성공하는 것 채택 | 우선순위 OR — "A 안되면 B, B 안되면 C" |
| Sequence (시퀀스) | 자식 조건이 모두 참이어야 그 안의 행동 실행 | AND 게이트 — "조건 다 맞으면 → 이 기동" |
| Condition (조건) | obs를 보고 참/거짓 판정 | if 검사 — "고도 < 1000ft?" |
| Action (행동) | 실제 기동 명령 | 명령 — "상승하라" |

핵심 읽는 법: 루트는 보통 Selector. 위쪽 가지일수록 높은 우선순위(긴급).
"제일 위에 HardDeck 회피, 그 아래 상황별 기동, 맨 아래 기본 추격" 식.

### 4.1 실제 예시 — `simple.yaml` (가장 단순한 적)
```yaml
tree:
  type: Selector              # ← 위에서부터 시도, 첫 성공 채택
  children:
  - type: Sequence            # [우선순위 1] 땅에 박힐 위기?
    children:
    - {type: Condition, name: BelowHardDeck}   #   고도 < 1000ft 이면
    - {type: Action,    name: ClimbTo}         #   → 상승 (다른 거 다 무시)
  - type: Action, name: Pursue                 # [우선순위 2] 평소엔 → 추격
```
→ 자연어: "땅에 박힐 것 같으면 무조건 상승, 아니면 무조건 적 추격." 끝.

### 4.1b 실제 예시 — `ace.yaml` (챔피언, 상황 인식)
ace는 같은 구조지만 상황 분기가 풍부합니다 (요약):
```
Selector:
  1. BelowHardDeck?          → ClimbTo            (안전 최우선)
  2. WEZ 안(거리·ATA)?        → GunAttack          (격추 기회)
  3. IsDefensiveSituation?   → (AA>130 BreakTurn / 고도열세 HighYoYo / ...)
  4. IsOffensiveSituation?   → (근거리 LeadPursuit / 측면 OneCircle / ...)
  5. IsNeutralSituation?     → (ATA>60 HighYoYo / 근거리 OneCircle / ...)
  6. (기본)                  → Pursue
```
→ 자연어: "안전 → 쏠 수 있으면 쏘고 → 불리하면 방어 → 유리하면 공격 → 대등하면 선회 →
기본 추격." 우리 상황분류(§3)와 같은 발상이지만, 경계가 손으로 박힌 고정 임계값.

### 4.2 인터프리터 (yaml_bt.py) — legacy를 우리 엔진에서 그대로
`load_bt(yaml) → opp_fn(obs) → Tactic`. 위 트리를 walk하며 평가:
- Selector: 자식 순서대로 → 첫 성공(행동 반환) branch 채택.
- Sequence: 모든 Condition 통과해야 → 그 Action 반환, 하나라도 실패면 이 가지 포기.
- Condition → obs 평가 (~26종): `DistanceBelow→거리`, `ATABelow→ata`,
  `BelowHardDeck→고도<1000`, `Is{Off/Def/Neutral}Situation→분류`, `UnderThreat→aa` ...
- Action → 우리 Tactic (~40종): `Pursue→PURE_PURSUIT`, `GunAttack→GUN_TRACK`,
  `BreakTurn→BREAK_TURN`, `ClimbTo→CLIMB`, `OneCircleFight→ONE_CIRCLE` ...

969/969 legacy 적이 손 포팅 없이 실행(실측). 이게 ① .yaml 구조 유지(제출·토너먼트
호환), ② legacy 엔진 대체 경로, ③ 오프라인 solver의 대규모 적 다양성을 동시에 제공.

> 우리 정책 vs 적 BT의 차이: 적 BT는 *손으로 박은 고정 임계값*(거리<6562ft 등)으로
> 분기. 우리는 §3 물리 분류 + §5 데이터로 학습한 정책 — 임계값을 사람이 안 정함.

---

## 5. 정책/가중치 도출 — 오프라인 Solver (핵심, 처음부터)

> 배경지식 없이도 따라올 수 있게 개념부터 쌓습니다.

### 5.0 목적과 설계 (무엇을 · 왜 · 어떤 방법)

목적. "지금 이 상황에서 어떤 기동(tactic)이 최선인가"를 매 순간 즉시 답하는 정책을 만든다.

문제 두 가지.
- 정답을 미리 알 수 없다 — 어떤 기동이 이기는지는 *실제로 싸워봐야* 안다 (공식으로 단정 불가).
- 실전은 매 0.1초 결정이라 *그 자리에서 깊이 계산할 시간이 없다.*

설계 — "시간을 분리"한다.
1. *사전에*(offline) 시간을 충분히 들여 실제로 싸워보고 각 기동을 채점 → 정답 데이터를 만든다.
2. 그 데이터를 *가벼운 함수*로 학습 → 실전엔 그 함수만 즉답시킨다 (시뮬 없이 μs).

이 방법의 이름 — 오프라인 정책 증류(offline policy distillation).
*증류(distillation)*란, 느리지만 정확한 출처(여기선 시뮬 채점)의 답을 빠른 모델(여기선 학습 함수)이
압축해 배우는 기법을 말한다 (지식 증류에서 온 표준 용어).

왜 이 설계인가. 정확성(사전 계산)과 실시간성(가벼운 실행)은 보통 맞바꿔야 한다 — 그런데
시간을 분리하면 *둘 다* 얻는다.

> *(보조 비유)* 느리고 정확한 선생(시뮬 채점)이 낸 답을 빠른 학생(함수)이 공부해, 실전엔
> 학생만 뛴다.

### 5.1 왜 "오프라인"인가 — 미리 요리 vs 주문 즉석
- 온라인(주문 즉석): 매 0.1초마다 *그 자리에서* 적 미래를 예측해 계산. 시간이 없어서
  적을 "그냥 직진한다"고 단순화할 수밖에 없음 → 반응하는 적을 못 잡음(실측: 추격형 무승부).
- 오프라인(미리 요리): 시간 여유가 많은 사전에 다 풀어두고, 실전엔 결과만 꺼내씀.
  여유가 있으니 적을 진짜로 반응시키며 정확히 평가 가능.
- 한 줄: 정확성(오프라인 계산)과 실시간성(가벼운 배포)을 분리해 둘 다 얻는다.

### 5.2 왜 "한 번만" 시뮬하면 되나 — 결정론
보통 몬테카를로(MC)는 같은 상황을 수천 번 반복합니다. *왜?* 매번 결과가 달라서(랜덤)
평균을 내야 참값이 나오기 때문. 하지만 우리 시뮬은 랜덤이 전혀 없습니다(JSBSim·제어·
적 BT 모두 결정론). → 같은 입력은 항상 같은 결과 → 1번 = 정확한 참값.
- 반복하면 똑같은 숫자만 나옴(정보 0). → 노력을 반복이 아니라 "다른 상황 많이"(coverage)에 투자.
- 이것이 §4.7의 LHS(다양 spawn)가 "분해능"인 이유. 다양성 = 데이터 품질.

### 5.2b 롤아웃(rollout) — 채점이 실제로 어떻게 이뤄지나 (핵심 도구)

목적. "이 상황에서 이 기동이 *실제로 얼마나 이기는지*"를 숫자로 측정한다. 이 측정이 §5.3 ②의
"채점"이고, 학습의 정답(라벨)이 여기서 나온다 — 즉 이 방법론 전체의 심장이다.

무엇인가 (방법론). 롤아웃(rollout) 이란, 어떤 상태에서 출발해 정해진 행동/정책을 적용하며
시뮬레이션을 *앞으로 전개*해 결과를 관찰하는 평가 기법을 말한다. 강화학습과 게임트리 탐색
(체스·바둑 엔진이 "이 수를 끝까지 둬보는" 것)에서 표준으로 쓰인다.

왜 롤아웃인가. 어떤 기동이 좋은지는 공식으로 단정할 수 없다(비선형 + 적이 반응함). 그래서
*추정하지 않고 실제로 둬본다* — 진짜 비행 시뮬(JSBSim)로 전개해 진짜 결과(내가 사격했나 / 맞았나)를
직접 본다. 추측이 아니라 측정이다.

어떻게 (구현).
```
상태 S ──(얼림: capture_state, 0.1ms)
   ├─ 기동 T1 을 H초 전개  [우리=T1, 적=실제 BT 반응]  → 결과 채점
   ├─(되감기: restore_state) 기동 T2 전개 → 채점
   └─ … 후보 기동 전부 → 제일 잘 풀린 기동 = "상태 S 의 정답"
```
세 가지가 이를 가능케 한다:
1. 상태 얼리고 되감기 (capture/restore_state): 게임을 그 순간으로 0.1ms에 되돌린다 →
   같은 출발점에서 여러 기동을 *공정하게* 비교 (스냅샷-복원, JSBSim 초기조건 기반).
2. 결정론(§5.2): 한 번 전개하면 그게 참값 → 반복 평균 불필요.
3. 적이 진짜 반응: 적을 "직진한다"고 가정하지 않고 *실제 BT*를 돌린다 → 진짜 교전 결과.

한 가지 보정 — "잠깐 두고 나머지는 평소대로". 기동 T를 끝까지(H초) 강제하면 *준비성 기동*
(선회·요요)이 손해처럼 보인다 — 그 보상(사격)이 H초 안에 안 끝나 데미지 0으로 채점되기 때문.
그래서 T를 잠깐만(약 4초) 두고 이후는 기준(base) 정책으로 이어 전개한다. 그러면 준비 기동이
만든 이득을 이후 정책이 거둬 *제값*을 받는다.
- *용어 정의*: 이렇게 "몇 스텝만 특정 행동, 이후는 기준 정책으로 이어 평가"하는 방식을 강화학습에서
  n-step 부트스트랩(bootstrap) 이라 한다 — '부트스트랩'은 *이후의 가치를 기준 정책의 추정값으로
  대체해 끌어다 쓴다*는 뜻. 이렇게 만든 채점을 fitted-Q(가치함수를 데이터로 맞춤) 라 부른다.

> 한 줄: 롤아웃 = 얼린 상태에서 한 기동을 실제로 둬보고 채점한다. 이것이 정답(라벨)의 출처.

### 5.3 4단계 파이프라인 — 무엇이 어떻게

각 단계의 *개념*을 먼저, 그다음 *구현*을:

```
① 상황 만들기 (build_situation_dataset / scaled_solver)
   [개념] 학습할 "다양한 1:1 교전 상황"을 만든다.
   [구현] Latin Hypercube로 거리·각도·HCA·에너지를 고르게 뿌린 spawn(수십~수백)
          × 970 적에서 뽑은 다양한 적 → 5분 매치를 돌리며 매 순간 "상태"를 기록.

② 채점하기 (라벨링) — offline_solver._Sim   선생이 하는 일 (fitted-Q)
   [개념] 각 상태에서 "이 기동을 잠깐 하고 그다음 평소대로 싸우면, 진짜로 얼마나 이기나".
   [구현] 상태 S에서, 각 기동 T마다:
          · capture/restore_state 로 그 상태를 정확히 재현 (0.1ms)
          · 우리 = T를 짧게(commit_s≈4초)만 강제 → 이후엔 base 정책으로 이어감
            적 = 실제 BT가 반응→ 총 H초 시뮬
          · 점수 = Σ(우리가 가한 데미지 − 받은 데미지)
            (데미지 = 진짜 게임 규칙: ATA<12° ∧ 500~3000ft → 25 HP/s)
   [결과] (상태) → [8개 기동의 진짜 데미지 점수]   ← 이게 "정답(라벨)"

③ 학습하기 (value 회귀) — RandomForest    학생이 공부하는 일
   [개념] 채점 결과들을 보고, 시뮬 없이 점수를 예측하는 함수를 만든다.
   [구현] sklearn RandomForestRegressor: 상태 feature → [8 기동의 예측 점수]
   [용어] 이 "상태→행동별 점수" 함수가 강화학습의 가치함수 Q(state, action).
          ※ 점수 1등 이름만 외우지(분류) 않고 8점수 전부 학습(회귀) — 동률·근소차 보존.

④ 쓰기 (배포) — tree_policy
   [개념] 실전에서 매 순간 상태를 보고 즉답.
   [구현] feature → RandomForest로 8점수 예측 → 제일 높은 기동(argmax) 실행. μs, 시뮬無.
          단 Safety(고도<2500ft)는 항상 우선 → CLIMB (땅 박기 방지).
```

### 5.3b 라벨의 함정과 해결 — Sparse Reward → Potential Shaping (실측 디버깅 여정)

라벨링(②)을 처음엔 단순하게 했습니다: "한 기동을 60초 강제하고 데미지를 잰다."
이게 함정이었고, *세 번의 실측 반복*으로 진짜 원인을 찾아냈습니다. (발표에서 가장
중요한 "어떻게 디버깅했나" 파트.)

(1) 증상 — 모든 상황의 답이 PURE_PURSUIT로 쏠림
| 라벨링 방법 | argmax PURE_PURSUIT | CV R² |
|---|---|---|
| 단일 tactic, 4 spawn (4182) | 75% | 0.47 |
| 단일 tactic, LHS 64 spawn (64173) | 83% (오히려↑) | 0.455 |
| fitted-Q (commit+base, 31693) | 95% (더 악화) | 0.188 |
→ 데이터 16배·fitted-Q 둘 다 안 통함. "양"이나 "한 가지 수정"의 문제가 아니었음.

(2) 가설1 — Myopia & fitted-Q 시도 (→ 역효과)
처음 가설: "60초 단일 commit이라 setup 전술(TWO_CIRCLE 등)이 빛볼 시간 전에 끊김(근시안)."
→ 해결 시도: fitted-Q — T를 4초만 commit하고 이후 base 정책으로 이어감.
→ 역효과: base가 pursuit-편중 정책이라, 어떤 T를 commit해도 이후 pursuit로 수렴 →
  pursuit 95%로 *더* 쏠리고 CV R²도 0.188로 떨어짐. base의 편향이 증폭됨.

(3) 진짜 원인 — 데이터로 진단 (재실행 없이!)
기존 데이터를 상황별로 쪼개 argmax·평균점수를 봄:
```
상황 분포:  CIRCLE 68% / CHASE 31% / DEFENSIVE 0.6%(!)   ← ① 상태 불균형
CIRCLE 상황: 모든 tactic 평균점수 ≈ 0.0                   ← ② sparse reward
```
- ① 상태 불균형: 매치가 pursuit로 돌아 방어 상황을 거의 안 거침(0.6%) → 못 배움.
- ② Sparse reward (핵심): 선회전(CIRCLE)은 60초 window 안에 사격으로 안 끝나
  데미지 0 → 모든 tactic 점수가 ~0 → argmax가 노이즈 → pursuit로 default + R² 낮음.
- 단, *집계 평균*은 정답을 앎(CHASE→TWO_CIRCLE, DEF→LEAD가 pursuit보다 높음).
  신호는 있는데 per-state 0-노이즈에 묻힌 것. → myopia가 아니라 sparse reward 가 주범.

(4) 해결 — Potential-based Reward Shaping (Ng et al. 1999)
진짜 데미지는 그대로 두고, WEZ-margin(사격위치 근접도) 개선분을 shaping으로 더함:
```
점수 = (진짜 데미지 차) + K·(Φ_끝 − Φ_시작),   Φ = wez_margin(우리) − wez_margin(적)
        └ 참 목적(불변) ┘   └ 위치개선의 dense gradient ┘
```
- 이론 보장: potential 차(Φ_끝−Φ_시작)는 최적 정책을 바꾸지 않음(Ng의 정리) —
  궤적 따라 telescoping돼 상쇄. 즉 편향 없이 dense 신호만 추가.
- 이전에 거부한 "_wez_margin을 진짜 데미지 *대신* 쓰기"와 다름: 여기선 데미지가
  *여전히 목적*이고 margin은 *potential 차로만* 더해짐.
- 부수효과: setup 전술(각도 개선→Φ↑)이 즉시 credit → sparse·myopia 동시 해결.

(5) 결과 (실측)
| | argmax 분포 | CV R² |
|---|---|---|
| shaping 전(fitted-Q) | PURE 95% | 0.188 |
| shaping 후 | PURE20%·TWO_CIRCLE19%·LEAD18%·LAG16%·ONE14%·GUN10%... | 0.39 |
→ pursuit 독점 붕괴, 균형 분포 + R² 2배. 정책이 상황별 다른 전술을 내기 시작.
(추가: 학습 시 상황 역빈도 sample_weight로 희소한 DEFENSIVE 보강.)

> 핵심 교훈 (발표 포인트): 강력한 도구(fitted-Q)를 *먼저 의심*하기보다 데이터를 쪼개
> 진단했더니 진짜 원인은 sparse reward였다. 해결은 화려한 게 아니라 이론이 보장하는
> potential shaping — 진짜 목적을 안 건드리고 dense 신호만 더하는 정석. "측정 먼저"가 또 통함.

### 5.4 "가중치"는 어떻게 정해지나? — 사람이 안 정한다

발표에서 가장 많이 받는 질문입니다. 답: 사람이 손으로 안 정합니다.
- 옛날 방식: "거리 가중 0.3, 각도 가중 0.5..." 를 사람이 튜닝 → 그 적에만 맞춰짐(overfit, 위험).
- 우리 방식: "진짜 게임에서 이긴 정도(데미지)"를 정답으로 두면, RandomForest가
  데이터에서 "어떤 상태 feature가 점수에 얼마나 중요한지"를 스스로 학습.
- "무엇이 중요한가"는 feature 중요도로 *창발*합니다 (사람이 박은 게 아니라 데이터가 말함):
  실측(라벨 4182) → aa(0.38) + dist(0.29) 지배 = *"적 뒤(aa↓)에 사거리(dist) 안에 있어라"*
  = 격추 기하 그 자체. 물리적으로 타당한 게 데이터에서 저절로 나옴.
- 상황별 차이는 *cost 공식*이 아니라 *상태별 점수*에 있음 → 같은 목적, 상태 다르면 답 다름.

### 5.5 왜 이렇게까지 하나 — 원칙과 이유 (한 표)
| 원칙 | 이유 (배경 없는 청중용) |
|---|---|
| 진짜 wez_damage로 채점 | 대충 근사하면 *진짜 승패와 어긋난 데이터* → 학생이 틀린 걸 배움 |
| potential shaping 추가 | 선회전은 60초 안에 사격이 안 끝나 데미지 0(sparse) → 위치개선분(Φ차)을 편향 없이 더해 dense 신호 |
| 적을 실제 BT로 반응시킴 | 적이 "가만히 있다"고 가정하면 *실제와 다른 정답* → 반응형 적 못 잡음 |
| LHS로 상황 고르게 | 4가지 상황만 보면 *세상의 일부만* 배움 → 다양해야 일반화 |
| 결정론이라 1회=참값 | 랜덤이 없으니 반복은 낭비 → *다양성*에 노력 투자 |
| 멀티프로세싱 병렬 | 매치들이 서로 독립 → 전 코어로 동시에 → 몇 시간이 몇 분으로 |

> 5장 한 줄: *"실제 교전을 시뮬해 진짜로 이기는 기동을 채점하고(선생), 그걸 가벼운
> 함수로 익혀(학생) 실전에 즉답한다. 사람이 가중치를 만지지 않고 데이터가 정한다."*

---

## 5.6 런타임 정책 — 상황 독립 dispatch (우리 BT 가 실제로 어떻게 결정하나)

오프라인 solver의 RF 정책은 "일반 상황"을 잘 풉니다. 하지만 실제 1v1 dogfight는 상황마다
지배 물리·요구 기동이 질적으로 달라, 단일 정책 하나로는 일부 상황(정면 merge, 도주 extend)이
안 풀립니다. 그래서 런타임은 상황을 먼저 판별해 그 상황 전용 기동을 dispatch하고 나머지를
RF에 맡깁니다 (= 사용자 비전 *"상황별 복합·독립 접근"*). 매 tick 위→아래로 검사, 걸리면 그 tactic
([tree_policy.py](../../new_match_engine/bt/tree_policy.py) `select`):

| 순위 | 상황 (조건) | tactic | 파훼 원리 |
|---|---|---|---|
| 1 | Hard Deck (alt<2500ft) | CLIMB | 안전 최우선 — 지연 시 자멸 |
| 2 | head-on merge (ata<40·aa>130·dist<9000, 첫5s) | ADAPTIVE | 정면 scissors는 양쪽 에너지 덤프·대칭화 → τ-블렌딩 yoyo perch로 우리만 떠 있고 적이 deck 추락 |
| 3 | evasive extend (dist>4500·ata<50·closure<30) | VERTICAL_PURSUIT | 적 zoom-climb 도주 → 적 고도 추종(h=enm)으로 따라붙음 (수평유지면 altgap −6600ft로 놓침) |
| 4 | close finish (dist<2800·ata<45) | GUN_TRACK | 사거리엔 들어가나 overshoot로 각 못 맞춤 → 적 선회예측 lead로 ata<12 락 |
| 5 | 그 외 | RF 정책 | offline solver 학습 (일반 추격·선회) |

핵심 설계: dispatch는 *상황을 기하로 분리*해 다른 상황을 안 건드림(독립). 예) head-on은
첫 5s 기하로 latch → beam 매치엔 안 걸려 일반 추격 무회귀. 새 tactic 2종:

- ADAPTIVE — τ-블렌딩 (legacy adaptive_eagle_v11 이식): 실제 dogfight는 "1-circle 진입하다
  적 기동 보고 추적으로 이탈" 같은 연속 전환. enum 하드 스위치는 못 담아(나쁜 tactic에 lock).
  `ψ = w_lag·ψ_lag + w_pur·ψ_pur` (미정렬 ata↑→lag로 각 따기, 정렬 ata↓→pursuit로 닫기) +
  교전락 시 수직 yoyo. sigmoid 게이트로 BFM 조건을 soft 인코딩. 적 선회율(`enm_r_dps`) 직접
  관측 → v11의 차분 추정 불필요. ([guidance.py](../../new_match_engine/control/guidance.py) `_adaptive`)
- VERTICAL_PURSUIT — 고도 추종: pure pursuit가 수평(h=ego)이면 적 zoom-extend를 수직으로
  놓침(실측 altgap −6618ft·WEZ 0). 적 고도(h=enm) 추종 시 따라붙어 WEZ 44~48%·격추(실측). 단
  글로벌 적용은 defensive 4/4→0/4 회귀 → evasive 전용 dispatch로 분리 (상황 독립 원칙).

## 5.7 분석 루프 — 측정으로 파훼책을 도출 (감 금지)

대책은 추측이 아니라 매 경기 정량 분석에서 나옵니다. 루프:

```
교전(canonical beam) → 분석(report.txt 7층) → 가설 → 실험 → 같은 report로 검증 → 반복
```

- 매 경기 자동 산출: [plot_match_3d_nme.py](../../tools/plot_match_3d_nme.py) 가 acmi+csv →
  `report.txt`(7층 정량: ①결과 ②교전성 ③BFM위치 ④에너지 ⑤기동패턴 ⑥제어 ⑦판정) +
  `plot.png`(3D궤적·WEZ dwell·에너지·circle fit). 승/패/무 모든 경기가 데이터 자산.
- 집계: [aggregate_reports.py](../../tools/aggregate_reports.py) 가 N경기를 한 표로 → 공통
  실패 레버(코너준수·미교전 횟수·hdgRMS 등) 도출.

> 발표 포인트 — 기각된 가설들: 측정이 *내 추측을 거듭 기각*했습니다.
> ① "턴레이트 한계?" → 제어가 이미 물리한계(78° bank=4.8G)를 다 씀 = 제어 아닌 *기하* 문제.
> ② "코너속도 유지?" → simple 승→무 회귀.
> ③ "circle가 에너지 주범?" → 오히려 pure가 최다 bleed(평면 하드선회=고도+속도 동시 손실).
> 교훈: 단일 글로벌 파라미터 수정은 늘 다른 상황을 회귀시킨다 → 상황 독립 dispatch만 유효.

## 5.8 상황별 파훼 대책 (한 표)

| 상황 | 증상 (측정) | 파훼 대책 | 결과 |
|---|---|---|---|
| head-on merge | 양쪽 deck 에너지 덤프·우리 피격·WEZ 0 | ADAPTIVE (τ-블렌딩 yoyo perch) | 적 deck 강제승 |
| evasive extend (zoom) | altgap −6600ft 수직 놓침·WEZ 0 | VERTICAL_PURSUIT (고도 추종) | 따라붙음·에너지 우위 |
| close 미완 (overshoot) | 사거리 OK·각 NG·WEZ 0 | GUN_TRACK (예측 lead 락) | defensive 격파(dmg 69) |
| 일반 추격·선회 | — | RF 정책 (offline) | simple/agg 승 |

→ CANONICAL 평가 = 4/4: `python new_match_engine/bt/run_match.py` (spawn_adt_neutral beam vs
4 .yaml 적). 표준 진입점이 ① canonical beam(메모리 조건) ② RF+dispatch 정책 ③ .yaml 적(yaml_bt)을
묶어 매 경기 acmi+csv+report+plot 저장.

---

## 6. 핵심 파일 맵

```
new_match_engine/
├── control/
│   ├── plant.py        F-16 JSBSim 래퍼 (+ capture/restore_state)
│   ├── lqr.py          Gain-scheduled LQR (Bryson, Riccati)
│   ├── autopilot.py    Outer PI + Inner LQR (게인 = AutopilotConfig)
│   ├── guidance.py     Tactic → Setpoint (3-phase chase PID + ADAPTIVE τ-블렌딩/VERTICAL_PURSUIT)
│   └── tactic.py       16 Tactic enum (+ADAPTIVE/VERTICAL_PURSUIT) + 엔진 상수(WEZ/HardDeck)
├── engine/
│   ├── obs.py          compute_obs → relational feature
│   ├── match.py        multi-rate 매치 루프 + event log
│   ├── scenarios.py    spawn (canonical 4 + spawn_param + LHS diverse)
│   ├── judge.py        wez_damage / Hard Deck 판정
│   └── replay.py       ACMI(Tacview) + CSV + 결정론 검증
└── bt/
    ├── situation.py        물리 상황 분류 (CHASE/CIRCLE/DEFENSIVE, HCA)
    ├── opponents.py        손포팅 적 4 (simple/agg/def/ace)
    ├── yaml_bt.py          generic yaml 인터프리터 (970 적)
    ├── real_rollout.py     온라인 rollout selector (참고/baseline)
    ├── build_situation_dataset.py  상황 데이터셋 생성
    ├── cluster_situations.py       KMeans 상황 클러스터링
    ├── offline_solver.py   MC 라벨(진짜 데미지+shaping) + value 회귀
    ├── scaled_solver.py    대규모 병렬 데이터 생성 (LHS×적)
    ├── tree_policy.py      배포 정책 = RF + 상황 독립 dispatch (§5.6)
    └── run_match.py        canonical 평가 표준 진입점 (beam vs .yaml 적, 4/4)
tools/
├── plot_match_3d_nme.py    매 경기 report.txt(7층)+plot.png + analyze_match_files
└── aggregate_reports.py    N경기 report 집계 → 공통 레버
```

---

## 7. 현재 상태 (2026-06-04)

| 항목 | 상태 |
|---|---|
| CANONICAL 평가 | 4/4 (spawn_adt_neutral beam vs 4 .yaml 적 — ace 포함) · `run_match.py` |
| LQR 제어 스택 | 동작 (Outer PI/P + Inner LQR) |
| 상황 독립 dispatch | head-on→ADAPTIVE, evasive→VERTICAL_PURSUIT, close→GUN_TRACK, else RF (§5.6) |
| 적 (.yaml 인터프리터) | yaml_bt — legacy .yaml 적 그대로 (969/969) |
| 오프라인 solver | 진짜 데미지 라벨 + potential shaping + value 회귀 + 병렬 |
| 분석 파이프라인 | 매 경기 report.txt(7층)+plot.png 자동, aggregate 집계 |
| 시각화 | Tacview ACMI(사라짐 해결: 위치줄 Name) + Event Log(전술·WEZ·피격) |

### 알려진 한계 / 다음
- 우리 정책 .yaml 미완 (비대칭): 적은 .yaml, 우리 정책은 Python(RF+dispatch). dispatch는
  condition→tactic 규칙이라 .yaml BT로 표현 가능 → 양측 대칭 .yaml 인터페이스가 다음 단계.
- head-on 승 = deck 강제: yoyo perch로 적을 hard deck으로 몰아 이김(clean gun-kill 아님) →
  더 robust한 격추로 강화 여지.
- ace — 포트 vs .yaml 차이: `opponents.py`의 ace 포트(zoom-extend)는 더 어려워 draw였음.
  평가는 ground-truth인 .yaml 적으로(메모리 규칙). Python 포트는 stress-test 참고용.
- 정책 재도출(staged): CANDS에 ADAPTIVE/VERTICAL 추가 → 새 권역을 RF가 데이터로 학습(선택).
- 장기 목표: new_engine으로 legacy 대체(.pyd), .yaml 인터페이스 양측 적용.

---

## 8. 방법론 요약 (한 표)

| 단계 | 방법론 | 알려진 툴 | 산출 |
|---|---|---|---|
| 상황 분리 | 물리(E-M)+HCA 상호배타 | — | CHASE/CIRCLE/DEFENSIVE |
| 상황 검증 | 클러스터링 | sklearn KMeans, PCA, silhouette | ~6 상황 확인 |
| 적 확보 | yaml 인터프리터 | — | 970 적 |
| 라벨 | forward-sim + potential shaping (진짜 데미지+Φ차) | JSBSim capture/restore | (state)→[tactic 점수] |
| 정책 | value 회귀 (policy distillation) | sklearn RandomForest | Q 근사 → argmax |
| 커버리지 | Latin Hypercube dense sampling | scipy.stats.qmc | 분해능 |
| 실행 | 멀티프로세싱 병렬 | concurrent.futures | feasible |
| 런타임 | 상황 독립 dispatch + RF (§5.6) | — | head-on/evasive/close 전용 + 일반 RF |
| 분석 루프 | 매 경기 정량 report → 가설→실험→검증 (§5.7) | plot_match_3d_nme, aggregate | 파훼책 도출(감 금지) |
| 평가 | canonical beam vs .yaml 적 (`run_match.py`) | yaml_bt | 4/4 |

> 철학: 측정 먼저 · 적 무관 relational · 진짜 게임 규칙 · 결정론 coverage · 투명 도구 · 상황별 독립.

---

## 연습문제
1. 오프라인 파이프라인 네 단계를 순서대로 적고 각 단계의 목적을 쓰라.
2. forward-sim 라벨링이 "정답"을 어떻게 숫자로 만드는지 설명하라.
3. 분류가 아니라 전술별 점수 회귀를 쓰는 이점(투명성)을 적어라.
4. 경기 중 예측·rollout을 하지 않는 것이 왜 가능한지 설명하라.

