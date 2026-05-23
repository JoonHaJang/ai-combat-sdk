# Phase 2 PR — τ_T(x) blend in Theorem branch (derivation)

> SUPERPLAN_v2 §3 Phase 2 Case H1 (rev. 2026-05-15+M1.3-verdict).
> M1.3 verdict: H1 (V_dist ω-zero) CONFIRMED 지배적. ∇V_pn 의 거의 전부 LOS-radial.
> 본 PR 은 *V_dist 의 함수 형태 재설계* 대신 *m_T (V_T capture-time) routing 재유도*
> — 동일 효과 (ω 채널 dist-닫기 신호 회복) 를 *기존 ∇V 자산 위에서* 달성.

## 1. 진단 요약 (Phase 1 M1.3)

| 적 | long-range (>8000ft) frac | median \|gPN_dist\|/\|gPN_head\| in LR | 결과 |
|---|---|---|---|
| simple | 12.7% | 1,599 | 6W/0L (mostly medium/short range) |
| defensive | 67.0% | 1,120,576 | 3W/0L/3D (LR dominant but partial closing) |
| aggressive | **97.6%** | **441,162** | **0W/0L/6D** (LR-locked, can't close) |

`grad_V_Tcap` (V_T) 의 *형태* 는 비-radial (closure-via-ATA): CSV 실측에서
`gT_dist ≈ gT_head` (e.g., tick 0: 1.55e-3 vs 1.66e-3) — 즉 ω 채널 transmission 비영.
**문제는 routing**: aggressive long-range Theorem(66.9%) 에서 τ_T = 0.

## 2. 유도 — PMP costate-regime split

Hamilton-Jacobi-Isaacs 의 connect 의 *PMP form*:
  H(x, λ, u, v) = λᵀ·f(x, u, v) + L(x)

표준 ZEM (Zero-Effort-Miss) 분해 (Bryson-Ho §5.3 / Shneydor PN ch.3):
- *Terminal-near* (dist ≈ d_WEZ, t_go → 0): λ_dist · (∂dist/∂t) = λ_dist · (−closure) 가 작은 잔차.
  *Transversality* λ_dist(t_f) = ∂J_T/∂dist 가 dominant → ATA-aim 항 (V_PN 의 LOS-tangential 가중) 이
  costate 를 좌우.
- *Terminal-far* (dist ≫ d_WEZ, t_go large): closure 자체가 capture-time 의 1차 결정요소.
  Hamiltonian 에서 −λ_dist · closure 가 dominant → V_T 형 capture-time 항이 costate 를 좌우.

이 *regime split* 는 fine-tune 임계값이 아니라 *PMP 의 costate dominance 구조* 에서 유도됨.

## 3. d_HANDOFF 의 *구조적* 선정

현 codebase 의 V_PN 정의 ([`gradient_approximators.py:122-129`](../../tools/basis/gradient_approximators.py#L122-L129)):
```python
sprint_frac = clip((dist - WEZ_OUTER_FT) / SPRINT_DIST_SCALE)
V_target = V_e + (V_SPRINT_KTS - V_e) * sprint_frac
```

- `WEZ_OUTER_FT = 3000`, `SPRINT_DIST_SCALE = 5000`.
- `dist = WEZ_OUTER + SPRINT_DIST_SCALE = 8000 ft` 에서 sprint_frac → 1.0 (포화).
- 포화 이후: V_target = V_SPRINT = 420 kts 상수.
- Stage-1 의 V_e clamp [160, 480] + V_p ≈ V_SPRINT 수렴 → `V_p - V_target ≈ 0`.
- 그 결과 V_PN 의 `∂V/∂V_p` 신호 (a-channel) ≡ 0.
- 동시에 long-range 에서 ATA ≈ 작음 (적이 멀리, 거의 정면) → `∂V/∂ATA` ≈ 0 → ω-channel ATA 신호도 약함.
- → **V_PN 의 정보적 자산이 dist = 8000 ft 너머에서 *구조적으로* 고갈됨**.

이 *고갈 경계* 가 PMP regime split 의 자연 위치. d_HANDOFF = 8000 ft 는 fine-tune 이 아니라
*기존 V_PN sprint 포화점*. R1 (수치 fine-tuning 금지) 충족.

Δ_HANDOFF (smooth transition 폭): WEZ_HALF_WIDTH ≈ 1250 ft = `SPRINT_DIST_SCALE / 4`.
WEZ 의 자연 scale, 역시 *구조적*.

## 4. τ_T(x) 함수 형태

```
τ_T(x) = σ((dist(x) - d_HANDOFF) / Δ_HANDOFF)
       = 1 / (1 + exp(−(dist − 8000) / 1250))
```

값 분포 (예측):
- dist = 3000 ft (WEZ 근처): σ(−4) ≈ 0.018 — τ_T 거의 0, V_PN 지배
- dist = 8000 ft (regime split): σ(0) = 0.5 — 50/50 blend
- dist = 12000 ft (aggressive 상한): σ(3.2) ≈ 0.96 — τ_T 지배, V_T 가 routing 점령

이는 PLAN §2.6.5 의 softmin τ-blend 형식과 정합 (PLAN 의 "임계 0/1 hardening 없음" 요건).

## 5. R1~R9 정합 점검

| 규칙 | 본 PR 의 충족 |
|---|---|
| R1 (fine-tuning 금지) | d_HANDOFF / Δ_HANDOFF 둘 다 기존 V_PN sprint 정의에서 유도 |
| R2 (추정기 금지) | dist 는 obs 직접 함수 (`x[0:3]` norm) |
| R3 (G1 통과) | τ_T 는 routing only — ∇V_Tcap 자체 미변경. G1 자동 보존 |
| R4 (Z3 정당화) | σ 의 monotone 속성으로 `dist→∞ ⇒ τ_T→1` 형식 검증 가능 (`verify_aa_gate.py` 패턴) |
| R5 (누적 회귀 검증) | simple/defensive/aggressive 각 ≥5, **R7 hard-gate** 적용 |
| R6 (5가정 점검) | 본 변경은 "이론적 천장" 결론에 의존하지 않음 — H1 (lemma) 의 *경험적 우회* |
| R7 (회귀 hard-gate) | simple WIN ≥ baseline (= 12W/0L) 강제 |
| R8 (1-변경 원자성) | 단일 분기 (Theorem) 의 단일 routing 변경 |
| R9 (스냅샷) | 변경 전 working tree = stage2_best + M1.1. 변경 후 R5 통과 시 새 snapshot 으로 보존 |

## 6. 예측

- aggressive: long-range tick (97.6%) 에서 τ_T ≈ 0.83~0.96 → V_T 신호가 ω-channel 로 전송됨.
  → ata<12 22% / dist<3000 0% 의 정렬-고정 → dist 닫기 가능. 기대: dist<3000 frac > 0.
- simple: long-range tick (12.7%) 에서만 τ_T 활성. 그 외 88% tick 은 τ_T < 0.1. 기존 PN blend 보존.
- defensive: long-range 67% → 일부 활성. defensive 가 *도주 자세* 일 때 V_T closure-항이 추격 강화.

## 7. 측정 계획 (Phase 2 PR R5)

별 프로세스 5회 × 3 적 → `logs/phase2_tau_T_routing/{simple,defensive,aggressive}_n{1..5}/`.
R7 invariant: **simple WIN ≥ 12/12 baseline 의 5/5 동등 수준 보존**.
실패 시 즉시 git revert (R7).

---

## 8. **FAILURE ADDENDUM** (2026-05-16, R7 위반)

R5 결과:

| 적 | Baseline | Phase 2 PR | Δ |
|---|---|---|---|
| simple | 12W/0L | **0W/5L** | **catastrophic 회귀** |
| defensive | 3W/0L/3D | 0W/0L/5D | 회귀 (승 → 무) |
| aggressive | 0W/0L/6D | 0W/0L/5D | 변화 없음 |

→ **R7 hard-gate 위반** → 즉시 revert (continuous_policy.py 의 변경분만 원복, M1.1 CSV
   컬럼·grad info 보존).

### 8.1 실패 원인 재진단

본 PR 의 §6 예측 ("simple 의 long-range tick 12.7% 에서만 τ_T 활성, 88% 보존") 이 *틀림*:

1. **tau_total 정규화의 효과**: `grad_approx = (τ_pn·g_pn + … + τ_T·g_T_unit) / tau_total`.
   τ_T 가 σ(-4)≈0.018 처럼 작아도, tau_total 에 추가되어 *비율* 차원에서는 τ_yoyo=0.29·simple
   Theorem 의 기여를 ~6% 감소 (0.29/(1.30) ≈ 0.223). 작아 보이지만 simple equilibrium 의
   load-bearing 항인 yoyo (climbing/diving 패턴) 의 균형이 *6% 감소*만으로도 깨짐.
2. **dist-only gate 의 정밀도 한계**: simple Theorem (19.6%) 의 dist 분포가 *long-range 까지
   확장됨* (mid-fight 에 dist 5000~10000 ft 통과). 거기서 τ_T = σ(-2.4) ≈ 0.08 ~ σ(0) = 0.5.
   8~50% 의 τ_T 가 simple 의 Theorem 의 PN-yoyo blend 를 흐트러뜨림.
3. **simple Theorem 의 load-bearing 특성**: M1.3 evidence 의 H3 PARTIAL 가 *역방향* 으로 작용.
   simple 의 Theorem 에서 ρ_pn=0.61, ρ_yoyo=0.29 — 이 정확한 비율이 simple 6W/0L 의 PE 관리 패턴
   을 만들어내는 *튜닝되지 않은 평형점*. 모든 외부 routing 신호가 이 평형을 깬다.

### 8.2 학습 — 다음 PR 의 제약조건

본 실패는 *어떤* dist-regime 기반 단순 routing 도 simple equilibrium 을 깰 수 있음을 시사.
다음 PR 의 후보:

- **(C1) τ_T blend isolation via 새 분기** — `LongRangeClosing` 분기 신설, entry =
  `ata < 20° ∧ dist > 8000`. *Theorem 안에서* τ_T 안 들어가게 분리. simple 의 Theorem 평형
  보존, aggressive 의 long-range tick 만 새 분기로 흐름. (단, 새 if-else 분기는 v2 §4 안티 —
  "분기는 *생성* 이 아니라 τ-blend 의 quantization" 에 저촉 가능. 정확히는 *PMP regime split*
  의 quantized 표현으로 정당화 시도 가능.)
- **(C2) Theorem 의 normalization 변경** — `grad_approx` 의 tau_total 정규화에서 yoyo·corner·ldt
  의 *최소 기여 floor* 도입. τ_T 가 추가돼도 simple-load-bearing 항 비율 보존.
- **(C3) aggressive-specific 진단 심화** — aggressive 의 적 BT 가 *왜* dist<8000ft 으로 못 들어가게
  방어하는지 정밀 분석. 아예 *우리가 거리를 닫지 못함* 이 아니라 *적이 거리를 유지함*. PMP/ZEM
  game-theoretic Nash 후보 우리쪽 일방적 routing 으로 못 풀 가능성. (PROJECT_COMPASS §G 의 P4
  Model B 이관 정당화 강화.)

### 8.3 SUPERPLAN_v2 §4 안티-카탈로그 추가 권고

> **(rev. (4)+M1.3 실험)** Theorem 분기에 *전역* τ_T blend 추가 (어떤 형태든) — simple Theorem
> (19.6%) 의 ρ_yoyo 평형 깨짐. 사유: simple equilibrium 의 load-bearing 항 비율 매우 민감.
> 우회: 격리된 sub-branch 또는 normalization 변경.

본 addendum 은 *역시 가치 있는 음의 결과*: H1 우회 routing 은 simple equilibrium
의 *load-bearing fragility* 라는 새로운 제약에 부딪힌다. 다음 사이클의 제약 조건이 명확해짐.
