# R15-K 종합 — bt_vs_bt 8 DRAW 진단 + Stage1-3 시도 결과

*2026-05-30 / 5 stalemate 매치 raw 데이터 + v3 도구 진단 + K 가설 결과 종합*

---

## 현 최적 (R15_J8_KS default = "K2,K8")

**bt_vs_bt 20 opps**: **12 WIN / 8 DRAW / 0 LOSS**

R14 baseline (+23.8 net) → R15-J12 K2 (+75.9) → R15-K Stage1 종료까지 동일 (회귀 없음).

---

## 8 DRAW 진짜 분해

| Opp | v3 VERDICT | 실제 결과 | 진단 |
|---|---|---|---|
| **v6h5a** | (분산) | **2/5 WIN (mean 3.20)** | P1 분산 — 1-run 측정 노이즈로 DRAW 잘못 분류 |
| **v6h5b** | (분산) | **4/5 WIN (mean 5.84)** ⭐ | P1 분산 입증 — 실제 WIN |
| **v6h_e1c** | (분산) | 1/5 WIN | P1 부분 (D 패턴 가능성) |
| **defensive** | MIXED — 추적 전환 실패 | 0/5 DRAW | C linear extend, 139ft 정렬 너무 짧음 |
| **aggressive** | MIXED — 추적 불안정 | 0/5 DRAW | C linear extend, CAS 500+ 도주 |
| **ace** | PHYSICS LIMIT | 0/5 DRAW | A' figure-8 like + 양쪽 alt climb |
| **v10** | PHYSICS LIMIT | 0/5 DRAW | A' figure-8 Nash 평형 |
| **v51** | PHYSICS LIMIT (B 0.93) | 0/5 DRAW | B offset spiral — 두 원 중심 떨어짐 |

→ "구조적 DRAW" = 5개 (defensive/aggressive/ace/v10/v51), "측정 분산" = 3개 (v6h5*).

---

## 5 매치 ACMI raw 측정값

| Opp | dist 시작 | dist 끝 | dist min | dist max | ATA min | CAS_A 평균 | CAS_B 평균 | HDG_A slope | HDG_B slope |
|---|---|---|---|---|---|---|---|---|---|
| defensive (C) | 3299 | **15023** | 3299 | 15023 | 5.0° | 423 | 451 | -0.140 | -0.028 |
| aggressive (C) | 3299 | **16175** | 3299 | 16176 | 5.5° | 460 | **491** | -0.168 | -0.046 |
| v10 (A') | 3299 | 1351 | **1351** | 10012 | 0.7° | 304 | 360 | **-0.009** | +0.002 |
| v51 (B) | 3299 | 2760 | 1743 | 8582 | **53.6°** | 283 | 303 | -0.673 | -0.701 |
| ace (D) | 3299 | 3869 | 1932 | 8441 | **0.4°** | 270 | 255 | -0.450 | -0.303 |

→ C: dist 5배 증가 / A': dist oscillation + HDG slope 0 / B: ATA 정렬 0회 / D: ATA 0.4° 정렬 모먼트 있음

---

## Stage 1-3 시도 결과 (이번 R15-K)

| 단계 | K | 목표 | 결과 | 처분 |
|---|---|---|---|---|
| **P0** | runner_core/.py per-agent obs snapshot | meta CSV per-agent 복사 버그 | A vs B 정상 구분 ✓ | commit 95afad6 |
| **P1** | 5-run 측정 | v6h5* 분산 가설 검증 | v6h5b 4/5 WIN 입증 ✓ | tools/p1_5run.py |
| **P2** | K8 corner-bleed lock | aggressive | 0/5 (도주 적엔 무력) | opt-in 보존 |
| **P3** | K9 tracking lock + bin rate-limit | defensive | 0/5 (139ft 정렬 짧음) | opt-in 보존 |
| **Stage 1** | K3 cut-off 완화 (8tick avg <50) | aggressive | 0/5 (lead 빗나감), v11 +3.24 | opt-in 보존 |

→ aggressive/defensive 직접 해결 못 함. K opt-in 으로 v6h5b 등 분산 매치에는 유효.

---

## PNG 진단 산출물

- [pattern_comparison.png](pattern_comparison.png) — 5 매치 top-down 궤도 (75초)
- [defensive.v3.png](defensive.v3.png) — C linear, MIXED VERDICT
- [aggressive.v3.png](aggressive.v3.png) — C linear, MIXED VERDICT (CAS 500+ corner 위)
- [ace.v3.png](ace.v3.png) — A' figure-8 like, PHYSICS LIMIT
- [adaptive_eagle_v10.v3.png](adaptive_eagle_v10.v3.png) — A' figure-8, PHYSICS LIMIT
- [adaptive_eagle_v51.v3.png](adaptive_eagle_v51.v3.png) — B offset (score 0.93), PHYSICS LIMIT

---

## 환경변수 toggle 요약

```bash
# 현 default (가장 안전)
R15_J8_KS="K2,K8"

# K3 추가 (v11_code +3.24 진보 가능)
R15_J8_KS="K2,K3,K8"

# K9 (defensive 시도용, taken 위험)
R15_J8_KS="K2,K8,K9"

# 모든 K (테스트용, 회귀 가능)
R15_J8_KS="K1,K2,K3,K4,K5,K7,K8,K9"
```

---

## 다음 작업 후보 (보류 — 비용/효과 평가 후)

| 후보 | ROI | 비용 | 위험 |
|---|---|---|---|
| Stage 2: v51 lateral via continuous_policy | 🟡 중간 | 🔴 큼 | 🟡 회귀 가능 |
| Stage 3: ace K6 강화 (감속 진입) | 🔴 낮음 | 🟡 중간 | 🟡 corner 회귀 |
| defensive continuous_policy 양자화 우회 | 🟡 불확실 | 🔴 매우 큼 | 🔴 전체 회귀 가능 |

→ 본질적 한계 (aggressive 도주 적, defensive 짧은 정렬) 는 bin-based dispatch 로 해결 어려움.
