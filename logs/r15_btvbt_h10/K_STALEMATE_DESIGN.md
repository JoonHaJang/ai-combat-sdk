# R15-K 후속 — 8 DRAW Stalemate 정밀 진단 + 해결 설계

*작성 2026-05-29 / 근거: meta CSV 시계열 + ACMI per-object 교차검증 + cost_branch_selector 코드 분석*

대상 8 DRAW: `defensive, aggressive, ace, v6h5a, v6h5b, v6h_e1c, v10, v51`
기존 진단(K_HYPOTHESES.md L242-245): *"본질적 limit — action bin (5×9×5) representation 한계"*

**결론 요약: 이 진단은 대부분 오진(誤診)이다.** 8 DRAW는 단일 원인이 아니라 4개의 서로 다른 root cause이며, 22.5° heading 양자화가 binding constraint인 케이스는 사실상 0개다. 진짜 레버는 (a) 데이터 정합성, (b) policy/cost 로직, (c) committed multi-tick maneuver, (d) 분산 감소에 있다.

---

## 0. 헤드라인 — 데이터 정합성 버그 (모든 분석의 선행 조건)

meta CSV(`logs/matches/.../*_meta.csv`)의 **per-agent 필드가 A0100(ego)에서 B0100으로 그대로 복사**되고 있다.

검증 (adaptive_eagle_vs_aggressive_round1, 모든 step에서):

| 필드 | A0100 | B0100 | 비고 |
|---|---|---|---|
| `ego_vc_kts` | 541.2 | 541.2 | 동일 — B는 aggressive 봇인데 우리 속도 |
| `specific_energy_ft` | 27576.9 | 27576.9 | 동일 |
| `ata_deg` / `aa_deg` | 112.5 / 112.9 | 112.5 / 112.9 | 동일 |
| `turn_rate_degs` | 0.0137 | 0.0137 | 동일 |
| `action_*` / `active_node` | 다름 | 다름 | **이것만 per-agent 정상** |

- **출처**: `src/match/runner.py:388` — `obs_i = task_i.blackboard.observation`. `task2.blackboard.observation`이 ego 필드에서 task1과 동일하게 채워짐(env→task2 obs 주입이 ego_ids[0] 관점). relational 스칼라(distance/closure)는 원래 대칭이라 무해하지만, **own-state 필드(vc/Es/ata/aa/turn_rate)는 오염**.
- **교차검증**: ACMI 리플레이는 정상. `replays_h1/ace`에서 A CAS mean 427 vs B CAS mean 408로 genuine하게 갈라짐(per-object T=/HDG=/CAS=). 따라서 `plot_match_3d_v2.py`의 **궤적·circle fit·HDG 분석은 유효**하나, meta CSV 기반 per-agent 비교는 무효.

**영향**: K_HYPOTHESES.md의 다음 결론들은 오염된 telemetry에 기반했을 수 있어 재검증 필요 —
- "omega 양쪽 mirror" (v11_code, ace) — turn_rate가 복사본
- "Es 양쪽 동등" (v11_code) — Es가 복사본
- "ATA us == opp" 류의 대칭 관찰

**액션 (P0, 코드 영역 — 본 문서 범위 밖이나 선행되어야 함)**: runner의 task2 obs 주입을 enm 관점으로 분리하거나, 최소한 분석 도구가 ACMI per-object만 신뢰하도록 전환. 이 수정 전에는 어떤 "per-agent 평형" 결론도 신뢰 불가.

---

## 1. "representation 한계"가 binding이 아니라는 직접 증거

같은 5×9×5 bin 안에 hdg=0/8(±90° 급선회)·vel=0(감속)이 멀쩡히 존재한다. 그런데 stalemate에서 우리 봇은 그걸 *안 고른다*.

**adaptive_eagle vs aggressive (1500 step) 실제 우리 action 분포:**

| action | 분포 |
|---|---|
| `action_hdg` | **4(직진) 91%** / 8:3% / 3:3% / 나머지 0% |
| `action_vel` | **4(풀가속) 93%** / 3:6% |
| `active_node` | LeadPursuit 61% / Accelerate 35% |

→ 우리 봇은 1500스텝 내내 **직진+풀가속**으로 비행했다. 양쪽 동일 airframe(F-16, Vmax genuine 동일 ~465kts)에서 직진+가속 = mutual extension at 580kts → 선회반경 거대 → 영원히 못 가리킴. **bin이 부족한 게 아니라 policy가 직진도주로 degenerate**한 것. hdg=8(급선회)+vel=0(감속, corner speed로 bleed)을 골랐다면 다른 결과가 가능했음.

**adaptive_eagle vs defensive (921 step):**

| action | 분포 |
|---|---|
| `action_hdg` | 0:47% / 8:31% / 4:6% (급선회 양방향 진동) |
| `active_node` | LeadPursuit 55% / HeadOnBreak 35% |
| 결과 | min dist **139ft** 도달, 그러나 WEZ **2틱**, dmg 0.2 |

→ 여기선 실제로 급기동해서 **139ft까지 붙었다**. 문제는 representation이 아니라 *근접을 sustained tracking으로 전환 실패* (hdg 0↔8 진동 = 매 tick 재평가 jitter로 추적 곡선 불안정).

**핵심**: aggressive = 너무 안 기동(extension degenerate), defensive = 기동하나 추적 불안정. 둘 다 22.5° 해상도와 무관. 22.5°는 기체 G-limit/roll-rate가 명령보다 느리게 반응하므로 애초에 binding이 될 수 없다.

---

## 2. 클러스터별 root cause + 해결 설계

### 클러스터 C-1 — aggressive (high-speed mutual extension)

- **Root cause**: 양쪽 580kts 고속 → 선회반경 거대 + 우리 policy가 LeadPursuit/Accelerate로 직진+가속만 선택 → 영원히 pointing 안 됨. **에너지/속도 관리 부재** + 교전 commit 실패.
- **설계 (E-fight → corner speed 강제)**:
  - **조건**: `dist > 6000ft` AND `|closure| < 50kts` AND `CAS > 500kts` AND `40 tick no_dmg` (high-speed neutral extension 감지).
  - **action**: 2-phase committed —
    1. **Bleed (20 tick lock)**: `vel=0`(idle/감속) + `hdg=8 또는 0`(적 방향으로 hard turn, sign = relative_bearing) → corner speed(~330kts F-16)로 bleed하며 선회반경 최소화. lock하여 매tick jitter 방지.
    2. **Convert**: bleed 후 CAS<400 되면 일반 cost dispatch 복귀하되 vel을 corner 근처(vel=2)로 bias.
  - **근거**: 동속 airframe에서 turn fight 승리 = 더 작은 반경. 반경 ∝ V². 고속 유지하면 절대 못 가림. K6(corner speed)의 강화판이며 **commit(lock)**이 핵심.
  - **주의**: 적도 같은 logic이면 co-corner-speed 2-circle로 회귀 가능 → 그땐 vertical(아래 v10 설계)과 결합.

### 클러스터 C-2 — defensive (근접하나 추적 전환 실패)

- **Root cause**: 139ft까지 붙지만 hdg 0↔8 진동으로 추적 곡선 불안정 → WEZ(ATA<12, 500-3000ft) 진입 순간을 못 잡음. 매 tick 재평가 jitter.
- **설계 (tracking lock / fire-dwell, K5 재활성 정밀화)**:
  - **조건**: `ATA < 25` AND `직전 5 tick 연속 ATA 하강 추세` AND `500 < dist < 3000`.
  - **action**: lead pursuit 곡선 **10 tick soft-lock** — hdg을 `relative_bearing` 추종으로 고정하되 bin 진동 억제(직전 hdg와 ±1 bin 이내로 rate-limit). vel=2(corner) 고정.
  - **근거**: 근접은 이미 됨(139ft). 필요한 건 안정. bin rate-limiting은 representation을 *줄이는* 게 아니라 jitter 제거. K5가 J12에서 high variance(+taken 37)였던 이유는 lock 중 무방비 → 조건에 `our threat 없음`(적 ATA로의 정렬 위험 낮음) gate 추가.

### 클러스터 B — v51 (offset spiral, 두 원 중심 다름)

- **Root cause**: 두 항공기가 서로 다른 중심으로 spiral → 절대 합쳐지지 않음(min dist 3000ft+). K4(vertical commit)는 J10에서 **-28.8 net으로 역효과 확정** → vertical은 답이 아님.
- **설계 (lateral center-walking / lag displacement)**:
  - **조건**: B_offset 자동분류(circle fit center_dist 큼) OR `30 tick dist std < 1000` AND `ATA mean > 60` AND `closure ≈ 0`.
  - **action**: **횡방향 center 이동** — 적 원 중심 방향으로 lag displacement roll: hdg을 *적 위치가 아니라 적의 미래 곡선 안쪽(lag point)*으로 commit + vel=2(반경 축소). 우리 원의 중심을 적 중심 쪽으로 "걸어서" 이동시켜 두 원을 수렴.
  - **계산**: lag point = 적 현재 위치에서 적 회전 방향 반대로 offset각 적용. 적 회전방향은 ACMI HDG 부호(d HDG/dt)로 추정.
  - **근거**: offset spiral은 평면 내 *중심 분리* 문제. 해법은 평면 내 횡방향 수렴이지 vertical이 아니다(K4 실패가 증명). pursuit_chase의 ∇V continuous policy(`continuous_policy.py`)가 이 lag-displacement를 연속으로 산출 가능 → 양자화는 마지막에만.

### 클러스터 D — ace (inside-outside lane, 에너지/반경)

- **Root cause**: baseline에선 +21dmg(inner lane 진입 성공)였으나 H10에서 0으로 깨짐. ACMI상 ace가 vertical 활용(alt 4500→7500m), HDG 반대부호(2-circle). 에너지/반경 경쟁.
- **설계 (inner-lane 회복, K6+K2 결합)**:
  - **조건**: 적 turn radius < 우리(circle fit R_opp < R_us) AND center_dist 작음(co-centric).
  - **action**: vel=1~2로 **corner speed 미만까지 감속 → 반경 축소 → inside 진입**. inside 진입 후 ATA 정렬되면 C-2의 tracking lock으로 인계.
  - **근거**: H10이 baseline의 inner-lane 진입을 깬 회귀(regression). baseline force_OffensivePursuit + 감속 조합이 작동했음 → H10에서 무엇이 그걸 막았는지 ablation 필요(아래 검증).
  - **재검증 필수**: "ace HDG 반대부호/omega mirror" 결론은 §0 버그 영향권 → ACMI per-object HDG로 재확인.

### 클러스터 A' — v10 (figure-8 위상 항상 반대, 대칭 평형)

- **Root cause**: 거울대칭 figure-8, phase 항상 180° → Nash형 평형. catch window가 구조적으로 안 열림. **이건 진짜 평형이라 깨려면 능동적 대칭 파괴 필요**.
- **설계 (committed symmetry-breaking perturbation, K2 정밀화)**:
  - **현 K2 문제**: 직진 10 tick(hdg=4,vel=4) 후 cooldown 80. 섭동이 너무 약하고/짧을 수 있음.
  - **개선**: phase_diff std < 30°(fully synced) 40tick 감지 시 → **비대칭 섭동**: vertical(alt=4) + 감속(vel=1)을 *동시에* 15 tick lock. 평면 내 직진(현 K2)은 적도 따라하면 다시 sync → out-of-plane + 속도변화의 *조합*이 mirror를 깨기 쉬움.
  - **검증**: 섭동 후 phase_diff가 실제로 shift되는지 ACMI HDG로 측정(섭동 전후 d(HDG_us−HDG_opp)).
  - **주의**: v10은 8개 중 가장 "본질적 평형"에 가까움. win 전환이 안 되면 **draw 유지가 합리적**(loss 안 나는 게 중요). 무리한 섭동이 loss로 가지 않게 gate.

### 클러스터 — v6h5a, v6h5b, v6h_e1c (분산/noise 케이스)

- **Root cause**: 구조적 stalemate **아님**. K_HYPOTHESES 자체 기록: v6h5b는 H9에서 25.3dmg ↔ H10에서 0 ↔ baseline 0.1로 가설별 큰 변동. J12 noise 분석도 std가 큼(K5 ±25.7). → **policy 분산 문제**.
- **설계 (robustness, 코드 변경 최소)**:
  - **즉시**: 이 3개를 "미해결 stalemate"에서 분리. 1 run 결과로 draw 판정한 것이 문제 → **각 5 run 이상 측정**해 평균이 win 쪽인지 확인. 평균이 양수면 이미 해결된 것.
  - **분산 감소**: 매 tick 재평가 jitter가 분산의 주원인으로 의심됨(C-2와 동근원) → 위 tracking lock / bin rate-limit이 분산도 동시에 줄임.
  - **근거**: 8개를 한 묶음으로 본 게 오류. 3개는 measurement noise이지 stalemate가 아닐 가능성 높음.

---

## 3. 검증 계획 (실매치 없이 가능한 정적/분석 검증 우선)

> 환경 제약: dogfight2 엔진 실매치는 게임 서버 필요 → 이 컨테이너에서 미실행 가정. 아래는 코드/데이터로 검증 가능한 항목.

1. **§0 데이터 버그 (P0)**: runner.py task2 obs 주입 추적 → enm 관점 분리. 수정 후 동일 ACMI로 meta CSV 재생성해 A≠B 확인.
2. **분류 재검증**: `plot_match_3d_v2.py`(ACMI 기반, 신뢰 가능)로 8개 각각 재분류. meta CSV 의존 결론 폐기.
3. **Z3 trigger 검증**: 각 신규 maneuver의 trigger 조건(C-1/C-2/B/D/A')을 `sub_situation_z3.py` 패턴으로 reachability + disjointness 증명 → if-then 충돌 방지(J10에서 ALL K 조합이 +0.4로 충돌했던 재발 방지).
4. **continuous_policy 단위테스트**: B(lag displacement), C-2(lead tracking)를 `continuous_policy.py`의 ∇V 산출 → bin 양자화 경로로 단위테스트(엔진 불필요).
5. **실매치 측정 프로토콜**: 각 maneuver를 **격리 toggle**로 H10 baseline 위에 추가, **opp당 5 run** (J10/J11의 1-run이 분산에 속았던 교훈). net mean ± std 보고.

---

## 4. 우선순위 (영향 × 실현가능성)

| 순위 | 항목 | 기대효과 | 비고 |
|---|---|---|---|
| **P0** | §0 데이터 버그 수정 | 진단 신뢰성 전체 | 선행 필수. 이거 없이는 측정이 거짓말 |
| **P1** | v6h5a/b/e1c 5-run 재측정 | 3 draw가 이미 win일 수 있음 | 코드 0, 측정만. 최저비용 최고 ROI |
| **P2** | C-1 aggressive E-fight (corner bleed lock) | extension degenerate 직접 해결 | 가장 명확한 policy 버그 |
| **P3** | C-2 + 분산 공통: tracking lock / bin rate-limit | defensive 전환 + 분산 동시 감소 | 두 문제 한 수정 |
| **P4** | B v51 lateral center-walking | offset spiral | continuous_policy 활용 |
| **P5** | D ace inner-lane (감속 진입) | baseline +21 회복 | H10 regression ablation 선행 |
| **P6** | A' v10 committed perturbation | 가장 어려움 | draw 유지가 차선. loss 방지 gate 필수 |

**한 줄 결론**: 8 DRAW는 "5×9×5 한계"가 아니라 — 1개 데이터 버그(P0), 3개 측정 분산(P1), 2개 policy degenerate(P2/P3), 2개 tactic 부재(P4/P5), 1개 진짜 평형(P6)이다. representation을 늘리기 전에 위 6개를 처리하면 대부분 win/robust-draw로 전환 가능하다.
