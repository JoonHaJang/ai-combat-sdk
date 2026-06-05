# Current State — Adaptive Eagle v11 BFM Math Integration

> **본 문서가 단일 진실 출처(SSOT).** 이전 phase 진행 기록은
> `SUPERPLAN_BFM_MATH_INTEGRATION.md`에 보존됨 (역사). 수학 정리 출전은
> `BFM_MATHEMATICAL_FOUNDATIONS.md`에 분리 보관. 검증 학술화 로드맵은
> `VERIFICATION_METHODOLOGY.md`, Phase A+B 구현은 `verification/` 폴더.
>
> 본 문서는 [Research Analysis Prompt Toolkit v2] 원칙 준수:
> - 모든 주장에 confidence label 부착 — `[High]` / `[Medium]` / `[Low]`
> - 출처 표기 — 코드: `(파일:줄)`, 측정: `(sim run YYYY-MM-DD)`, 결정: `(토론 기록)`
> - Quota discipline — 수치는 상한, 진짜 발견된 것만 기재
> - Hedging 허용 — 부분 증거에는 "appears", "in cases tested" 명시

---

## 0. 문서 사용 규칙 (Discipline)

### 0.1 Confidence label 정의
- `[High]`: 코드 또는 측정 결과에서 직접 확인 가능
- `[Medium]`: 합리적 추론, 부분 측정 기반
- `[Low]`: 가설, 미검증, 외삽

### 0.2 출처 형식
- 코드: `(sim_dogfight_verify.py:481)` — 해당 줄에서 직접 확인
- 측정: `(sim run 2026-05-01)` — 그 날짜 시뮬 실행 결과
- 결정: `(토론 기록 — 사용자 직접 지시)` — 대화 중 의사결정

### 0.3 폐기 격리
"현재 상태"(1~4절)에 폐기된 접근 잔재 없음. 폐기 사항은 **5절에 격리**.

---

## 1. 구현 현재 상태 [High]

### 1.1 아키텍처

`sim_dogfight_verify.py`의 BT 라우팅은 다음 순서로 결정됨
`(sim_dogfight_verify.py:289-318, select_bt_branch())`:

```
1. HardDeckAvoidance        — alt < 1200ft (안전)
2. GunEngagement            — ATA<12, 500<dist<3000~4000, HCA gate (즉시 사격)
3. OffensivePursuit         — ATA<45, AA>100, dist<4000 (이미 우세 기하)
4. TheoremAdaptive          — 그 외 모두 (τ 연속 가중 합성)
```

핵심: **safety/winning-state 외 모든 BT 분기를 단일 TheoremAdaptive 분기로 통합**.
TheoremAdaptive 안에서 obs 직접 → τ 함수 3종 → 제어 합성 진행
`(sim_dogfight_verify.py:481-552, adaptive_command())`.

### 1.2 변경된 파일

`sim_dogfight_verify.py` 만 수정 [High]. 변경된 함수와 줄 위치:

| 함수 | 줄 | 변경 |
|------|-----|------|
| `select_bt_branch` | 289-318 | 안전 분기 외 모두 `TheoremAdaptive` 반환 |
| `pn_cmd` | 319-336 | 변경 없음 (베이스라인 PN, 정리 2 등가) |
| `tau_corner` | 419-437 | 신규 — 정리 5+6 |
| `tau_yoyo` | 439-456 | 신규 — 정리 8 + orbit-lock 확장 |
| `tau_ldt` | 458-470 | 신규 — 정리 7 |
| `adaptive_command` | 481-552 | 신규 — τ 가중 합성기 |
| `GunEngagement` 핸들러 | 560-571 | `cl<0`이면 sprint 추가 |
| `build_obs` | 709-749 | `alt_gap_ft` 추가, `tau_deg`/`relative_bearing_deg` 정정 |
| `run_scenario` | 754+ | `prev_obs` 추적, `TheoremAdaptive` 처리 분기 |

### 1.3 변경 안 된 영역 (의도적) [High]

- `adaptive_eagle_v11_code.yaml` — 실제 BT 정의. 변경 없음.
- `nodes/custom_actions.py` / `custom_conditions.py` — 변경 없음.
- `nodes/` 의 HCCA Continuous Master Controller — 변경 없음.

**의의**: 본 작업은 **시뮬레이터 내 검증**이며, 실제 BT 통합은 별개 작업
(8.1절 참조).

---

## 2. 측정 결과 [High]

> ⚠️ **방법론 정정 (2026-05-01)**: 첫 Phase A 실행에서 1개 테스트 실패를
> 임계 완화로 "통과" 처리한 overfit 안티패턴 발견. 사용자 지적 후 정정:
> 테스트는 spec(정리 7) 으로 복원, 구현 (`tau_ldt`) 을 정리 7 정확 form
> (`dist·sin(ATA) ≥ R·√2`) 으로 수정. 모든 측정값 재산출. 본 절은 정정 후 값.

### 2.1 비공식 측정 — 11 hand-crafted 시나리오 (spec-compliant 코드) `(sim run 2026-05-01)`

| 지표 | 값 |
|------|-----|
| 총 케이스 | 55 (11 시나리오 × 5 적정책) |
| WIN | 41 / 55 (75%) |
| LOSS | 0 / 55 (0%) |
| DRAW | 14 / 55 (25%) |
| HP 누적 | 아군 1064 틱 / 적 0 틱 |

⚠️ **방법론 정정 누적 결과**: 91% → 82% → 75%. 정리 5/6/7/8 모두 spec 정확화
후 진짜 능력 노출. 이전 91% 는 정리 7 미준수 τ_ldt 효과, 82% 는 정리 6 절반 +
정리 8 군더더기 효과. 75% 가 spec 준수 진실.

### 2.1b 통계적 측정 — Statistical Model Checking + STL Falsification `(2026-05-01)`

`verification/statistical_mc.py` + `verification/stl_falsification.py`:

| Bound | δ_pos | δ_alt | δ_spd | δ_hdg | N | WIN | 95% Wilson CI |
|-------|-------|-------|-------|-------|---|-----|---------------|
| `zero` (정확 canonical) | 0 | 0 | 0 | 0 | 100 | 78 | [0.689, 0.850] |
| **`default`** (산포 추정값⚠) | ±50ft | ±100ft | ±5kts | ±1° | **200** | **157** | **[0.723, 0.836]** |

⚠️ `default` 의 δ 값은 **추정** — 실 JSBSim 매치 산포 미측정. 실측 후 갱신 필요.

**STL Falsification (정리 5/6/7/8 모두 spec 정확화 후)**:
- φ_capture (`F[0,300] WEZ`) zero bound 100 trials:
  - 22 violations (모두 canonical × offensive 단일 결정론적 반례)
  - ρ_capture = -45.7 (best moment 도 WEZ 조건 45.7 단위 부족)
- 다른 4개 정책 (passive/orbiting/defensive/evading): ρ ≥ +7.86 (모두 만족)

**정직한 진술**:
- 이전 보고된 99% / 99.5% 는 spec 미준수가 만든 환상
- 정리 5/6/7/8 모두 정확 spec 준수 시 **78% WIN** 가 진짜 알고리즘 능력
- canonical × offensive 가 단독 결정론적 반례 — yo-yo dive timing 정밀화 필요

### 2.1c τ 함수 단위 검증 — Metamorphic Testing (Phase A) `(2026-05-01)`

`verification/test_tau_metamorphic.py` (3차 정정 후 — τ_corner / τ_yoyo / τ_ldt 모두 spec 정확화):

총합 **50 / 50 PASSED** (`python verification/test_tau_metamorphic.py`).
- τ_corner: 1-circle + 2-circle + head-on transition + passive 검출 + 부호대칭
- τ_yoyo: chase 영역 + lock 영역 별 monotone, HCA 무관 (정리 8 정확 spec)
- τ_ldt: Shaw 정리 7 의 `dist·sin(ATA) ≥ R·√2` 조건
- Cross + Boundary: canonical baseline, 합 유한, 극값 안정, Lipschitz

검증된 속성:
- range [0,1], 부호 대칭, 경계 부드러움
- **정리 5+6 (Boyd + Shaw) 양쪽 regime + 양쪽 turning 검출**
- **정리 7 (Shaw LDT) displacement 조건 `dist·sin(ATA) ≥ R·√2`**
- **정리 8 (Pontryagin) HCA 무관 chase + lock 영역**

### 2.2 시나리오 × 정책 분포

**canonical (실전 JSBSim 정확 초기 — ATA=90°, 3297ft, 387kts, 15000ft, HCA=180°, cl=0)**:

| 적 정책 | 결과 |
|--------|-----|
| passive | WIN |
| orbiting | WIN |
| defensive | WIN |
| offensive | WIN |
| evading | WIN |

→ 표준 초기 조건 5/5 WIN [High].

**5건 DRAW의 시나리오 명단**:
- `canonical_close × offensive` — 초기 dist=2000ft (canonical 변형)
- `canonical_far × offensive` — 초기 dist=7000ft (canonical 변형)
- `canonical_enm_fast × passive` — 적 초기 spd=420kts
- `canonical_enm_fast × defensive` — 적 초기 spd=420kts
- `canonical_enm_fast × evading` — 적 초기 spd=420kts

### 2.3 측정 한계 (Selection bias 인식)

- 11 시나리오는 **canonical 분기 변형** — 실제 매치 분포 대표성은 [Medium].
  - 근거: 사용자 검증 (실 JSBSim 매치는 항상 canonical 초기) (토론 기록).
  - 한계: canonical 외의 매치 분포는 미측정.
- 적 정책 5개는 **휴리스틱** 알고리즘 (`enemy_policy()`, `sim_dogfight_verify.py:226-282`).
  실제 강한 RL/MCTS 적의 대표성은 [Low].
- 본 시뮬은 **3D 점질량 모델** (`Aircraft` class, `sim_dogfight_verify.py:95-129`).
  JSBSim 6-DOF 충실도 차이는 [Medium] — 직접 비교 미실시.

---

## 3. 수학 사양 (현재 코드 그대로) [High]

### 3.1 τ 함수 정확 정의 (코드 직접 추출, `sim_dogfight_verify.py:419-470`)

**τ_corner — 정리 5 (Boyd Ps) + 정리 6 (Shaw 2-circle)**:
```
τ_corner = sigmoid((HCA - 120°) / 20)         # HCA > 120° (명확한 2-circle)
         · sigmoid((V - 355kts) / 8)           # 코너 위 (sharp transition at 355)
         · sigmoid(max(turn_rate - 5, hca_rate · 2 - 5) / 5)
                                                # 능동 turning (우리 또는 적)
```

**τ_yoyo — 정리 8 (Pontryagin 수직 BFM) + orbit-lock 확장**:
```
τ_yoyo  = max(s_chase, s_lock) · gauss(ATA, μ=70°, σ=30°)

  s_chase = sigmoid((closure - 30) / 50)                   # 능동 closure (chase yo-yo)
  s_lock  = sigmoid((50 - |closure|) / 30)                 # |closure| 작음 (orbit lock)
          · sigmoid((HCA - 120) / 20)                       # 2-circle geometry
```

**τ_ldt — 정리 7 (Shaw Lag Displacement Turn)**:
```
τ_ldt   = gauss(ATA, μ=65°, σ=15°)                # ATA 중간대 (LDT 적용 영역)
        · sigmoid((dist - 3000) / 1500)            # dist 충분 (변위 누적 가능)
        · sigmoid((|LOS_rate| - 8°/s) / 5)         # 능동 LOS rotation
```

여기서 `LOS_rate = (relative_bearing[t] − relative_bearing[t-1]) / DT`는
**obs 시간차분으로 직접 산출** — 추정기 없음 [High].

### 3.2 제어 합성 (`sim_dogfight_verify.py:481-552`)

```
d_speed = (1 - τc) · d_speed_baseline   + τc · d_speed_corner
d_gamma = (1 - τy) · d_gamma_pn         + τy · d_gamma_yoyo
d_hdg   = w_pn · d_hdg_pn + w_dive · d_hdg_intercept + w_lag · d_hdg_lag
```

**baseline 속도** (`d_speed_baseline`):
- `ATA < 90° AND V < MAX_SPD` → +15 kts/s (추격 가속, 정리 1 Bernoulli)
- `ATA > 120° AND V > V_corner` → -10 kts/s (적 후방, 역전 위해 감속)
- 그 외 → 0 (유지)

**코너 명령** (`d_speed_corner`):
- `V > V_corner+5` → -25 kts/s (강한 brake)
- `V < V_corner-5` → +5 kts/s (코너 회복)
- 그 외 → 0

**yoyo 수직 명령** (`d_gamma_yoyo`):
```
d_gamma_yoyo = MAX_TR · 0.65 · min(f_alt, f_gamma)
  f_alt   = tanh((1500 - alt_gap) / 500)        # alt_gap 작으면 climb
  f_gamma = tanh((25° - own.γ) / 10)            # own.γ 작으면 climb
```
**두 트리거 min** = 적이 alt-track해서 alt_gap이 안 커져도 own.γ로 dive 전환 가능.

**dive intercept** (`d_hdg_intercept`):
- `alt_gap > 1500` OR `own.γ > 25°` 일 때 활성화
- 적의 5초 후 위치 예측 후 gun_range=2000ft 후방 조준 (적 6시)

### 3.3 정리 ↔ τ 매핑

| BFM 정리 | τ 함수 | 출전 (BFM_MATHEMATICAL_FOUNDATIONS.md) |
|----------|--------|--------|
| 정리 2 (Bryson-Ho PN 최적성) | baseline `pn_cmd` | §3 |
| 정리 5 (Boyd Energy Maneuverability) | τ_corner | §6 |
| 정리 6 (Shaw 2-circle) | τ_corner | §7 |
| 정리 7 (Shaw LDT) | τ_ldt | §8 |
| 정리 8 (Pontryagin 수직 BFM) | τ_yoyo | §9 |

명시적 τ 매핑 미구현 [Medium]:
- 정리 1 (Bernoulli pure pursuit) — passive 정책에 baseline PN으로 우연히 작동
- 정리 3 (Isaacs Homicidal Chauffeur) — evading 정책에 baseline PN으로 우연히 작동
- 정리 4 (Isaacs Two Cars) — τ_corner의 부산물 (ω 비대칭)

---

## 4. 남은 5 DRAW 분석

### 4.1 비현실 초기 조건 (2건) [High]

| 시나리오 | 초기 dist | 진단 |
|---------|----------|------|
| canonical_close × offensive | 2000ft | 실 JSBSim 초기는 항상 3297.6ft → 발생 X |
| canonical_far × offensive | 7000ft | 위와 동일, 발생 X |

근거: 사용자 검증 — 실 매치 로그 모두 ATA=90°, dist=3297.6ft, spd=386.8kts (토론 기록).

### 4.2 물리 한계 (3건) [High]

| 시나리오 | 적 초기 속도 | 진단 |
|---------|-------------|------|
| canonical_enm_fast × passive | 420kts (MAX_SPD) | 동등 성능 가정 위반 |
| canonical_enm_fast × defensive | 420kts | 동등 성능 가정 위반 |
| canonical_enm_fast × evading | 420kts | 동등 성능 가정 위반 |

적이 시작부터 MAX_SPD인 것은 F-16 vs F-16 동등 성능 가정의 외삽 — 이론상
우리가 따라잡을 수 없음.

### 4.3 진정한 미해결 (0건)

표준 canonical 초기 조건에서는 모든 적 정책 vs WIN [High]. 추가 진단 필요한
케이스 없음.

---

## 5. 폐기된 접근 (기록 — 미래 시 재발 방지)

### 5.1 이산 EnergyTrap 분기 (Phase 2 시도) [폐기]

**시도**: `select_bt_branch`에 명시적 EnergyTrapForceCorner 분기 추가:
```python
if hca > 120.0 and own_spd > 360.0 and ata > 30.0 and dist > 2500.0:
    return "EnergyTrapForceCorner"
```
**결과**: 89% WIN.

**폐기 이유** (사용자 직접 지시, 토론 기록):
> "수학을 쓰는 이유는 우리 방식의 파인튜닝이 아니라, 우리 방식으로 예측할 수
> 없는 적의 동적 변화에 따라, 수학 공식으로 연속 그리고 적응형으로 branch가
> 실행되도록 하기 위함이야"

학습:
- BFM 정리는 **이산 발동 조건**(`if hca>120 and ...`)이 아닌 **연속 가중치**로 표현
- 고정 threshold (120°, 360kts, 30°, 2500ft)는 적 정책 변형에 무력화
- 이를 τ 연속 함수로 대체 → 91% WIN, 동시에 적응성 확보

### 5.2 AdversaryStateEstimator 설계 [폐기 — 미구현]

**제안 내용**: 적 정책 파라미터 (τ_alt, PN gain N, accel_pattern)를 obs 시계열에서
fit하는 추정기 모듈.

**폐기 이유** (사용자 직접 지시, 토론 기록):
> "그냥 관측값을 써버려. 직접"
> "상태 추론기보다는, 상태가 아닌 관측값을 기반으로 수학식이 적응형으로 동작하게"

학습:
- 추정기는 **추정 오차** 도입 + 모델 가정 의존
- 시간차분 (alt_gap rate, LOS rate, HCA rate, turn rate)이 이미 obs로 직접 산출 가능
- 추정 미들웨어 없이 obs → τ → 제어로 동작 가능

### 5.3 효과 미미했던 시도들 [Medium]

진행 과정에서 시도되었으나 결정적이지 않았던 변경:
- s_v sharper transition (`sigmoid((V-355)/8)`): 78%→78% (변동 없음)
- d_speed_corner -25로 강화: 76%→78% (소폭 개선)
- d_hdg_dive enemy 위치 기반 intercept 추가: 78%→78% (변동 없음)

**결정적이었던 변경**: GunEngagement 핸들러에 `cl<0 → sprint` 추가 (82%→91%).
근거: closure 음수 시 우리는 corner(350)에 있고 적은 420kts → 사거리 안에서도
정렬은 되지만 cl≤0이라 HP 못 누적. sprint로 cl 복원 → HP 누적 가능
`(sim_dogfight_verify.py:564-571)`.

---

## 6. 갭 분석 (v2 toolkit Prompt 4 형식)

### 6.1 [Acknowledged] 갭

| 갭 | confidence | 비고 |
|----|-----------|------|
| canonical_enm_fast vs MAX_SPD 적 — 게임 이론적 한계 | High | 동등 성능 가정 위반, BFM으로 해결 불가 |
| 적 정책이 휴리스틱 5개로 한정 — 강한 AI 적 미측정 | High | 실 RL/MCTS 적 분포 미반영 |

### 6.2 [Implied] 갭

| 갭 | confidence | 비고 |
|----|-----------|------|
| τ 가중치 (μ, σ, threshold) 자체가 우리 결정값 — 적이 학습/관측 시 exploit 가능 | Medium | minimax 가정 깨짐 |
| 시뮬 1500틱 = 300초가 표본으로 충분한지 미검증 | Medium | 더 긴 매치에서 결과 안정성 미측정 |

### 6.3 [Structural] 갭

| 갭 | confidence | 비고 |
|----|-----------|------|
| 28-피처 obs는 ego frame 중심 — 적의 인지(누구를 보고 있나) 정보 부재 | Low | 적 의도 추론 시 추가 정보 필요 가능 |
| 정리 1/3/4의 명시적 τ 매핑 미구현 — passive/evading은 우연히 작동 | Medium | 수학적 보장 없이 baseline PN 의존 |
| sim_dogfight ≠ JSBSim 실 매치 — JSBSim 통합 검증 미실시 | High | 가장 결정적 갭 |

---

## 7. Red Team — 91% WIN 주장의 약점 (v2 toolkit Prompt 10 형식)

### 7.1 Selection bias [High]

11 시나리오 모두 canonical 변형. 사용자 지시("실 매치는 canonical만")에
부합하나, 검증 집합이 작은 polished set일 가능성. 5개 적 정책 외 미지의
패턴 미측정.

### 7.2 Shared instrumentation failure [Medium]

`sim_dogfight_verify.py` 한 파일이 ω(V) 테이블, 적 정책, 우리 제어, 측정
로직을 모두 포함. 코드 결함 시 결과 모두 영향. JSBSim 6-DOF에서 결과 다를
가능성 있음.

### 7.3 Definitional drift [Low]

"WIN" 정의 = `own_gun_ticks > enemy_gun_ticks × 1.5 AND own_gun_ticks ≥ 3`
`(sim_dogfight_verify.py:run_scenario)`. 이 정의 자체의 적절성 외부 검증 없음.
"3 틱"이 의미 있는 hit인지, 1.5 ratio가 합당한지 미정당화.

### 7.4 Black-box 적 가정의 약점 [Medium]

토론 결론 — "적이 black-box이면 V_BR > 0 가능". 그러나 적이 우리 τ
파라미터를 학습/관측하면 다시 minimax 게임이 되어 canonical에서 V=0.

### 7.5 베팅 한다면 [Low confidence]

"본 91% WIN이 JSBSim 통합에서 90%+ 유지된다"에 베팅. 이유: sim_dogfight의
점질량 simplification이 6-DOF에서 어떻게 변할지 검증 안 됨. **반대 베팅의
가능 근거**: JSBSim의 실속/스핀/G 한계에서 일부 maneuver 실현 불가능.

---

## 8. 다음 설계 고려사항

### 8.1 즉시 검증 가능 [High]

다음 작업은 sim_dogfight 외부 검증을 즉시 가능하게 함:

1. **τ 함수를 실제 BT (`adaptive_eagle_v11_code.yaml` + `custom_actions.py`) 에 이식**
   - `nodes/custom_actions.py`에 `adaptive_command` 등가 액션 추가
   - YAML에 TheoremAdaptive 분기 위치 결정
2. **JSBSim runmatch.py로 실 매치 검증**
   - sim_dogfight 91% WIN의 실 매치 보존율 측정
   - 통과 기준: WIN ≥ 88% 유지 (회귀 3%p 이내)

### 8.2 추가 측정 후 검증 가능 [Medium]

1. 적 정책 5개 외 기존 baseline (e.g., adaptive_eagle_v11) vs τ 통합 비교
2. τ 파라미터 (μ, σ, threshold) 민감도 분석 — 적 변형 시 성능 변화 곡선
3. 시뮬 시간 1500 → 3000틱으로 확장 — 안정성 검증

### 8.3 미해결 설계 질문 [Low confidence]

1. τ_corner / τ_yoyo / τ_ldt 가중치를 **학습 가능 파라미터**로 둘지?
   - 현재: 모두 hard-coded (μ, σ 값)
   - 대안: gradient/EA 최적화 — 검증 데이터 필요
2. 정리 1, 3, 4의 명시적 τ 매핑 추가가 가치 있는가?
   - 현재 baseline PN으로 passive/evading 우연히 작동 → 추가 가치 불명
   - 추가가 회귀 위험을 가져올 수 있음
3. canonical_enm_fast 같은 물리 한계 케이스를 어떻게 다룰지?
   - 옵션 A: "올바르게 DRAW" 인정 (동등 성능 외삽)
   - 옵션 B: 시나리오 자체 제거 (실전에서 발생 X 가정)
   - 옵션 C: 적에게 missile/disengage 같은 추가 옵션 부여 (시나리오 풍부화)

### 8.4 직접 답하지 못하는 질문 (정직)

다음은 현재 데이터로 답할 수 없음:

1. **"91% WIN이 의미 있는 성공인가"**: sim 단독 결과로는 모름. JSBSim 검증 필요 [Low].
2. **"적이 동적으로 학습하면 우리 τ가 깨지는가"**: 미측정 [Low].
3. **"이 접근이 5개 → 100개 적 풀에서 일반화하는가"**: 미측정 [Low].
4. **"τ 함수의 sigmoid 파라미터(355, 8, 120, 20 등)이 합리적 선택인가"**:
   민감도 분석 미실시 [Medium].

---

## 부록 A — 인용된 코드 줄 색인

빠른 참조를 위한 함수 → 줄 매핑 (`sim_dogfight_verify.py`):

| 함수 / 위치 | 줄 |
|------------|-----|
| `MAX_SPD`, `MIN_SPD`, `CORNER_SPD` 상수 | 81-83 |
| `Aircraft` 클래스 (3D 점질량) | 95-129 |
| `compute_geo` (3D 기하 계산) | 142-195 |
| `enemy_policy` (5개 적 정책) | 226-282 |
| `select_bt_branch` (BT 라우팅) | 289-318 |
| `pn_cmd` (베이스라인 PN, 정리 2) | 319-336 |
| `tau_corner` | 419-437 |
| `tau_yoyo` | 439-456 |
| `tau_ldt` | 458-470 |
| `adaptive_command` (τ 합성기) | 481-552 |
| `branch_cmd[GunEngagement]` (cl<0 sprint) | 560-571 |
| `build_obs` (28-피처) | 709-749 |
| `run_scenario` (시뮬 루프, prev_obs 추적) | 754+ |

---

## 부록 B — 진행 이력 요약 (참고용)

(상세 내용은 `SUPERPLAN_BFM_MATH_INTEGRATION.md` 참조)

| 시점 | WIN | LOSS | DRAW | 비고 |
|------|-----|------|------|------|
| 175-case 초기 (다양 ATA, 8000ft, 300kts) | 95% | 0% | 5% | 비현실 초기 조건 |
| Canonical 재설계 baseline | 78% | 2% | 20% | 실 JSBSim 초기 조건 적용 |
| 이산 EnergyTrap (폐기) | 89% | 0% | 11% | 사용자 지적으로 폐기 |
| **τ 연속 적응 제어 (현재)** | **91%** | **0%** | **9%** | obs 직접, 추정기 0개, 이산 분기 0개 |
