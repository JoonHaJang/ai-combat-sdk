# ARCHITECTURE_MAP — ai-combat-sdk 전체 구조 및 정리 방안

> 생성 시점: 2026-06-21  
> 기준: `graphify-out/graph.json` + AST 기반 import 스캔 (`src/`, `tools/`, `new_match_engine/`, `examples/`, `scripts/`)

---

## 1. Graphify 추출 요약

| 항목 | 수량 | 비고 |
|---|---|---|
| Graphify 전체 노드 | 26,264 | 외부 레포(ai-combat-core-main, external_repo 등) 포함 |
| Graphify 전체 엣지 | 43,126 | — |
| 프로젝트 내부 Python 파일 | 279 | `src/` 44, `tools/` 91, `new_match_engine/` 8, `examples/` 129, `scripts/` 7 |
| Markdown 문서 | 28 | `docs/` 기준 |

> **핵심 인사이트**: `graphify`가 포착한 그래프는 외부 의존성이 과다하게 포함되어 있어, **내부 프로젝트 핵심 경로만 필터링하는 설정(`.graphifyignore`)이 필요**합니다. AST 스캔 결과와 결합하면 실제 내부 의존성 패턴이 드러납니다.

---

## 2. Graphify + AST 기반 내부 의존성 패턴

### 2.1 핵심 Cross-Package Import 엣지

```
examples/adaptive_eagle_*  → src/intent
examples/pursuit_chase_v1  → src/behavior_tree, src/control
examples/eagle2, viper1    → src/intent, src/behavior_tree

src/match       → src/control, src/simulation
src/tournament  → src/match, src/submission
src/visualization → src/simulation
src/intent      ← tools/train_eim.py, tools/train_intent_model.py

scripts/run_match.py      → src/match
scripts/run_tournament.py   → src/tournament
scripts/collect_pool_metadata.py → scripts/run_match

tools/evaluate.py         → src/match
tools/bt_optimizer.py     → scripts/run_match
tools/adaptive_optimizer.py → tools/evaluate
tools/verify/*            → examples/pursuit_chase_v1
tools/test_intent_live.py → src/intent, src/match
```

### 2.2 이상/주의 엣지 (Anomalies)

| 엣지 | 의심 내용 |
|---|---|
| `src/simulation` → `scripts/train` | **역방향 import**. `scripts/`가 `src/`를 참조하는 것은 정상이나, `src/`가 `scripts/`를 참조하면 순환 의존성(cycle) 가능성이 있습니다. 코드 점검 필요. |
| `tools/` → `scripts/run_match.py` (다수) | `scripts/run_match`가 단순 CLI가 아닌 **라이브러리로 재사용**되고 있음. 라이브러리/CLI 분리가 필요합니다. |
| `new_match_engine/` → (None) | `src/`, `examples/`, `tools/` 어디에서도 import되지 않음. **고립된 연구 모듈**입니다. |

---

## 3. Graphify 기반 고립/누락 노드 분석

| 대상 | 상태 | Graphify/AST 근거 |
|---|---|---|
| `new_match_engine/` | � 고립 | `src/`, `examples/`, `tools/` 전역에서 import 0건. 그래프 상 독립 서브그래프로 존재. |
| `examples/` | 🟡 평평화 | 129개 파일이 25개 이상 디렉토리에 흩어져 있음. graphify 상 커뮤니티가 과다하게 쪼개짐(버전별 폴더 때문). |
| `tools/` → `scripts/run_match` | 🟡 역할 혼동 | CLI 스크립트가 라이브러리로 재사용되는 엣지가 다수 발견됨. |

---

## 4. 참조

- `graphify-out/GRAPH_REPORT.md` — Graphify 전체 그래프 보고서 (6,304 라인)
- `graphify-out/graph.json` — 전체 그래프 원본 (32 MB, NetworkX JSON)
- `docs/PROJECT_OVERVIEW/05_document_map.md` — 기존 문서 지도
- `new_match_engine/README.md` — F-16 LQR/NDI 제어 스택 개요
