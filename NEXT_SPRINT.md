# Next Sprint — 실행 가능한 다음 작업 목록

> 최종 갱신: 2026-04-15
> 현재 상태: Sprint A/B 완료. H-E family 전부 REFUTED (695 풀 포함). Intent classifier 필요성 데이터로 입증.

---

## 현재 상태 요약

### ✅ 완료
- **Sprint A**: 측정 인프라 (schema 1.0, tagging, Wilson CI)
- **Sprint B**: Hypothesis Miner 4종 통합 (`hypothesis_miner.py`)
- **데이터 축적**: 72 v6 매치 + 4170 full-pool 매치 (v6h2 + v6h_e1c) = **4,242 매치**
- **중복 정리**: `find_rigid_behavior.py` 흡수, `hypothesis_list_builder.py` 삭제
- **가설 검증**: H0-H5, H-E1~H-E1d 총 10+ 가설 검증 완료

### 📊 현재 최선
| Agent | 6 opp WR | 695 풀 WR |
|---|---|---|
| **adaptive_eagle_v6h2** | 83.3% | **54.96%** |
| GwangPung-1.0 (제출용) | - | 미검증 |

### 🔴 주요 문제점 (데이터로 확정)
1. **L3 (phase-decomposed) 36.9%** — 가장 약한 layer, 60% draw
2. **L1 defensive opponents** — 55% draw, 단일 BT 분기로 해결 불가
3. **Pareto frontier 도달** — context-free BT로는 더 이상 개선 안 됨

---

## 다음 Sprint 액션 아이템 (우선순위 순)

### 🎯 Sprint C — 데이터 확장 + Intent 학습 준비 (1-2 세션)

**C-1. v6h2 + 더 많은 rounds 추가 수집** (병렬 가능)
```bash
# 5R로 증가 시 더 안정적 per-opponent 통계
python tools/adaptive_optimizer.py --validate \
  examples/adaptive_eagle_v6h2/adaptive_eagle_v6h2.yaml \
  --validate-rounds 5 --workers 4
```
목표: per-opponent Wilson CI ±13% → ±10%.

**C-2. 기존 매치 데이터 intent label로 변환** (Intent classifier 학습용)
```bash
# train_intent_model.py가 metadata CSV에서 intent label 자동 추출 가능
python tools/train_intent_model.py --data logs/metadata/ \
  --output models/intent_model.pt --dry-run
```
먼저 `--dry-run`으로 클래스 분포 확인 → 부족한 class 보강 필요 여부 판단.

**C-3. Miner 8 재실행 on 누적 4242 매치**
```bash
# opponent type별 가설 추출 (layer 특화 패턴 발견 기대)
python tools/hypothesis_miner.py mine \
  --matches logs/knowledge/matches.jsonl \
  --csv-dir logs/metadata/v6_all \
  --top-k 20
```
H-E family 실패를 반영한 **새 가설** 자동 생성.

---

### 🧠 Sprint D — Intent Classifier 학습 (1-2 세션)

**전제조건**: Sprint C-2 클래스 분포가 per-class ≥ 100 sample.

**D-1. ProtoNet 학습**
```bash
python tools/train_intent_model.py \
  --data logs/metadata/ \
  --output models/intent_model.pt \
  --episodes 2000 \
  --k-shot 5 --n-query 15
```

**D-2. per-class accuracy 측정**
```bash
python tools/train_eim.py --validate-only \
  --model models/intent_model.pt
```
**Gate**: per-class accuracy ≥ 75% (validation_gates.json에 정의).

**D-3. class_coverage.json 생성**
- 각 intent class별 샘플 수, 정확도, 혼동 행렬 저장.

**실패 시**: Sprint C로 복귀, 부족 class 상대 풀 수집.

---

### 🎯 Sprint E — Counter Selector 빌드 (2-3 세션)

**E-1. 매치 CSV에서 (intent_predicted, active_node, outcome) 추출**
- 각 tick마다 OnlineIntentTracker로 intent 예측
- active_node와 최종 outcome 매핑
- → `logs/knowledge/intent_node_outcomes.jsonl` 생성

**E-2. Counter table 빌드**
```python
# 각 intent × node 조합의 승률을 Wilson CI로 집계
for intent in INTENT_CLASSES:
    for node in BT_NODES:
        wr = compute_wilson_lower(wins, total)
    best_node = argmax(wr)
counter_table[intent] = best_node
```
**Gate**: per-intent best node의 Wilson lower ≥ 0.55.

**E-3. `counter_table.json` 저장**
- 스키마: `{intent: {best_node, wr, ci_95, n_samples}}`
- 각 intent 최소 n ≥ 100.

---

### 🚀 Sprint F — APPLY 통합 + Universal 검증 (2-3 세션)

**F-1. BT 자동 생성기**
```bash
python tools/build_bt_from_counter_table.py \
  --counter-table logs/knowledge/counter_table.json \
  --template examples/adaptive_eagle_v6h2/adaptive_eagle_v6h2.yaml \
  --output examples/adaptive_eagle_v7/adaptive_eagle_v7.yaml
```
Intent-based 분기 자동 삽입:
```yaml
- type: Sequence
  name: CounterPursuit
  children:
    - {EnemyIntentIs, intent: "PURSUIT"}
    - {Action: SmartLagPursuit}  # from counter_table
```

**F-2. 695 × 10R 검증** → **Universal WR 최종 측정**
```bash
python tools/adaptive_optimizer.py --validate \
  examples/adaptive_eagle_v7/adaptive_eagle_v7.yaml \
  --validate-rounds 10 --workers 4
```
**목표**: Universal WR ≥ **65%** (Wilson CI ±1.18%)

**F-3. GwangPung-2.0 제출 패키지 생성**
```bash
# intent_model.pt 포함한 self-contained submission
mkdir -p submissions/GwangPung-v2/nodes/
cp examples/adaptive_eagle_v7/*.yaml submissions/GwangPung-v2/GwangPung-v2.yaml
cp examples/adaptive_eagle_v7/nodes/*.py submissions/GwangPung-v2/nodes/
cp models/intent_model.pt submissions/GwangPung-v2/nodes/
# EnemyIntentIs inline EIM inference 확인
python tools/test_suite.py GwangPung-v2
```

---

### 🔁 Sprint G — Failure Loop 활성화 (1-2 세션)

**G-1. failures.jsonl 자동 채우기**
- 매치 결과 → cause 분류 (4-category):
  - (a) Misclassification — intent wrong
  - (b) Wrong counter — intent right but node wrong
  - (c) Execution failure — node params wrong
  - (d) Novel pattern — no matching intent class

**G-2. Miner 재실행 on failures.jsonl**
- 4-category 각각에 대한 새 가설 생성
- Hypothesis queue 자동 갱신

**G-3. Auto re-verification loop**
- top-K 가설을 hypothesis_tracker가 자동 실행
- verdict 기록 → Sprint H 피드백

---

## 대안 분기 (데이터 충분성에 따라)

### Path α: Intent-light 접근 (Sprint D 실패 시 fallback)
Intent classifier accuracy가 <70%면:
- 대신 **situation-based counter table** (ATA, dist, energy 조합)
- Miner 8 output을 직접 counter_table로 변환
- BFM physics 규칙을 explicit branch로 구현

### Path β: Holdout pool 집중 개선
현재 L6 holdout 41%만 제대로 잡아도 universal WR 크게 상승:
- L6 counter strategy 대해서만 특화 가설 탐색
- 각 counter에 대한 BT 분기 신설

### Path γ: 대규모 CMA-ES 재진입
H-E family 실패는 manual branch의 한계 — CMA-ES로 다시:
- v6h2 warm-start + `--budget 400`
- 평가: 695 stratified 40 sample (기존 방식)
- 목표: Miner가 발견한 방향을 자동으로 튜닝

---

## Backlog (우선순위 낮음)

- [ ] `bt_optimizer.py`, `match_knowledge.py`, `train_eim.py` deprecate 실제 삭제
- [ ] `validation_gates.json` 정식 정의
- [ ] `hypothesis_tracker` 에 gate 체크 로직 추가
- [ ] Replay 자동 정리 스크립트 (`.gitignore` 에 `replays/` 이미 있음)
- [ ] Knowledge DB schema 2.0 (failures cascade, counter history)
- [ ] README 업데이트 (v6.0 파이프라인 설명)

---

## 즉시 실행 가능한 체크리스트

**다음 세션에서 바로 실행 가능**:

- [ ] `train_intent_model.py --dry-run` 으로 현재 데이터 class 분포 확인
- [ ] `hypothesis_miner.py mine --csv-dir logs/metadata/v6_all --top-k 20` 재실행 (H-E 결과 포함)
- [ ] `adaptive_optimizer.py --validate v6h2 --validate-rounds 5` 로 statistics 강화
- [ ] `match_knowledge.py compare-outcomes --agent-version v6h_e1c` — 디테일 분석

각각 **15분~1시간** 정도.

---

## 핵심 질문 (다음 세션 시작 시)

1. **Intent classifier 학습 데이터 충분한가?** → Sprint C-2 dry-run으로 확인
2. **695 풀의 L3 draw 문제 해결 가능한가?** → Intent model로 L3 상대 분류 정확도 확인
3. **H-E family 실패가 진정한 데드엔드인가?** → CMA-ES 재실행이 의미 있는가?

각 질문에 답할 수 있어야 Sprint D 진입 가능.
