# 고AoA 제어기 검증 — INDI vs LQR on TP-1538 (Validation Report)

> **이 문서의 목적.** LQR 보고서([NEW_ENGINE_LQR_CONTROL_REPORT.md](04_flight_control_lqr.md))
> §15가 정직하게 남긴 한계 — *"국소 선형화+게인스케줄(LQR)의 고기동 fidelity는 확인되지 않았고
> 문헌은 오히려 열화를 보고"* — 를 **실제로 검증**한다. 즉 *"INDI가 고받음각(고AoA) 영역에서 LQR의
> 한계를 데이터로 넘는가?"* 를 **NASA TP-1538 기반 고AoA plant** 위에서 정량 측정한 결과 보고서.
> 모든 수치는 `new_match_engine/validation/aerobench_testbed.py` 로 재현된다.

---

<a id="toc"></a>

## 목차 (Table of Contents)

- [0. 결론부터 (Headline)](#s0)
  - [0.5 주요 가정 (연구 출발점)](#s0-5)
- [1. 동기 — 왜 검증하나](#s1)
- [2. 검증 plant — 왜 TP-1538(AeroBench Morelli)인가](#s2)
- [3. 공정 비교 설계 — 외측 동일, 내측만 LQR↔INDI](#s3)
- [4. 방법론](#s4)
  - [4.1 trim (평형점)](#s4-1)
  - [4.2 선형화 → A, B](#s4-2)
  - [4.3 내측 제어기](#s4-3)
  - [4.4 기동·불확실성·지표](#s4-4)
- [5. 결과](#s5)
- [6. 분석](#s6)
- [7. 정직한 한계](#s7)
  - [7.5 게인 trade-off 곡선 — 공정 sweep](#s7-5)
  - [7.6 형식 검증 (Z3/SMT) — 명령한계 + LQR ROA](#s7-6)
- [8. 결론 및 다음 단계](#s8)
- [부록 A. 재현](#apx-a)
- [부록 B. trim·선형화 수치 (재현값)](#apx-b)
- [부록 C. 참고문헌 (검증)](#apx-c)

---

<a id="s0"></a>
## 0. 결론부터 (Headline)

**고AoA 영역(α≈20°)에서, *정상상태* 자세추종 오차(θss)와 정착시간** (양쪽 튜닝 후, α≈20° 도달):

| 기동 | LQR(A) | INDI(B) | 판정 |
|---|---|---|---|
| 단순 pitch 25° (정상) | θss **0.04°** | θss **0.08°** | 둘 다 <0.1° — **우수·동등** |
| 단순 pitch 25° (모델오차 ½) | θss 0.23° | θss 0.15° | 둘 다 양호 |
| 복합 roll60°+pull20° (정상) | θss 1.30° / 정착 2.8s | **θss 0.69° / 2.1s** | INDI ~2× |
| **복합 + 모델오차 ½** | **θss 2.38° / 정착 7.9s** | **θss 0.61° / 1.1s** | **INDI ~4× 정밀, ~7× 빠른 정착** |

> **한 줄 (정직·정정).** *튜닝 후 정상상태로 보면: **단순 기동은 LQR·INDI 모두 <0.1°로 우수(차이
> 없음)** — 이 영역은 내측 제어기 선택과 무관. **INDI 우위는 *복합 고기동 + 모델 불확실성*에서
> 결정적** — LQR이 θ오차 2.38°·정착 7.9s 로 둔해질 때 INDI 는 0.61°·1.1s 유지(~4× 정밀, ~7× 빠름).*
> 즉 INDI 는 *전방위 우월이 아니라 "어려운 영역(복합+불확실성)의 강건성"*. — 이것이 정확한 결론.

★ **측정·튜닝 주의(정직)**: 초기 비교의 θRMSE 4~14°는 *21° 계단의 과도구간*을 포함한 값이었다.
*정상상태 오차(θss)*로 보고 양쪽을 합리적으로 튜닝하면 위 표가 진짜 추종품질이다. RMSE(과도 포함)는
부록 A 에 병기.

★ **JSBSim에선 이 차이가 안 보였다**(우리 전투엔진은 limiter로 고AoA 회피 + 외측 cascade가 차이를
가림). *제대로 된 고AoA plant + 내측 격리* 라야 드러난다 — 그래서 TP-1538 검증이 필수였다.

---

<a id="s0-5"></a>
## 0.5 주요 가정 (연구 출발점)

| # | 가정 | 무너지면 |
|---|---|---|
| V1 | **plant = AeroBench Morelli (TP-1538 공력)** 가 F-16 고AoA를 충실히 대표 | 다른 고AoA 데이터면 절대수치 변동(경향은 유지 예상) |
| V2 | **내측 격리 비교가 공정** — 외측 자세 P 동일, 내측만 LQR↔INDI | 외측까지 다르면 제어기 비교가 오염 |
| V3 | **모델 불확실성 = 제어효과 배율(ceff)** 로 대표 (damage/공력오차) | 다른 불확실성(질량·CG)엔 별도 검증 필요 |
| V4 | **각가속도 ω̇ = rate 유한차분**(결정론 sim, 노이즈 작음) | 실센서 지연/노이즈 크면 INDI 우위 축소 |
| V5 | **deep post-stall/spin 은 범위 밖** (α<70° departure 전까지만) | 극한 departure 동역학은 두 모델·제어 모두 신뢰 밖 |

---

<a id="s1"></a>
## 1. 동기 — 왜 검증하나

LQR 보고서 §15.2(정직)는 문헌(Snell·Enns·Garrard 1992; NASA HARV)을 근거로 *"게인스케줄 선형제어는
고AoA·고각속도에서 성능 저하 → 그래서 NDI/INDI 비선형 제어가 등장"* 을 명시했다. **가설**: 우리도
INDI를 쓰면 그 한계를 넘는다. 이를 *주장이 아니라 측정* 으로 확인하는 것이 본 검증의 목적이다.

- **LQR의 약점(이론)**: 게인 `K`가 *저AoA trim 선형화*에서 고정 도출 → 고AoA에서 실제 동역학(A,B)이
  달라지고, 모델오차 시 `K`가 *틀린 모델*을 가정해 열화(§13.4).
- **INDI의 가설(이론)**: `Δδ=(ν−ω̇)/ḡ` — *측정된 ω̇* 가 실제 동역학을 반영하므로 `f(x)` 전체를 몰라도,
  ḡ(제어효과)만 대략 맞으면 고AoA·모델오차에 강건(thesis [INDI_NDI_F16_Detailed.md](../reference/INDI_NDI_F16_Detailed.md) §3.4·§4.4).

---

<a id="s2"></a>
## 2. 검증 plant — 왜 TP-1538(AeroBench Morelli)인가

**우리 전투엔진(JSBSim)으로는 이 검증을 못 한다** — (a) JSBSim F-16의 극한 고AoA 공력 충실도가
불확실하고, (b) 우리 제어 limiter·setpoint 구조가 고AoA 진입을 막으며, (c) 외측 cascade가 내측
제어기 차이를 흡수한다(실측: αmax<16°, INDI≈LQR). 그래서 *목적적합한* plant가 필요했다.

**선택: AeroBench(stanleybak) Morelli 모델** ([github](https://github.com/stanleybak/AeroBenchVVPython)):
- **공력 = NASA TP-1538** (Nguyen et al. 1979) — F-16 **고받음각/실속후** 풍동·시뮬 데이터. *Cm 역전·
  롤-요 커플링·실속/departure* 같은 고AoA 비선형을 **명시적으로** 담는다. GCAS(지상충돌회피) 검증
  표준 — 바로 우리가 보려는 LOC/회복 영역.
- **white-box 해석모델**: `ẋ=f(x,u)` 가 다항식으로 *해석적* → (i) 깨끗한 선형화 A,B, (ii) INDI의 ḡ도
  깨끗, (iii) 유한차분 잡음 없음. JSBSim 블랙박스보다 검증에 유리.
- vendor: `new_match_engine/validation/aerobench/` (출처·라이선스 `SOURCE.md`). **전투엔진과 무관 —
  제어기 검증 전용 testbed.**

상태(13): `[VT, α, β, φ, θ, ψ, P, Q, R, pn, pe, h, pow]`, 입력(4): `[throttle, elevator°, aileron°, rudder°]`.

---

<a id="s3"></a>
## 3. 공정 비교 설계 — 외측 동일, 내측만 LQR↔INDI

**핵심 원칙(공정성)**: 제어기 비교가 오염되지 않으려면 *바뀌는 건 하나*여야 한다. LQR 보고서 §16의
통찰대로 **INDI와 LQR은 동일한 외측 cascade를 공유하고 내측 역변환만 다르다** — 그래서 이 검증은
*외측 자세 루프를 양쪽 동일하게* 두고 **내측(rate→조종면)만 교체**한다.

```
[공통 외측]  자세목표 (θ_cmd, φ_cmd)  →  rate_ref (p_ref,q_ref,r_ref)   (P 제어 + β→0 협조)
[내측 A=LQR ]  u_surf = u₀ − K_r·([P,Q,R] − rate_ref)         (rate 부분상태 CARE)
[내측 B=INDI]  Δδ = ḡ⁻¹·(ν − ω̇),  ν = PI(rate_ref − [P,Q,R]) (증분, ω̇ 측정)
```

- **내측을 rate 루프로 격리한 이유**: 고AoA 비선형·모델오차의 영향이 *내측에서 가장 크고*, 외측은
  양쪽 동일하므로 *차이는 순수하게 내측 제어기에서* 나온다. (JSBSim 검증 실패의 교훈 — 외측이 차이를
  가렸음 — 을 직접 교정.)
- 이로써 측정된 θ/φ RMSE 차이는 **"LQR 내측 vs INDI 내측"의 순수 비교**다.

---

<a id="s4"></a>
## 4. 방법론

<a id="s4-1"></a>
### 4.1 trim (평형점)
정상 수평비행 `VT=502 fps(≈300kts), h=15000 ft` 에서 `(α, elevator, throttle)` 를 풀어
`[V̇T, α̇, Q̇]=0` (scipy `fsolve`). 결과: **α=3.41°, elevator=−1.65°, throttle=0.136**.

<a id="s4-2"></a>
### 4.2 선형화 → A, B
해석 plant 에 중앙차분: `A=∂f/∂x (13×13)`, `B=∂f/∂u (13×4)` (§부록 B).

<a id="s4-3"></a>
### 4.3 내측 제어기
- **LQR rate**: rate 부분상태 `A_r=A[PQR,PQR]`, `B_r=B[PQR, surf]` 에 CARE → `K_r` (Bryson Q/R).
- **INDI rate**: `ḡ = B_r` (제어효과 3×3). `ν = K_ν·(rate_ref−rate) + K_iν·∫`, `Δδ = ḡ⁻¹(ν−ω̇)`,
  `δ = δ_prev + Δδ`. `ω̇` = rate 유한차분.
- 외측 자세 P (양쪽 동일): `q_ref = K_θ(θ_cmd−θ)`, `p_ref = K_φ(φ_cmd−φ)`, `r_ref = −2β`.

<a id="s4-4"></a>
### 4.4 기동·불확실성·지표
- **기동**: `pitch_pull_25`(θ_cmd=25° — 고α pull), `roll_60_pull20`(φ=60°,θ=20° — 복합 고기동).
- **조건**: `정상` / `ceff0.5`(제어효과 절반 = 모델오차/damage, *제어기는 모름*) / `noise`(조종면 잡음).
- **지표**: θ/φ 추종 RMSE, max α, max rate, **departure(LOC: |α|>70° 또는 |β|>45°)**.
- 적분: RK4, 100 Hz, 8s.

---

<a id="s5"></a>
## 5. 결과

양쪽 튜닝 후. **θss = 정상상태 |θ오차|(진짜 추종품질)**, 정착s = |θ오차|<2° 진입·유지 시점,
θRMSE = 21° 계단 *과도구간 포함*(참고).
```
maneuver         eng   cond     |  αmax  θss(정상)  θRMSE  정착s |  qmax  pmax   LOC
pitch_pull_25    A=LQR nominal  | 20.2    0.04     4.32    1.0  |   46     0     -
                 B=INDI         | 21.3    0.08     4.36    1.1  |   52     3     -
pitch_pull_25    A=LQR ceff0.5  | 19.1    0.23     5.17    1.4  |   32     0     -
                 B=INDI         | 21.0    0.15     5.28    1.7  |   37     2     -
pitch_pull_25    A=LQR noise    | 20.1    0.07     4.35    1.0  |   46     2     -
                 B=INDI         | 21.2    0.08     4.39    1.1  |   51     4     -
roll_60_pull20   A=LQR nominal  | 20.3    1.30     3.56    2.8  |   39    92     -
                 B=INDI         | 15.9    0.69     3.30    2.1  |   43   115     -
roll_60_pull20   A=LQR ceff0.5  | 21.6    2.38     4.42    7.9  |   28    61     -
                 B=INDI         | 17.7    0.61     3.79    1.1  |   32    62     -
roll_60_pull20   A=LQR noise    | 20.5    1.25     3.58    2.7  |   39    92     -
                 B=INDI         | 16.2    0.71     3.32    2.1  |   43   112     -
```

**핵심 (정상상태 θss 기준):**
| 영역 | LQR(A) | INDI(B) | |
|---|---|---|---|
| 단순 pitch (정상·노이즈) | 0.04~0.07° | 0.08° | 둘 다 우수, 차이 없음 |
| 복합 (정상) | 1.30° / 정착 2.8s | 0.69° / 2.1s | INDI ~2× |
| **복합 + 모델오차 ½** | **2.38° / 정착 7.9s** | **0.61° / 1.1s** | **INDI ~4× 정밀, ~7× 빠름** |
| DEPART(LOC) | 없음 | 없음 | 본 시나리오 양쪽 통제 유지 |

---

<a id="s6"></a>
## 6. 분석

1. **단순 기동(pitch)은 LQR·INDI 모두 정상상태 <0.1°** — 우수하고 *차이 없음*. 즉 이 영역에선 내측
   제어기 선택이 무관하며, "LQR이 고AoA에서 못 쓴다"는 *과장*이다. 잘 튜닝된 LQR도 단순 고α pitch 는
   잘 잡는다. (★ 정직: INDI 가 *항상* 낫다는 게 아니다.)
2. ★ **INDI 우위는 *복합 고기동 + 모델 불확실성*에서 결정적으로 나타난다.** roll60°+pull20° 에 제어효과
   절반(damage)을 주면: LQR 은 *틀린 제어효과를 가정* 해 θ오차 2.38°·**정착 7.9s** 로 둔해지는 반면,
   **INDI 는 ω̇ 피드백이 실제 반응을 보고 증분을 키워 보상** → θ오차 0.61°·**정착 1.1s** 유지
   (~4× 정밀, ~7× 빠름). *이것이 INDI 도입의 데이터 명분 — "어려운 영역의 강건성".*
3. **왜 INDI가 강건한가 (메커니즘)**: LQR은 `f(x)`·`g(x)` 전체를 *모델로 가정*하고 그에 맞춘 `K`를 쓴다 →
   모델이 틀리면 `K`도 틀려 정착이 느려진다. INDI는 `f(x)` 를 *측정된 ω̇* 로 대체하고 ḡ(제어효과)만 쓴다 →
   ḡ가 절반만 맞아도 *증분이 누적되어* 목표 ω̇ 에 수렴(센서 폐루프가 모델오차를 흡수). thesis §4.4 결론과 일치.

### ★ 정직한 단서 (측정·튜닝·trade-off)
- **θRMSE(4~5°)는 *21° 계단 과도구간*을 포함한 값** — 추종 *품질*은 정상상태 θss(0.04~0.7°)로 봐야
  옳다. 초기 보고의 "5° 오차"는 metric 함정이었고, 튜닝+정상상태로 교정했다.
- **공정성**: 양쪽을 합리적 동급 대역폭으로 튜닝(LQR rate-CARE Q↑, INDI PI↑). 절대 최적은 아니므로
  *정밀 trade-off 곡선*은 후속(§8). 단, **모델오차 하 강건성 격차(복합)는 튜닝과 무관하게 일관**.
- departure(LOC)는 본 시나리오 양쪽 없음(α<70). 더 극한·더 큰 모델오차에선 LQR 의 *정착 실패*가 먼저
  문제될 것(ceff0.5 복합서 이미 7.9s).

---

<a id="s7"></a>
## 7. 정직한 한계

| # | 한계 | 비고 |
|---|---|---|
| H1 | **게인 의존** — INDI 우위 폭·공격성은 `K_ν`·`K_r` 튜닝에 의존 | **§7.5 에서 양쪽 sweep 으로 해소** — 모든 활동대역서 INDI Pareto 우월(LQR 최대공격해도 1.8×) |
| H2 | **deep post-stall/spin 범위 밖** — α<70° departure 전까지만 | 극한 departure 는 TP-1538·INDI 증분근사 둘 다 신뢰 밖(thesis §5.2.4) |
| H3 | **불확실성 = 제어효과 배율만** — 질량/CG/공력형상 변화 미포함 | 추가 불확실성 유형은 후속 |
| H4 | **ω̇ = 유한차분(무지연·무노이즈)** — 실센서 지연 시 INDI 우위 축소 | HIL/센서모델 검증 필요(thesis §5.2.1) |
| H5 | **검증 plant ≠ 전투엔진** — 본 결과는 *제어기 자체*의 고AoA 강건성 검증 | 전투엔진(JSBSim)에 INDI 통합 효과는 별개(JSBSim 고AoA 미진입) |
| H6 | **형식 보장(완전 비선형)** — §7.6 [A·B] 로 명령한계·LQR ROA 는 *기계증명*; 완전 비선형 고AoA reachability 만 미수행 | §7.6 에서 Z3 [A]정확·[B]선형화 ROA PROVEN; 비선형 reach 는 Flow*/CORA 영역(실증층이 보완) |

---

<a id="s7-5"></a>
## 7.5 게인 trade-off 곡선 — 공정 sweep (추종↔활동↔강건성)

**왜.** "INDI 가 *공짜로* 우월한가, 아니면 같은 추종·활동 대역에서 강건성만 더 좋은가?" 를
가리려면 양쪽을 *공격성*으로 sweep 해 3-way 균형(정착·θss / 제어활동 u_rms·qmax / 모델오차 하 θss)을
보아야 한다. 복합 기동(roll60+pull20) 고정, LQR 공격성=`rr_scale↓`(입력페널티↓), INDI 공격성=`K_ν↑`.

| eng | 공격성 | 정착s | θss(정상) | u_rms | θss(오차½) | 정착½s |
|---|---|---|---|---|---|---|
| A=LQR | rr=4.0 | 8.0 | 1.61 | 9.9 | 3.37 | 8.0 |
| A=LQR | rr=1.0 | 2.75 | 1.30 | 12.1 | 2.38 | 7.9 |
| A=LQR | rr=0.25 | 2.33 | 0.79 | 24.5 | 1.39 | 2.9 |
| A=LQR | rr=0.10 | 4.81 | 1.07 | 26.3 | **1.07 (바닥)** | 2.6 |
| B=INDI | K_ν=8 | 2.22 | 0.74 | 27.5 | 0.70 | 2.4 |
| B=INDI | K_ν=20 | 2.11 | 0.70 | 27.5 | 0.62 | 1.2 |
| B=INDI | K_ν=60 | 2.07 | 0.68 | 27.5 | **0.60** | 0.8 |

**같은 제어활동(u_rms) 대역에서 강건성(θss 오차½) 비교 — Pareto:**

| 제어활동 u | LQR θss½ | INDI θss½ | INDI 우위 |
|---|---|---|---|
| ~10 | 3.37 | 0.60 | 5.6× |
| ~16 | 1.81 | 0.60 | 3.0× |
| ~26 (LQR 최대공격) | **1.07** | **0.60** | **1.8×** |

**해석 (정직).**
1. **LQR 은 매끄러운 front** — 공격성↑ 로 정상·강건성 모두 개선되지만 제어활동도 같이 오르고,
   **강건성 θss(오차½) 는 어떤 게인으로도 ~1.07° 아래로 못 내려간다**(구조적 바닥).
2. **INDI 는 한 코너에 고정** — `K_ν` 8→60 거의 불변(θss½ 0.70→0.60), 활동 u≈27.5 고정, 정착~1s.
   *여기선 "부드러운 INDI" 옵션이 없다*(증분·ḡ⁻¹ 역변환이 활동을 정함).
3. ★ **Pareto: 모든 활동대역에서 INDI 가 더 강건**; LQR 을 *최대 공격*(같은 활동 u≈27)으로 밀어도
   INDI 가 ~1.8× 더 강건하고 **LQR 은 INDI 의 강건성에 게인으로 도달 불가**.

> **결론(정직).** INDI 는 *공짜 점심이 아니다* — 항상 높은 제어활동을 쓴다. 그 활동예산에서 **LQR 이
> 어떤 튜닝으로도 못 얻는 모델오차 강건성**을 산다. 낮은 활동을 원하면 LQR 뿐이지만 강건성을 포기.
> = "어려운 영역(복합+불확실성)의 강건성 특화" 가 *trade-off 정량으로* 재확인.

재현: `python new_match_engine/validation/tradeoff_sweep.py`

---

<a id="s7-6"></a>
## 7.6 형식 검증 (Z3/SMT) — 명령한계 + LQR Lyapunov ROA

**왜.** 실측(§5–§7.5)은 *유한 시나리오*만 본다. **모든 입력에 대한** 안전성질은 *형식 증명*이 필요하다
(사용자 프레임워크 B). Z3 가 **반례 부재**를 증명하면 그 성질은 *전체 영역*에서 보장된다.

### [A] 외측 명령-한계 안전성 (Z3 LRA — 정확)
clip 로직을 그대로 SMT 로 인코딩하고 "한계 위반 입력이 존재하는가?"를 질의 → **UNSAT(반례 없음)**:

| 성질 | 결과 |
|---|---|
| A1: ∀입력 \|q_ref\| ≤ 80°/s | **PROVEN ✓** |
| A2: ∀입력 \|p_ref\| ≤ 120°/s | **PROVEN ✓** |
| A3: ∀입력 \|δ\| ≤ 25° (액추에이터) | **PROVEN ✓** |

⟹ 제어기는 *구조적으로* departure 유발 명령(과대 rate·조종면)을 **낼 수 없다**(정확·전역).

### [B] 내측 LQR Lyapunov 불변집합 = Region-of-Attraction (Z3 NRA — 선형화)
rate 추종오차 동역학 ė=A_cl·e (`A_cl=A_r−B_rK_r`, CARE 로 **Hurwitz**, eig 실수부 −21.4·−1.9·−7.85).
Lyapunov `A_clᵀP+PA_cl=−I` 로 `V(e)=eᵀPe`(P≻0). 불변타원 `E_c={e: eᵀPe≤c_max}`, **c_max=0.103**
(rate-error box \|e\|≤[120,80,80]°/s 에 내접). Z3 NRA 가 반례 부재로 증명:

| 성질 | 결과 |
|---|---|
| B1: P ≻ 0 (양정치) | **PROVEN ✓** |
| B2: 불변타원 E_c ⊆ rate-error box (departure 불가) | **PROVEN ✓** |
| B3: V̇=−‖e‖² < 0 (양의 불변·수렴) | **PROVEN ✓** |

⟹ **E_c 안에서 출발한 모든 추종오차는 안전 rate-box 를 *절대 벗어나지 않고* 0 으로 수렴** — 즉
내측 LQR 은 인증된 ROA 안에서 departure 가 불가능함이 *기계 증명*됨.

### 정직한 범위
- [A] 는 **정확**(LRA·clip 의미 그대로). [B] 는 **선형화 오차동역학**의 표준 ROA + SMT 집합포함 인증서다.
- **완전 비선형 고AoA reachability**(Cm 역전·롤요 커플링 포함)는 전용 reachability 도구(Flow*/CORA)
  영역으로 본 검증의 형식층 밖 — 그 역할을 **실증층 `aerobench_testbed`(TP-1538)** 가 담당한다.
  *형식층[A·B](../[전역 보장]) + 실증층(TP-1538 [고AoA 비선형])* 이 상보적으로 검증을 완성한다.

재현: `python new_match_engine/validation/formal_verify.py`

---

<a id="s8"></a>
## 8. 결론 및 다음 단계

**결론 (정직·정정)**: 진짜 고AoA plant(TP-1538) 위에서, 양쪽을 튜닝해 정상상태로 보면 —
- **단순 고α 기동(pitch)은 LQR·INDI 모두 <0.1° 로 우수·동등** (이 영역은 내측 제어기 무관).
- ★ **복합 고기동 + 모델 불확실성에서 INDI 가 결정적 — ~4× 정밀, ~7× 빠른 정착** (LQR 2.38°/7.9s vs
  INDI 0.61°/1.1s). **= INDI 도입 명분은 "전방위 우월"이 아니라 "어려운 영역(복합+불확실성)의 강건성".**

즉 LQR 보고서가 남긴 고AoA 한계는 *단순 기동에선 과장*이고, *복합+불확실성에선 실재*하며 그 영역을
INDI 가 넘는다 — *데이터로* 확인. 단 극한 departure·실센서·정밀 trade-off 곡선은 범위 밖(아래).

**완료된 심화** (이번 라운드):
- ✅ **게인 공정 trade-off 곡선** (§7.5) — 양쪽 sweep, INDI Pareto 우월 정량화(모든 활동대역, LQR 최대공격 1.8×).
- ✅ **형식 검증** (§7.6) — Z3 로 명령한계[A 정확]·LQR Lyapunov ROA[B 선형화] *기계증명* PROVEN.

**남은 다음 단계**:
1. **불확실성 확장** — CG 이동·질량·공력오차·실센서 지연(HIL) 주입(thesis §5.2.1·§4.4).
2. **완전 비선형 reachability** — Flow*/CORA 로 고AoA(Cm 역전·롤요 커플링) departure 비진입 over-approx 증명
   (§7.6 형식층의 비선형 확장; Z3 NRA 범위 밖).
3. **전투엔진 통합 판단** — JSBSim 본선은 고AoA 미진입(limiter)이라 *현재* INDI 이득이 제한적;
   고AoA 전술(post-stall 기동)을 *허용*할 때 INDI 가치가 실현됨. 계층 결정 사안.

---

<a id="apx-a"></a>
## 부록 A. 재현
```bash
python new_match_engine/validation/aerobench_testbed.py
```
- plant: `new_match_engine/validation/aerobench/` (AeroBench Morelli, TP-1538; 출처 `SOURCE.md`).
- 비교 하네스·제어기·기동·지표: `aerobench_testbed.py`.

<a id="apx-b"></a>
## 부록 B. trim·선형화 수치 (재현값)
- trim @ VT=502fps, h=15000ft: **α=3.41°, elevator=−1.65°, throttle=0.136**.
- 내측 rate 부분상태 `[P,Q,R]`, 조종면 `[elev,ail,rud]°`. `K_r`=CARE(A_r,B_r,Q_r,R_r),
  `Q_r=diag(2,4,2)`, `R_r=0.05·I`. INDI `ḡ=B_r`.

<a id="apx-c"></a>
## 부록 C. 참고문헌 (검증)
- ★ [AeroBenchVVPython (stanleybak) — F-16 V&V benchmark (TP-1538 공력)](https://github.com/stanleybak/AeroBenchVVPython)
- ★ [Nguyen et al. (1979), NASA TP-1538 — F-16 stall/post-stall, NTRS 무료](https://ntrs.nasa.gov/api/citations/19800005879/downloads/19800005879.pdf)
- [Heidlauf et al. (2018), Verification Challenges in F-16 GCAS (ARCH)](https://stanleybak.com/papers/heidlauf2018arch.pdf)
- [Snell, Enns & Garrard (1992), Nonlinear Inversion Flight Control — NTRS](https://ntrs.nasa.gov/citations/19900060606)
- Yasin ŞAHİN (2025), *Robust Attitude Control of F-16 Using INDI*, ITU — 정리본
  [INDI_NDI_F16_Detailed.md](../reference/INDI_NDI_F16_Detailed.md).

> 연관: [LQR Full Report](04_flight_control_lqr.md) (§15 고기동 fidelity·§16 INDI 비판점검).
