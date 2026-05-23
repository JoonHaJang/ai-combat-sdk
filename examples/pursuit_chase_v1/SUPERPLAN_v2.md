# SUPERPLAN v2 — Diagnosis-First Curriculum (rev. 2026-05-15 +simple-regression)

> **작성**: 2026-05-15 (1) — diagnosis-first 채택.
> **개정**: 2026-05-15 (2) — H1 lemma Z3 PROVED.
> **개정**: 2026-05-15 (3) — R3 4 cycle 모두 무진전; magnitude scale frontier 식별 (§8).
> **개정**: 2026-05-15 (4) — **R3 cycle 변경의 누적이 simple 100% WIN 까지 회귀시켰음을 사용자 확인.**
>   → §1 에 R7 (회귀 hard-gate) 신설, §3 에 Phase -1 (Baseline 복원 + bisect) 신설, §6 즉시 액션 전면 재배열.
>
> 본 문서는 `SUPERPLAN_CUMULATIVE_CURRICULUM.md` (v1) 를 *대체* 한다.
> v1 의 Stage 1 성과(simple 10W/0L/0D)는 유효; v1 의 결론("단일-tick 천장")과 권고("EIM 추정기 도입")는 본 v2 가 *원칙 위반*으로 판정·기각한다.
>
> **방법론 (사용자 강제)**:
> 모델 오류 → **실험 데이터** → 어디서 misperception 발생 → 우리 모델의 어느 부위가 그것을 담당하나 → **그 부위가 왜 그 결과를 내는지 수리적 분석** → 재설계 → 수리적 정당화(이게 맞다) → 실험 → 반복.
> **금지**: 모델 오류 → "수치가 문제" → 수치 변경 → 실험.
>
> **본 rev. 핵심 한 줄**: 우리는 더 새로운 V_i 항을 *추가하기 전에*, **이미 가진 simple 6W/0L 베이스라인을 회복**하고, 그 위에서만 *한 번에 하나씩* 회귀 차단 게이트(R7)로 보호된 변경을 한다. magnitude scale 천장(§8)은 회귀 복구 후 정통 PMP/ZEM 또는 LUT-16⁶ 재솔브로 우회한다.

---

## §0. 이전 세션 정체의 *원인* 진단 — 방법론 위반 3건

`docs/PROJECT_OVERVIEW/03_recent_analysis.md` §8 은 본 프로젝트의 originating principles 를 명시한다 (사용자 본인 작성):

> 교훈 1 — 수학 정리는 if-else 로 박지 말고 0~1 연속 가중치로 표현하라.
> 교훈 2 — 추정기 없이 관측값 직접 사용. obs 에 이미 결과가 찍혀 있다.
> 교훈 4 — "수학 이론적으로 못 이긴다" 결론은 가정 5개 (ω 상수, 적 최적성, 2D, 닫힌 궤도, 정적 정책) 를 점검해야 함.

전(2026-05-14) 세션의 결과·권고는 이 셋과 직접 충돌한다.

| 위반 | 증거 (v1 / HANDOVER 2026-05-15) | 결과 |
|---|---|---|
| **W1. if-else 임계값 fine-tuning** (교훈 1 위반) | Stage 2 의 12+ 시도 전부 임계값 추가/변경: TurnAround A0/A2/A3/A4 (`AA>90`, `AA<90`, `dist>5000`), EnergyRecovery 게이트 (`ata<60`, `ata<90`, `ata>90∧closure<0`), V_aa B1~B5 (sigmoid `c=4000/2500`, `w=1500/500`). | "수치 바꿔 실험"의 12회 반복. simple-회귀 cumulative basin 천장. |
| **W2. 추정기 도입 권고** (교훈 2 위반) | HANDOVER §5.1 "(가) 다-tick EIM: 적 의도 `CLOSING/EXTENDING/EVADING/GUN_RUN` 분류기". 이는 03_recent §6 이 명시 폐기한 *상태 추론기*. | "추정기는 추정 오차 + 모델 가정 의존을 도입한다" 가 위반. 차세션도 동일 함정 예약. |
| **W3. "이론적 천장" 결론** (교훈 4 위반) | HANDOVER §3: "*단일-tick obs 로 적 의도 분리 불가능*". 5가정 점검 없이 *증상*을 *원인*으로 오인. | 진짜 책임 부위(V 함수 형태, dispatcher routing) 가 trace 되지 않은 채 결론 봉인. |
| **W4. 회귀 격리 게이트 부재** (rev. 2026-05-15 (4) 추가) | R3 4 cycle 동안 V_T 두 형태·(iv) AA-gate·C/C'/C'' magnitude blend 가 *누적적으로* working tree 에 적층 (138-line diff vs HEAD in `gradient_approximators.py`). 각 cycle 마다 R5(simple/defensive/aggressive 각 ≥5) 회귀검증을 *해당 cycle 종료 시점에* 일관되게 강제하지 않음. | **simple 6W/0L → 회귀** (사용자 확인). 어떤 cycle 의 어떤 hunk 가 원인인지 trace 안 됨. |

사용자가 본 세션에서 금지한 anti-pattern("모델→수치문제→수치변경→실험")은 W1·W2·W3 의 합성형이다. **본 SUPERPLAN_v2 의 출발점은 위 진단의 명시화이다.**

W4 는 rev. (4) 에서 추가된 *방법론적 메타-결함*: 진단/재유도/Z3 가 옳아도, 회귀 격리가 부재하면 누적 변경이 베이스라인을 무너뜨린다. §1 R7·R8 (rev. (4) 신설) 가 직접 응답.

---

## §1. 변경 불가 Ground Rules

| 원칙 | 강제 메커니즘 |
|---|---|
| **R1. 수치 fine-tuning 금지** | 모든 변경은 (a) ∇V_i 의 함수 형태, (b) τ_i(obs) 매핑, (c) dispatcher routing 의 *유도* 변경. 단순 임계값 추가/스윕 PR 는 reject. |
| **R2. 추정기 금지** | τ_i, ∇V_i 는 6D state x 및 obs(시간차분 포함)의 직접 함수. 분류기·hidden state·intent label 도입 금지. |
| **R3. G1 항상 통과** | 모든 ∇V 변경 → `python -m tools.basis.gradient_approximators` G1_a~G1_e ≤1% rel err. |
| **R4. Z3 정당화 (가능 시)** | sign/monotone/boundary 속성은 `tools/basis/verify_smt_*.py` 패턴으로 형식화. LRA 환원 가능한 fragment 는 SMT-complete proof. |
| **R5. 누적 회귀 검증** | 매 변경: simple, defensive, aggressive 각 ≥5 *별도 프로세스* (FP 결정성 회피). |
| **R6. 5가정 점검 (교훈 4)** | "이론적으로 불가능" 결론 금지. 가정 (ω 상수, 적 최적성, 2D, 닫힌 궤도, 정적 정책) 명시적 반박이 선행. |
| **R7. 회귀 hard-gate (rev. (4) 신설)** | R5 결과에서 *이전 stage 의 어떤 cell 이라도 WIN 비율이 하락*하면 (예: simple 6W/0L → 5W/1L 도 위반) **변경은 즉시 git revert / stash drop**. 예외 없음. "다른 stage 가 개선되니까" 도 위반. *최소 보존 invariant*: simple WIN ≥ 직전 baseline의 WIN 수. |
| **R8. 1-변경 원자성 (rev. (4) 신설)** | 한 working tree 에 동시 진행되는 ∇V_i/τ_i/dispatcher 변경은 *최대 1개*. R3 cycle 4 처럼 V_T·V_aa·magnitude blend 누적 후 한꺼번에 검증 금지. 각 변경은 commit 또는 stash 로 격리된 후 R5 통과 시에만 다음 변경 시작. **`git stash list` 가 SUPERPLAN 시퀀스의 ledger 역할**. |
| **R9. Baseline snapshot 의무 (rev. (4) 신설)** | 새 stage 진입 직전의 last-WIN 베이스라인은 `logs/snapshots/{stage}_best/` 에 *코드 + ∇V 함수 + 검증 결과 CSV* 트라이얼 동시 보존. R7 위반 시 즉시 복원 출발점. 현 시점 사용 가능 스냅샷: `optA`, `pre_dive`, `stage2_best` (←simple 6W/0L 시점). |

---

## §2. 1차 수리적 진단 (가설 3종)

**관측된 misperception** (HANDOVER §1, aggressive 6 매치):
- `ata<12` 비율: 22% (헤딩 정렬은 자주 달성)
- `dist<3000` 비율: 0% (사거리 진입 전무)
- **요약**: 각도는 잡히는데 거리는 한 번도 안 닫힘.

**코드 대조** ([`tools/basis/gradient_approximators.py:71-187`](../../tools/basis/gradient_approximators.py#L71-L187)):
```
V_PN = ½·ATA² + ½·ATA_vert² + ½·λ_d·(dist - d_WEZ*)² + ½·λ_V·(V_p - V_target)²
λ_d  = 1 / WEZ_HALF_WIDTH² = 1 / 1250² ≈ 6.4e-7
V_target = V_e + (V_SPRINT - V_e) · clip((dist - 3000) / 5000)
```

**3개 책임 부위 후보 가설**. 모두 임계값이 아니라 *함수 형태* 의 결함을 가리킨다:

### H1 — V_dist 의 ω 채널 transmission 이 영구히 0 (수학적으로 도출됨)

**Lemma (V_dist ω-zero)** — V_dist = ½·λ_d·(dist−d_WEZ*)² 의 ω 채널 신호 `(B_dᵀ ∇V_dist)_ω` 는 *모든 상태 x* 에 대해 정확히 0:

  ∇₍Δx,Δy,Δh₎ V_dist = λ_d·(dist−d_WEZ*) · (Δx, Δy, Δh) / dist        (LOS-radial)
  B_d 의 ω 행 = [Δy, −Δx, 0, −1, 0, 0]ᵀ                                (LOS-tangential)
  (B_dᵀ ∇V_dist)_ω = Δy·λ_d·dist_err·(Δx/dist) − Δx·λ_d·dist_err·(Δy/dist) ≡ 0

증명: 두 벡터의 외적 0 (radial ⊥ tangential). LRA-환원 가능 → Z3 SMT 로 형식 검증 가능
(R4 항목).

**함의** — V_dist 가 "거리 좁혀라" 신호를 ω 채널로 *전혀* 보내지 못한다. dist-닫기 명령은
오로지 a 채널의 V_target(d) sprint coupling 으로만 전달되며, 그 통로는
WEZ_OUTER(3000) ~ WEZ_OUTER+SPRINT_DIST_SCALE(8000) ft 사이에서만 nonzero
([`gradient_approximators.py:122-129`](../../tools/basis/gradient_approximators.py#L122-L129)).
dist > 8000 영역 (aggressive 의 BT 가 적을 유지하는 6562~16404 ft 범위 상한쪽) 에서는
V_target = V_sprint = 420 상수 → V_p≈420 (Stage 1/2 유지) → V_err≈0 → a 채널도 무신호.
ATA→0 영역에서는 V_ATA gradient → 0 → ω 채널도 무신호. 종합 u ≈ 0 — **정렬 유지·평행
비행 equilibrium**, 측정 signature (ata<12 22%, dist<3000 0%) 와 *수학적으로 정합*.

- 보조 magnitude 논거: V_dist 의 정규화 폭(1250ft) 도 WEZ 너비에 맞춰져 있어 dist→large
  영역에서 quadratic 이 saturating. 그러나 *근본 결함은 magnitude 가 아닌 방향(=ω-zero)*.
- Phase 1 시그니처: aggressive 매치에서 dist>8000 인 틱의 `|B_dᵀ∇V_pn|_ω` 과 `|B_dᵀ∇V_pn|_a`
  분포가 두 채널 모두 0 근방에 집중되면 H1 확정.

### H2 — V_target 의 sprint_frac 부호 함정 (자발적 감속 명령)

- 메커니즘: 근거리 (sprint_frac=0) 에서 `V_target = V_e`. 만약 V_p > V_e 면 `V_err > 0` → `∂V/∂V_p = λ_V·V_err > 0` → BtG_a > 0 → **u_a* < 0** (감속).
- aggressive 적은 BT 가 Pursue+Accel (`MediumApproach ≤16404ft Pursue+Accel`) → 우리 향해 closing → closure < 0 → `V_e_est = V_p - closure` 폭주 → clamp [160, 480] 발동. clamp 후 V_e_est 가 *실제 적 속도와 다른 값* (대개 작은 값) 으로 박힘 → V_p > V_e_clamped → 자발 감속.
- Phase 1 시그니처: aggressive 매치에서 `u_star[a] < 0` 비율 ≫ simple 매치. 그리고 그 순간 `V_e_clamp_active = True`.

### H3 — Dispatcher routing 의 ∂V/∂dist=0 분기 우세

- 메커니즘: [`branch_dispatcher.py`](nodes/branch_dispatcher.py) 의 9-way if-else 가 aggressive 상황에서 `TheoremAdaptive` (default) 로 떨어지고 τ_corner 우세 부여 시, `grad_V_corner` 는 `grad[4]=V_p-V_c` 만 (∂V/∂dist=0). 거리 닫는 신호 자체가 없음.
- Phase 1 시그니처: 분기 점유율 중 `TheoremAdaptive` ≥ 50%, 그 안에서 τ_corner > τ_pn.

### 공통 함의
세 가설 모두 **임계값 fine-tuning 으로 풀리지 않는다.** 각각 (a) V_dist 의 함수 형태 재유도, (b) V_target 의 정의 재유도, (c) dispatcher 의 if-else 를 τ-blend 로 *형식화* — 03_recent 교훈 1 의 본래 요구. Phase 1 측정이 어느 후보(혹은 조합) 인지 갈라낸다.

---

## §3. Work Plan — Phase -1 ~ 5

### Phase -1. Baseline 복원 + 회귀 bisect (rev. (4))

> **2026-05-16 측정 결과: 회귀 미재현, Phase -1 자동 종료.**
> - simple n=12: **12W/0L/0D** (직전 baseline 6W/0L/0D 대비 안정·우월)
> - defensive n=6: **3W/0L/3D** (직전 2W/0L/4D 대비 약간 개선)
> - aggressive n=6: **0W/0L/6D** (동일, 무패 무진전 — 핵심 과제 유지)
> - 산출: `logs/regression/{simple,defensive,aggressive}_currentHEAD.csv`
> - 결론: 사용자 인식의 "simple 회귀" 는 현 working tree 에서 미재현. P-1.2/P-1.3/P-1.4 bisect 불필요. 다음: Phase 0 커밋 후 Phase 1 진단.

R7/R8/R9 가 직접 강제. Phase 0 보다 *앞서* 실행. 목적: simple 6W/0L 회복 + 회귀 hunk trace.

| Step | 행위 | 산출물 |
|---|---|---|
| **P-1.1** | 현 working tree 로 simple ×6 별프로세스 측정 → 회귀 정량화 | `logs/regression/simple_currentHEAD.csv` |
| **P-1.2** | `logs/snapshots/stage2_best/` 의 코드자산을 별도 worktree 로 복원 후 simple ×6 재측정. 6/6 확인 시 bisect 의 known-good 으로 채택. | bisect upper 확정 |
| **P-1.3** | working tree 138-line diff 를 5 그룹(G_T1 V_Tcap, G_T2 V_T weight, G_AA, G_CC magnitude blend, G_BR dispatcher) 으로 분해, 각 그룹 단독 적용 시 simple ×5 측정 | `docs/diag/regression_bisect_2026-05-15.md` |
| **P-1.4** | 비회귀 그룹만 채택, 회귀 그룹은 stash 보존 후 R5 (3 적 ≥5) 검증 | 회복된 working tree |

**종료 invariant**: simple ≥ 6W/0L 회복 + 회귀 원인 hunk 기록 (Phase 2 재유도 입력).

---

### Phase 0. Baseline 고정 (커밋)

미커밋 23 항목을 의미단위 커밋:
1. `fix(pursuit_chase): dx-sign in obs_to_state (RT-1.3)` — `continuous_policy.py`, `custom_actions.py`
2. `feat(grad_V): 3D ATA + V_e-matching speed term in grad_V_PN` — `gradient_approximators.py`
3. `feat(grad_V): grad_V_1circle (RT-2) + σ_1c/σ_2c regime blend in optimal_control`
4. `feat(grad_V): Stage-2 dist-dep V_target + V_e clamp` — `gradient_approximators.py`
5. `feat(branch): EnergyRecovery hysteresis + DefensiveBreak predictive + OrbitBreak + LagPursuit + ZoomClimb (v11 이식, ∇V-derived per PLAN §2.6.5)` — `branch_dispatcher.py`
6. `feat(tools): verify_smt_cover + verify_grad_lut_xcheck (RT-3)`
7. `chore(test_hdg): hdg-sign stub agents (RT-1.3 evidence)`
8. `docs: SUPERPLAN v2 + HANDOVER 2026-05-15`

*git push 는 사용자 명시 신호 시까지 보류.*

### Phase 1. 진단 측정 (no policy change)

**M1.1** — `optimal_control` info dict 에서 직접 산출, CSV 컬럼 추가:
- `gPN_dist_proj` = ∇V_pn · r̂ (단위벡터 r̂ = (dx,dy,dh)/dist), `gPN_head_proj` = ‖∇V_pn‖ - |gPN_dist_proj|
- 동일 분해 for `grad_corner`, `grad_ldt`, `grad_yoyo`
- `active_branch` (이미 있음), `u_star_omega/gamma/accel`, `V_e_raw` (= V_p - closure), `V_e_clamp_active` (bool)

**M1.2** — simple/defensive/aggressive 각 3 매치 수집. (n=3 은 H1/H2/H3 *분별*엔 충분; Phase 3 의 회귀검증은 n=5.)

**M1.3** — 분석 스크립트 `tools/basis/diag_signal_decomp.py`:
- aggressive 매치 vs simple 매치의 `(dist 방향 / heading 방향)` 비율 히스토그램
- `u_star_accel < 0` 비율의 매치별 분포
- 분기 점유율 + 분기 내 τ_i 평균

**Phase 1 종료물**: `docs/diag/aggressive_signal_decomposition.md` — H1/H2/H3 verdict (혹은 조합).

> **2026-05-16 M1.1~M1.3 결과**: `tools/basis/diag_signal_decomp.py` 자동 분석. n=9 매치 (3 적 × 3) × 1500 tick.
>
> | 가설 | 판정 | 핵심 |
> |---|---|---|
> | **H1 (V_dist ω-zero)** | **CONFIRMED, 지배적** | aggressive long-range (>8000ft, **97.6%** of ticks) 에서 median \|gPN_dist\|/\|gPN_head\| = **441,162** vs simple = 1,599. ∇V_pn 거의 전부 LOS-radial → ω 채널 ≡ 0 (Z3 PROVED). |
> | **H2 (자발 감속)** | WEAK | u_a<0 agg 0.249 vs sim 0.145, V_e_clamp 활성 50.7% 이나 u_a<0 동시 발생 10%. 부수적. |
> | **H3 (routing)** | PARTIAL | agg Theorem frac 0.669 — 그러나 그 안 ρ_pn=0.77 ≫ ρ_corner=0.06. PN-우세 + long-range 결합이 H1 효과를 그대로 통과. |
>
> *Phase 2 의 본 회 진입 방향*: H1 정면. `grad_V_Tcap` (V_T) 가 *이미 비-radial gradient 구조* (closure 의 ATA-결합) — CSV 실측 `gT_dist ≈ gT_head` (e.g., tick 0: 1.55e-3 vs 1.66e-3) → 형태 OK. 문제는 *long-range Theorem 에서 τ_T=0*. **Phase 2 가 magnitude 가 아닌 τ_T routing 재유도가 핵심** (Case H1+H3 결합).

### Phase 2. 책임 부위 trace + 수리적 분석 (verdict-dependent)

**Case H1 (V_dist 정규화 부적합)**
- *유도*: PLAN §2.6.3 line 2304 의 `V_2* = ½·ATA² + ½·λ_d·(dist-d_WEZ*)²` 는 *WEZ 근방 quadratic approximation*. 도주자 추격 regime (dist ≫ d_WEZ*) 에서는 quadratic이 saturating 신호를 못 만듦.
- *후보 재유도*: 두 가지 — (i) scale-free `V_dist = ½·log²(dist/d_WEZ*)` — ∂V/∂dist = log(dist/d_WEZ*)/dist 로 long-range 에서도 비영, (ii) capture-time 형 `V_dist = T_cap(x)` (ZEM-style, Bryson-Ho PN 이론).
- *G1 통과 필수*. Z3: `dist > d_WEZ* → ∂V/∂dist > 0` SMT (LRA-friendly).

**Case H2 (V_target sprint 부호 함정)**
- *유도*: closure-required-for-capture 수식. T_cap = (dist - d_WEZ*)/closure_required. closure_required = κ · ε(x) (κ: 시상수, ε: 기하 게인).
- *재정의*: `V_target = V_e + κ·max(0, (dist - d_WEZ*)/T_target)`. 근거리 dist≤d_WEZ* 면 V_target=V_e (station-keep), 원거리면 closing rate 명시.
- 부호 invariant: dist > d_WEZ* → V_target > V_e → V_p<V_target 추구 → ∂V/∂V_p < 0 → 가속. Z3 SMT 가능.

**Case H3 (dispatcher routing)**
- *유도*: PLAN §2.6.5 의 softmin → τ-blend 정당화. 9-way if-else 는 PLAN 의 원래 *연속* τ-blend 의 *quantized degradation* 임을 형식화.
- *재구성*: dispatcher 의 출력을 분기 *선택* 이 아니라 `{τ_pn, τ_corner, τ_ldt, τ_yoyo}` 의 obs-함수 *생성*으로. 각 τ_i 는 monotone obs-함수 (예: τ_pn ∝ σ(WEZ_proximity), τ_corner ∝ σ_2c(HCA)). 임계값 0/1 hardening 없음.

**(rev. (4) 추가) Phase 2.A — Magnitude scale calibration (PMP/ZEM)**
- *문제 (§8 frontier)*: closed-form ∇V_i 의 weight (λ_d, λ_V, α_aa, weight on V_T) 가 *임의 선택*. V_ATA 와 same-order 아니면 simple equilibrium 깨짐 (R3 cycle 4 의 회귀 원인).
- *유도 후보*:
  - **(α) PMP costate normalization** — Bryson-Ho §3.6. Hamiltonian H = λᵀ·f + L 에서 terminal cost J_T 의 ∂J_T/∂x 로 λ(t_f) 의존 → terminal manifold (WEZ entry) 에 대한 transversality 가 각 V_i 의 weight 를 *유도* 결정.
  - **(β) ZEM t_go scaling** — `V_dist ~ t_go²·closure²/2`, `V_ATA ~ t_go·ATA²/2`. 두 항이 *동일 t_go 함수* 로 자동 normalize → magnitude 통일.
- *산출*: `docs/diag/magnitude_calibration_pmp_zem.md` (코드 변경 0, 1~2시간).
- *수용 조건*: G1 PASS + Z3 monotone/sign + R5 (3 적 ≥5) 통과.

**(rev. (4) 추가) Phase 2.B — LUT grid 확장 (background)**
- *목적*: 12⁶ LUT 의 ∇V central-diff cos≈0 (RT-3 verify_grad_lut_xcheck) 해소. 정확도 회복 시 closed-form ∇V_i magnitude 의 *ground truth* 확보 → Phase 2.A 의 (α)/(β) 후보들의 calibration target.
- *명령*: `python tools/basis/hji_solve_v3.py --grid 16 --time 60 --accuracy medium` (수 시간, JAX CPU).
- *수용 조건*: `verify_grad_lut_xcheck.py` 의 cos 가 ≥ 0.5 (적어도 ∇V_PN, ∇V_corner 에 대해) 회복.
- *분기점*:
  - cos ≥ 0.5 회복 → Phase 2.A 의 magnitude calibration 를 LUT-앵커로 fix.
  - cos < 0.5 지속 → 본 SDK 의 LUT path 가 closed-form ∇V 와 *구조적으로* 일치하지 않음을 확정. §8 P4 (Model B 조기 이관) 정당화 확보.

각 케이스 모두: (a) PLAN §2 의 어느 정의에서 유도되는지 명시, (b) G1 통과 증거, (c) Z3 fragment 가능 시 SMT proof.

### Phase 3. 재설계 (한 PR 당 1 함수)

- 변경 단위: ∇V_i 또는 τ_i 정의 *1개*.
- PR 메시지 필수 4 항: ① derivation (PLAN 어느 식에서), ② G1 결과, ③ Z3 sketch (해당 시), ④ R5 결과 (simple/defensive/aggressive 각 ≥5).
- 회귀: 이전 stage 100% 유지 *없이* merge 금지.

### Phase 4. 실험·반복

- Phase 3 결과 → 잔여 misperception 식별 → Phase 1 로 복귀.
- 종료조건: PLAN §8 (3 상대 모두 100% WIN, FP-robust).

### Phase 5. Stage 4/5 확장

- ace, gen_* 아키타입. 동일 진단→trace→재설계 루프.
- 새 상대마다 *misperception 카탈로그* 갱신 — 어떤 obs 차원이 새 적에 대해 모델에 missing 인지 명시.

---

## §4. 안티-카탈로그 (v1 의 기각 시도 + 본 v2 가 추가 금지하는 것)

v1 §3 의 12+ 기각 시도는 *모두* W1 (임계값 fine-tuning) 의 사례. 본 v2 는 추가로:

| 금지 항목 | 사유 |
|---|---|
| 적 의도 분류기 (EIM `CLOSING/EXTENDING/...`) | W2 (추정기). 03_recent §6 폐기. |
| ∇V 에 V_p, V_e 외 추가 hidden state 도입 | R2. obs 직접 사용. |
| sigmoid 게이트 파라미터 (c, w) 스윕 | R1. 함수 형태 유도 없는 fine-tuning. |
| 새 if-else 분기 추가 (DiveAttack, RunDown 류) | R1. 분기는 *생성* 이 아니라 τ-blend 의 quantization. |
| "단일-tick 으론 불가능" 류 결론 | R6 (교훈 4). 5가정 점검 선행 의무. |
| **동시 다중 ∇V/τ 변경 후 R5 한 번에 검증** (rev. (4) 추가) | R8 (1-변경 원자성). R3 cycle 4 의 실패 패턴 — 회귀가 발생해도 어느 변경의 책임인지 분리 불가. |
| **"다른 stage 가 개선되니까 simple 미세 회귀는 수용"** (rev. (4) 추가) | R7 (회귀 hard-gate). simple WIN 수 비감소가 모든 변경의 minimum invariant. trade-off 어휘 금지. |
| **closed-form ∇V_i 에 magnitude scale 자유 hyperparameter 도입** (rev. (4) 추가) | §8 frontier. d_REF/V_REF/α_aa 등 *임의* 스케일은 simple equilibrium 을 깬다. Phase 2.A (PMP/ZEM) 또는 2.B (LUT 16⁶) 로 *유도* 후에만 도입. |
| **Theorem 분기에 전역 τ_T blend 추가 (어떤 형태든)** (2026-05-16 rev. (4)+M1.3 실험 추가) | simple Theorem (19.6%) 의 ρ_yoyo=0.29 평형이 load-bearing — τ_T 가 σ(-4)≈0.018 만큼 작아도 tau_total 정규화로 yoyo 비율 6% 감소 → simple 0W/5L. 우회: 격리된 sub-branch (예: LongRangeClosing) 또는 normalization 의 yoyo floor. 상세: `docs/diag/phase2_tau_T_routing_derivation.md` §8. |

---

## §5. 파일 포인터 (v1 §7 갱신)

| 파일 | 역할 | v2 와의 관계 |
|---|---|---|
| [`tools/basis/gradient_approximators.py`](../../tools/basis/gradient_approximators.py) | ∇V_i closed-form. λ_d, V_target, σ_1c/2c | Phase 2 H1/H2 책임 부위 |
| [`examples/pursuit_chase_v1/nodes/branch_dispatcher.py`](nodes/branch_dispatcher.py) | 9-way if-else dispatcher | Phase 2 H3 책임 부위 |
| [`examples/pursuit_chase_v1/nodes/continuous_policy.py`](nodes/continuous_policy.py) | hybrid 정책, obs→6D, V_e clamp, CSV 로그 | Phase 1 M1.1 (CSV 컬럼 추가) |
| [`tools/basis/tau_functions.py`](../../tools/basis/tau_functions.py) | τ_i Layer1+2, obs_history 지원 | Phase 2 H3 재구성 거점 |
| [`docs/PURSUIT_CHASE_PLAN.md`](../../docs/PURSUIT_CHASE_PLAN.md) §2.6 | V_m* 정의 (V_2~V_8) | derivation 출처 |
| [`docs/PROJECT_OVERVIEW/03_recent_analysis.md`](../../docs/PROJECT_OVERVIEW/03_recent_analysis.md) §8 | 교훈 1·2·4 (R1·R2·R6 의 원전) | 원칙 ground truth |
| `tools/basis/verify_smt_*.py` | Z3 SMT 패턴 | R4 의 템플릿 |

---

## §6. 즉시 다음 액션 (본 세션, rev. (4) 재배열)

> **순서가 곧 R7/R8/R9 의 강제 시퀀스**. 1 → 2 → 3 → 4 의 game-tree 분기점에서 *조건부* 다음 액션이 결정된다.

1. **Phase -1.1 회귀 정량화** — 현 working tree 로 simple ×6 별프로세스 측정. → 회귀 확정 + 정도 측정. 산출: `logs/regression/simple_currentHEAD.csv`.
   - simple ≥ 6/6: P-1 종료, 사용자 보고. 측정 인식 오류 가능성 정정.
   - simple < 6/6: → 2.

2. **Phase -1.2 stage2_best 스냅샷 검증** — `git worktree add ../ai-combat-sdk-stage2 <snapshot-commit>` (or 직접 코드 복원) 후 simple ×6 재측정. 스냅샷이 *진짜* 6W/0L 인지 ground-truth.
   - 6/6 확인: bisect known-good 채택 → 3.
   - 미달: 스냅샷이 더 오래된 commit. P-1.2 의 upper 를 `e867a8b` 등으로 이동 후 재측정.

3. **Phase -1.3 hunk-level bisect** — 5 그룹 (G_T1 V_Tcap, G_T2 V_T weight, G_AA, G_CC magnitude blend, G_BR dispatcher) 각각 *단독 적용* 시 simple ×5. 회귀 그룹 식별. 산출: `docs/diag/regression_bisect_2026-05-15.md`.

4. **Phase -1.4 최소 회복 변경 채택** — 비회귀 그룹만 유지, 회귀 그룹은 stash. R5 (3 적 ≥5) 측정으로 simple ≥ 6W/0L + defensive/aggressive 비회귀 확인.

5. **Phase 0 커밋** (P-1.4 통과 후, 사용자 명시 신호 시) — HANDOVER §5.2 의 8 의미단위. push 보류.

6. **Phase 1 M1.1 ~ M1.3 진단** (Phase 0 종료 후) — `continuous_policy.py` CSV 컬럼 추가, simple/defensive/aggressive 각 3 매치, H1/H2/H3 verdict.

7. **Phase 2.A (PMP/ZEM derivation) + Phase 2.B (LUT 16⁶ background)** 병행 — 2.B 는 `python tools/basis/hji_solve_v3.py --grid 16 ...` 백그라운드 실행, 그 동안 2.A derivation 문서 작성. 2.B 결과로 §8 의 P1/P4 분기 결정.

8. **Phase 3 ~ 5** — R7/R8 강제 하의 1-변경-1-PR 사이클. 종료조건 PLAN §8.

---

## §7. 종료 조건

PLAN §8 (모든 heuristic 상대 100% WIN, FP-robust) **및** misperception 카탈로그가 1 라운드 동안 비공석 (잔여 가설 0). 둘 다 만족 시 Model B (R5/R4/m_4 σ_2c·ATA² 등) 로 이관.

---

## §8. Magnitude Scale Frontier — COMPASS §G 통합 (rev. (4) 신설)

R3 4 cycle 의 무진전과 본 rev. 의 simple 회귀가 *같은 한 지점* 에 수렴한다:

> **closed-form V_i 의 magnitude scale 이 진짜 게임이론적 V*(x) 와 calibrate 불가능.**

각 항의 scale:
- `V_ATA ~ rad²` (∼1 at ATA=1).
- `V_dist ~ (1/L²)·L² = dimensionless` (∼0.5 at canonical).
- `V_T` (exp form): dimensionless 이나 `d_REF·V_REF` 의 *임의 선택* 에 따라 1~1000 변동.
- `V_aa` (R3 cycle (iv)): AA-gate verify FAIL 의 직접 원인이 axiomatization 결함이 아닌 *gate 의 scale 모순* 일 가능성.

추가 V_i 가 V_ATA 와 same-order 가 아니면 ω 명령을 단독으로 좌우 → simple equilibrium 깨짐 ⇒ **rev. (4) 의 simple 회귀 메커니즘**.

### 4 path (우선순위 순)

| Path | 내용 | 비용 | R1~R6 정합 | 추천 |
|---|---|---|---|---|
| **P1. LUT 16⁶ 재솔브** | `tools/basis/hji_solve_v3.py --grid 16 ...`. cos > 0.5 회복 시 ground truth 확보. | 수 시간 (JAX CPU) | ✅ 전부 | ★★★★ |
| **P2. PMP/ZEM 정통 magnitude 유도** | Bryson-Ho §3.6 costate normalization 또는 ZEM t_go scaling 으로 weight 를 *유도*. | 1~2 세션 | ✅ R1·R4 | ★★★★ |
| **P3. AA-gate 재공리화** | `verify_aa_gate.py` FAIL 원인 분리 (L_AA1/2/3 어느 lemma) + sigmoid abstraction 강화 or tanh/piecewise gate. | 30분~2h | ✅ R4 | ★★ |
| **P4. Model B 조기 이관 (현실주의)** | PLAN §8 미달 인정. HP 누적·running cost 로 이관. simple 100% 보존만 유지. | 큰 재설계 | R6 — 5 가정 점검 선행 의무 | ★★ (P1 결과 의존) |
| **(기각) P5. Neural ∇V approximator** | LUT 위 NN fit. | 큼 | R2 (추정기) 위반 가능성 | — |

### 의사결정 트리

```
Phase 2.A (P2 derivation) + Phase 2.B (P1 LUT 16⁶ background) 동시 진입
  │
  ├─ P1 결과 → cos > 0.5?
  │   ├─ YES: P2 의 magnitude 후보를 LUT ∇V* 와 calibrate. R5 회귀검증.
  │   └─ NO : 본 SDK 가 game-theoretic V* 를 구할 수 있는 *closed-form 영역* 한계 확정 → P4 정당화.
  │
  └─ P2 결과 → derivation 가능?
      ├─ YES: G1 + Z3 통과 시 Phase 3 (1-변경-1-PR) 채택.
      └─ NO : 본 SDK 의 정당화 가능 영역 한계 명시 → P4.
```

P3 는 P1/P2 대기 중 *부산물 작업*. AA-gate FAIL 의 axiomatization 결함을 30분~2시간 안에 격리.

본 §8 은 §6 액션 7~8 의 *판정 기준* 역할 — Phase 2 진입 시 즉시 참조.

---

### 2026-05-16 갱신 — Phase 2 cycle 완료, Model B 권고

**Phase 2 cycle 3 후보 (C1/C2/C3) 결과**:

| 후보 | 결과 | R7 |
|---|---|---|
| **C1 LongRangeClosing 새 분기** (ata<20 ∧ dist>8000 ∧ closure>-100 → m_T) | simple 5W/0L ✓, **defensive 3W → 0W** | **REJECT** |
| **C2 Theorem bias_tau_T 분리정규화** (BIAS_SCALE=0.3) | **simple 5W → 0W**, defensive 3W → 0W | **REJECT** |
| **C3 aggressive 진단 심화** | dist min = dist start = 3298ft, mean 15,000ft, closure mean −20kts → *parallel PE-build chase Nash*. Model A 의 saddle-free 평형 확인. | (진단) |

**P1 (LUT 16⁶) 완료**: ∇V_PN/corner/2circle 여전히 cos≈0 (unusable). 1circle median cos +0.962 (97% |cos|>0.5) — HCA<90° regime 만 정합. aggressive HCA~150° → P1 무효.

**§G P4 (Model B 이관) 직접 권고**:
- C3 진단: aggressive Nash 는 parallel chase draw — Model A cost structure 의 *근본적* 평형.
- 일방적 routing/blend 로 Model A Nash 깰 수 없음 (C1/C2 가 실증).
- HP 누적 cost (running cost), m_4 σ_2c·ATA² (terminal time-on-tail) — Model B 만이 turn-precommit 인센티브 유도.
- 상세: [`docs/diag/c3_aggressive_parallel_chase.md`](../../docs/diag/c3_aggressive_parallel_chase.md)

**Phase 2 cycle 종료, SUPERPLAN_v3 (Model B) 작성 권고**.
