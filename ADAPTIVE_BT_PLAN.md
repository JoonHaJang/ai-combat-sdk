# Dogfight-aware BT Generator Platform — 설계 계획서 v7.0

> 최초 작성: 2026-04-05
> 최종 갱신: 2026-04-16 (v7.0: Trajectory EIM + 전체 파이프라인 현행화)
> 목표: **1:1 공중전 교전 결과로부터 적의 궤적 패턴에 따른 최적 대응을 자동 도출하는 BT generator platform 연구**
> 비유: Fuzzing framework의 1:1 dogfight-aware 버전

---

## 목차

1. [프로젝트 정의](#1-프로젝트-정의)
2. [문제 정의 & 성공 기준](#2-문제-정의)
3. [이론적 배경 (BFM + Trajectory Classes)](#3-이론적-배경)
4. [전체 파이프라인 — EXPLORE → LEARN → APPLY](#4-파이프라인)
5. [EIM 모델 상세 (Trajectory ProtoNet)](#5-eim-모델-상세)
6. [Counter Table — 관측값 전이 기반 결정기](#6-counter-table)
7. [Coverage Gap Detection & Opponent Generation](#7-coverage-gap)
8. [도구 카탈로그](#8-도구-카탈로그)
9. [실험 결과 & 가설 이력](#9-실험-결과)
10. [다음 단계](#10-다음-단계)
11. [부록](#11-부록)

---

## 1. 프로젝트 정의

### 1.1 연구 프레이밍

본 프로젝트는 **단일 BT를 만드는 것이 아니라 BT generator platform**을 연구한다.

- **대상**: 1:1 공중전 (dogfight), JSBSim 6DOF 물리 시뮬레이션
- **유사 framework**: Fuzzing — 입력(적 기동)을 체계적으로 탐색하여 취약점(패배/교착)을 발견하고 수정
- **핵심**: 과거 교전 데이터 → 가설 → 대규모 검증 → 적 궤적 분류 모델 → 카운터 선택 → 피드백 루프

### 1.2 한 문장 요약

> **적의 관측 궤적 패턴을 실시간 분류하고, 각 패턴에 대해 "어떤 관측값 변화를 달성해야 하는지"에 기반한 최적 BFM 기동을 선택한다.**

---

## 2. 문제 정의

### 2.1 왜 정적 BT로는 부족한가 (데이터로 증명)

H-E family 실험 (4 variants, 모두 REFUTED):
- 같은 BT 변경이 **어떤 상대에겐 +63 HP, 다른 상대에겐 -17 HP**
- 단일 분기로는 **Pareto trade-off 회피 불가**
- Jensen 부등식: $\mathbb{E}_o[\max_x f(x,o)] \geq \max_x \mathbb{E}_o[f(x,o)]$
- **Adaptive BT의 이론적 상한 > Static BT** — 데이터로 입증됨

### 2.2 성공 기준

| 지표 | 목표 | 현재 (v9) |
|---|---|---|
| 6 opp WR | ≥ 90% | **100% (18/18)** ✅ |
| EIM accuracy | ≥ 75% | **98.8%** ✅ |
| 695 풀 WR | ≥ 60% | 검증 대기 |
| 미지 상대 대응 | 관측 기반 | **궤적 분류 (노드 이름 무관)** ✅ |

---

## 3. 이론적 배경

### 3.1 BFM (Basic Fighter Maneuvers)

Shaw의 3대 분류:

```
OBFM (Offensive)    : Lead/Pure/Lag Pursuit, Gun Attack
HABFM (Head-on)     : 1-circle, 2-circle, Scissors
DBFM (Defensive)    : Break Turn, Extension, Last Ditch
```

### 3.2 관측 단위 규약

| 키 | 범위 | 변환 |
|---|---|---|
| `ata_deg`, `aa_deg`, `hca_deg` | 0~1 | `×180 → 도` |
| `tau_deg`, `relative_bearing_deg` | -1~1 | `×180 → 도` |
| `distance_ft`, `closure_rate_kts` | raw | 변환 불필요 |

> ⚠️ 이 규약 위반 = BUG-4 수준의 silent failure.

### 3.3 Trajectory Classes — BFM 물리에서 직접 도출 (B안)

**기존 Node-based intent** (A안, 73.7% accuracy):
- 적의 `active_node` → NODE_TO_INTENT 매핑 (예: LeadPursuit → PURSUIT)
- 문제: 같은 노드라도 파라미터에 따라 완전히 다른 행동. 미지의 상대에 무용.

**Trajectory-based intent** (B안, 98.8% accuracy):
- 적의 **관측 시퀀스 → 궤적 패턴** 직접 분류
- 노드 이름을 모르는 미지 상대에도 작동

| Trajectory Class | 판정 조건 | BFM 해석 | Counter |
|---|---|---|---|
| **CLOSING** | closure > +100 지속 | 적이 접근 중 | SmartHighYoYo (오버슈트 유도) |
| **EXTENDING** | closure < -100 지속 | 적이 이탈 중 | SmartLowYoYo (dive 가속) |
| **ORBITING** | \|closure\| < 50 + dist 안정 | 교착/선회 | LeadPursuit (포인팅 유지) |
| **CLIMBING** | alt 500ft+ 상승/window | 에너지 축적 | SmartLowYoYo (따라감) |
| **DIVING** | alt 500ft+ 하강/window | 에너지→속도 전환 | SmartHighYoYo (상승 회피) |
| **GUN_RUN** | dist < 1500 + ATA < 20° | 사격 시도 | SmartBreakTurn (긴급 회피) |

**왜 이게 더 좋은가**: 분류 대상이 "노드 이름"(이산, 외부 의존)이 아니라 "관측 추세"(연속, 자체 관측) → ProtoNet이 훨씬 쉽게 분리 (73.7% → 98.8%).

### 3.4 WEZ (Weapon Engagement Zone)

- Distance: 152 ~ 914 ft
- ATA: < 12°
- Base DPS: 25
- Hard Deck: 1,000 ft 이하 즉시 패배

### 3.5 Wilson Score Interval

$$
\text{CI}_{95\%} = \frac{\hat{p} + \frac{z^2}{2n} \pm z\sqrt{\frac{\hat{p}(1-\hat{p})}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}, \quad z=1.96
$$

| 매치 수 | CI margin | 의미 |
|---|---|---|
| 100 | ±10% | 단일 가설 검증 최소 |
| 695 | ±3.7% | layer별 진단 |
| 6,950 | ±1.18% | Universal claim |

---

## 4. 파이프라인 — EXPLORE → LEARN → APPLY

### 4.1 전체 흐름

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  ① EXPLORE (탐색)                                              │
│    collect_phase1.py → metadata CSV 수집                       │
│    hypothesis_miner.py → 가설 후보 자동 생성 (5 miners)        │
│    hypothesis_tracker.py → 가설 검증 + verdict 기록            │
│                        ↓                                       │
│              Validation Gate: 10+ 가설 CONFIRMED               │
│                        ↓                                       │
│  ② LEARN (결정기)                                              │
│    train_intent_model.py --label-mode trajectory               │
│      → Trajectory ProtoNet 학습 (98.8% acc)                   │
│      → models/intent_model_trajectory.pt                      │
│    counter_table 빌드 (CSV ground truth 집계)                  │
│      → logs/knowledge/counter_table.json                      │
│                        ↓                                       │
│  ③ APPLY (실전)                                                │
│    BT YAML: EnemyIntentIs[CLOSING] → SmartHighYoYo             │
│    Runtime: OnlineIntentTracker → 실시간 궤적 분류              │
│    매치 결과 → metadata CSV → EXPLORE로 feedback               │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 4.2 각 Stage 산출물

| Stage | 입력 | 도구 | 산출물 |
|---|---|---|---|
| **EXPLORE** | BT YAML + 상대 풀 | `collect_phase1.py` | `logs/metadata/*.csv` (per-tick 30 col) |
| | metadata CSV | `hypothesis_miner.py` | `hypothesis_queue.json` (가설 후보) |
| | 가설 후보 | `hypothesis_tracker.py` | `hypotheses.jsonl` (verdict) |
| **LEARN** | metadata CSV | `train_intent_model.py` | `intent_model_trajectory.pt` |
| | metadata CSV | counter_table builder | `counter_table.json` |
| **APPLY** | intent model + counter_table | BT YAML 생성 | `adaptive_eagle_v9.yaml` |
| | BT + 상대 | `evaluate.py` | WR + CI + replays |
| | 매치 결과 | `collect_phase1.py` | feedback → EXPLORE |

---

## 5. EIM 모델 상세 (Trajectory ProtoNet)

### 5.1 모델 아키텍처

```
입력: K-tick 관측 시퀀스 (K=20 = 4초)
  ↓
TacticalEncoder (GRU + Attention Pooling)
  ├─ GRU: input_size=28, hidden_dim=128, num_layers=2, dropout=0.1
  ├─ Attention: Linear(128 → 1) + softmax → 가중합
  └─ Projection: Linear(128→128→ReLU→Dropout→64) → L2 normalize
  ↓
Embedding: (batch, 64) — L2 정규화된 벡터
  ↓
Prototypical Classification:
  ├─ 각 class의 prototype = 학습 데이터 embedding 평균
  ├─ 추론: query embedding과 prototype 간 Euclidean distance
  └─ 가장 가까운 prototype의 class = 예측
```

### 5.2 입력 Features (28개)

```
연속형 (14): distance_ft, ata_deg, aa_deg, hca_deg,
             relative_bearing_deg, ego_altitude_ft, ego_vc_kts,
             specific_energy_ft, ps_fts, energy_diff_ft,
             closure_rate_kts, turn_rate_degs, alt_gap_ft, tau_deg

이진형 (7):  in_wez, enm_in_wez, in_39_line, overshoot_risk,
             energy_advantage, alt_advantage, spd_advantage

BFM one-hot (7): OBFM, DBFM, HABFM, UNKNOWN,
                 UNK_NEAR_OFF, UNK_SCISSORS, UNK_DISENGAGING
```

### 5.3 라벨링 방식 (B안 — Trajectory)

```python
def _trajectory_label(window_df, window_size):
    closure_mean = mean(closures)
    dist_mean = mean(dists)
    ata_mean = mean(atas)
    alt_delta = alts[-1] - alts[0]

    if dist_mean < 1500 and ata_mean < 20:  return "GUN_RUN"
    if closure_mean > 100:                   return "CLOSING"
    if closure_mean < -100:                  return "EXTENDING"
    if alt_delta > 500:                      return "CLIMBING"
    if alt_delta < -500:                     return "DIVING"
    return "ORBITING"
```

**핵심**: 적의 `active_node`를 모르는 미지 상대에도 작동. 관측 시퀀스만으로 판단.

### 5.4 학습 결과

| Metric | A안 (Node-based) | **B안 (Trajectory)** |
|---|---|---|
| 라벨 소스 | 적 active_node 이름 | **관측 궤적 패턴** |
| Classes | 6 (GUN_ATTACK/PURSUIT/...) | **6 (CLOSING/EXTENDING/...)** |
| Episode accuracy | 73.7% | **98.8%** |
| Prototype 전체 정확도 | - | **80.8%** |
| 미지 상대 작동 | ❌ (노드 이름 의존) | **✅ (관측만 사용)** |
| 학습 데이터 | 130,211 windows | **81,966 windows** |

### 5.5 Online Few-shot Learning (설계됨, 미활성화)

```python
# OnlineIntentTracker — 매치 중 prototype 점진 업데이트
tracker = OnlineIntentTracker.from_file("intent_model_trajectory.pt")

# 매 tick
tracker.update(enemy_obs)
intent, conf = tracker.current_intent()

# 매치 종료 후 (안전한 시점에서만)
tracker.update_prototypes_from_match(alpha=0.1, n_min=5)
tracker.save_prototypes("intent_model_trajectory.pt")
```

**현재 비활성화 이유**: BUG DRIFT — mid-match update가 prototype 불안정 유발. 매치 종료 후 batch update로 제한하여 안정성 확보 계획.

### 5.6 EIM → BT 연결

```yaml
# BT에서 EnemyIntentIs 조건으로 호출
- type: Sequence
  name: CounterClosing
  children:
    - type: Condition
      name: EnemyIntentIs       # → OnlineIntentTracker.current_intent()
      params:
        intent: CLOSING          # trajectory class 이름
        min_confidence: 0.50
    - type: Action
      name: SmartHighYoYo       # counter_table에서 선택
```

**Self-contained 제출**: `nodes/intent_model.pt` + inline `EnemyIntentIs` (src.intent 의존 없음). 대회 서버 upstream runner에서 작동.

---

## 6. Counter Table — 관측값 전이 기반 결정기

### 6.1 설계 원칙

> **"어떤 기동이 유리하다"가 아니라 "어떤 관측값 변화를 달성해야 하는데, 그걸 가장 빠르게 해주는 기동이 뭔가"**

### 6.2 Counter Mapping (BFM 물리 기반)

| 적 패턴 | 관측값 문제 | 필요한 변화 | Counter | 근거 (데이터) |
|---|---|---|---|---|
| **CLOSING** | closure↑, 적 접근 중 | closure 역전 → 오버슈트 유도 | SmartHighYoYo | WR 76%, n=4125 |
| **EXTENDING** | dist↑, 적 이탈 중 | 속도 회복 → 거리 좁힘 | SmartLowYoYo | WR 96%, n=1550 |
| **ORBITING** | ATA/AA 교착 | lead angle 유지 | LeadPursuit | WR 72%, n=803 |
| **CLIMBING** | 적 고도↑ | 따라가며 에너지 전환 | SmartLowYoYo | BFM 원칙 |
| **DIVING** | 적 하강 + 속도↑ | 상승 회피 | SmartHighYoYo | BFM 원칙 |
| **GUN_RUN** | 적 근접 + 포인팅 | 긴급 회피 | SmartBreakTurn | BFM Last Ditch |

### 6.3 Counter Table 데이터 구조

`logs/knowledge/counter_table.json`:
```json
{
  "CLOSING": {
    "best_node": "SmartHighYoYo",
    "observation_objective": "closure 역전 (+→-), ATA 역전",
    "wr": 0.76, "n": 4125
  },
  ...
}
```

---

## 7. Coverage Gap Detection & Opponent Generation

### 7.1 관측 공간 커버리지 (Miner 9)

4차원 관측 공간: ATA(6) × dist(5) × closure(4) × energy_diff(4) = **480 bins**

| 매치 수 | 커버된 bins | 비율 |
|---|---|---|
| 144 매치 | 57 | 11.9% |
| **695 매치** | **129** | **26.9%** |
| 목표 | 300+ | 60%+ |

### 7.2 매치 궤적 역추적 — "교착은 초반 20초에 결정"

695 매치 분석 결과:
- **DRAW 매치**: 초반 HeadOnBreak 46% + SmartHighYoYo 34% = 도망/climb → 거리 16,600ft 이격 → 교착
- **WIN 매치**: 초반 LeadPursuit 61% + Accelerate 31% = 적극 추격 → 거리 11,300ft → 교전 성공
- **분기점**: tick 100 (20초) — 여기서 추격 vs climb이 교착 여부를 결정

### 7.3 Gap → 상대 생성 (Coverage-driven Fuzzing)

```
Miner 9: 빈 관측 영역 자동 발견
  → "ATA 90-120° + dist 6000-10000" 에 데이터 없음
  → generate_opponent_pool.py L7 layer: 해당 관측 영역 강제하는 BT 생성
  → 매치 수집 → counter_table 확장 → EIM 재학습
```

---

## 8. 도구 카탈로그

### 8.1 현재 도구 (정리 완료 2026-04-16)

#### Data Collection
| 도구 | 역할 |
|---|---|
| **`collect_phase1.py`** | PRIMARY — per-tick CSV + result JSON 수집 (rglob 재귀) |
| `metadata_logger.py` | CSV 스키마 util |

#### Analysis & Knowledge
| 도구 | 역할 |
|---|---|
| `analyze_metadata.py` | CSV → SAE/TIR/WPP 등 통계 분석 |
| `analyze_acmi.py` | ACMI replay 기하학/에너지 분석 (시각화 보조) |
| `metadata_to_knowledge.py` | CSV → matches.jsonl 적재 (schema 1.0 + tagging) |

#### Hypothesis Generation & Testing
| 도구 | 역할 |
|---|---|
| **`hypothesis_miner.py`** | **5 miners 통합** (아래 상세) |
| `hypothesis_tracker.py` | 가설 등록 + 검증 매치 + verdict |

**통합 Miners (hypothesis_miner.py)**:

| Miner | Level | 역할 |
|---|---|---|
| **Miner 1** (Rigid Behavior) | tick CSV | 관측 변화 + action 고정 탐지 (5 패턴) |
| **Miner 2** (Outcome Discriminator) | match jsonl | WIN vs LOSS metric Cohen's d |
| **Miner 5** (Node Usage) | match jsonl | 과소/과대 발동 node |
| **Miner 8** (Tactical Delta) | tick CSV | ego vs enm 관측 차 (BFM 물리) |
| **Miner 9** (Coverage Gap) | tick CSV | 관측 공간 빈 영역 자동 발견 |

#### Training
| 도구 | 역할 |
|---|---|
| **`train_intent_model.py`** | ProtoNet 학습 (`--label-mode node\|trajectory`) |

#### BT Optimization
| 도구 | 역할 |
|---|---|
| `adaptive_optimizer.py` | CMA-ES (final polish) + `--validate` 전체 풀 검증 |
| `bt_templates.py` | BT YAML dict 생성 유틸 (`generate_bt_yaml`) |

#### Testing & Validation
| 도구 | 역할 |
|---|---|
| **`evaluate.py`** | PRIMARY — Wilson CI + per-opponent + replay 저장 |
| `test_suite.py` | 정적 BT 검증 (5 checks) |
| `validate_agent.py` | 제출 전 YAML 검증 |

#### Opponent Generation
| 도구 | 역할 |
|---|---|
| **`generate_opponent_pool.py`** | 695 직교 풀 (L1~L6) |
| `expand_archetypes.py` | 168 archetypes (ProtoNet balance) |
| `generate_agents.py` | 8 hypothesis-driven agents |

### 8.2 삭제된 도구 (정리 이력)

| 삭제 | 이유 | 대체 |
|---|---|---|
| `find_rigid_behavior.py` | hypothesis_miner Miner 1로 흡수 | `hypothesis_miner.py` |
| `bt_optimizer.py` (v2) | LHS 구버전, 아무도 import 안 함 | `adaptive_optimizer.py` |
| `bt_optimizer_v3.py` | 21D CMA-ES, `generate_bt_yaml`만 사용 | `bt_templates.py` |
| `hypothesis_list_builder.py` | 중복 생성 → 삭제 | `hypothesis_miner.py` |

---

## 9. 실험 결과 & 가설 이력

### 9.1 버전 진화

| 버전 | 핵심 변경 | 6 opp WR | 695 풀 WR |
|---|---|---|---|
| v5.1 | builtin LP + SmartGunAttack | 81.7% | - |
| v6.0-h1 | + purpose-driven 4 nodes + IsLostPursuit + IsChaseStale | 83.3% | - |
| v6.0-h2 | + IsLostPursuit 보수화 (140°, -100kts) | 83.3% (0L) | **54.96%** |
| v7 | + Node-based EIM (73.7%) + counter_table | **100%** | - |
| v8 | + StaleChaseBreak 거리 분할 | 22% ❌ | - |
| **v9** | **+ Trajectory EIM (98.8%) + BFM counter** | **100%** | **검증 대기** |

### 9.2 가설 검증 이력 (hypotheses.jsonl)

| ID | Statement | Verdict | Δ |
|---|---|---|---|
| H0 | rigid conditions > baseline | ✗ REFUTED | -6.7pp |
| H1 | IsLostPursuit dist>2000 | ✓ CONFIRMED | +25pp |
| H2 | IsLostPursuit 보수화 | ~ Pareto | ±0 |
| H3 | SmartHighYoYo → Accelerate | ✗ REFUTED | -44pp |
| H5a/b/c | L1 defensive draw | ✗ REFUTED | - |
| H-E1~E1d | Energy convert (4 variants) | ✗ ALL REFUTED | -2~-17pp |
| **B안** | **Trajectory EIM** | **✓ CONFIRMED** | **+16.7pp** (v6→v9) |

**핵심 교훈**: Single branch 수정은 Pareto trade. **Intent-based adaptation**만이 frontier 돌파 가능. Trajectory 라벨이 Node 라벨보다 25pp 더 정확.

### 9.3 자동 가설 생성 결과 (Miner 8, 144 매치)

- `enm_wez_pct` WIN > LOSS (d=+1.36) — WIN에서 교전 발생 빈번
- `energy_diff_avg` WIN < LOSS (d=-1.46) — WIN은 에너지 적극 사용
- `overshoot_pct` WIN < LOSS (d=-0.85) — WIN은 오버슈트 적음

### 9.4 관측 궤적 역추적 (695 매치)

> "교착의 원인은 교착 시점이 아니라 초반 20초에 있다"

- DRAW 매치: tick 100에서 dist 13,672ft (이미 이격)
- WIN 매치: tick 100에서 dist 10,674ft (복귀 시작)
- **분기 원인**: DRAW는 SmartHighYoYo 38% (climb → 이격), WIN은 Accelerate 31% (추격)

---

## 10. 다음 단계

### 10.1 완료된 것 (2026-04-18)

- [x] v9 × 695 풀 검증: **55.01%** (v6h2 54.96%와 동일 — EIM coverage 부족 확인)
- [x] 695 풀 metadata CSV 수집 완료 (695 매치)
- [x] Trajectory EIM 학습 완료 (98.8% acc)
- [x] **B-1**: L7 gap-targeted 상대 100개 자동 생성 (5 dist × 5 energy × 4 aggression)
- [x] **B-2**: v9 × L7 × 1R 매치 수집 (100 매치 / 0 errors / 14.9m)

### 10.1.1 Repo 재생성 가이드 (metadata git 포함 범위)

Git에 포함되는 파일/폴더:
- `logs/knowledge/` (396KB) — hypothesis queue, coverage gaps, match history (재계산 불가, 필수)
- `logs/metadata/v9_vs_L7/` (75MB, 200 파일) — L7 gap-targeted 수집 결과
- `examples/opponent_pool/L7_*.yaml` (100개) + `manifest.json`

Git에서 제외되는 파일 (용량/재생성 가능):
- `logs/metadata/v7_vs_695pool/` (670MB) — 재생성 필요 시:
  ```bash
  python scripts/collect_pool_metadata.py \
      --agent examples/adaptive_eagle_v9/adaptive_eagle_v9.yaml \
      --exclude-layer L7 \
      --output logs/metadata/v7_vs_695pool
  # ~100분, 695 매치
  ```
- Note: `logs/knowledge/coverage_gaps.json`에 695 기반 통계 이미 보존됨 → 재수집은 EIM 재학습/re-mining 시에만 필요

### 10.2 Exp 2 — Coverage-driven Gap Expansion

**목적**: EIM이 아는 관측 공간 26.9% → 40%+ 확장 → WR 55% → 60%+ 개선

**진행 상황**:

| 단계 | 작업 | 상태 | 결과 |
|---|---|---|---|
| **B-1** | Miner 9 gap → L7 gap-targeted 상대 생성 | ✅ 완료 | 100 상대 (795 total pool) |
| **B-2** | v9 vs L7 × 1R 매치 수집 | ✅ 완료 | 100 매치, 0 err, 14.9m |
| ⚠ **이슈** | L7 coverage gain 정량화 | 진단 필요 | **26.9% → 27.9% (+5 bin만)** — 예상 +50~100 bin 대비 크게 미달 |
| **B-3** | EIM 재학습 (trajectory, 확장 데이터) | ⏸ 보류 | L7 분포 분석 후 재설계 고려 |
| **B-4** | Counter table v3 재빌드 | 대기 | |
| **B-5** | v10 BT 생성 + 695+L7 풀 검증 | 대기 | |
| **B-6** | Coverage 변화 + WR Δ 정량화 | 대기 | |

**현재 블로커**: L7 100매치가 대부분 이미 커버된 bin에 몰림. 원인 가능성:
1. L7 BT 설계가 관측값 분포를 충분히 분산 못 시킴 (대부분 매치가 유사한 trajectory로 수렴)
2. Gap bin이 물리적으로 도달 불가능한 구간 (e.g. extreme energy_diff)
3. v9 자체가 특정 bin으로 매치를 몰아감 (상대 BT 영향 제한적)

**다음 액션**: L7 매치 실제 bin 분포 분석 → L8 재설계 vs 현 데이터로 B-3 강행 결정

**검증 기준**: "coverage X%p 증가 → WR Y pp 증가" 상관관계 도출

**L7 상대 설계 기준** (gap bin → BT 설계):

| Gap 예시 | 상대 BT |
|---|---|
| ATA 0-30° + dist 0-1000 | 근접 정면 돌진 (GunAttack 극대화) |
| ATA 90-120° + dist 6000-10000 + closure - | 중거리 측면 유지 (LagPursuit + Evade) |
| ATA 150-180° + dist 3000-6000 | 후방 접근 (rear-aspect pursuit) |
| CLIMBING dominant | 수직 에너지 전투 (HighYoYo loop) |
| DIVING dominant | 하강 공격 특화 (dive + gun run) |

### 10.3 Head-on Gun Attack 조사 (별도 연구 과제)

**발견**: GunAttack 발동의 83%가 head-on (AA > 120° or < 60°). SDK WEZ 모델이 AA를 체크하지 않음.

**조사 계획**:

| 단계 | 작업 |
|---|---|
| **A-1** | SDK 데미지 로직 확인 — head-on vs rear-aspect 데미지 동일한지 |
| **A-2** | 695 CSV에서 AA 구간별 실제 데미지 통계 비교 |
| **A-3** | 필요 시 IsRearAspect 조건 추가 또는 IsWEZOpportunity AA 제한 |

**결정 기준**:
- SDK가 head-on/rear 데미지 동일 → 현재 로직 유지 (시뮬레이터 규칙 내 최적화)
- rear-aspect가 데미지 더 높음 → AA 조건 추가하여 BFM 교리 반영

**관련 파일**: `custom_conditions.py` (IsWEZOpportunity), `adaptive_eagle_v9.yaml` (GunEngagement)

### 10.4 장기 과제

- **Online few-shot learning**: 매치 중 prototype EMA update (DRIFT 방지 후)
- **Failure loop 자동화**: 패배 원인 4-category 분류
- **Self-play**: 이전 세대 best를 풀에 추가
- **Adversarial generation**: 현재 best가 지는 패턴 자동 생성

---

## 11. 부록

### 11.1 BFM 노드 분류 (23 액션 + 15 조건)

#### 액션

| 카테고리 | 노드 |
|---|---|
| **OBFM** | SmartLeadPursuit, SmartPurePursuit, SmartLagPursuit, SmartGunAttack, SnapshotAttack |
| **Energy** | SmartHighYoYo, SmartLowYoYo, SmartClimbingTurn, SmartDescendingTurn, VerticalFight |
| **DBFM** | SmartBreakTurn, SmartDefensiveSpiral, ExtensionBreak, Jink, GunsDefense, LastDitch |
| **HABFM** | SmartOneCircle, SmartTwoCircle, FlatScissors, RollingScissors |
| **Disengage** | HeadOnBreak, UnloadedExtension, Chandelle |

#### 조건

| 카테고리 | 노드 |
|---|---|
| 기하학 | IsDefensiveGeometry, IsOffensiveGeometry, IsNeutralGeometry |
| 에너지 | IsHighEnergy, IsLowEnergy |
| 교전 | IsCloseCombat, IsWEZOpportunity, IsUnderFire |
| 선회전 | IsOneCircleSituation, IsTwoCircleSituation |
| 특수 | CustomOrbitDetector, IsOvershooting |
| 시계열 | IsLostPursuit, IsChaseStale, IsExtensionFailing |
| **Intent** | **EnemyIntentIs** (trajectory ProtoNet 기반) |

### 11.2 핵심 수식

**Fitness Score**: $\text{score} = \sum_o (W_\text{base} + \alpha \cdot \Delta\text{hp})$, $W=10, D=1, L=-5, \alpha=2.0$

**Specific Energy**: $E_s = h + v^2/2g$, $g = 32.174$ ft/s²

**Turn Radius**: $r \approx v^2 / (g\sqrt{n^2-1})$

**Corner Velocity** (F-16): ≈ 330 kts

### 11.3 Knowledge DB 구조

```
logs/knowledge/
├── matches.jsonl           # 매치 집계 (schema 1.0, tagged)
├── hypotheses.jsonl        # 가설 verdict 이력
├── situations.jsonl        # ADVANTAGE/DISADVANTAGE/STALEMATE 패턴
├── counter_table.json      # intent → counter 매핑
├── hypothesis_queue.json   # 미검증 가설 후보
└── failures.jsonl          # 실패 원인 DB (TBD)
```

### 11.4 BUG 수정 이력

| ID | 위치 | 원인 | 해결 |
|---|---|---|---|
| BUG-4 | custom_conditions.py | pyd 빌트인 이름 충돌 | `CustomOrbitDetector`로 개명 |
| BUG-5 | runner.py | `tracker1.update(obs2)` 오입력 | `tracker1.update(obs1)` |
| DRIFT | runner.py | mid-match `update_online()` | 비활성화 |
| rglob | train_intent_model.py | `glob` → `rglob` (하위 디렉토리 미탐색) | 수정 |
| worker crash | adaptive_optimizer.py | JSBSim 리소스 누수 | `maxtasksperchild=50` |

### 11.5 프로젝트 구조

```
ai-combat-sdk/
├── ADAPTIVE_BT_PLAN.md          # 본 문서
├── NEXT_SPRINT.md               # 다음 작업 목록
├── examples/
│   ├── adaptive_eagle_v9/       # 현재 best (trajectory EIM)
│   │   ├── adaptive_eagle_v9.yaml
│   │   └── nodes/
│   │       ├── custom_actions.py
│   │       ├── custom_conditions.py  (inline EnemyIntentIs)
│   │       └── intent_model.pt       (trajectory ProtoNet)
│   └── opponent_pool/           # 695 직교 풀
├── models/
│   ├── intent_model.pt          # A안 (node-based, 73.7%)
│   └── intent_model_trajectory.pt  # B안 (trajectory, 98.8%)
├── logs/
│   ├── metadata/                # per-tick CSV (raw data)
│   └── knowledge/               # 집계/가설/counter_table
├── submissions/
│   └── GwangPung/               # 대회 제출 (v1.0, v6h1 기반)
└── tools/                       # 전체 도구 (§8 참조)
```
