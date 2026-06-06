# Project Overview — 프로젝트 입문 (한 곳에 모은 안내서)

> **이 폴더의 용도**: 프로젝트가 처음이거나, 최근 무엇을 했는지 빠르게 잡고 싶은 사람을 위한 자연어 입문서.
>
> **읽는 순서**: 처음 보는 사람은 1 → 2 → 3 → 4 순서. 특정 정보가 필요한 사람은 5번 (문서 지도)에서 직접 점프.

---

## 폴더 안 파일

| # | 파일 | 무슨 내용 | 누가 읽으면 좋은가 |
|---|------|-----------|--------------------|
| 1 | [01_what_is_this.md](./01_what_is_this.md) | 이 프로젝트가 만들고자 하는 게 뭔지 | "이게 뭐 하는 프로젝트야?" 처음 본 사람 |
| 2 | [02_how_organized.md](./02_how_organized.md) | 폴더·파일이 어떻게 짜여 있는지 | 코드 베이스 처음 둘러보는 사람 |
| 3 | [03_recent_analysis.md](./03_recent_analysis.md) | 최근 무엇을 시도했고 왜, 결과는 (자연어 풀이) | "τ가 뭐야? 91% WIN이 뭐야?" 궁금한 사람 |
| 4 | [04_glossary.md](./04_glossary.md) | τ / canonical / ATA / BFM / WEZ 등 용어 한 줄 사전 | 읽다가 막히는 단어 만난 사람 |
| 5 | [05_document_map.md](./05_document_map.md) | 모든 .md 파일이 어디 있고 무슨 내용인지 매핑 | 특정 정보 찾는 사람 |

---

## 빨리 알아야 할 3가지

1. **무엇을 만드는가** — F-16 두 대가 1대1 공중전(dogfight)을 하는 시뮬에서, 우리 비행기를 조종할 **AI(에이전트)** 를 만든다. AI는 행동 트리(Behavior Tree, BT)와 BFM 수학 정리에 기반한 연속 제어로 동작.

2. **현재 성능** — 검증 시뮬에서 **WIN 91% / LOSS 0% / DRAW 9%** (55 케이스, 2026-05-01).

3. **최근 가장 큰 변화** — "고정된 if-else 분기"에서 **"τ 연속 가중 합성"** 으로 전환. 적의 변화에 따라 BFM 기동을 부드럽게 섞어서 적용.

---

## 더 깊이 들어가려면

- 수학 정리 (Bryson-Ho, Boyd, Shaw, Pontryagin 등) → [`BFM_MATHEMATICAL_FOUNDATIONS.md`](../../examples/adaptive_eagle_v11_code/BFM_MATHEMATICAL_FOUNDATIONS.md)
- 현재 구현 상태 정확히 → [`CURRENT_STATE_AND_DESIGN.md`](../../examples/adaptive_eagle_v11_code/CURRENT_STATE_AND_DESIGN.md)
- 검증 학술화 로드맵 (HJI/STL/Scenic/SMT/AST/SMC) → [`VERIFICATION_METHODOLOGY.md`](../../examples/adaptive_eagle_v11_code/VERIFICATION_METHODOLOGY.md)
- 처음 에이전트 만들기 → [`docs/GUIDE.md`](../GUIDE.md)
- 노드 종류와 파라미터 → [`docs/NODE_REFERENCE.md`](../NODE_REFERENCE.md)
