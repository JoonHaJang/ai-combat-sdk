# Project Compass

> **용도**: 매 세션 docs 재탐색 시간 절약 + reachability/deadlock 판정.
> *내용 자체*는 짧게 유지 — 본문은 다른 문서 가리키기, 여기서는 *현재 상태 한 줄*.
> **갱신 규약**: 새 발견·새 결정 즉시 본 문서의 §A/§B/§D 갱신. §C/§E 는 매 phase 종료시 점검.

---

## §A. Quick-orient URLs (정적 참조)

### 1. 마스터 문서

| 문서 | 역할 | 핵심 §  |
|---|---|---|
| [docs/PURSUIT_CHASE_PLAN.md](PURSUIT_CHASE_PLAN.md) | 마스터 플랜 (정의·HJI·V_m*·종료조건) | §0.4 용어, §2.5 V_adv, §2.6 hybrid game, §8 100%-WIN 조건 |
| [docs/PROJECT_OVERVIEW/03_recent_analysis.md](PROJECT_OVERVIEW/03_recent_analysis.md) | **방법론 ground truth** (교훈 1·2·4) | §5 τ 연속 가중, §6 추정기 회피, §8 한 발 물러서서 본 4교훈 |
| [docs/PROJECT_OVERVIEW/05_document_map.md](PROJECT_OVERVIEW/05_document_map.md) | 문서 지도 | 전체 |
| [examples/pursuit_chase_v1/SUPERPLAN_v2.md](../examples/pursuit_chase_v1/SUPERPLAN_v2.md) | **현재 작업 계획** (diagnosis-first) | §0 위반 진단, §1 ground rules, §2 H1 lemma, §3 Phase 0~5 |
| [examples/pursuit_chase_v1/SUPERPLAN_CUMULATIVE_CURRICULUM.md](../examples/pursuit_chase_v1/SUPERPLAN_CUMULATIVE_CURRICULUM.md) | v1 (대체됨, 역사 보존) | Stage 1 성과만 유효 |
| [docs/HANDOVER_2026-05-15.md](HANDOVER_2026-05-15.md) | 인수인계 (이전 세션 결론, v2 가 부분 기각) | §1 측정값 유효, §5 권고는 기각 |
| [docs/HANDOVER_2026-05-13.md](HANDOVER_2026-05-13.md) | 더 이전 인수인계 (RT-1/2/3 출발) | — |
| [README.md](../README.md) | 프로젝트 개요 | — |

### 2. 핵심 코드 파일

| 파일 | 역할 | 변경 빈도 |
|---|---|---|
| [tools/basis/gradient_approximators.py](../tools/basis/gradient_approximators.py) | ∇V_i closed-form + optimal_control (PLAN §2.5/§2.6.3) | 자주 (모든 V_m* 변경) |
| [tools/basis/tau_functions.py](../tools/basis/tau_functions.py) | τ_i Layer1+2, obs_history 입력 | 가끔 (τ 재설계) |
| [tools/basis/envelope_f16.py](../tools/basis/envelope_f16.py) | V_c, R(V), ω_max, γ̇_max (PLAN §2.2) | 거의 안 변경 |
| [examples/pursuit_chase_v1/nodes/branch_dispatcher.py](../examples/pursuit_chase_v1/nodes/branch_dispatcher.py) | 9-way if-else → mode 선택 | 자주 (분기 추가/이식) |
| [examples/pursuit_chase_v1/nodes/continuous_policy.py](../examples/pursuit_chase_v1/nodes/continuous_policy.py) | obs→x, mode-τ 매핑, CSV log | 자주 (logging, mode 추가) |
| [examples/pursuit_chase_v1/nodes/custom_actions.py](../examples/pursuit_chase_v1/nodes/custom_actions.py) | BT 노드, per-match prev_branch | 가끔 |
| [tools/basis/verify_smt_cover.py](../tools/basis/verify_smt_cover.py) | RT-3 Z3 cover proof 템플릿 (R4 패턴 거점) | 새 SMT proof 추가시 |
| [tools/basis/verify_grad_lut_xcheck.py](../tools/basis/verify_grad_lut_xcheck.py) | ∇V↔LUT cross-check | 거의 안 변경 |

### 3. 데이터·로그 위치

| 경로 | 용도 |
|---|---|
| `logs/hji/V6d_wez_v3.npz` | HJI 6D LUT (321MB, gitignored). 재생성: `python tools/basis/hji_solve_v3.py --grid 12 --time 60 --accuracy medium` |
| `logs/metadata/` | 매치별 메타 + tick CSV (`PURSUIT_CONT_LOG` 환경변수 → 별도 CSV) |
| `logs/snapshots/` | 백업 (stage2_best, pre_dive) — Stage 회귀 비교용 |
| `models/intent_model.pt` | adaptive_eagle v8/v9/v10 자산. **현 pursuit_chase 작업과 무관**. |

### 4. 외부 참조

| 주제 | URL |
|---|---|
| hj-reachability (Stanford ASL) | https://github.com/StanfordASL/hj_reachability |
| JSBSim | https://github.com/JSBSim-Team/jsbsim |
| Z3 SMT | https://github.com/Z3Prover/z3 |
| Shaw 1985 (BFM 정전) | — (책: *Fighter Combat: Tactics and Maneuvering*) |
| Isaacs 1965 (Differential Games) | — (책: *Differential Games*) |

---

## §B. 검증된 사실 레지스트리 (Ground Truth)

> 측정값은 *언제 어떻게 측정했는지* + 의의를 짧게.
> 수학 결과는 lemma/proof 위치.

### B.1 측정값 (별도 프로세스 ≥3, FP-robust)

| 항목 | 값 | 측정일 | 출처 |
|---|---|---|---|
| vs simple | 6W/0L/0D (결정적, 100/89~96) | 2026-05-14 | HANDOVER 2026-05-15 §1 |
| vs defensive | 2W/0L/4D (무패, 4무는 FP-basin) | 2026-05-14 | HANDOVER 2026-05-15 §1 |
| vs aggressive | 0W/0L/6D (무패, dist 못 닫음) | 2026-05-14 | HANDOVER 2026-05-15 §1 |
| aggressive `ata<12` 비율 | 22% | 2026-05-14 | HANDOVER 2026-05-15 §1 |
| aggressive `dist<3000` 비율 | 0% | 2026-05-14 | HANDOVER 2026-05-15 §1 |
| G1_a~G1_e (analytic vs FD ≤1%) | ALL PASS | 매 commit | `python -m tools.basis.gradient_approximators` |
| HJI canonical V*(x₀) | +2374ft (escape zone) | RT-2 | PLAN §2.5.9 |

### B.2 수학적 결과 (lemma/proof)

| 명제 | 위치 | 도구 | 상태 |
|---|---|---|---|
| **H1: V_dist ω+a 채널 항등 0** — `(B_dᵀ ∇V_dist)_ω ≡ 0 ∧ ()_a ≡ 0 ∀x`; γ̇ 만 nonzero (Δh 경유) | [SUPERPLAN_v2 §2 H1](../examples/pursuit_chase_v1/SUPERPLAN_v2.md), [verify_h1_omega_zero.py](../tools/basis/verify_h1_omega_zero.py) | Z3 NRA (4.16.0) | **PROVED 2026-05-15** |
| RT-3 Item 1: τ-cover Σρ_m≥1>ε on continuous domain | [verify_smt_cover.py](../tools/basis/verify_smt_cover.py) | Z3 4.16.0, LRA-complete | **PROVED** |
| RT-3 Item 2: 12⁶ LUT 의 ∇V 와 closed-form ∇V 무상관 | [verify_grad_lut_xcheck.py](../tools/basis/verify_grad_lut_xcheck.py) | cosine sim | confirmed cos≈0 |
| dx-sign convention (RT-1.3) | [memory: rt1-3-hdg-sign-convention](../C--Users-USER-Desktop-AI-pilot-ai-combat-sdk/memory/rt1-3-hdg-sign-convention.md) | 실측 stub agent | confirmed (test_hdg/) |

### B.3 기각된 시도 (반복 금지)

[SUPERPLAN_v2 §4 안티-카탈로그](../examples/pursuit_chase_v1/SUPERPLAN_v2.md) 참조.
12+ 시도 (TurnAround A0/2/3/4, ZoomClimb 단독, EnergyRecovery 게이트 3종, LDT speed-lag 단순추가, accel-cap, DiveAttack, V_aa B1~B5). 모두 W1 (임계값 fine-tuning) 위반.

---

## §C. Reachability Graph (목표·블로커·전선)

**목표 노드 (`Goal`)**: PLAN §8 — simple/defensive/aggressive **모두 100% WIN, FP-robust**.

```
Goal: simple=100% ∧ defensive=100% ∧ aggressive=100%
                                 ▲
                                 │ (Phase 3 redesign → R5 회귀)
                                 │
                    ┌────────────┴────────────┐
                    │ R3: 재설계 후보 검증     │ ← 현재 우리가 여기로 가야 함
                    │   (i) V_dist log²        │
                    │   (ii) V_T = T_cap²/2    │  ← 유력 후보
                    │   (iii) closure-aligned  │
                    └────────────▲────────────┘
                                 │ (G1 + Z3 + 수리적 정당화)
                                 │
                    ┌────────────┴────────────┐
                    │ R2: H1 Z3 형식증명       │ ✓ DONE 2026-05-15
                    │   - L1 ω-ch ≡ 0 PROVED  │
                    │   - L2 a-ch ≡ 0 PROVED  │
                    │   - L3 γ̇-ch ≠ 0 (Δh)    │
                    └────────────▲────────────┘
                                 │ (data + lemma)
                                 │
                    ┌────────────┴────────────┐
                    │ R1: H1 lemma 도출       │ ✓ DONE
                    │   ((B_dᵀ∇V_dist)_ω ≡ 0)  │
                    └─────────────────────────┘
```

### 현재 활성 전선 (active frontier)
- **R3** 진입. SUPERPLAN_v2 §3 Phase 2 — V_dist 의 ω-channel-bearing 재유도.

### 도달 가능 노드 (reachable)
- R2 (H1 Z3 형식검증) — 10~30분 코드 + Z3 LRA 결정가능.
- R3 후보 (i)(ii)(iii) — 각 후보 derivation 30분~1시간. G1 자동.

### 차단 노드 (blocked, 우회 필요)
- HJI LUT 의 ∇V 정확도 — 12⁶ grid 코사인 0 (B.2 RT-3 Item 2). LUT 재솔브는 grid↑ 비용 큼. 차단 회피책: closed-form ∇V_i 만 사용 (현 방침).
- aggressive 적 BT 의 *정확한* 결정함수 — `examples/pursuit_chase_v1/agents/aggressive.yaml` 의 BT 노드 정적 파싱 필요. 부분 정보만 있음 (EmergencyClimb / CloseEngagement(≤6562) / MediumApproach(≤16404 Pursue+Accel) / Pursue).

---

## §D. Deadlock Indicators (정체 탐지)

다음 *증상* 중 하나라도 발견되면 **즉시 정지하고 W1/W2/W3 위반 여부 점검**:

| Indicator | 위반 후보 | 대응 |
|---|---|---|
| 같은 파라미터의 5+ 변형 sweep (sigmoid c, w, 임계값 N) | W1 (수치 fine-tuning) | 함수 *형태* 재유도로 전환 |
| "지금까지 한 것 다 회귀시키지 않는 변경" 을 찾는 grid search | W1 | 가설→측정→trace 로 전환 |
| 새 if-else 분기 추가가 솔루션의 후보로 떠오름 | W1, R1 위반 | τ 연속 가중으로 표현 |
| obs 외 새 추정값/분류 라벨 도입 | W2 (추정기) | obs 시간차분 직접 사용 |
| "이론적으로 불가능"·"단일-tick 으론 안 됨" 류 결론 | W3 (이론 천장) | 가정 5점검 (ω 상수, 적 최적성, 2D, 닫힌 궤도, 정적 정책) |
| 같은 verdict 가 3 세션 누적 (해결 미진전) | 진단의 입자도 부족 | sub-hypothesis 로 분해 |
| 코드 변경량 ↑ 인데 G1/회귀 통과 못 함 | 가설 mis-trace | Phase 1 으로 백 |

---

## §E. 미해결 질문 / 보류 항목

| 질문 | 등급 | 보류 사유 |
|---|---|---|
| H2 (V_target sprint 부호함정) 와 H3 (dispatcher routing) 가 H1 *추가* 원인인가 | M | Phase 1 측정으로 갈라야 함 |
| 후보 (ii) V_T = T_cap²/2 의 G1 성립 여부 | H | Phase 2 derivation 진입시 즉시 점검 |
| Stage 4 (vs ace) 아키타입 매핑 | L | Stage 3 완료 후로 미룸 |
| Model B (HP 누적, running cost) 이관 시점 | L | Stage 5+ |
| `models/intent_model.pt` 의 (수정)/(.lock 삭제) 상태 어떻게 할지 | L | 현 작업과 무관, 별도 결정 |

---

## §F. 갱신 로그 (changelog of compass itself)

- **2026-05-15 (1)** — 초기 작성. §A·§B·§C·§D·§E 채움.
- **2026-05-15 (2)** — H1 lemma Z3 PROVED (L1 ω≡0, L2 a≡0, L3 γ̇≠0). R2 노드 닫힘. R3 진입.
- **2026-05-15 (3)** — R3 4 사이클 (iv/C/C'/C''/D1+D2) 모두 실험적 무진전 또는 회귀.
  - **새 frontier 한계 식별 (§G 참조)**: closed-form ∇V_i 의 magnitude scale 임의성.
  - V_T 의 두 형태 (1/(c²+C²), exp(-c/V_REF)) 모두 G1·Z3 통과, 그러나 R5 에서 V_ATA 와 magnitude calibration 불일치 → simple 회귀 또는 무진전.
  - 진단 evidence: aggressive 매치 67% TheoremAdaptive default (branch routing 한계, H3 확정).
  - 보존: grad_V_Tcap 단독 (G1 PASS) + m_T mode in optimal_control + OffensivePursuit τ_T=0.4 — simple 보존 (slight HP variance), defensive/aggressive 무진전.

## §G. Frontier 한계 — 다음 세션이 직시할 것

본 세션의 4 cycle 가 모두 한 지점에 막혔다: **closed-form V_i 의 magnitude scale 이 진짜 게임 이론적 V*(x) 와 calibrate 불가능**. 구체적으로:

- V_ATA 는 rad² 단위 (~1 scale at ATA=1).
- V_dist 는 (1/L²)·L² = dimensionless (~0.5 scale at canonical).
- V_T (exp form, 본 세션 추가) 는 dimensionless 이나 d_REF·V_REF 의 *임의 선택* 에 따라 scale 1~1000 변화.
- 추가 V_i 항이 V_ATA 와 *같은 order of magnitude* 가 아니면 ω 명령을 단독으로 좌우 → simple equilibrium 깨짐.

수학적 정당화 가능한 magnitude 통일 = **HJI V*(x)** 의 ∇V*. 그러나:
- 12⁶ grid LUT (`logs/hji/V6d_wez_v3.npz`) 의 ∇V central-diff cos≈0 with closed-form (RT-3 verify_grad_lut_xcheck.py) — *unusable*.
- 16⁶ 또는 20⁶ grid 재솔브 가능 (JAX CPU, hours scale).

다음 세션 가능한 path:
1. **LUT grid 확장** (12⁶ → 16⁶) — `tools/basis/hji_solve_v3.py` 의 grid arg 변경. ∇V 정확도 회복 시도. cost: 수 시간.
2. **Neural ∇V approximator** — LUT 위에 NN fit, smooth ∇V 얻음. cost: 더 큼.
3. **현실주의** — simple 100% 보존만 유지하고 defensive/aggressive 의 100% 는 PLAN §8 미달 인정. Model A → Model B (HP 누적, running cost) 로 조기 이관.
4. **본 세션 evidence 위에서 magnitude scaling 정통 정당화 탐색** — 예: PMP 의 costate normalization, ZEM 의 t_go scaling.

**이전 세션 권고 (EIM 추정기) 는 여전히 기각** — 03_recent §6 위반.
