# 05. 문서 지도 — 어디에 무엇이 있나

> **이 문서의 용도**: "이 프로젝트에 .md가 너무 많은데 뭐를 보면 되지?" 답.
> 질문 → 가야 할 문서 매핑.

---

## 1. 질문별 가는 곳 (FAQ 스타일)

### A. 처음 시작 / 설치
| 질문 | 가는 곳 |
|------|---------|
| 이 프로젝트 어떻게 설치해? | [README.md](../../README.md) |
| 설치 후 처음 무엇부터? | [Tutorial.md](../../Tutorial.md) |
| VSCode 어떻게 세팅? | [docs/VSCODE_SETUP.md](../VSCODE_SETUP.md) |

### B. 행동 트리(BT) 만들기
| 질문 | 가는 곳 |
|------|---------|
| 첫 BT(에이전트) 어떻게 만들어? | [docs/GUIDE.md](../GUIDE.md) |
| 사용 가능한 노드 종류는? | [docs/NODE_REFERENCE.md](../NODE_REFERENCE.md) |
| 커스텀 액션·조건 어떻게 만들어? | [CUSTOM_NODE_GUIDE.md](../../CUSTOM_NODE_GUIDE.md) |
| 만든 BT 어떻게 검증? | [README.md §검증및테스트](../../README.md) |

### C. 프로젝트 이해
| 질문 | 가는 곳 |
|------|---------|
| 이게 뭐 하는 프로젝트야? | [01_what_is_this.md](./01_what_is_this.md) |
| 폴더·파일은 어떻게 짜여 있어? | [02_how_organized.md](./02_how_organized.md) |
| τ가 뭐야? canonical이 뭐야? | [04_glossary.md](./04_glossary.md) |
| 모든 문서 어디 있어? | (이 문서) |

### D. 최근 BFM 수학 통합 작업
| 질문 | 가는 곳 |
|------|---------|
| 최근 무슨 분석 했고 결과는? (자연어) | [03_recent_analysis.md](./03_recent_analysis.md) |
| 현재 정확한 구현 상태 (코드 줄 인용) | [examples/adaptive_eagle_v11_code/CURRENT_STATE_AND_DESIGN.md](../../examples/adaptive_eagle_v11_code/CURRENT_STATE_AND_DESIGN.md) |
| BFM 수학 정리 8개 정확한 출전·증명 | [examples/adaptive_eagle_v11_code/BFM_MATHEMATICAL_FOUNDATIONS.md](../../examples/adaptive_eagle_v11_code/BFM_MATHEMATICAL_FOUNDATIONS.md) |
| **검증 방법론 학술화 로드맵 (HJI / STL / Scenic / SMT / AST / SMC)** | [examples/adaptive_eagle_v11_code/VERIFICATION_METHODOLOGY.md](../../examples/adaptive_eagle_v11_code/VERIFICATION_METHODOLOGY.md) |
| **Phase A+B 구현 — metamorphic 40/40, SMC 99.5% WIN CI** | [examples/adaptive_eagle_v11_code/verification/](../../examples/adaptive_eagle_v11_code/verification/) |
| 진행 이력 (폐기된 접근 포함) | [examples/adaptive_eagle_v11_code/SUPERPLAN_BFM_MATH_INTEGRATION.md](../../examples/adaptive_eagle_v11_code/SUPERPLAN_BFM_MATH_INTEGRATION.md) |

### E. 옛 종합 문서 (2026-04 시점)
| 질문 | 가는 곳 |
|------|---------|
| 옛날 만든 종합 정리서 (HCCA, EIM 등 포괄) | [MASTERBOOK.md](../../MASTERBOOK.md) |

⚠️ MASTERBOOK은 2026-04-27 기준 — 현재(2026-05) 상태와 일부 차이.
"현재 진실"은 CURRENT_STATE_AND_DESIGN.md 우선.

---

## 2. 모든 .md 파일 일람 (위치별)

### 2.1 프로젝트 루트
```
README.md            — SDK 입문, 설치, 빠른 시작 (참여자용)
Tutorial.md          — 처음 세팅 튜토리얼
CUSTOM_NODE_GUIDE.md — 커스텀 BT 노드 작성 (코드)
MASTERBOOK.md        — (옛) 종합 정리, 45KB
CLAUDE.md            — Claude Code 작업 환경 설정
```

### 2.2 docs/
```
docs/
├── GUIDE.md             — 메인 BT 개발 가이드
├── NODE_REFERENCE.md    — 모든 노드·파라미터 사전
├── VSCODE_SETUP.md      — IDE 설정
├── DOGFIGHT2_INTEGRATION.md — 통합 문서
└── PROJECT_OVERVIEW/    — ★ (이 폴더, 입문 자연어)
    ├── README.md
    ├── 01_what_is_this.md
    ├── 02_how_organized.md
    ├── 03_recent_analysis.md
    ├── 04_glossary.md
    └── 05_document_map.md
```

### 2.3 examples/adaptive_eagle_v11_code/ (최근 작업)
```
examples/adaptive_eagle_v11_code/
├── BFM_MATHEMATICAL_FOUNDATIONS.md  — 정리 1~8 출전·증명
├── CURRENT_STATE_AND_DESIGN.md      — ★ 현재 SSOT (단일 진실 출처)
├── VERIFICATION_METHODOLOGY.md      — 검증 학술화 로드맵 (HJI/STL/Scenic 등)
├── SUPERPLAN_BFM_MATH_INTEGRATION.md — 진행 이력 (폐기 사항 포함)
└── verification/                     — Phase A+B 구현 (metamorphic + SMC)
    ├── README.md                        — 검증 결과 요약
    ├── canonical_perturbation.py        — P(x_0; δ) sampler
    ├── test_tau_metamorphic.py          — 40 MR 테스트
    └── statistical_mc.py                — Wilson CI + Wald SPRT
```

### 2.4 examples/ (참고 AI 샘플)
```
examples/
├── eagle1/README.md        — 단순 BT 예시
└── viper1/README.md        — 또 다른 예시
```

### 2.5 기타
```
LAG/                            — 외부 의존
├── README.md
└── docs/missile_engine.md, Human-agent.md, parameterized_shooting.md

web-flight-simulator/           — 웹 시뮬레이터
├── README.md
└── DEPLOY.md

submissions/README.md           — 참여자 제출 폴더 안내
src/simulation/envs/JSBSim/data/README.md   — JSBSim 데이터 안내
```

---

## 3. 역할별 추천 읽는 순서

### 3.1 새로 합류한 참여자
1. [README.md](../../README.md) (설치)
2. [Tutorial.md](../../Tutorial.md) (튜토리얼)
3. [01_what_is_this.md](./01_what_is_this.md) (이게 뭐 하는 프로젝트인지)
4. [docs/GUIDE.md](../GUIDE.md) (BT 만드는 법)
5. [docs/NODE_REFERENCE.md](../NODE_REFERENCE.md) (노드 사전)

### 3.2 최근 BFM 작업 이어받는 사람
1. [01_what_is_this.md](./01_what_is_this.md) (배경)
2. [03_recent_analysis.md](./03_recent_analysis.md) (최근 무슨 분석 했는지)
3. [04_glossary.md](./04_glossary.md) (용어)
4. [CURRENT_STATE_AND_DESIGN.md](../../examples/adaptive_eagle_v11_code/CURRENT_STATE_AND_DESIGN.md) (정확한 현재 상태)
5. (필요 시) [BFM_MATHEMATICAL_FOUNDATIONS.md](../../examples/adaptive_eagle_v11_code/BFM_MATHEMATICAL_FOUNDATIONS.md) (수학 출전)
6. (역사 보고 싶으면) [SUPERPLAN_BFM_MATH_INTEGRATION.md](../../examples/adaptive_eagle_v11_code/SUPERPLAN_BFM_MATH_INTEGRATION.md)

### 3.3 코드 구조 이해 필요한 사람
1. [02_how_organized.md](./02_how_organized.md) (전체 구조)
2. [docs/GUIDE.md](../GUIDE.md) (BT 흐름)
3. [CUSTOM_NODE_GUIDE.md](../../CUSTOM_NODE_GUIDE.md) (커스텀 노드 시스템)

### 3.4 전체 심화 학습
1. [01](./01_what_is_this.md) → [02](./02_how_organized.md) → [03](./03_recent_analysis.md) → [04](./04_glossary.md)
2. [docs/GUIDE.md](../GUIDE.md) + [docs/NODE_REFERENCE.md](../NODE_REFERENCE.md)
3. [BFM_MATHEMATICAL_FOUNDATIONS.md](../../examples/adaptive_eagle_v11_code/BFM_MATHEMATICAL_FOUNDATIONS.md)
4. [CURRENT_STATE_AND_DESIGN.md](../../examples/adaptive_eagle_v11_code/CURRENT_STATE_AND_DESIGN.md)
5. (필요 시) [MASTERBOOK.md](../../MASTERBOOK.md) (옛 통합 — 일부 정보)

---

## 4. 정리 / 처리된 파일

### 아카이브로 이동된 파일 (`.archive/`)
- `_mpe_test.md`, `_mpe_test_top.md`, `_mpe_test_bottom.md` — 수식 렌더링 테스트 잔재.
  본 작업과 무관하므로 `.archive/` 폴더로 이동 (삭제는 안 함).

### 옛 문서 (참고만)
- [MASTERBOOK.md](../../MASTERBOOK.md) — 2026-04-27 기준. HCCA·EIM 통합 정리서.
  현재 BFM 통합 결과는 반영 안 됨 → 그건 [CURRENT_STATE_AND_DESIGN.md](../../examples/adaptive_eagle_v11_code/CURRENT_STATE_AND_DESIGN.md) 참조.

---

## 5. 단일 진실 출처(SSOT) 표시

특정 주제별로 "이 정보는 여기가 진실"이라는 SSOT 매핑:

| 주제 | SSOT 문서 |
|------|-----------|
| 프로젝트 입문 안내 | [README.md](../../README.md) |
| BT 개발 방법 | [docs/GUIDE.md](../GUIDE.md) |
| 노드 사전 | [docs/NODE_REFERENCE.md](../NODE_REFERENCE.md) |
| BFM 수학 출전 | [BFM_MATHEMATICAL_FOUNDATIONS.md](../../examples/adaptive_eagle_v11_code/BFM_MATHEMATICAL_FOUNDATIONS.md) |
| **최근 BFM 통합 현재 상태** | [**CURRENT_STATE_AND_DESIGN.md**](../../examples/adaptive_eagle_v11_code/CURRENT_STATE_AND_DESIGN.md) |
| 용어 정의 | [04_glossary.md](./04_glossary.md) |
