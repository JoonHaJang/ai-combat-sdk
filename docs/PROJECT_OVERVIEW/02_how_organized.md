# 02. 프로젝트가 어떻게 구성되어 있는가

> **요약**: 시뮬레이터(JSBSim) + 행동트리 엔진(py_trees) + 우리 AI 코드(예시 + 수학 통합) + 검증 도구.
> 참여자는 `submissions/`에 자기 AI를 두고, 우리가 만든 도구들로 검증·대전합니다.

---

## 1. 폴더 한눈에

```
ai-combat-sdk/
├── README.md                  # 참여자 입문 (설치/시작)
├── Tutorial.md                # 처음 세팅 튜토리얼
├── CUSTOM_NODE_GUIDE.md       # 커스텀 노드 만들기
├── CLAUDE.md                  # Claude Code 설정 (작업 환경)
├── MASTERBOOK.md              # (옛) 종합 정리서 — 2026-04 시점
│
├── docs/                      # 공식 가이드
│   ├── GUIDE.md                  # BT 개발 메인 가이드
│   ├── NODE_REFERENCE.md         # 모든 노드·파라미터 사전
│   ├── VSCODE_SETUP.md           # IDE 설정
│   ├── DOGFIGHT2_INTEGRATION.md  # 통합 문서
│   └── PROJECT_OVERVIEW/      # ★ 이 폴더 (입문 자연어 설명)
│
├── src/                       # SDK 코어 (수정 X)
│   ├── simulation/               # JSBSim 환경 래퍼
│   ├── intent/                   # 적 의도 분류 (EIM)
│   └── match/                    # 매치 실행 엔진
│
├── scripts/                   # 실행 도구
│   ├── run_match.py              # 1대1 매치 실행
│   └── ...
│
├── tools/                     # 보조 도구
│   └── validate_agent.py         # YAML 문법 검증
│
├── examples/                  # 참고 AI 샘플
│   ├── eagle1/                   # 단순 BT 예시
│   ├── viper1/                   # 또 다른 예시
│   └── adaptive_eagle_v11_code/  # ★ 최근 BFM 수학 통합 실험장
│       ├── adaptive_eagle_v11_code.yaml  # BT 정의
│       ├── nodes/                # 커스텀 액션·조건
│       ├── sim_dogfight_verify.py  # 검증 시뮬 (가벼운 3D 점질량)
│       ├── BFM_MATHEMATICAL_FOUNDATIONS.md
│       ├── CURRENT_STATE_AND_DESIGN.md   # ★ 현재 진실
│       └── SUPERPLAN_BFM_MATH_INTEGRATION.md  # 진행 이력
│
├── submissions/               # ★ 참여자 작품 (각자 본인 AI)
│   └── README.md
│
├── config/                    # 매치 룰, 토너먼트 설정
├── logs/                      # 실행 로그
├── replays/                   # ACMI 리플레이 (TacView로 봄)
└── LAG/                       # 외부 의존 (LAG 프레임워크)
```

---

## 2. 코드의 흐름 — 한 매치가 어떻게 돌아가는가

```
[1] scripts/run_match.py 실행
    ↓
[2] config/match_rules.yaml 읽어서 두 AI 로드
    ↓
[3] 각 AI는 YAML(BT 정의) + nodes/ (커스텀 코드) 로 구성
    ↓
[4] src/match/runner.py 가 1500틱(=300초) 매치 진행
    ↓ (매 틱 0.2초)
    ┌─ JSBSim이 두 비행기 위치/속도 업데이트
    │  ↓
    │  관측값(28 피처) 추출 (src/intent/encoder.py)
    │  ↓
    │  각 AI의 BT 평가 → 액션 선택 (e.g. ClimbTo, GunAttack)
    │  ↓
    │  액션 → 저수준 명령(피치율, 헤딩율, 가속도)
    │  ↓
    │  JSBSim에 명령 적용 → 다음 틱
    └─
    ↓
[5] 매치 종료 → 누가 더 많이 데미지를 줬는지 → 승패 판정
    ↓
[6] replays/*.acmi 저장 → TacView로 3D 시각화 가능
```

---

## 3. 두 종류의 시뮬레이터

같은 프로젝트에 두 시뮬레이터가 있다는 점이 헷갈리는 부분.

### 3.1 JSBSim (실제, 6-DOF, 무거움)
- 위치: `src/simulation/envs/JSBSim/`
- 특징: 실제 비행 물리 (중력·양력·항력·G·실속 모두 계산)
- 사용처: 토너먼트 본 매치, 정확한 검증
- 단위 시간: 1 틱 = 0.2초 (시뮬 내부는 더 잘게 쪼개서 계산)

### 3.2 sim_dogfight_verify (간단 3D 점질량)
- 위치: `examples/adaptive_eagle_v11_code/sim_dogfight_verify.py`
- 특징: 점질량 + 속도 의존 ω 테이블 — JSBSim보다 단순하지만 빠름
- 사용처: BFM 수학 가설을 빠르게 검증할 때 (수만 시뮬을 분 단위로)
- **현재 91% WIN 결과는 이쪽 시뮬에서 측정** (JSBSim 통합 검증은 미실시)

이 차이가 중요한 이유: 가벼운 시뮬에서 91%여도 JSBSim에서 그대로 유지된다는
보장은 **아직 검증 안 됨** (현재 상태 문서의 Red Team 7.5절 참조).

---

## 4. 행동 트리 엔진 (py_trees)

행동 트리는 외부 라이브러리 `py_trees` 위에서 돌아갑니다.

기본 노드 종류:
- **Selector** (=OR): 자식 중 하나라도 성공하면 성공
- **Sequence** (=AND): 모든 자식이 성공해야 성공
- **Condition**: True/False 반환 (조건 검사)
- **Action**: 실제 제어 명령 발행

가장 단순한 BT 예시:

```yaml
tree:
  type: Selector
  children:
    - type: Sequence              # AND 조건들
      children:
        - type: Condition
          name: BelowHardDeck
        - type: Action
          name: ClimbTo

    - type: Action                # fallback
      name: LeadPursuit
```

자세한 노드 목록은 [docs/NODE_REFERENCE.md](../NODE_REFERENCE.md).

---

## 5. 28-피처 관측값 (28-dim obs)

매 틱 AI가 읽을 수 있는 정보는 정해진 28개 (`src/intent/encoder.py`):

```
연속값 14개:
  거리, ATA, AA, HCA, 상대방위, 내 고도, 내 속도,
  비에너지, Ps, 에너지차, 클로저, 선회율, 고도차, tau

이진값 7개:
  in_wez, enm_in_wez, in_39_line, overshoot_risk,
  energy/alt/spd_advantage

BFM one-hot 7개:
  OBFM/DBFM/HABFM/UNKNOWN(4)
```

이 28개 값이 BT의 모든 조건/액션에 입력. 자세한 의미는 [04_glossary.md](./04_glossary.md).

---

## 6. 어디 가서 무엇을 보는가

| 알고 싶은 것 | 가는 곳 |
|------------|---------|
| 처음 SDK 설치 | `README.md` → `Tutorial.md` |
| 첫 BT 만들기 | `docs/GUIDE.md` |
| 모든 노드 목록 | `docs/NODE_REFERENCE.md` |
| 커스텀 액션 만들기 | `CUSTOM_NODE_GUIDE.md` |
| 최근 BFM 실험 결과 | `examples/adaptive_eagle_v11_code/CURRENT_STATE_AND_DESIGN.md` |
| BFM 수학 출전 | `examples/adaptive_eagle_v11_code/BFM_MATHEMATICAL_FOUNDATIONS.md` |
| 옛 종합 문서 | `MASTERBOOK.md` (2026-04 시점) |

또는 한 번 더 정리한 **[05_document_map.md](./05_document_map.md)** 참조.
