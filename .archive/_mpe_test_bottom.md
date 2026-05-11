alt:     연속 alt_cont → {−1, 0, +1}  (하강/유지/상승)

저고도 안전: ego_alt < 500ft → alt = +1 강제
```

---

## 8. sim_dogfight_verify — 1:1 전황별 시뮬레이션 검증

> 파일: `examples/adaptive_eagle_v11_code/sim_dogfight_verify.py`  
> 목적: 순수 Python 물리 모델로 adaptive_eagle_v11_code BT를 전황별로 검증

### 8.1 HP 교환 비율 모델 — 승리 판정 방식

"첫 WEZ 진입 = WIN"이 아니라 **누가 더 오래 상대를 사격 위치에 두는가**로 판정:

```python
# 매 틱 누적
own_gun_ticks   += 1  if is_victory(geo) else 0
enemy_gun_ticks += 1  if is_enemy_win(geo) else 0

def is_victory(geo):
    """우리가 사격 가능한 조건."""
    dist_max = 4000.0 if geo["aa"] > 45.0 else 3000.0  # Extended WEZ
    return (geo["ata"] < 12.0
            and 500.0 < geo["dist"] < dist_max
            and geo["closure"] > 0.0)

def is_enemy_win(geo):
    """적이 우리를 사격 가능한 조건."""
    return (geo["aa"] < 12.0
            and 500.0 < geo["dist"] < 3000.0
            and geo["closure"] > 0.0)

# 최종 판정 (60틱마다 + 종료 시)
if own_gun_ticks > enemy_gun_ticks × 1.5 AND own_gun_ticks >= 5:  → "WIN"
elif enemy_gun_ticks > own_gun_ticks × 1.5:                       → "LOSS"
else:                                                              → "DRAW"
```

**Extended WEZ (AA > 45°)**: 꼬리-chase 상황에서 `dist_max = 4000ft`로 확장.  
근거: AA=180°는 적기가 나를 조준할 수 없는 완전한 후방 상황 → 정확도 향상 + 반격 없음.

### 8.2 전황 구역 분류 (Z1~Z6)

| 전황 | 이름 | ATA 범위 | 핵심 특징 |
|---|---|---|---|
| **Z1** | Gun Shot Opportunity | 0~12° | 사격 가능 위치, WEZ 진입 |
| **Z2** | Offensive Chase | 12~45° | 적 전방 확보, PN 추격 중 |
| **Z3** | Neutral Turning Fight | 45~110° | 선회 교착 / orbit / scissors |
| **Z4** | Defensive Geometry | 110~140° | 적이 우리 후방 진입 |
| **Z5** | Lost Pursuit | 140~180° | ATA 크고 closure 음수 (최악) |
| **Z6** | Energy Management | ATA 무관 | 에너지 결핍 상황 |

### 8.3 BT 브랜치 선택 로직 (select_bt_branch)

```python
def select_bt_branch(geo, avg_cl, own_spd=300.0, alt=8000.0):
    ata, aa, dist, cl, hca = ...

    if alt < 1200.0:
        return "HardDeckAvoidance"          ← 저고도 우선

    # Extended WEZ + 확장 HCA gate (TCA 부분 반영)
    dist_gun_max = 4000.0 if aa > 45.0 else 3000.0
    if ata < 12.0 and 500 < dist < dist_gun_max:
        if hca < 30.0 or hca > 150.0 or aa > 45.0:
            return "GunEngagement"          ← 사격 (HCA gate 3가지 조건)

    if ata < 45.0 and aa > 100.0 and dist < 4000.0:
        return "OffensivePursuit"           ← 적 후방 확보 상태

    if 35.0 <= ata <= 110.0 and abs(cl) < 200.0 and dist > 3000.0:
        return "CircularOrbitBreak"         ← 교착 감지 → 가속 탈출

    if ata > 140.0 and dist > 2000.0:
        return "LostPursuitReverse"         ← Z5 역전 기동

    if ata < 20.0 and dist > 3000.0 and cl < 20.0 and own_spd > 380.0:
        return "ScissorsBreak"              ← 고속 tail-chase 교착 탈출

    if avg_cl <= 0.0:
        return "StaleChaseBreak"            ← 장기 stale 감지

    if dist < 3000.0:
        return "CloseCombat"               ← 근접전

    if ata > 90.0 and aa < 70.0:
        return "DefensiveEscape"           ← 방어 기하학

    return "LeadPursuit"                   ← 기본 fallback
```

### 8.4 주요 BFM 기동 구현

#### N=0 Pure Pursuit (꼬리-chase 수렴 가속)

tail-chase(ATA<15°, dist>3000ft)에서 `N=0`으로 전환:

```python
if ata < 15.0 and dist > 3000.0:
    d_hdg, _ = pn_cmd(own, geo, N=0.0)   # pure pursuit
    accel = -15.0 if own.speed > CORNER_SPD and cl < 20.0 else 20.0
```

**물리 원리**: 두 PN 추격자(N=3 각각)는 안정적 원형 궤도(limit cycle)를 형성한다. N=0(현재 적 위치로 직접 조향)으로 변경하면 대칭이 깨져 나선형 수렴이 시작된다.

#### LostPursuitReverse (Z5 역전 기동)

ATA>140°, closure<0, dist>2000ft인 완전 역전 상황에서 2단계 BFM:

```python
# Phase 1: 스피드브레이크 → 적 오버슈트 유도
if phase == "speedbrake":
    d_hdg = 0.0          # 기수 고정 (회전하지 않음)
    accel = -MAX_ACCEL   # 최대 감속 → 적이 앞질러 지나가게

# Phase 2: 적 방향으로 하드턴 (각도 컷)
elif phase == "hardturn":
    err = ang_diff(bear, own.hdg)
    d_hdg = max(-MAX_TR, min(MAX_TR, err / (DT × 1.0)))
    accel = MAX_ACCEL    # 최대 가속 + 급선회
```

**BFM 교리**: Z5 역전 = "적 방향으로 하드턴(각도 컷)". 적 반대 방향으로 이탈하면 계속 ATA=180°로 수렴 — 틀린 기동. "시저스 기동은 neutral 선회전에서 쓰는 간보기 기동"이므로 Z5에서는 부적절.

#### CircularOrbitBreak (교착 탈출)

ATA∈[35°,110°], |closure|<200kts, dist>3000ft인 교착 상황:

```python
# 그냥 가속 (BT의 Accelerate 액션 매핑)
accel = MAX_ACCEL
# → closure -7kts → +200kts 즉시 역전 (T08에서 증명)
```

#### ScissorsBreak (고속 tail-chase 교착)

ATA<20°, cl<20kts, own_spd>380kts인 고속 정체 상황:

```python
# 적에 수직인 방향으로 선회 (측면 이격 생성)
perp = (bear ± 90.0) % 360.0   # 가까운 수직 방향
err = ang_diff(perp, own.hdg)
d_hdg = max(-MAX_TR, min(MAX_TR, err / (DT × 1.0)))
accel = -15.0 if own.speed > CORNER_SPD else 5.0   # corner speed로 감속
```

> **주의**: 시저스 기동은 중립 선회전의 간보기 기동. tail-chase 교착에서는 보조 수단으로만 사용 (cl<20kts인 극단적 정체 상황에만 발동).

### 8.5 시뮬레이션 결과 (2026-04-27)

175개 시나리오 (Z1~Z6 × 4개 적 정책):

| 결과 | 수 | 비율 |
|---|---|---|
| **WIN** | **166** | **95%** |
| DRAW | 9 | 5% |
| LOSS | 0 | 0% |

#### 잔여 DRAW 9개 — 수학적 분석

모두 `× offensive` 정책 상황. 물리적 한계로 인한 DRAW:

| 시나리오 | HP | 원인 |
|---|---|---|
| z1_headon × offensive | 11/11 | 완전 대칭 기하 → HP 동률 |
| z4_fast_enm × offensive | 0/0 | 비수렴 |
| z5_entry/typical/deep/tail/longrange × offensive | 0/0 | 물리적 불가 (↓) |
| z6_e_z5_entry/typical × offensive | 0/0 | 에너지 열위 + Z5 |

**Z5 × offensive: 왜 300틱 안에 불가능한가**

```
초기 상태: dist=9493ft, cl=+95kts (적이 우리를 추격)

closure 감쇠 (offensive 적 정책이 PN N=3으로 지속 추격):
  t=0:   cl=+95kts
  t=100: cl=+45kts  (적기 방향 변화로 LOS 성분 감쇠)
  t=236: cl=+1kts   (사실상 정체)

236틱 동안 총 이동거리 ≈ 3832ft
최종 dist = 9493 − 3832 = 5661ft

Extended WEZ(4000ft)에도 5661 > 4000 → 진입 불가
필요 틱 수: ≈ 463틱  →  시뮬 한도 300틱 초과
```

**근본 원인**: MAX_SPD=420kts 동일 → 추월 불가. LostPursuitReverse는 적의 PN 추격을 상쇄하기엔 물리적으로 역부족.

### 8.6 BT 브랜치 구조 (adaptive_eagle_v11_code.yaml)

```yaml
ROOT (Selector) — 우선순위 순
├── HardDeckAvoidance        ← alt < 1200ft → ClimbTo 3000ft
├── GunEngagement            ← ATA<12°, Extended WEZ, HCA gate (3조건)
├── OffensivePursuit         ← ATA<45°(적이 내 전방), AA>100°(나는 적 후방), dist<4000 → PNLeadPursuit
├── CircularOrbitBreak       ← 35<ATA<110, |cl|<200, dist>3000 → Accelerate
├── TacticalLookup           ← data-driven (tactical_lookup.json)
├── CounterGunRun            ← GUN_RUN intent → SmartBreakTurn
├── CounterClosing           ← CLOSING intent → SmartHighYoYo
├── CounterExtending         ← EXTENDING intent → SmartLowYoYo
├── CounterClimbing          ← CLIMBING intent → SmartLowYoYo
├── CounterDiving            ← DIVING intent → SmartHighYoYo
├── CounterOrbiting          ← ORBITING intent → PNLeadPursuit
├── LostPursuitReverse       ← ATA>140°, cl<-100, dist>2000 → HeadOnBreak
├── StaleChaseBreak          ← 30틱 평균 cl≤0 → SmartHighYoYo
├── CloseCombat              ← dist<3000 → PNLeadPursuit
├── DefensiveEscape          ← ATA>90°(적이 내 후방), AA<70°(적이 나를 향함) → ExtensionBreak
└── LeadPursuit              ← 기본 fallback
```

---

## 9. 수학적 승리 증명 (proof_of_win.py)

> 파일: `examples/adaptive_eagle_v11_code/proof_of_win.py`  
> 실행: `python3 examples/adaptive_eagle_v11_code/proof_of_win.py`  
> 결과: **91/91 PASSED (100%)**

### 9.1 승리 집합 V

$$
V = \{\, \text{ATA} < 12^{\circ} \;\text{AND}\; 500 < \text{dist} < 3000\,\text{ft} \;\text{AND}\; \text{closure} > 0 \,\}
$$

V에 진입 = GunEngagement 발동 = 사격 가능.

### 9.2 증명 구조

$$
\text{state } S \;\xrightarrow{\tau}\; \text{mode select} \;\xrightarrow{A}\; S' \quad \Rightarrow \quad d(S', V) < d(S, V)
$$

"다음 상태가 승리 집합에 더 가까워져야 한다" — 각 전황에서 이 조건이 성립함을 보임.

### 9.3 10개 정리 (Theorems)

| 정리 | 내용 | 체크 | 결과 |
|---|---|---|---|
| T01 | BT 브랜치 도달 가능성 — 모든 전황에 대응 브랜치 존재 | 12 | ✅ 12/12 |
| T02 | BT 우선순위 비중복성 — 경계 정확히 분리됨 | 10 | ✅ 10/10 |
| T03 | τ_threat 단조성 — Z5 > Z4 > Z3 > Z2 > Z1 | 9 | ✅ 9/9 |
| T04 | τ_opportunity 단조성 — Z1 > Z2 > Z3 > Z4 > Z5 | 7 | ✅ 7/7 |
| T05 | τ_energy 사이클 — 결핍→ENERGY→회복→복귀 루프 작동 | 8 | ✅ 8/8 |
| T06 | τ_pursuit 선회율 반응 — 선회율 반영, 2-circle lag-roll 확인 | 6 | ✅ 6/6 |
| T07 | Z2→Z1 수렴 — PN N=4에서 28틱(5.6초) 내 V 진입 가능 | 8 | ✅ 8/8 |
| T08 | Z3 탈출 — CircularOrbitBreak → closure 즉시 역전 | 12 | ✅ 12/12 |
| T09 | Z4/Z5 생존 — DEFEND → τ_threat 64~67% 감소 → Z3 복귀 | 7 | ✅ 7/7 |
| T10 | 상태 공간 커버 — 4D 그리드 600셀 전부 결정 존재 | 12 | ✅ 12/12 |
| **합계** | | **91** | **✅ 91/91** |

### 9.4 핵심 증명 결과 발췌

#### T07: Z2→Z1 수렴 (물리 방정식)

PN guidance 미분방정식:
$$\frac{d(\text{ATA})}{dt} = -N \cdot \frac{V_{\text{ego}} \cdot \sin(\text{ATA})}{\text{dist}}$$

ATA=35°, dist=4000ft, V=300kts, N=4 → dATA/dt = **16.6°/s** → V 진입: **28틱(5.6초)**

| 시나리오 | ATA | dist | closure | V 진입 |
|---|---|---|---|---|
| Z2 전형 | 35° | 4000ft | 80kts | 28틱(5.6s) |
| Z2 근접 | 30° | 3500ft | 100kts | 14틱(2.8s) |
| Z2 원방 | 45° | 5000ft | 60kts | 55틱(11.0s) |

#### T08: Z3 탈출

CircularOrbitBreak 발동 후: closure −7kts → +200kts 즉시 역전. orbit 탈출 후 Z2 복귀 → V 진입 45틱(9.0s).

#### T09: Z4/Z5 생존

| 전황 | τ_threat 초기 | τ_threat 이후 | 변화 |
|---|---|---|---|
| Z4 (ATA=125°) | 0.548 | 0.197 | −64% |
| Z5 (ATA=160°) | 0.703 | 0.230 | −67% |

#### T10: 상태 공간 커버

4D 그리드 (ATA×closure×dist×e_diff) 200 BT셀 × 3 에너지 = 600 모드셀:

| 전황 | 우세 모드 | 비율 |
|---|---|---|
| Z1 | PURSUE | 83% |
| Z2 | PURSUE | 54% |
| Z3 | PURSUE | 61% |
| Z4 | PURSUE | 59% |
| Z5 | DEFEND | 59% |

---

## 10. BFM 교리 기반 Red Team 분석

> 출처: AETC TTP 11-1, Boyd E-M Theory, DTIC AD1130933 등  
> 목적: 현실 BFM 교리 대비 현재 구현의 누락 요소 식별

### 10.1 🔴 HIGH — 전술 판단에 직결

#### Turn Radius / Turn Rate 비교 없음

**교리 근거**: "Turn radius is determined by airspeed and load factor. An aircraft with smaller turn radius can create and solve problems better."

**현재 구현**: `energy_diff`와 `Ps`만 있음. 실시간 선회반경 계산 없음.

**영향**: 1-circle fight에서 선회반경 우위/열위 판단 불가. Z2 추격 타이밍의 불확실성.

**수정 방향**:
```python
# Layer 0에 추가
turn_radius_own = ego_vc_kts**2 / (g × tan(bank_angle))  # ft
corner_margin = ego_vc_kts - 350.0                         # corner speed 기준 여유
```

#### Pursuit Mode 판별 없음

**교리 근거**: Lag pursuit(오버슈트 방지), Pure pursuit(현위치 조준), Lead pursuit(적 앞 조준)의 명확한 구분.

**현재 구현**: `tc_type=="2-circle"`로 N 감소(lag-roll)를 부분 구현했으나, 실시간 pursuit mode 판별 로직 없음.

**영향**: 오버슈트 타이밍의 오판 가능성.

#### Control Zone 개념 없음

**교리 근거**: Control zone = 2000ft aft ±20° ~ 4000ft aft ±40°. 최적 공격 준비 위치.

**현재 구현**: `in_39_line`을 ATTACK 모드에서 N 보너스에 활용하지만, 본격적인 control zone 판별은 없음.

### 10.2 🟡 MEDIUM — 성능 최적화에 영향

#### Aspect-Dependent WEZ — 부분 구현 완료

**교리**: AA=0°(적 후방) → WEZ 범위 더 넓음.

**현재 구현**: AA>45°이면 WEZ를 4000ft로 확장 (sim_dogfight_verify.py) ✅.  
단, 본체 custom_actions.py에는 아직 미반영.

#### E-M 코너속도 최적화 — ENERGY 모드에 부분 구현

**현재 구현**: `if ego_spd > corner+80: vel = min(vel, 2.5)` — 기본 코너속도 클램프 구현 ✅.  
단, E-M Diagram(속도별 지속 선회율 곡선) 전체는 미반영.

### 10.3 현재 구현 상태 종합

| 항목 | 교리 중요도 | 현재 반영 |
|---|---|---|
| Turn Radius Ratio | 🔴 Critical | ❌ 없음 |
| Pursuit Mode 판별 | 🔴 Critical | △ tc_type만 |
| Control Zone | 🔴 Critical | △ in_39_line 보너스만 |
| Track Crossing Angle (HCA gate) | 🔴 Critical | ✅ GunEngagement gate 구현 |
| Aspect-Dependent WEZ | 🟡 High | △ sim만 구현, 본체 미반영 |
| E-M 코너속도 최적화 | 🟡 High | ✅ ENERGY 모드 구현 |
| 2-circle lag-roll | 🔴 Critical | ✅ PURSUE 모드 구현 |
| Lateral Displacement | 🟡 High | ❌ 없음 |

---

## 11. Superplan: PhaseController & 어택큐

> **상태**: 설계 완료, 미구현. HCCA v12 검증 후 진행 예정.

### 11.1 반응형 AI의 한계

현재 HCCA v12는 매 틱 τ에 반응. 문제:

```
반응형: 관찰 → 분류 → 대응 → (반복)  ← 매 3~5틱 모드 전환 → orbital lock
선제형: 목표 결정 → 단계 실행 → 조건 달성 → 다음 단계
```

데이터 증거:
- `eagle2`: dist<5000ft 후 LeadPursuit 50+ 틱 고정 → WR 98.4%
- 우리(v9): 매 3~5틱 전환 → orbital lock

### 11.2 어택큐 (Attack Queue) — BFM 교리

공중전은 **단일 목표(WEZ 진입+사격)를 향한 순차 진행**이다.

```
Phase 1  ENERGY      → e_diff > 1500ft, Ps > 0 달성
Phase 2  POSITION    → ATA < 55°, alt_advantage 달성
Phase 3  ATTACK_RUN  → dist < 3000ft, ATA < 15° 진입
Phase 4  FIRE        → 사격
Phase 5  BREAK       → 이탈, 에너지 회복

[INTERRUPT] τ_threat > 0.75 → 즉시 DEFEND, 해소 시 복귀
```

### 11.3 PhaseController 전이 조건

| 전이 | 조건 |
|---|---|
| ENERGY → POSITION | `e_diff > 1500 AND Ps > 0` |
| POSITION → ATTACK_RUN | `ATA < 55° AND alt_advantage` |
| ATTACK_RUN → FIRE | `dist < 3000 AND ATA < 15°` |
| FIRE → BREAK | `dist < 500 OR 20틱 경과` |
| BREAK → ENERGY | `dist > 6000 AND closure < 50` |
| POSITION → ENERGY (후퇴) | `score_energy < 0.35` |
| ATTACK_RUN → POSITION (후퇴) | `ATA > 70° OR e_diff < −2000` |

### 11.4 7-브랜치 BT 구조 (목표)

```
ROOT (Selector)
├── [1] HardDeckSafety        ← 저고도 불변조건
├── [2] GunWEZ                ← 즉시 사격 조건
├── [3] DefendInterrupt       ← τ_threat > 0.75
├── [4] PhaseController       ← 핵심: 어택큐 순차 실행
├── [5] ForcingAction         ← 수동적 상대 forcing (stale > 20틱)
├── [6] OrbitBreak            ← 교착 탈출 (|closure| < 80kts)
└── [7] SafetyFallback        ← LeadPursuit
```

기존 48 노드 → **7 브랜치** (~28 파라미터 → CMA-ES 최적화 가능)

### 11.5 성공 기준

| 기준 | 목표 |
|---|---|
| 전체 WR | > 66.7% (v11_code baseline) |
| vs defensive | 0% → ≥ 33% |
| vs eagle2 | 0% → ≥ 33% |
| 어떤 상대도 | v11_code 대비 −20pp 이하 없을 것 |

---

## 12. 다음 스프린트 & 로드맵

### 12.1 현재 상태 (2026-04-27)

| 항목 | 상태 |
|---|---|
| Sprint A: 측정 인프라 (schema 1.0, Wilson CI) | ✅ 완료 |
| Sprint B: Hypothesis Miner 4종 통합 | ✅ 완료 |
| EIM ProtoNet 98.8% 정확도 | ✅ 완료 |
| HCCA v12 5-레이어 구현 | ✅ 완료 |
| proof_of_win.py 91/91 증명 | ✅ 완료 |
| sim_dogfight_verify WIN=166(95%) | ✅ 완료 |
| 데이터 축적: 4,242 매치 | ✅ 완료 |
| PhaseController 구현 | 🔲 미착수 |
| Universal WR 65% | 🔲 미달성 |

### 12.2 Sprint C — 데이터 확장 + Intent 학습 준비

```bash
# C-1. 클래스 분포 확인 (dry-run)
python tools/train_intent_model.py --data logs/metadata/ --dry-run

# C-2. Hypothesis Miner 재실행 (4242 매치 누적)
python tools/hypothesis_miner.py mine \
  --matches logs/knowledge/matches.jsonl --top-k 20
```

**Gate**: per-class ≥ 100 sample 확보.

### 12.3 Sprint D — EIM 학습

```bash
python tools/train_intent_model.py \
  --data logs/metadata/ \
  --output models/intent_model.pt \
  --episodes 2000 --k-shot 5
```

**Gate**: per-class accuracy ≥ 75%.

### 12.4 Sprint E — Counter Selector

1. `(intent_predicted, active_node, outcome)` 추출 → `intent_node_outcomes.jsonl`
2. Wilson CI로 per-intent best node 집계 → `counter_table.json`
3. Gate: Wilson lower ≥ 0.55, n ≥ 100

### 12.5 Sprint F — APPLY + Universal 검증

```bash
python tools/build_bt_from_counter_table.py \
  --counter-table logs/knowledge/counter_table.json \
  --output examples/adaptive_eagle_v7/adaptive_eagle_v7.yaml

python tools/adaptive_optimizer.py --validate \
  examples/adaptive_eagle_v7/adaptive_eagle_v7.yaml \
  --validate-rounds 10
```

**목표**: Universal WR ≥ **65%**

### 12.6 미해결 과제

| 과제 | 우선순위 | 비고 |
|---|---|---|
| Z5 × offensive DRAW (9개) | 🟡 중간 | 시뮬 한도 300→500틱 확장으로 해결 가능 |
| Turn Radius Ratio L0 추가 | 🟡 중간 | 갭#1 근본 해결 |
| control_zone 본체 반영 | 🟡 중간 | in_39_line 활용 확대 |
| PhaseController 구현 | 🟢 장기 | Sprint F 이후 |
| Universal WR 65% | 🔴 목표 | Sprint F 검증 |

---

## 13. 부록

### 13.1 파일 구조

```
ai-combat-sdk/
├── MASTERBOOK.md                              ← 이 문서 (유일한 정본)
├── CLAUDE.md                                  ← Claude Code 지침
├── README.md                                  ← 프로젝트 소개 (외부용)
├── examples/adaptive_eagle_v11_code/
│   ├── adaptive_eagle_v11_code.yaml           ← BT 구조 정의 (16 브랜치)
│   ├── nodes/
│   │   ├── custom_actions.py                  ← HCCA v12 구현 (L0~L4, 2459줄)
│   │   └── custom_conditions.py               ← BT 조건 노드
│   ├── sim_dogfight_verify.py                 ← 1:1 전황별 Python 시뮬 (979줄)
│   ├── proof_of_win.py                        ← 수학적 증명 91 assertions
│   └── poc_orbit_fix.py                       ← orbit 수정 검증 52 assertions
├── tools/
│   ├── hypothesis_miner.py
│   ├── train_intent_model.py
│   └── adaptive_optimizer.py
├── logs/
│   └── knowledge/
│       ├── tactical_lookup.json
│       └── matches.jsonl                      ← 4,242 매치 결과
└── src/match/runner.py                        ← 매치 실행기
```

### 13.2 설계 갭 이력 (수정 완료 항목)

| 갭 | 증상 | 수정 내용 | 상태 |
|---|---|---|---|
| B1: τ_opp 과포화 | 에너지 위기에서 PURSUE 오선택 | op_suppress 완화 로직 추가 | ✅ 완료 |
| B2: 원거리 ATTACK 오선택 | dist=7000ft에서 ATTACK 선택 | dist_decay 감쇠 추가 | ✅ 완료 |
| 갭#1: stale closure 조건 | closure=+20kts에서 stale 미발동 | abs(closure)<50 조건으로 변경 | ✅ 완료 |
| 갭#3: flat scissors 무한 PURSUE | closure±30kts 진동 시 탈출 불가 | τ_pu<0.65 임계값 상향 | ✅ 완료 |
| 갭#2: 2-circle lag-roll | lead pursuit 에너지 과소모 | tc_type 기반 N 감소 구현 | ✅ 완료 |
| GunEngagement HCA gate | head-on에서 사격 오시도 | hca<30° OR hca>150° OR aa>45° | ✅ 완료 |
| PURSUE stale orbit | orbit 교착 탈출 미발동 | dist>6000 sprint 조건 추가 | ✅ 완료 |
| GAP-Z45: DEFEND 오선택 | ATA<45°에서 방어 기동 | ata 범위별 모드 강제 전환 | ✅ 완료 |

### 13.3 이론 참고 문헌

| 출처 | 내용 |
|---|---|
| AETC TTP 11-1 | 미 공군 Fighter Fundamentals 공식 교범 |
| Boyd E-M Theory (1960s) | Energy-Maneuverability Theory |
| DTIC AD1130933 | Air Combat Maneuvers via Operations Research |
| Springer 2023 | Deep RL for Air Combat |
| AIAA I011234 | Manual-Based Automated Maneuvering Decisions |
| Springer Nature 2024 | Tactical Intent-Driven Autonomous Air Combat |

---

*이 문서는 프로젝트의 유일한 정본(Single Source of Truth)입니다.*  
*코드 변경 시 관련 섹션을 함께 갱신하십시오.*
