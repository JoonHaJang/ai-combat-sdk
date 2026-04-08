# Pipeline Audit — "적의 의도를 파악하고 적응형으로 상쇄시키는 1:1 도그파이트"

**감사 기준**: 의심 우선(adversarial) — 올바른 것만 올바르다고 판정.
**날짜**: 2026-04-07

---

## 파이프라인 전체 흐름

```
[collect_phase1.py]
     ↓  logs/metadata/*.csv (angle: degrees × 180)
[train_intent_model.py]
     ↓  models/intent_model.pt
[runner.py: OnlineIntentTracker]
     ↓  shared_state (intent, conf)
[bt_nodes.py: EnemyIntentIs / EnemyIntentConfidence]
     ↓  BT Condition
[adaptive_eagle.yaml: SelectStrategy → YAML Branch]
     ↓  blackboard.action
[MatchCore.pyd]
     → 실제 기동
```

목적과의 연결:
- **파악**: runner → tracker → shared_state → EnemyIntentIs → BT
- **적응형 상쇄**: EnemyIntentIs + SelectStrategy → 적 intent에 따른 분기 → 맞춤 action

---

## BUG-1: 각도 단위 불일치 — Train/Inference Mismatch (CRITICAL)

### 증거

**runner.py (CSV 쓰기, lines 397–401)**:
```python
"ata_deg": round(obs_i.get("ata_deg", 0) * 180.0, 4),  # 라디안 → 도
"aa_deg":  round(obs_i.get("aa_deg",  0) * 180.0, 4),
"hca_deg": round(obs_i.get("hca_deg", 0) * 180.0, 4),
"tau_deg": round(obs_i.get("tau_deg", 0) * 180.0, 4),
"relative_bearing_deg": round(obs_i.get("relative_bearing_deg", 0) * 180.0, 4),
```
→ CSV 저장값 = **도(degree)** 단위

**encoder.py (NORM_MEAN/NORM_STD)**:
```python
NORM_MEAN = {"ata_deg": 90.0, "aa_deg": 90.0, "tau_deg": 0.0, ...}
NORM_STD  = {"ata_deg": 60.0, "aa_deg": 60.0, "tau_deg": 60.0, ...}
```
→ 정규화 파라미터 = **도(degree)** 스케일로 설계됨

**runner.py (EIM 추론, line 348)**:
```python
_tracker1.update(obs2)   # obs2 = blackboard 원본 dict → 라디안 값
```
→ `obs_dict_to_tensor`에 **라디안** 값이 들어감

### 충격 계산 (예: ATA = 57.3°)

| 경로 | ata_deg 입력 | 정규화 결과 |
|---|---|---|
| 학습 (CSV) | 57.3 (도) | (57.3 − 90.0) / 60.0 = **−0.545** |
| 추론 (obs dict) | 1.0 (라디안) | (1.0 − 90.0) / 60.0 = **−1.483** |

**오차: 2.72배 이상.** 모델이 추론 시 완전히 다른 공간에서 동작함.

### 영향 범위

5개 angular feature 전부 오염:
`ata_deg`, `aa_deg`, `hca_deg`, `tau_deg`, `relative_bearing_deg`

전체 28개 feature 중 5개 = **17.9%** 오염.
그러나 이 5개는 적 의도 분류에 가장 핵심적인 기하학 feature임.

### 판정: ❌ EIM 추론 결과 신뢰 불가

---

## BUG-2: EIM이 adaptive_eagle BT에 연결되지 않음 (CRITICAL)

### 증거

**adaptive_eagle.yaml (v3)**:
```yaml
tree:
  type: Selector
  children:
    - HardDeckAvoidance   # BelowHardDeck → ClimbTo
    - GunEngagement       # 거리+ATA 조건 → GunAttack
    - CircularOrbitBreak  # IsCircularOrbit → Accelerate
    - CloseCombat         # DistanceBelow → LeadPursuit
    - Pursue              # fallback
```

EIM 관련 노드 (`EnemyIntentIs`, `EnemyIntentConfidence`, `EnemyIntentNot`, `SelectStrategy`) 중
YAML에서 사용되는 것: **없음 (0개)**

**nodes/__init__.py**는 import함:
```python
from .custom_conditions import IsCircularOrbit, EnemyIntentIs, EnemyIntentConfidence, EnemyIntentNot
```
→ 수입(import)만 되고 YAML에서 호출되지 않음.

### 목적과의 관계

"적의 의도를 파악하고 **적응형으로** 상쇄"에서 "적응형" 부분이 없음.

- runner.py에서 EIM은 매 스텝 돌아가고 있음 → intent 예측은 됨
- 그러나 BT가 그 예측값을 읽지 않음 → 예측이 아무 행동도 바꾸지 않음

### 판정: ❌ "파악"은 되지만 "적응형 상쇄"가 구조적으로 단절

---

## BUG-3: BFM 서브분류 Feature가 학습/추론 모두에서 Dead Weight

### 증거

**encoder.py BFM_CLASSES**:
```python
BFM_CLASSES = ["OBFM", "DBFM", "HABFM", "UNKNOWN",
               "UNK_NEAR_OFF", "UNK_SCISSORS", "UNK_DISENGAGING"]  # 7개
```

**런타임 obs dict의 bfm_situation**: MatchCore.pyd는 `OBFM / DBFM / HABFM / UNKNOWN` 4가지만 반환.

**학습 CSV의 bfm_situation 컬럼**: 역시 `OBFM / DBFM / HABFM / UNKNOWN` 4가지만.

→ `UNK_NEAR_OFF`, `UNK_SCISSORS`, `UNK_DISENGAGING`는 학습과 추론 모두에서 항상 **0**.

서브분류는 `train_intent_model.py`에서 *레이블 생성*에만 사용되고,
feature 벡터에는 절대 1이 들어가지 않음.

### 판정: ⚠️ 치명적 버그는 아니지만 7차원 중 3차원이 무의미 (정보 낭비 + 모델 혼란 가능성)

---

## BUG-4: SAE/TIR/WCS 데이터가 eagle2 vs eagle1 문제에 적용 불가

### 증거

**collect_phase1.py AGENTS 목록**:
```python
AGENTS = ["simple", "aggressive", "defensive", "eagle1", "ace", "viper1", "golden",
          "gen_rush", "gen_gunfighter", ...]
```
→ `eagle2`, `adaptive_eagle` 없음.

**분석 도구 결과** (`logs/analysis/summary_report.txt`):
- WCS, SAE, TIR → eagle1이 simple/aggressive/golden을 상대할 때의 통계
- "Scissors→Accelerate→OBFM TIR 51.6%" → eagle1 vs gen_breaker 등에서 측정된 것

**alpha2/adaptive_eagle 커스텀 노드의 데이터 근거**:
```python
# alpha2/nodes/custom_actions.py 주석:
# TIR: Scissors → Accelerate→OBFM 51.6% (LeadPursuit 20.8%의 2.5배)
# SAE: Disengaging → HighYoYo +0.016 (유일한 양수)
```
→ 이 TIR/SAE는 eagle2 vs eagle1 문제와 무관한 데이터에서 도출됨.

### 판정: ❌ Phase 1 → BT 노드 설계 근거로 사용된 것은 잘못된 적용

---

## BUG-5: NODE_TO_INTENT에서 Accelerate의 의미 충돌

### 증거

**proto_net.py**:
```python
NODE_TO_INTENT = {
    "Accelerate": "PURSUIT",   # viper1 custom
    ...
}
```

**adaptive_eagle.yaml v3**:
```yaml
- name: CircularOrbitBreak
  # IsCircularOrbit → Accelerate  ← 궤도 탈출 전술
```

`Accelerate`를 실행하는 adaptive_eagle의 intent는 **NEUTRAL_CIRCLE 탈출** (anti-deadlock).
그러나 EIM 학습 레이블에서 `Accelerate` = **PURSUIT**.

→ adaptive_eagle이 Phase 1 수집 대상에 포함될 경우 이 스텝들이 PURSUIT으로 잘못 레이블됨.
→ 현재는 adaptive_eagle이 AGENTS에 없어 직접 영향 없으나, 미래 파이프라인 확장 시 오염.

### 판정: ⚠️ 현재는 잠재적 문제. 미래 수집 시 오염 위험.

---

## 올바른 것들 (adversarial 검증 통과)

### ✅ 1. BT → blackboard.action 연결

HeadOnBreak 실험: alt 13,133ft avg (vs Pursue 13,919ft), 431kts (vs 303kts).
custom action 노드가 실제로 항공기를 제어함. MatchCore.pyd가 blackboard.action을 읽는 것 확인.

### ✅ 2. shared_state 의도 전달 체인 (논리 구조)

runner.py → tracker1/2 → shared_state → get_enemy_intent(ego_id) → bt_nodes.py.
BUG-1(단위 오류)를 제외하면 **논리 흐름은 올바름**.

구체적:
- `tracker1.update(obs2)` → agent2의 obs를 관찰 → agent2의 intent 예측 ✅
- `_shared.set_intent(enm_id, intent1, conf1)` → enm_id = agent2's ID에 저장 ✅
- `get_enemy_intent(agent1_id)` → `_AGENT_PAIR[agent1_id] = agent2_id` → returns intent of agent2 ✅

### ✅ 3. EIM 학습 레이블 전략 (BFM 기반)

`train_intent_model.py` 레이블 소스: `bfm_situation` (MatchCore가 기하학으로 결정).
BFM 상태는 두 기체의 상대 위치의 함수 → 상대가 누구든 같은 기하학 = 같은 상태.
→ eagle1의 BFM 레이블은 누구를 상대해도 기하학적으로 일관성 있음.

### ✅ 4. IsCircularOrbit 조건 로직

조건 자체(`ata_min ≤ ATA ≤ ata_max AND |closure| < threshold AND dist > min`)는
eagle2 vs eagle1 실측 데이터(ATA~57.9°, closure≈0) 기반. 로직 올바름.
파라미터(closure_abs_max=30kts) 튜닝 문제는 별개.

### ✅ 5. EIM 아키텍처 (ProtoNet + GRU + Attention)

few-shot 적응을 위한 ProtoNet 선택, 시계열 패턴을 위한 GRU, 중요 timestep 가중용 Attention.
목적(교전 중 실시간 적 의도 추적)에 적합한 아키텍처.
온라인 prototype 업데이트(EMA)도 설계 방향 올바름.

### ✅ 6. Phase 1 → EIM 학습 데이터

BFM 기반 레이블 + active_node 기반 레이블 조합.
다양한 에이전트 조합 → PURSUIT/DEFENSIVE/ENERGY/GUN_ATTACK/NEUTRAL 클래스 커버.
EIM 학습 목적으로 Phase 1 데이터는 유효.

---

## 목적과의 관계 매트릭스

| 목적 요소 | 구현 요소 | 상태 |
|---|---|---|
| 적 의도 **파악** | EIM (ProtoNet + GRU) | ✅ 아키텍처 올바름, ❌ 추론 시 각도 오염 |
| 의도 → BT 전달 | shared_state + bt_nodes | ✅ 논리 올바름 (BUG-1 수정 필요) |
| **적응형** 분기 | EnemyIntentIs + SelectStrategy | ❌ adaptive_eagle.yaml이 사용 안 함 |
| 상쇄 기동 | HeadOnBreak, Accelerate, etc. | ✅ 실제 기동 제어 확인됨 |
| 상쇄 근거 데이터 | SAE/TIR (Phase 1) | ❌ eagle2 vs eagle1 맥락 없음 |
| 교착 탈출 | CircularOrbitBreak | ✅ 로직 올바름, ⚠️ 파라미터 미조정 |

---

## 우선순위별 수정 계획

### P0 — 즉시 수정 (시스템 올바름의 전제조건)

**P0-A: EIM 추론 시 각도 변환 추가**

`runner.py`에서 tracker에 obs를 넘기기 전 각도 변환:
```python
# 수정 전
_tracker1.update(obs2)

# 수정 후
obs2_deg = {**obs2}
for k in ("ata_deg", "aa_deg", "hca_deg", "tau_deg", "relative_bearing_deg"):
    if k in obs2_deg and obs2_deg[k] != "":
        obs2_deg[k] = obs2_deg[k] * 180.0
_tracker1.update(obs2_deg)
```

또는: `encoder.py`의 NORM_MEAN/NORM_STD를 라디안 스케일로 변경 (학습-추론 양쪽 통일).

**P0-B: adaptive_eagle.yaml에 EIM 조건 연결**

목적("적응형 상쇄")을 달성하려면 EIM → BT 분기가 반드시 있어야 함.
최소 구현: `EnemyIntentIs(intent=PURSUIT)` 확인 후 counter-tactic 분기 추가.

### P1 — 검증 후 수정

**P1-A: eagle2 vs eagle1 전용 데이터 수집**

Phase 1에 eagle2 추가 후 분석 → BT 노드 설계 근거를 올바른 맥락으로 교체.

**P1-B: BFM 서브분류 정리**

`encoder.py` BFM_CLASSES에서 `UNK_NEAR_OFF/UNK_SCISSORS/UNK_DISENGAGING` 제거,
또는 classify_unknown_sub()을 online_tracker에 통합하여 실제로 활성화.

### P2 — 미래 작업

**P2-A: Accelerate NODE_TO_INTENT 맥락화**

adaptive_eagle의 Accelerate는 별도 intent 클래스 또는 NEUTRAL_CIRCLE로 분리.

---

## 결론

**현재 adaptive_eagle이 eagle1을 이기지 못하는 실제 원인:**

1. **EIM이 garbage input으로 작동** → 예측 신뢰도 낮음 → EIM-based 분기 없어도 무관하지만,
   BUG-2로 인해 EIM 분기가 YAML에 없으므로 어차피 EIM 예측이 전투에 영향 없음.

2. **adaptive_eagle은 실제로 "적응형"이 아님** — 기하학 기반 순수 BT 에이전트.
   eagle1도 LeadPursuit 기반 기하학 BT → Nash equilibrium에서 탈출 불가.

3. **CircularOrbitBreak(Accelerate)는 이론적으로 올바른 탈출 전략**이지만
   파라미터 및 BT 우선순위 구조가 실제로 발동되지 않게 구성되어 있을 가능성 있음.

**올바른 순서:**
1. BUG-1 수정 (각도 변환)
2. EIM 재학습 및 accuracy 재확인
3. adaptive_eagle.yaml에 EIM 분기 추가 (SelectStrategy 또는 EnemyIntentIs 직접 사용)
4. eagle2 vs eagle1 specific 데이터로 반응 전략 검증
