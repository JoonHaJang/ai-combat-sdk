# BT → 새 엔진 → JSBSim 관계 (tutorial)

> **목적**: BT(`cost_branch_selector`)가 어떤 명령을 내리면 JSBSim에서 어떤 결과가 나오는지
> — 실측 전달함수(transfer function). 이걸 알아야 cost 기반 결정을 설계할 수 있다.
> 측정 코드: `engine/analyze_transfer.py` (재현 가능). RNN §10 맵의 새-엔진 버전.

---

## 0. 전체 파이프라인

```
BT (cost_branch_selector)              "무엇을 하고 싶다" (전술)
   │  Tactic enum (13개)
   ▼
guidance.py                            tactic + obs → 연속 setpoint
   │  Setpoint(psi*_deg, h*_ft, v*_kts)   ← 단위: °/ft/kts
   ▼
autopilot.py                           단위변환(°/ft/kts → rad/ft/fps)
   │  Outer PI/P → theta_cmd, phi_cmd, thr   + Inner LQR
   ▼
JSBSim F-16 (120Hz)                    조종면 → 6-DOF 물리
   │  [aileron, elevator, rudder, throttle]
   ▼
결과: heading 변화, 고도 변화, 속도 변화
```

**핵심**: BT는 *연속 setpoint*(목표 heading/고도/속도)만 주면 된다. bin(5×9×5) 없음.
구체 조종면은 autopilot+LQR이 결정론적으로 계산.

---

## 1. 측정된 전달함수 (실측, alt 15000ft / 350kts 기준)

### A. 선회 (heading 명령 → 선회율)

| 명령 | 결과 선회율 | 대칭성 |
|---|---|---|
| 우선회 (psi\* = +방향) | **+4.84 °/s** | |
| 좌선회 (psi\* = −방향) | **−5.04 °/s** | 비대칭 **4.0%** ✅ |

→ **좌우 대칭**. (RNN §10은 좌−13/우+10 = ~30% 비대칭 → 진영 불균형 원인이었음.
  새 엔진은 LQR이 대칭이라 **진영 무관**.)
→ 지속 선회율은 `MAX_PSI_RATE`(기본 9°/s)로 제한 — corner-speed 기동 보호.

### B. 속도 (v\* 명령 → 실제 속도)

| 명령 v\* | 30s 후 vc | 변화 |
|---|---|---|
| 250 kts | 311 | **−119 (감속)** |
| 300 kts | 366 | −65 |
| 350 kts | 430 | ±0 (유지) |
| 400 kts | 493 | +62 |
| 420 kts | 517 | **+86 (가속)** |

→ **단조 증가 = 속도 제어 가능. 감속도 됨.**
  (RNN §10은 throttle 바닥 고정 → 감속 불가였음. 새 엔진은 throttle이 제어입력 → **감속 가능**.)
  ※ 표는 TAS(kts). v\*=350(CAS) → 430(TAS)는 15000ft 고도 변환이라 정상.

### C. 수직 (h\* 명령 → 상승/강하율)

| 명령 Δh | 상승률 |
|---|---|
| +3000 ft | **+151.8 ft/s** |
| +1500 ft | +151.8 ft/s |
| −1500 ft | −185.5 ft/s |
| −3000 ft | **−185.5 ft/s** |

→ **부호대로 상승/강하**. 수직 기동(yoyo, immelmann류) 물리적으로 가능.
  상승률은 명령 크기보다 기체 성능에 포화 (큰 Δh든 작은 Δh든 최대 상승률).

### D. heading 응답 선형성

| 명령 Δψ | 10s 후 잔여오차 |
|---|---|
| +10° | −5.6° |
| +30° | −16.3° |
| +60° | −31.9° |
| +90° | −51.8° |

→ 작은 명령은 빨리 정착, 큰 명령은 선회율 한계로 시간 더 걸림(포화). 방향·비례성 정상.

---

## 2. Tactic → setpoint 매핑 (BT가 고를 13개)

각 Tactic이 어떤 setpoint를 만드는지 (guidance.py, TACTIC_SPEC.md §4):

| Tactic | psi\* | h\* | v\* | 결과 거동 |
|---|---|---|---|---|
| `LEVEL_FLIGHT` | 현 heading | 현 고도 | trim 350 | 직진 |
| `PURE_PURSUIT` | heading+rel_b | 현 고도 | 유지 | 적 향해 직진 |
| `LEAD_PURSUIT` | heading+lead | 현 고도 | +가속 | 적 앞 조준 |
| `LAG_PURSUIT` | heading+rel_b·0.5 | 적−500 | 유지 | 적 뒤 선회유지 |
| `ONE_CIRCLE` | −sign(적선회)·90° | 현 고도 | corner | 반대선회 |
| `TWO_CIRCLE` | +sign(적선회)·90° | 현 고도 | corner | 동일선회 |
| `HIGH_YOYO` | 현 heading | +3000 | −40 | 상승+감속 |
| `LOW_YOYO` | 현 heading | −2000 | +40 | 강하+가속 |
| `BREAK_TURN` | −sign(rel_b)·90° | 현 고도 | corner | 방어 break |
| `EXTENSION` | heading+180° | 현 고도 | 최대 | 이탈가속 |
| `GUN_TRACK` | 연속 lead | 적 고도 | −10 | 정밀조준 |

→ **BT는 이 enum 하나만 고르면 됨.** 나머지는 guidance가 obs로 자동 계산.

---

## 3. cost_branch_selector 가 결정할 때 알아야 할 것

1. **명령이 결과로 이어짐이 보장됨** (위 A~D 실측). 그래서 cost는 *"이 tactic을 고르면 이런
   궤적이 나온다"* 를 신뢰하고 설계 가능.
2. **좌우 대칭** → 진영별 cost 분기 불필요 (RNN때와 달리).
3. **감속 가능** → 에너지 관리 tactic(HIGH_YOYO, GUN_TRACK 감속)이 실제로 작동.
4. **선회율 한계 9°/s** → cost가 "급선회로 즉시 정렬" 같은 비현실 가정 금지.
5. **결정론** → 같은 obs+tactic → 같은 결과. cost 평가가 재현 가능.

---

## 4. RNN §10 vs 새 엔진 (요약)

| 항목 | RNN (§10) | 새 엔진 (실측) |
|---|---|---|
| 감속 | ❌ 불가 (throttle 바닥) | ✅ 가능 (v\*↓→감속) |
| 좌우 선회 | ❌ 비대칭 30% | ✅ 대칭 4% |
| 수직 | 비대칭만 | ✅ 대칭 상승/강하 |
| 분해능 | 5×9×5 bin (실효 21) | ✅ 연속 |
| 설명가능 | ❌ 블랙박스 | ✅ LQR 게인 명시 |
| 결정론 | 평균수렴 | ✅ 결정론 |

---

## 5. 재현 / 갱신

```bash
python engine/analyze_transfer.py    # 전달함수 재측정 (이 표 갱신)
python engine/replay.py              # 결정론 검증 + ACMI 출력
python control/verify.py             # 단위·부호·안정성 L1~L5
```

**원칙**: 엔진/제어기 변경 시 이 전달함수를 재측정하고 표를 갱신한다 (§10 맵과 동일 철학).
