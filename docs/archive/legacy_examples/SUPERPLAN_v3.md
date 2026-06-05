# SUPERPLAN v3 — Model B/B' 이관 (Pragmatic Path)

> **작성**: 2026-05-16. 사용자 명시 ("프로젝트 목적 달성이 더 중요") 후의 path.
> **대체**: [`SUPERPLAN_v2.md`](SUPERPLAN_v2.md) — v2 는 Model A 안에서의 진단·재유도 cycle.
> v2 의 R1~R9 ground rules 는 유지하되, **R6 (5가정 점검)** 의 *"정적 정책"* 가정 완화 +
> **R2 (추정기 금지)** 의 *최소 완화* (적 HP 추정 등 dynamics-driven proxy 허용).
> 모든 변경은 여전히 R7 (회귀 hard-gate) + R8 (1-변경 원자성) 하에서 진행.

---

## §0. 왜 Model B/B' 인가 (v2 의 4 cycle 음의 결과 요약)

| Cycle | 시도 | 결과 |
|---|---|---|
| C1 LongRangeClosing 새 분기 | simple ✓ / **defensive 3W→0W** | REJECT |
| C2 Theorem bias_tau_T 분리 | **simple 5W→0W** | REJECT |
| C3 aggressive 진단 | parallel chase Nash 확정 | (verdict) |
| D1 Theorem argmax-quantize | **simple 12W→0W** | REJECT |

**누적 결론**: Model A 의 stationary policy + binary capture cost 안에서:
- 모든 dispatcher 변경이 simple/defensive load-bearing equilibrium 의 *fragility* 에 부딪힘
- aggressive 의 parallel chase 가 *수학적* Nash (PLAN §2.5.7 single-Lyapunov trade-off)
- 일방적 routing/blend 는 Nash 깰 수 없음 (saddle-free)

**Model B/B' 가 깨는 메커니즘** (PLAN §11.7):
- Running cost J = ∫_0^T (HP_them - HP_us) dt — *시간 자체가 비용*
- Symmetric 도그파이트의 Nash 가 *fixed-horizon* 에서 깨짐: 종료 시점 임박 시 *commit-to-turn* 의 expected payoff > parallel-chase
- aggressive 는 *고정 BT* (Nash player 아님) — Model B' optimal vs heuristic 비대칭 exploit 가능

---

## §1. 변경 (v2 §1 R-rules 보완)

| 규칙 | 변경 |
|---|---|
| R1 (수치 fine-tuning 금지) | **유지**. magnitude 는 PMP/ZEM/HP-rate 에서 *유도*. |
| R2 (추정기 금지) | **부분 완화**. 적 HP 는 closure × time 의 *dynamics-driven 추적량* (분류기 아님). 적 BT 의도 추정은 여전히 금지. |
| R3 (G1 통과) | **유지**. 모든 ∇V/∇J 변경 G1. |
| R4 (Z3 정당화) | **유지**. running-cost HJI 의 sign/monotone 속성 형식화. |
| R5 (누적 회귀 검증) | **유지**. simple/defensive/aggressive 각 ≥5 별프로세스. |
| **R6 (5가정 점검)** | **"정적 정책" 가정 완화**. 시간-의존 policy 허용 — Model B' 의 fixed-horizon 자연 결과. |
| R7 (회귀 hard-gate) | **유지**. simple WIN ≥ baseline (12/12). |
| R8 (1-변경 원자성) | **유지**. PR 당 ∇J 또는 dispatch 변경 1개. |
| R9 (snapshot) | **유지**. Phase 진입 시 baseline 보존. |

---

## §2. Model B/B' 의 *우리 상황* 특화

PLAN §11 의 정통 path 는 *대칭* 게임 (V_us, V_them 두 LUT) — 비용 크다 (8D HJI). 우리의 *목표*:
PLAN §8 (3 적 100% WIN). aggressive 가 *고정 BT* (Nash 아님) 라는 점을 활용 → *비대칭 exploit*
형식이면 충분.

### 2.1 핵심 통찰

aggressive 가 *고정 BT* + 시간-제약 매치 (1500 step ≈ 75s) 두 조건이 결합:
- Aggressive 의 Nash 가 *우리 Nash 와 같은 가정* 아래 도출됨 (둘 다 max V_p + min dist).
- 그러나 aggressive 는 *우리 행동 변화에 적응 못 함* (BT static).
- → 우리가 시간-의존 policy 채택하면 비대칭 exploit 가능.

### 2.2 두 path 비교

| Path | 비용 | 기대효과 | 추천 |
|---|---|---|---|
| **B-Lite. 시간-의존 bias** | 작음 (~1일) | aggressive Nash 깨기 시도, simple 비회귀 가능성 | ★★★★ |
| **B-Full. 8D HJI (V_us + V_them)** | 큼 (~1주, ~11MB·8분) | 정통 Model B, mutual-kill 식별 가능 | ★★ |
| B'-Full. Running-cost HJI (HP 누적) | 매우 큼 (~수주, 8D LUT) | PLAN §11.7 의 완전 형식화 | (장기) |

→ **B-Lite 부터 진입**. 결과 따라 B-Full 또는 B' 확장.

---

## §3. B-Lite Phase 계획

### Phase B-0. Baseline 보존 (커밋)

미커밋 변경분 (M1.1 CSV 컬럼 + Theorem revert + verify scripts) Phase 0 8 의미단위 커밋.
B-Lite 변경의 *비교 baseline* 로 보존.

### Phase B-1. 시간-의존 aggressive bias

> **가설**: aggressive parallel-chase Nash 는 *stationary policy 가정* 의 결과. 시간-의존 정책
> 으로 깨짐. 종료 시점 임박 (tick > t_pressure) + dist > d_pressure (Nash 영역) 에서 *commit-
> to-turn* bias 활성.

**유도** (R1 정합):
- Running-cost game: J(t) = ∫_t^T (HP_them - HP_us) dt'.
- 잔여 시간 (T-t) 가 작아질수록 *현재 미세 turn 이 payoff 에 미치는 영향* 큼.
- → bias_t = (t / T)·σ((dist - d_pressure)/Δ) 의 형태. 시간-단조 + dist 게이트.

**구현**:
- Theorem 분기에 *시간-asymmetric V_T bias* 추가 (C2 와 유사하지만 *시간 의존*).
- 0~t_pressure: bias = 0 (Model A 그대로, simple 평형 보존).
- t_pressure~T: bias 단조 증가, 최종 bias_scale = 0.3.

**파라미터 (R1: 유도-기반)**:
- t_pressure = T/2 (=750 ticks) — 매치 절반 (잔여 시간 < 진행 시간 자연 break).
- d_pressure = 8000 ft (구조적: V_PN sprint 포화점, SUPERPLAN_v2 §3 Phase 2.A).
- bias_scale_max = 0.3 (C2 와 동일 — 동일 stress 조건).

**R7 hard-gate**: simple WIN ≥ 12/12 (n=5), defensive WIN ≥ 3/5.

### Phase B-2. 적 BT 의도-역설계 (R2 부분 완화)

Phase B-1 실패 시. aggressive yaml BT 의 *결정함수* 정적 파싱 → 우리 정책의 *역 BT* 작성.
적 의도 추정 아니라 *역 추론 (deterministic)* — R2 허용 영역.

### Phase B-3. WEZ damage rate 추적 (Model B' 시작)

```python
D_us(x)   = w_ATA(ATA_us) · w_dist(dist)    # 우리가 적에게 가하는 damage rate
D_them(x) = w_ATA(AA)     · w_dist(dist)    # 적이 우리에게 가하는 damage rate
∫(D_us - D_them) dt → bias toward maximizing
```

PLAN §0.8 의 가중치 함수. 우리 BFM mode 선택의 *bias 가중치*.

### Phase B-4. 8D HJI (B-Full, 선택적)

PLAN §11.4 의 D-1~D-4. V_them table + 4-region classifier + Model B BT 노드.

---

## §4. 즉시 액션 (본 세션)

1. **Phase B-0 커밋** — 의미단위 8 commit. push 보류.
2. **Phase B-1 코드 변경** — `continuous_policy.py` Theorem 분기에 시간-asymmetric bias 추가.
3. **R5 측정** — simple/defensive/aggressive 각 ×5. R7 검증.
4. 결과 따라:
   - **WIN 발생**: Phase B-1 채택 + 추가 dist/time 영역 확장 검토.
   - **R7 위반**: revert + Phase B-2 진행.
   - **무진전 (전부 DRAW)**: Phase B-2 진행.

---

## §5. 종료 조건

PLAN §8 (3 heuristic 100% WIN, FP-robust) 달성 또는 *모든 B-* phase 소진 후 정직 보고.
