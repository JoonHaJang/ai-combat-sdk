# AIPILOT
### F-16 AI Pilot Implementation with JSBSim

*Joonha Jang © 2026. All rights reserved.*

---

> **이 파일은 책의 표지·서문·표기법·마스터 목차**다. 각 章은 `docs/` 의 별도 파일이며 여기서 링크한다.
> 모든 章은 동일한 교과서 표준(§서문 "이 책을 읽는 법")을 따른다.

---

## 서문 (Preface)

### 왜 이 책인가
현대 공중전 AI는 대개 **블랙박스 신경망**으로 비행을 제어한다. 잘 날지만 *왜 그렇게 움직이는지
설명할 수 없고*, 불확실한 상황에서 *평균적 기동으로 뭉개진다*. 이 책은 정반대의 길을 택한다:
**설명 가능하고(transparent), 결정론적이며(deterministic), 교과서로 인용 가능한(citable)** 방법만으로
F-16 자율 공중전 파일럿(AIPILOT)을 *처음부터 끝까지* 구현한다.

구체적으로 우리는:
1. 비행 제어를 **gain-scheduled LQR**(선형 2차 조절기)과 **INDI**(증분 비선형 동적 역변환)로 구현하고
   안정성을 *수식으로 증명*한다.
2. 전술 의사결정을 **투명한 정책(규칙 + 오프라인 학습)**으로 구현한다.
3. 모든 것을 **오픈소스 JSBSim** F-16 6자유도 시뮬레이터 위에서 *재현 가능하게* 돌린다.
4. **형식 검증(Z3/SMT)**과 **고AoA 실증(NASA TP-1538)**으로 주장을 뒷받침한다.

즉 이 책은 "AI가 비행기를 어떻게 모는가"를 *코드 한 줄까지 추적 가능한* 형태로 가르친다.

### 대상 독자와 선수지식
- **주 독자**: 학부 3~4학년 ~ 대학원 입문. 항공·제어·로보틱스·AI 전공 또는 그 교차.
- **가정하는 선수지식**: 거의 없음. 미적분·선형대수 기초, 파이썬 읽기 정도면 충분.
  *벡터/행렬, 미분방정식, 확률* 의 최소 개념은 필요한 곳에서 그때그때 정의한다.
- **★ 표시 절**: 증명·고급 유도 등 심화. 처음 읽을 땐 건너뛰어도 흐름이 끊기지 않는다.

### 이 책을 읽는 법 (모든 章 공통 표준)
각 章은 동일한 형식을 따른다:
- **학습 목표** — 章을 마치면 할 수 있게 되는 것.
- **난이도 표시**: 🟢 개념(누구나) · 🟡 흐름(연결) · 🔴 코드/수식(상세).
- 서술 순서: **무엇을(정의) → 왜(동기) → 어떻게(절차) → 예시 → 연습문제**.
- **모든 용어는 처음 등장할 때 정의**한다. 비유보다 *목적·설계*를 먼저 말한다.
- 章 끝에 **연습문제**와 필요한 **용어집**을 둔다.
> 표준 章의 모범 = [9~10장: 의사결정 정책](NEW_ENGINE_BT_POLICY_SPEC.md) (이 깊이가 전 章의 기준).

### 재현성 원칙
이 책의 모든 결과는 코드로 재현된다. 각 章은 실행 명령을 명시한다. 핵심 환경:
**Python 3.14 · JSBSim 1.3.0 · numpy/scipy · (검증) z3-solver**. 엔진 본체는 자급식(self-contained)
이며 F-16 비행데이터를 번들한다(`new_match_engine/jsbsim_data/`, LGPL-2.1).

---

## 표기법 (Notation) — 전 章 공통

> 章 사이 혼동을 막기 위해 *기호·단위·부호*를 여기서 한 번에 못 박는다. 章 본문은 이 규약을 따른다.
> (출처·정합: `new_match_engine/TACTIC_SPEC.md`, 정밀도 정책 `precision-policy`.)

### 단위 (외부 인터페이스)
| 물리량 | 단위 | 비고 |
|---|---|---|
| 각도 | 도(°) | 라디안은 JSBSim 내부(plant)에서만. 경계에서 변환. |
| heading(방위) | °, 0~360, 진북 기준, 시계방향 증가 | 절대값 |
| 고도 | 피트(ft), MSL | 절대값(AGL 아님) |
| 속도 | 노트(kts, CAS) 외부 / fps(TAS) 제어내부 | 경계에서 변환 |
| 거리 | 피트(ft) | |
| 시간 | 초(s) | tick 주기로 환산 |

### 상태·기하 기호
| 기호 | 뜻 | 부호/범위 |
|---|---|---|
| $\psi$ (psi) | heading 방위 | 0~360° |
| $\theta$ (theta) | pitch 자세각 | 상승 + |
| $\phi$ (phi) | roll 뱅크각 | 우뱅크 + |
| $V$ | 속도 | + |
| $h$ | 고도 | + |
| ATA | 내 기수→적 각(Antenna Train Angle) | 0~180°, 0=정조준 |
| AA | 적 꼬리 기준 내 각(Aspect Angle) | 0~180° |
| HCA | 진행방향 사잇각(Heading Crossing Angle) | 0~180° |
| closure | 거리 변화율 | +접근/−이격 (kts) |
| $E_s$ | 비에너지 $h + V^2/2g$ | ft 등가 |
| rel_b | 상대방위 | ±180°, 우+/좌− |

### 제어 입력·setpoint
| 기호 | 뜻 |
|---|---|
| $u = [\delta_{thr}, \delta_{elev}, \delta_{ail}, \delta_{rud}]$ | 조종면 명령 (throttle/elevator/aileron/rudder) |
| Setpoint $(\psi^*, h^*, V^*)$ | 유도가 만든 목표값 |
| $K$ | LQR 게인 행렬, $u = u_0 - K(x - x^*)$ |
| $\bar g$ | INDI 제어효과(control effectiveness) |

### 속도(rate)
| 기호 | 뜻 | 단위 |
|---|---|---|
| $p, q, r$ | roll/pitch/yaw rate | rad/s(내부), °/s(표시) |
| ego_r_dps, enm_r_dps | 나/적 yaw rate | °/s, 부호 |

### 게임 규칙 상수
| 이름 | 값 |
|---|---|
| WEZ | ATA < 12° ∧ 500~3000 ft → ≤25 HP/s |
| Hard Deck | < 1000 ft = 패배 |
| 매치 | 300 s |
| tick rate | 물리 120Hz · 제어 20Hz · BT 10Hz |

### 정밀도 규약
- 내부 계산은 float64. 표시 자릿수는 물리량별로 통일(각 1°, 거리 1ft, 점수 소수 2자리 등).
- 분모는 항상 0-가드(`+1e-9`). (상세: 정밀도 정책 문서.)

---

## 마스터 목차 (Master Table of Contents)

> 각 章은 별도 파일. ✅=교과서 표준 완료, 🔧=내용 있음·표준 승급 필요, ⬜=신규 집필 필요.

### Part I — 기초 (Foundations)
| 章 | 제목 | 파일 | 상태 |
|---|---|---|---|
| 1 | 문제와 동기 — 왜 투명한 AI 파일럿인가 | [NEW_ENGINE_PROJECT_INTRO](NEW_ENGINE_PROJECT_INTRO.md) | 🔧 |
| 2 | 큰 그림 — 4계층과 직관 | [NEW_ENGINE_STUDENT_GUIDE](NEW_ENGINE_STUDENT_GUIDE.md) | 🔧 |
| 3 | 공중전·BFM·기하·단위 (JSBSim 소개) | (본 파일 표기법 + TACTIC_SPEC) | ⬜ |

### Part II — 비행 제어 (Flight Control)
| 章 | 제목 | 파일 | 상태 |
|---|---|---|---|
| 4 | 비선형 동역학을 선형으로 — 선형화의 정당성 | [NEW_ENGINE_LQR_CONTROL_REPORT §3](NEW_ENGINE_LQR_CONTROL_REPORT.md) | 🔧 |
| 5 | LQR과 게인 스케줄링 | [LQR_CONTROL_REPORT §5](NEW_ENGINE_LQR_CONTROL_REPORT.md) | 🔧 |
| 6 | Cascade 자동조종과 안정성 증명 | [LQR_CONTROL_REPORT §6,§9](NEW_ENGINE_LQR_CONTROL_REPORT.md) | 🔧 |
| 7 | INDI — 고기동·불확실성의 강건 제어 | [INDI_VALIDATION](NEW_ENGINE_INDI_VALIDATION_REPORT.md) · [INDI_NDI 상세](INDI_NDI_F16_Detailed.md) | 🔧 |

### Part III — 의사결정·전술 (Decision & Tactics)
| 章 | 제목 | 파일 | 상태 |
|---|---|---|---|
| 8 | 관측·전술·정책의 기초 | [BT_POLICY_SPEC 1~5장](NEW_ENGINE_BT_POLICY_SPEC.md) | ✅ |
| 9 | 우리 정책(TreePolicy) — 정의와 동작 | [BT_POLICY_SPEC 6~9장](NEW_ENGINE_BT_POLICY_SPEC.md) | ✅ |
| 10 | 전술 전환 동역학·카탈로그 | [BT_POLICY_SPEC 7~8,10장](NEW_ENGINE_BT_POLICY_SPEC.md) | ✅ |
| 11 | 오프라인 정책 도출 방법론 | [OFFLINE_POLICY_METHODOLOGY](NEW_ENGINE_OFFLINE_POLICY_METHODOLOGY.md) | 🔧 |
| (참조) | 노드·blackboard 레퍼런스 | [NODE_REFERENCE](NODE_REFERENCE.md) · [BLACKBOARD](BLACKBOARD_REFERENCE.md) | 🔧 |

### Part IV — 시스템·통합·검증 (System, Integration, Verification)
| 章 | 제목 | 파일 | 상태 |
|---|---|---|---|
| 12 | 시스템 아키텍처 | [NEW_ENGINE_ARCHITECTURE](NEW_ENGINE_ARCHITECTURE.md) | 🔧 |
| 13 | 기존 엔진 대체 — bridge와 드롭인 | [CORE_REPLACEMENT_PLAN](NEW_ENGINE_CORE_REPLACEMENT_PLAN.md) | 🔧 |
| 14 | 형식 검증(Z3)과 고AoA 실증(TP-1538) | [INDI_VALIDATION §7.6](NEW_ENGINE_INDI_VALIDATION_REPORT.md) | 🔧 |

### Part V — 부록 (Appendices)
- A. 용어집 (각 章 부록 통합)
- B. 표기법 (본 파일)
- C. 참고문헌 (통합 bibliography — LQR/INDI 章 citation 집약)
- D. 실습 가이드 (재현 명령 모음)

---

## 章 표준 템플릿 (새 章 집필 시)
```markdown
# N장. 제목
## 학습 목표
- (이 章을 마치면 ~ 할 수 있다)
## N.1 🟢 개념 …
## N.2 🟡 흐름 …
## N.3 🔴 코드/수식 …
## N.x 예시 / 워크드 예제
## 연습문제
## 용어집(章)
```

---

## 집필 로드맵
- **1단계 (완료)**: 표지·서문·표기법·마스터 목차 (본 파일).
- **2단계**: 🔧 章들을 표준으로 승급 (학습목표·난이도표시·연습문제·표기 통일). Part 순서대로.
- **3단계**: ⬜ 3장(공중전·BFM·JSBSim) 신규 집필.
- **4단계**: 통합 참고문헌·색인·그림목록, 최종 교정.
