# Adaptive Combat BT — 설계 계획서

> 최초 작성: 2026-04-05
> 최종 갱신: 2026-04-08 (Phase 4 감사 + 실전 테스트 결과 반영)
> 목표: **"적의 현재 전술 상태를 인식하고 최적 대응으로 전환하는 BT"**

---

## 0. 요약 (현재 상태 스냅샷)

| 항목 | 내용 |
|---|---|
| adaptive_eagle 버전 | v4.6 |
| vs eagle1 승률 (단발) | ~63% (소표본 평균) |
| vs eagle1 승률 (50연전) | 38% ← EIM 드리프트 문제 |
| 주요 기동 | ExtensionBreak + Accelerate + LeadPursuit |
| EIM 기여도 | 낮음 (HeadOnBreak 매치당 0-1회 발동) |
| 핵심 미해결 | 온라인 EIM 프로토타입 드리프트 불안정 |

---

## 1. 전체 아키텍처

```
┌──────────────────────────────────────────────────────────────────┐
│  LAYER 1: 인식 — EIM (Enemy Intent Model)                         │
│                                                                  │
│  적 obs 20-step trajectory                                        │
│      └─► ProtoNet (GRU + Attention) → intent 예측                │
│          {GUN_ATTACK, PURSUIT, DEFENSIVE, ENERGY,                │
│           NEUTRAL_CIRCLE, NEUTRAL_SCISSORS}                      │
│                                                                  │
│  현재 정확도: 81.7% (episode acc, 6-way ProtoNet)                │
│  [주의] eagle1 자기 관측 기준 분류 → DEFENSIVE로 과분류 중         │
└──────────────────────────────┬───────────────────────────────────┘
                               │ shared_state (매 스텝)
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  LAYER 2: 결정 — Adaptive BT (adaptive_eagle v4.6)               │
│                                                                  │
│  우선순위 Selector 7-branch 구조:                                  │
│  1. HardDeckAvoidance   → ClimbTo(3000ft)                        │
│  2. GunEngagement       → GunAttack                              │
│  3. IntentAdaptiveEscape → HeadOnBreak (EIM+기하학 융합)          │
│  4. CircularOrbitBreak  → Accelerate                             │
│  5. CloseCombat         → LeadPursuit                            │
│  6. DefensiveEscape     → ExtensionBreak                         │
│  7. LeadPursuit (기본)                                            │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  LAYER 3: 실행 — BT Action Nodes                                  │
│                                                                  │
│  이산 action space: 5(alt) × 9(hdg) × 5(vel) = 225 조합          │
│  → JSBSim 6DOF 물리 엔진                                          │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. Phase 4 감사 결과 — 발견된 버그 및 수정 사항

### BUG-1: 각도 단위 불일치 ✅ 수정됨

**파일**: `src/match/runner.py`

**증상**: `_tracker1.update(obs2)` — blackboard obs의 각도 필드(ata_deg 등)는 라디안이지만,
EIM encoder의 NORM_MEAN/STD는 도(degree) 기준으로 학습됨. (예: NORM_MEAN[ata_deg]=90°)
→ ATA=57°(1라디안) → 정규화 시 `(1.0-90)/60 = -1.483` (정상: `(57-90)/60 = -0.545`) = 2.7× 오차

**수정**:
```python
_ANGLE_KEYS = ("ata_deg", "aa_deg", "hca_deg", "tau_deg", "relative_bearing_deg")
def _to_deg(obs):
    out = dict(obs)
    for k in _ANGLE_KEYS:
        if k in out and out[k] != "":
            try: out[k] = float(out[k]) * 180.0
            except: pass
    return out
_tracker1.update(_to_deg(obs2))  # 라디안 → 도 변환 후 입력
```

### BUG-2: EIM → BT 연결 누락 ✅ 수정됨

**파일**: `examples/adaptive_eagle/adaptive_eagle.yaml`

**증상**: adaptive_eagle v3에 EIM 인프라는 구축됐으나, YAML에 `EnemyIntentIs` 조건이 없어
EIM 예측값이 BT 결정에 전혀 반영되지 않음. "적응형" BT가 실제로는 순수 기하학 BT였음.

**수정**: v4.0에서 `IntentAdaptiveEscape` 브랜치 추가 (EnemyIntentIs + IsCircularOrbit → HeadOnBreak)

### BUG-3: BFM 서브분류 누락 ✅ 수정됨

**파일**: `src/intent/online_tracker.py`

**증상**: 학습 데이터에는 `UNK_NEAR_OFF`, `UNK_SCISSORS`, `UNK_DISENGAGING` 서브클래스가
사용됐으나, 추론 시에는 항상 `UNKNOWN` → 3개 BFM 피처가 항상 0 → 표현 불일치

**수정**: `_enrich_bfm()` static method 추가하여 추론 시에도 서브분류 주입

### BUG-4: 컴파일된 IsCircularOrbit 오버라이드 ⚠️ 신규 발견, 미수정

**증상**: Python 커스텀 `IsCircularOrbit` 클래스는 매치 중 **한 번도 호출되지 않음**
→ MatchCore.pyd의 컴파일된 `IsCircularOrbit`이 YAML params를 무시하고 사용됨
→ 실측 발동 조건: `|closure_rate_kts| < 200 AND dist > 2000 ft` (ATA 범위 체크 없음)
→ ATA = 35~85° 파라미터가 실제로는 적용되지 않고, ATA=112~173° 상황에서도 발동됨

**영향**: IntentAdaptiveEscape(branch3)의 IsCircularOrbit도 동일한 컴파일 버전 사용
→ 우리 설계의 ATA 필터 무효화. 발동 범위가 원래 의도보다 훨씬 광범위함.

### BUG-5: EIM 분류 대상 불일치 ⚠️ 신규 발견, 미수정

**증상**:
```
설계 의도: eagle1이 NEUTRAL_CIRCLE 의도 → EIM 탐지 → HeadOnBreak 발동
실제 상황: tracker1이 obs2 (eagle1 자신의 blackboard obs)를 분석
          → eagle1 자신의 ATA가 고각(~95°)이므로 EIM이 DEFENSIVE로 분류
          → EnemyIntentIs(NEUTRAL_CIRCLE) 발동률 <10% (100 tick 중 10회)
```

**근본 원인**: EIM은 "에이전트 자신의 obs"로 "자신의 행동 의도"를 분류하도록 학습됨.
eagle1의 self-obs에서 ATA=95°는 eagle1이 방어적 위치에 있음을 의미 → DEFENSIVE 분류.
우리가 의도한 "eagle1의 LeadPursuit = NEUTRAL_CIRCLE 공전" 패턴과 불일치.

---

## 3. adaptive_eagle 버전별 이력

| 버전 | 주요 변경 | 10라운드 결과 |
|---|---|---|
| v3.x | 순수 기하학 BT (EIM 미연결) | ~50% (불안정) |
| v4.0 | EIM 연결 + IsCircularOrbit 200kts | BUG 다수 |
| v4.1 | DefensiveEscape 추가 | 50% 첫 달성 |
| v4.2 | ExtensionBreak (결정론적) | 5/0/5 |
| v4.3 | ta_max=180 (너무 넓음) | 0/10/0 무승부 |
| v4.4 | RLInspiredAttack fallback | **0/0/10 패배** |
| v4.5 | LeadPursuit fallback 복귀 | 23/40 ≈ 57% |
| **v4.6** | **EnemyIntentIs NEUTRAL_CIRCLE** | **불안정 (38~80%)** |

**v4.4 패배 원인 분석**:
- `RLInspiredAttack`은 `tau_deg * 180 = +90°` → `heading_idx=8` (우측 강선회)
- 적이 왼쪽(rel_b=-90°)에 있을 때 반대 방향으로 선회 → 즉시 방어 기하학 악화
- Eagle1은 `heading=0` (좌측 = 적 방향)으로 각도 우위 확보 → 1라운드도 못 이김

**v4.6 불안정 원인 분석**:
- `update_online()` 매 50 step 호출 → 50라운드 × 1500 step / 50 = 1500회 프로토타입 업데이트
- 누적 드리프트로 NEUTRAL_CIRCLE 프로토타입이 변형 → 발동 조건 불안정화
- 소표본(20라운드)에서는 초기 배치 효과로 16/4=80%, 대표본(50라운드)에서는 19/50=38%

---

## 4. 실전 기동 분석 (1500-step 매치 상세)

### 주요 분기 발동 횟수 (대표 1회)
```
LeadPursuit      1294 steps (86%) ← 기본 행동
ExtensionBreak    162 steps (11%) ← 방어 탈출 핵심
Accelerate         38 steps  (3%) ← 공전 이탈
HeadOnBreak         0 steps  (0%) ← EIM 브랜치 미발동
GunAttack           0 steps  (0%) ← WEZ 진입 미달
```

### 매치 시퀀스 (승리 케이스)
```
Step 0-5:   대칭 공전 시작 (ATA=90°, 쌍방 LeadPursuit)
Step 6-22:  ExtensionBreak 발동 (ATA 90→117°, AA 90→10°, dist 3300→6600ft)
Step 23-47: 재진입 (LeadPursuit, eagle1 오버슈트 시작)
Step 48-67: 공격적 접근 (ATA 45°→2°, closure 134→454 kts)
Step 68+:   다중 접근-퇴각 사이클 (LeadPursuit 지배)
Step 431-434: Accelerate 발동 (IsCircularOrbit: ATA 75-83°, closure 106-196 kts)
Step 529-533: WEZ 진입 (ATA 22-36°, dist 2000-3000ft) → 데미지 축적
결과: eagle1 HP=96.9 < adaptive_eagle HP=98.4 → 승리
```

### 승리 메커니즘 요약
1. `ExtensionBreak`: eagle1이 추격할 때 반대 방향 선회(vel=4) → eagle1 오버슈트 유도
2. `Accelerate`: 공전 상태에서 속도 변화 → 기하학 비대칭 생성
3. `LeadPursuit`: 재진입 후 WEZ 기회 탐색
4. EIM HeadOnBreak: **실질적 기여 없음** (BUG-4/5로 인해 미발동)

---

## 5. EIM 파이프라인 상태

### 데이터 수집 현황
```
logs/metadata/ 총 CSV: 5,183개
  - arch_gun_attack_* (40종): 1,120개
  - probe_gun_aggro/close:     325개
  - 기타:                    3,738개
```

### 클래스 분포 (현재 학습 모델 기준)
```
GUN_ATTACK         3,718   ████         ← 병목! 목표 200K+
PURSUIT           11,774   ████████████████████████
DEFENSIVE         15,000   ██████████████████████████████ (상한)
ENERGY             9,893   ████████████████████
NEUTRAL_CIRCLE    15,000   ██████████████████████████████ (상한)
NEUTRAL_SCISSORS   3,415   ███████
총                58,800
```

### 실전 EIM 예측 검증 결과
```
테스트 조건: eagle1 LeadPursuit 행동 (50 tick, 10 tick 간격 예측)
입력: eagle1 자신의 blackboard obs (ATA 95°, closure ≈ 0)
결과: DEFENSIVE 57% 신뢰도 (예상: NEUTRAL_CIRCLE)

올바른 입력 (adaptive_eagle 관점의 eagle1):
입력: ATA = 90-115° (적 추정 공전 위치)
결과: NEUTRAL_CIRCLE 57% → 이것이 의도한 분류
```

**결론**: tracker1이 eagle1의 self-obs를 관측하는 현재 방식으로는
eagle1의 LeadPursuit 행동이 NEUTRAL_CIRCLE로 분류되지 않음.
올바른 구현: **adaptive_eagle의 obs1에서 eagle1 관련 필드만 추출하여 tracker1에 공급**

---

## 6. 핵심 미해결 과제 및 다음 단계

### [P0] EIM 온라인 드리프트 안정화

**문제**: `update_online(alpha=0.03, n_min=10)` 매 50 step 호출
→ 장기전(50라운드 이상)에서 프로토타입 변형 → 승률 불안정

**방안 A (즉시 적용)**: runner.py에서 `update_online()` 호출 비활성화
```python
# 현재 (매 50 step):
if step % 50 == 0:
    _tracker1.update_online(n_min=10, alpha=0.03)
# 제안: 주석 처리하거나 n_min을 매우 높게 설정
```

**방안 B**: 매치 종료 시에만 업데이트 (EMA, alpha=0.01, n_min=50)

### [P0] tracker1 입력 소스 수정

**문제**: `_tracker1.update(_to_deg(obs2))` — obs2는 eagle1 자신의 관점
**수정**: eagle1에 대한 관측을 adaptive_eagle 관점에서 구성

```python
# 현재 (eagle1 자신의 obs):
_tracker1.update(_to_deg(obs2))

# 제안: adaptive_eagle이 eagle1을 바라보는 관점 (ATA 미러)
# obs1의 ata_deg, aa_deg, closure_rate_kts, distance_ft를 사용
# (이미 라디안→도 변환됨)
enemy_obs_from_ego = {k: v for k, v in _to_deg(obs1).items()
                      if k not in ('agent_id',)}
_tracker1.update(enemy_obs_from_ego)
```

이렇게 하면 eagle1의 LeadPursuit 공전 패턴이 ATA≈90°, closure≈0 → **NEUTRAL_CIRCLE 57%** 분류 가능

### [P1] IsCircularOrbit Python 버전 활성화

**문제**: MatchCore.pyd의 컴파일된 IsCircularOrbit이 Python 버전을 오버라이드
**방안**: 조건 노드 이름을 변경하거나 다른 이름으로 래핑
```python
class OurCircularOrbitDetector(IsCircularOrbit):  # 다른 이름 사용
    pass
```
또는 YAML에서 `name: OurCircularOrbit`으로 변경하고 `__init__.py`에 등록

### [P1] 재공격 기동 강화

**문제**: ExtensionBreak 이후 LeadPursuit(vel=3)로 복귀 — eagle1과 동일한 행동
**개선**: AO < 45° (공격 기하학) 감지 시 vel=4 추가 추진으로 WEZ 진입 가속
```yaml
# 새 브랜치 (branch 6과 7 사이 추가):
- type: Sequence
  name: OffensivePursuit
  children:
    - type: Condition
      name: IsOffensivePrime        # AO < 45° + TA > 100°
    - type: Action
      name: RLInspiredAttack        # vel=4 + tau-based heading
```
**주의**: RLInspiredAttack은 방어 기하학(AO>90°)에서 heading 계산 오류 발생 확인됨
→ IsOffensivePrime(AO<45°) 조건 필수로 방어 상황 제외

### [P2] GUN_ATTACK 데이터 보강

현재 방식의 한계: 단순히 매치 수를 늘려도 GUN_ATTACK 레이블은 거의 증가 안 함
→ `active_node = GunAttack`인 찰나의 스텝만 포착됨

```
Option A: 레이블 확장
  → in_wez=True + ata_deg < 45° 스텝도 GUN_ATTACK으로 레이블
  → 매치당 수십 스텝 → 722 gun matches × ~50 = ~36K 추가 예상

Option B: WEZ 진입 전조 N스텝 포함
  → GunAttack 발동 직전 5-10스텝을 GUN_ATTACK으로 레이블

Option C: intent 에이전트 신규 생성
  → 전체 매치 80%+ 동안 GunAttack 발동하는 특수 에이전트 설계
```

---

## 7. 검증 기준 (업데이트)

| 지표 | 현재 | 목표 |
|---|---|---|
| vs eagle1 승률 (안정, 50라운드) | 38% | 65%+ |
| vs eagle1 승률 (소표본, 10라운드) | ~63% 평균 | 70%+ |
| HeadOnBreak 발동률 | ~0/match | 10+/match |
| EIM NEUTRAL_CIRCLE 정확도 | (eagle1 self-obs 기준) DEFENSIVE 분류 | NEUTRAL_CIRCLE 55%+ |
| GUN_ATTACK 학습 데이터 | 3,718 | 200K+ |
| EIM episode acc | 81.7% | 85%+ |

---

## 8. 파일 구조 (현재 상태)

```
src/intent/
  ├── encoder.py          ✅ Attention GRU
  ├── proto_net.py        ✅ 6-way ProtoNet
  ├── online_tracker.py   ✅ 온라인 few-shot + _enrich_bfm (BUG-3 수정)
  ├── shared_state.py     ✅ runner↔BT 통신
  ├── bt_nodes.py         ✅ EnemyIntentIs 등
  └── bt_nodes.py         ✅ EnemyIntentIs 등

examples/adaptive_eagle/
  ├── adaptive_eagle.yaml  ✅ v4.6 (LeadPursuit + NEUTRAL_CIRCLE EIM)
  └── nodes/
      ├── custom_actions.py    ✅ HeadOnBreak, RLInspiredAttack, ExtensionBreak
      └── custom_conditions.py ✅ IsCircularOrbit*, IsDefensiveGeometry*, EnemyIntentIs

src/match/
  └── runner.py           ✅ BUG-1 수정 (라디안→도 변환), 온라인 업데이트

* Python 버전이 MatchCore.pyd 컴파일 버전에 오버라이드됨 (BUG-4)
```

---

## 9. 데이터 수집 인프라

| 도구 | 목적 |
|---|---|
| `tools/collect_gun.py` | GUN_ATTACK 집중 수집 (280 matches) |
| `tools/collect_phase1.py` | 전체 phase1 수집 (182+ matches) |
| `tools/train_intent_model.py` | EIM 학습 (6-way ProtoNet) |
| `tools/query_lag_policy.py` | LAG 정책 그리드 쿼리 (1,008 상태) |
| `tools/distill_lag_dt.py` | LAG → Decision Tree 증류 |

---

## 10. LAG 정책 분석 결과 (참조)

### 보상함수 (최적 전술 포지션의 수학적 정의)
```
Reward = f(AO, TA) × f(R)
목표: AO→0 (적 조준), TA→π (적이 등을 보임), R≈3km (사거리 내)
= Superior Position의 정의
```

### 핵심 규칙 (lag_dt_rules.json 기반)
```
HEAD_ON:        OFFENSIVE_DIVE 66.7% → alt_idx=1, vel_idx=4
OFFENSIVE_PRIME: OFFENSIVE_DIVE 66.7% → alt_idx=1, vel_idx=4
DEFENSIVE:      NEUTRAL_FAST   83.3% → alt_idx=2, vel_idx=4
```
→ 모든 상황에서 **최고속(throttle avg 0.87+)** 유지가 핵심
