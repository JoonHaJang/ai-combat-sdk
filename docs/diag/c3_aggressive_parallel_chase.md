# C3 — aggressive "PE-build race draw" 진단 (2026-05-16)

> SUPERPLAN_v2 §3 Phase 2 C3. 사용자 지시 ("다 해보고") 하에 C1/C2 reject 후의 진단.

## 1. 측정값 (M1.2 aggressive ×3)

| 항목 | n1 | n2 | n3 |
|---|---|---|---|
| ticks | 1500 | 1500 | 1500 |
| dist start (ft) | 3,298 | 3,298 | 3,298 |
| dist min (ft) | 3,298 | 3,298 | 3,298 |
| dist max (ft) | **19,942** | **20,017** | **20,017** |
| dist end (ft) | 13,771 | 14,848 | 14,848 |
| dist mean (ft) | 15,116 | 15,204 | 15,204 |
| closure mean (kts) | −19 | −22 | −22 |
| closure range (kts) | (−786, +372) | (−786, +380) | (−786, +380) |
| pct closing > 50 | 35.07% | 34.53% | 34.53% |
| pct extending < −50 | 44.80% | 42.87% | 42.87% |

## 2. 결정적 관측

- **dist min = 3298 = dist start**. 즉 매치 동안 dist 가 *한 번도 더 가까워지지 않음*.
  canonical IC 부터 점진적으로 멀어지기만 함 (mean 15,000 ft 로 정착).
- **dist max ≈ 20,000 ft** — 매치 mid-phase 에 적과 우리가 거의 *6km 이상 분리*.
- **closure 평균 −20 kts** — 전체 평균으로 *멀어지는 중*. 35% closing 은 적이 *방향 전환*
  시점의 일시적 closing.

## 3. aggressive 의 BT (재확인)

```yaml
CloseEngagement (dist ≤ 6562ft): Pursue
MediumApproach  (dist ≤ 16404ft): Pursue + Accelerate
Default          (dist > 16404ft): Pursue
```

→ aggressive 는 *항상 Pursue (우리 향함)* + 5km 안에선 *동시 Accelerate (가속)*.
   즉 **우리를 향해 closing 하면서 동시에 가속**.

## 4. 우리의 정책 (hybrid v1)

- 모든 분기에서 PE 관리 (yoyo / corner / EnergyRecovery / ZoomClimb).
- canonical (dist=3298) 시작 시점: 진입 분기 = OrbitBreak (ATA=90° abeam) → V_corner 가속.

→ 둘 다 동시에 *가속* + 둘 다 *추격 자세* (head-on 또는 mutual orbit).

## 5. 게임이론 해석

이는 *zero-sum dist 최소화 / 최대화* 게임의 **saddle-free Nash equilibrium**:

- 우리: max V_p (corner) + min dist
- 적: max V_p (corner) + min dist (적 BT 정의)
- 둘 다 코너 속도 (V_c ≈ 438 kts @ 15000ft) 에서 *평행 비행* 이 Nash.
- closure 는 turning maneuver 의 *2차 미분* 으로만 결정됨 — 둘 다 직진 정렬 시 = 0.
- 어느 한쪽이 *불리한 turn* 을 시작하면 turning advantage 잃음 → equilibrium 강화.

PLAN §2.5.7 의 "single-Lyapunov trade-off" 의 *경험적 확인*: V_adv 최소화가
*동시 행위자* (둘 다 V_adv 최소화) 에선 *비-종료 평형* 으로 귀결.

## 6. C1/C2 가 *왜* 실패했는지 이 진단 하에 재해석

- **C1 (LongRangeClosing 분기 + τ_T routing)**: τ_T 의 closure-aware 신호로 *우리만* turn-toward
  하면 turning advantage. 그러나 우리만 turn 하면 우리 V_p ↓ → 적이 우리 추월 → 우리가
  *방어자세* 로 전환. 결국 defensive 매치들 (이미 적이 도주 자세) 의 WIN-yielding 평형
  깨짐 (3W → 0W).
- **C2 (Theorem bias τ_T)**: 위와 동일 메커니즘. 모든 매치에서 turn-toward 신호가 *부분* 활성 →
  simple 의 (도주 안 함) WIN-yielding yoyo 평형도 깨짐 (5W → 0W).

→ 일방적 routing 으로 Model A 의 Nash 깰 수 없음. 두 행위자 모두 *running cost* (HP 누적,
   running ATA-time) 에 incentive 가 박힐 때만 turn-precommit 가능.

## 7. Path Verdict (PROJECT_COMPASS §G 기준)

| Path | 본 진단 후 verdict |
|---|---|
| **P1 LUT 16⁶** | LUT 16⁶ 완료. ∇V_PN/corner/2circle cos ≈ 0 (unusable, 12⁶ 와 동일). 1circle 만 median cos +0.962 (HCA<90° 영역). aggressive 는 HCA~150° → 1circle 못 씀 → **P1 effectively closed** for aggressive. |
| P2 PMP/ZEM magnitude | 여전히 가능. 그러나 본 C3 진단 (parallel chase Nash) 은 magnitude 가 아닌 *cost structure (running cost)* 가 결손이라고 가리킴. P2 만으로 aggressive 해결 어려움. |
| P3 AA-gate axiomatization | 부차적, aggressive 해결과 직접 연관 없음. |
| **P4 Model B 이관** | **본 C3 진단의 직접 권고**. Model A 가 *근본적* parallel-chase draw 임을 측정 + 게임이론 해석으로 확정. Model B (running cost HP 누적, terminal time-on-tail, σ_4 ATA² 등) 만이 aggressive Nash 깬다. |

## 8. SUPERPLAN_v2 결론

**Phase 2 cycle (C1/C2/C3) 완료. 3 후보 모두 Model A 안에서는 aggressive 해결 불가**.

R7 invariant 보존 하에서 PLAN §8 (3 적 100% WIN) 은 Model A 에서 *수학적으로 도달 불가*
— H1 lemma (V_dist ω-zero) + parallel-chase Nash 의 결합. 5 가정 점검 (R6, 교훈 4):

| 가정 | 본 C3 가 반박하는가 |
|---|---|
| ω 상수 | 아니오 — 우리도 적도 ω varying |
| 적 최적성 | **부분** — 적은 yaml-encoded heuristic, 진정한 maximin 아님. 그래도 |
|   | parallel-chase 가 *경험적* Nash. |
| 2D | 아니오 — 6D dynamics |
| 닫힌 궤도 | **부분** — 양쪽 다 mid-phase 6km 직선화. |
| 정적 정책 | 아니오 — branch dispatcher 가 dynamic |

따라서 "이론적 천장" 결론 *조건부 합법* (R6 점검 통과): Model A 의 cost structure 가
parallel-chase 를 Nash 로 허용. **Model B 가 유일 path** (또는 적 BT 의 ε-perturbation
robustness 분석 후 Model A 유지).

## 9. 즉시 권고

1. *현 상태 (simple 12W/0L + defensive 3W/3D + aggressive 0W/6D) 가 Model A 의 final state*
   로 인정. Phase 0 커밋 (의미단위, 사용자 신호 시).
2. SUPERPLAN_v3 작성 — Model B 이관 plan (HP 누적 cost, R5 정적 게임, m_4 σ_2c·ATA²).
   PLAN §11 의 정식 path.
3. *Optional*: P2 (PMP/ZEM magnitude calibration) 를 Model B 의 *terminal cost* 정의에 활용.
   ZEM t_go scaling 이 running ATA-time cost 의 자연 정규화.
