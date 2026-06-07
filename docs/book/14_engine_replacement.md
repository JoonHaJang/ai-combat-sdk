# 14장. 기존 엔진 대체 — 브리지와 드롭인

## 학습 목표
이 장을 마치면 다음을 할 수 있다.
- 기존 매치 엔진을 무수정으로 두고 새 엔진을 끼우는 드롭인 설계를 안다.
- 동일 생성자·실행·결과 계약이 왜 중요한지 안다.
- --backend 로 legacy, lqr, indi 를 고르는 방법을 안다.
- 교환이 제대로 됐는지 검증하는 절차를 안다.


> 작성: 2026-06-04 · 목표: 투명 LQR/INDI 스택(`new_match_engine/`)이 legacy `.pyd` core 역할을
> 대체하되, 기존 SDK 시스템(스크립트·평가·토너먼트)과 `.yaml` 에이전트 인터페이스를 최대한 그대로
> 재사용. BT 충실도는 검증된 `yaml_bt`(.yaml→Tactic) 경로 사용.

---

## 0. 한 줄 요약

`new_match_engine.bridge.BehaviorTreeMatch` 라는 드롭인 어댑터를 만든다. 기존 SDK 코드가 쓰는
`src.match.runner.BehaviorTreeMatch` 와 *동일한 생성자·`.run()`·결과 계약*을 제공하되, 내부는
`.pyd` core(JSBSim env + AIPILOT RNN) 대신 new_engine(자체 JSBSim + LQR/INDI + judge + WEZ) 으로
실행한다. 호출부는 *import 한 줄(또는 backend 플래그)* 만 바꾸면 된다.

---

## 1. 목표·제약 (합의됨)

| # | 항목 | 결정 |
|---|---|---|
| G1 | core 대체 범위 | 최대한 — sim + 저수준제어(RNN) + WEZ + judge 를 new_engine 으로 |
| G2 | 기존 SDK 재사용 | 최대한 — `BehaviorTreeMatch` 계약·CSV·replay·결과형태 보존 → 호출부 무수정(또는 플래그) |
| G3 | BT 충실도 | `yaml_bt`(.yaml→Tactic) 경로 — 이미 canonical 4/4 검증. action-bin 브릿지는 *미채택* |
| G4 | `.pyd` core | 무수정 (수정 불가). 대체는 *병렬 백엔드* 로 — 기존 .pyd 경로도 그대로 살림 |

핵심 사실(통합 가능 근거): new_engine·SDK 둘 다 Python 3.14.2 + jsbsim 1.3.0 → 동일 인터프리터
공존 가능. 드롭인이 물리적으로 성립.

---

## 2. 대체 대상 seam (무엇을 갈아끼우나)

legacy 매치 1틱 (근거: `src/match/runner.py`, `runner_core.py`, `singlecombat_task.py`):

```
BT(.yaml, py_trees .pyd) ── action-bin [Δalt,Δhdg,Δvel] ──▶ AIPILOT RNN(.pyd) ──▶ 조종면
                                                                                     │
   obs(blackboard) ◀── combat_geometry/bfm(.pyd) ◀── JSBSim env(.pyd) ◀── 조종면 ────┘
                                                          │
                                              WEZ(.pyd) → health → judge(.pyd)
```

new_engine 으로 대체 후 (근거: `new_match_engine/{engine/match.py, bt/yaml_bt.py, control/*, engine/judge.py}`):

```
BT(.yaml) ── yaml_bt 해석 ──▶ Tactic ──▶ guidance ──▶ setpoint ──▶ LQR/INDI ──▶ 조종면
                                                                                  │
   obs ◀── compute_obs ◀──────────────── JSBSim F16Plant ◀── 조종면 ──────────────┘
                                              │
                                  wez_damage → HealthGauge → judge
```

대체되는 것: env(JSBSim 래퍼)·AIPILOT RNN·combat_geometry·WEZ·judge → 전부 new_engine 투명 구현.
보존되는 것: `.yaml` BT 파일(에이전트)·매치 초기조건(bt_vs_bt)·결과/replay/CSV 계약·호출 API.

---

## 3. 호환 계약 (드롭인이 지켜야 할 표면)

근거: `src/match/runner.py:93`(생성자), `scripts/run_match.py:211`(호출), `result.py`(MatchResult).

### 3.1 생성자·실행 API (그대로 복제)
```python
BehaviorTreeMatch(tree1_file, tree2_file,
                  config_name="1v1/NoWeapon/bt_vs_bt",
                  max_steps=0, tree1_name=None, tree2_name=None,
                  step_callback=None, log_csv=None,
                  controller="lqr")        # ← 신규(옵션): "lqr"|"indi" 엔진 선택
   .run(replay_path=None, verbose=False) -> result
```
- 실행 후 객체에 `.health1`·`.health2`·`.task1`·`.task2` 노출 (runner.py:284-287 계약).

### 3.2 결과 객체 (`result`)
| 필드 | legacy 값 | new_engine 매핑 |
|---|---|---|
| `.winner` | `"tree1"`/`"tree2"`/`"draw"` | new MatchResult `"agent1"→"tree1"`, `"agent2"→"tree2"` 변환 |
| `.total_steps`(=`.steps`) | int | `res.steps` |
| `.duration_seconds`(=`.elapsed_time`) | float | `res.time_s` |
| `.tree1_reward`/`.tree2_reward` | float | new 엔진은 reward 미산출 → damage_dealt 로 대용(또는 0.0, §6-D1) |
| `.health1`/`.health2` (side-channel) | HealthGauge류 | `res.health1`/`res.health2` 래핑(`.current_health`) |

### 3.3 CSV 컬럼 (`runner.py:34` _CSV_COLUMNS, 50+열)
- step_callback/CSV 경로 켜질 때만 필요. new_engine `_log_row`(match.py:109) 가 대부분 보유.
- 갭: `action_altitude/heading/velocity`(이산 bin), `active_node/active_nodes_path`(py_trees 활성노드),
  `servo_*`(JSBSim 서보위치). → §6-D2 에서 처리(근사/공란/대용).

### 3.4 초기조건 (config_name="…/bt_vs_bt")
- legacy `bt_vs_bt.yaml`: 15000ft, 3000ft 분리, anti-parallel(ψ 180 vs 0), 600fps.
- new_engine `spawn_adt_neutral()` 가 이미 동일(메모리 match-canonical-initial-condition, 검증됨).
- 다른 `config_name`(tail_chase 등)은 Phase 4 로 미룸(현재 beam 고정 정책과 충돌 — §6-D4).

### 3.5 replay
- legacy: `.pyd` replay_writer. new: `replay.write_acmi_plot`(Tacview 사라짐 수정 완료).
- 어댑터가 `replay_path` 받으면 new_engine log → `write_acmi_plot` 로 저장.

---

## 4. 산출물 (파일)

```
new_match_engine/bridge/
├── __init__.py            # from .core_adapter import BehaviorTreeMatch
├── result_compat.py       # new MatchResult → legacy-shape result(winner 변환·health 래핑)
├── core_adapter.py        # BehaviorTreeMatch 드롭인 (yaml_bt×2 + Match 실행 + CSV/replay)
└── run_legacy.py          # CLI: python -m ...bridge.run_legacy a.yaml b.yaml --controller indi
```
- 기존 SDK 무수정. 전환은 호출부에서 `from new_match_engine.bridge import BehaviorTreeMatch` 한 줄.
- (선택) `scripts/run_match.py` 에 `--backend new_engine|legacy` 플래그 추가(G2 "최대 재사용" 강화).

---

## 5. 단계별 실행 (phased)

| Phase | 내용 | 산출·검증 |
|---|---|---|
| P0 | 계약 동결 — 본 문서 §3 확정 | (이 문서) |
| P1 | `result_compat` + `core_adapter` 구현 — yaml_bt×2, Match(controller), winner 변환, health 래핑, replay | `bridge.BehaviorTreeMatch('aggressive','ace').run()` 동작 |
| P2 | CSV/step_callback 호환 — _CSV_COLUMNS 채움(갭은 D2 규약) | 기존 CSV 소비 도구가 안 깨짐 |
| P3 | 병렬 검증 — 동일 .yaml 매치쌍을 legacy(.pyd) vs new_engine 양 백엔드 실행, 결과 대조표 | winner 일치율·divergence 리포트(§6-D3) |
| P4 | SDK 소비자 연동 — `scripts/run_match.py`·`tools/evaluate.py` 에 backend 플래그. tournament 는 그 다음 | 1개 스크립트가 new_engine 으로 토너먼트 1회 |

각 Phase 끝에 짧은 증분 보고(메모리 feedback-incremental-progress).

---

## 6. 리스크·결정 — 갭 처리 원칙 = 연착륙(soft-landing)

> 원칙(사용자 지시 2026-06-05): 갭을 *근사·공란·stub* 으로 때우지 않는다. legacy core 가 더
> 충실한 기능이고 new_engine 에 없으면, new_engine 에 그 기능을 *추가*해서 메운다. 목표는
> new_engine 이 legacy core 의 능력 위로 *연착륙* — 기능 손실 없이 수렴. (단, RNN 학습 전용·투명제어와
> 모순되는 것은 예외로 명시.)

| ID | 갭 | legacy 기능 | new_engine 현재 | 연착륙 결정 |
|---|---|---|---|---|
| D1 | reward | RNN 학습 reward | 미산출 | 예외 — reward 는 *학습 전용*(전투 결과 무관). `tree*_reward=damage_dealt` 로 의미 보존, 별도 학습 reward 는 추가 안 함 |
| D2a | `servo_*` 서보위치 | JSBSim `fcs/*-pos-norm` 읽음 | u(명령)만 기록 | 완료 — match `_log_row` 에 서보위치 readout 추가 |
| D2b | `active_node`·`active_nodes_path` | py_trees 활성노드 경로 | yaml_bt 는 Tactic 만 | 완료 — yaml_bt `_walk` 로 성공경로 추적(`last_node`/`last_path`) |
| D2c | `action_alt/hdg/vel`(이산 bin) | BT→bin | Tactic | 공란(정직) — LQR 은 이산 action 없음. legacy_csv 에서 공란+문서화 |
| D2-CSV | legacy `_CSV_COLUMNS`(46) | per-agent 행·보조기하 | new 로그(병합행) | 완료 — `bridge/legacy_csv.py`: 46컬럼 정확일치·에이전트별 행·~20Hz |
| D3 | RNN≠LQR → 수치 비동일 | 학습 RNN 저수준 | 투명 LQR/INDI | 예외(의도) — 투명제어가 *목적*. P3 는 winner/정성 패턴 일치를 봄(수치동일 아님) |
| D4 | `config_name` 다양화(tail_chase 등) | 다중 시나리오 IC | beam 만 | ADD(P4) — legacy config IC → new_engine spawn 매핑 추가 |
| D5 | yaml_bt 어휘(조건26/액션40, 미지원→근사) | 전체 BT 노드 | 부분 | ADD(측정 후) — 970 .yaml 미지원 노드 빈도 측정 → 빈도순 yaml_bt 확장 |
| D6 | py_trees stateful condition(20Hz hysteresis) | Condition.update() 상태 | yaml_bt stateless | ADD(조건부) — 영향 BT 식별 후 yaml_bt 에 상태 보존 추가 |
| D7 | 결정성/seed | MATCH_SEED 경로 | 항상 결정론 | new_engine 은 노이즈 0 → 결정론. legacy seed 무관(어댑터는 deterministic) |

연착륙 작업 트래킹: D2a·D2b 는 P2 에서 *new_engine 에 기능 추가*로 닫는다. D4·D5·D6 는 측정·빈도
기반으로 P4+ 에서 추가. 각 추가는 *legacy 동작과 1:1 대조* 후 반영(메모리 feedback-agile-coverage).

---

## 7. 비목표 (이번 범위 밖)

- action-bin → setpoint 브릿지(RNN 인터페이스 충실 재현) — G3 에서 미채택.
- `.pyd` core 수정/대체 컴파일 — 불가·불필요(병렬 백엔드).
- legacy py_trees 정확 실행(노드활성·stateful) — yaml_bt 근사로 대체.
- 토너먼트 전체 이관 — P4 이후 별도.

---

## 8. 합의 필요 포인트 (착수 전)

1. P1 우선 착수 OK? (core_adapter 드롭인 → `bridge.BehaviorTreeMatch('aggressive','ace').run()`)
2. reward 대용(D1) = damage_dealt 로 OK? (아니면 0.0 고정)
3. 전환 방식 = (a) import 교체만 / (b) `scripts/run_match.py` 에 `--backend` 플래그 추가까지(권장).

---

## 연습문제
1. 드롭인 어댑터가 기존 엔진과 같아야 하는 계약 세 가지를 들어라.
2. --backend lqr 과 --backend legacy 가 각각 무엇을 실행하는지 적어라.
3. 약한 두 에이전트가 붙으면 원본 엔진도 무승부인데, 이것이 왜 결함이 아닌지 설명하라.

