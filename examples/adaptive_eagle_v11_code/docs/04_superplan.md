# HCCA v12 → SUPERPLAN: PhaseController 어택큐 설계

## 왜 반응형 AI는 한계가 있나

현재 HCCA v12는 매 틱 `τ_threat/τ_opp/τ_energy/τ_pursuit`에 반응해서 모드를 고른다.
문제는 이것이 **반응형**이라는 점이다.

```
반응형 (현재): 관찰 → 분류 → 대응 선택 → (반복)
선제형 (목표): 목표 결정 → 단계 실행 → 조건 달성 → 다음 단계
```

**데이터 증거**:
- `eagle2`: dist<5000ft 진입 후 LeadPursuit 50+ 틱 고정 → WR 98.4%
- `defensive`: ClimbTo 100+ 틱 유지 → 에너지 점유
- v9 (우리): 매 3~5틱 모드 전환 → orbital lock

---

## 어택큐 (Attack Queue) — BFM 교리

공중전은 WEZ 진입 후 사격이라는 **단일 목표를 향한 순차적 진행**이다.

```
Phase 1 ENERGY     → e_diff > 1500ft, Ps > 0 달성
Phase 2 POSITION   → ATA < 55°, alt_advantage 달성
Phase 3 ATTACK_RUN → dist < 3000, ATA < 15° 진입
Phase 4 FIRE       → 사격
Phase 5 BREAK      → 이탈 후 에너지 회복

[INTERRUPT] τ_threat > 0.75 → 즉시 DEFEND, 해소 시 이전 phase 복귀
```

---

## BT 구조 (7 브랜치)

```
ROOT (Selector)
├── [1] HardDeckSafety        ← 저고도 불변조건
├── [2] GunWEZ                ← 즉시 사격 조건
├── [3] DefendInterrupt       ← τ_threat > 0.75
├── [4] PhaseController       ← 핵심: 어택큐 순차 실행
├── [5] ForcingAction         ← 수동적 상대 forcing (stale > 20틱)
├── [6] OrbitBreak            ← 교착 탈출 (abs_closure < 80kts)
└── [7] SafetyFallback        ← LeadPursuit
```

기존 v11_code 48 노드 → **7 브랜치** (~28 파라미터, CMA-ES 최적화 가능)

---

## PhaseController 전이 조건

| 전이 | 조건 |
|------|------|
| ENERGY → POSITION | `e_diff > 1500 AND Ps > 0` |
| POSITION → ATTACK_RUN | `ATA < 55° AND alt_advantage` |
| ATTACK_RUN → FIRE | `dist < 3000 AND ATA < 15°` |
| FIRE → BREAK | `dist < 500 OR 20틱 경과` |
| BREAK → ENERGY | `dist > 6000 AND closure < 50` |
| 후퇴: POSITION → ENERGY | `score_energy < 0.35` |
| 후퇴: ATTACK_RUN → POSITION | `ATA > 70° OR e_diff < −2000` |

---

## defensive / eagle2 수정 메커니즘

**vs defensive** (현재 0% → 목표 50%+)
1. ENERGY 단계: defensive climb을 따라가지 않음 → 수평 순항으로 Ps 확보
2. e_diff 확보 후 POSITION: alt_advantage 추구
3. ATTACK_RUN: dive attack (altitude → speed 전환)

**vs eagle2** (현재 0% → 목표 33%+)
1. POSITION 단계: dist<5000 진입 **전에** ATA<55° 달성
2. eagle2의 LeadPursuit commitment보다 우리가 먼저 ATTACK_RUN 조건 충족
3. OrbitBreak: closure 임계값 200→80kts (교착 조기 감지)

---

## 파라미터 예산 (~28개)

| 구성요소 | 수 |
|----------|---|
| score_energy 가중치 (w1~w3, bias) | 4 |
| score_position 가중치 (w4~w6, bias) | 4 |
| score_attack 가중치 (w7~w9, bias) | 4 |
| τ_threat 가중치 (w_rdot, w_aa, w_bdot, bias) | 4 |
| 전이 임계값 | 6 |
| ForcingAction | 5 |
| 기타 (min_commit 등) | 1 |
| **합계** | **28** |

기존 노드 파라미터(PNLeadPursuit 24개 등)는 변경 없이 재사용.

---

## 구현 파일

| 파일 | 변경 내용 |
|------|-----------|
| `nodes/custom_actions.py` | `PhaseController` (+150줄), `ForcingAction` (+60줄) |
| `nodes/__init__.py` | 신규 노드 import |
| `adaptive_eagle_v11_code.yaml` | 7-브랜치 구조로 교체 |
| `nodes/custom_conditions.py` | `DefendThreat` condition 추가 |

---

## 성공 기준

| 기준 | 목표 |
|------|------|
| 전체 WR | > 66.7% (v11_code baseline) |
| vs defensive | 0% → ≥ 33% |
| vs eagle2 | 0% → ≥ 33% |
| 어떤 상대도 | v11_code 대비 −20pp 이하 없을 것 |
