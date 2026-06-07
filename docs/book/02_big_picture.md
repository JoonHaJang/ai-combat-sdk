# new_match_engine 학생용 입문서

> **이 문서의 목적**: 새 엔진(`new_match_engine/`)이 *무엇을, 왜, 어떻게* 하는지를
> 비전문가·신입도 따라올 수 있게 한 번에 잇는다. 논문 수준 설명은 `NEW_ENGINE_LQR_CONTROL_REPORT.md`
> 등에 있고, 이 문서는 **전체 그림과 직관**을 준다. 모든 용어는 처음 나올 때 정의한다.
>
> 더 깊게: [구조 다이어그램](13_architecture.md) · [LQR 제어 리포트](06_lqr.md) ·
> [INDI 검증](08_indi.md) · [core 교체 계획](14_engine_replacement.md)

---

## 0. 한 줄 요약

**1:1 공중전(dogfight)을 자율로 수행하는 AI 전투기 조종사**를, *블랙박스 신경망이 아니라
교과서로 설명·증명 가능한 제어기*로 만든 것이 새 엔진이다.

---

## 1. 왜 만들었나 (문제 → 설계 목표)

기존 엔진은 저수준 비행(조종면을 얼마나 꺾을지)을 **RNN**(Recurrent Neural Network, 순환신경망 —
학습된 블랙박스 제어기)으로 처리했다. 두 가지 약점이 있었다:

1. **설명 불가** — "왜 그렇게 움직였나"를 답할 수 없다(블랙박스).
2. **불확실하면 뭉갠다** — 애매한 상황에서 평균적 기동으로 수렴(mode-averaging)해 결단이 흐려진다.

그래서 새 엔진의 설계 목표는:

> **모델 기반·결정론적·인용 가능한 제어기**로 저수준 비행을 대체한다. 게인(gain, 제어 세기 숫자)이
> 명시되고, 안정성을 *수식으로 증명*하며, 같은 입력엔 항상 같은 출력을 낸다.

이를 위한 핵심 도구가 **LQR**(Linear Quadratic Regulator, 선형 2차 조절기 — 아래 §3.3에서 정의)이다.

---

## 2. 큰 그림 — 4계층 파이프라인

전투기 한 대를 모는 과정은 *사람 조종사*의 사고와 같은 4단계로 나뉜다. 위에서 아래로 추상 → 구체:

```
 [1] 상황 판단 (dispatch)     "지금 머리-온 정면충돌 상황 → 어떤 전술?"
        │   Tactic(전술) 하나 선택
        ▼
 [2] 유도 (guidance)          "그 전술을 위해 어디로 향하고, 고도/속도는?"
        │   Setpoint(목표값: 방위 ψ*, 고도 h*, 속도 V*)
        ▼
 [3] 자동조종 (autopilot+LQR) "그 목표를 만들려면 조종면을 얼마나 꺾나?"
        │   u = [throttle, elevator, aileron, rudder]
        ▼
 [4] 물리 (JSBSim F-16)       실제 6자유도 비행역학으로 한 스텝 전진
```

각 화살표 위의 단어(Tactic, Setpoint, u)가 **계층 간 인터페이스**다. 하나씩 풀어보자.

---

## 3. 각 계층, 쉽게

### 3.1 상황 판단 — dispatch (어떤 전술을 언제)

매 결정 시점마다 적과의 **기하(geometry)**를 본다. 핵심 관측값:
- **ATA**(Antenna Train Angle) — *내 기수*가 적을 향한 정도(0°=정조준).
- **AA**(Aspect Angle) — 적 꼬리 기준 내가 보는 각(적이 내게 등을 보이는지).
- **거리**, **closure**(접근 속도), **고도차**, **에너지**(고도+속도의 합).

`bt/tree_policy.py`의 **TreePolicy**가 if-then 스택으로 *상황 → 전술*을 고른다:
- 정면 머지(head-on)면 → `ADAPTIVE`(혼합 기동)
- 적이 도망(evasive)이면 → `VERTICAL_PURSUIT`(수직 추격)
- 가까우면 → `GUN_TRACK`(조준 추적)
- 그 외 → `RF`(기본 추격)

> **왜 상황별인가**: 공중전은 *상황의 조합*이라 단 하나의 전술로 다 못 푼다. 하나를 전역
> 강화하면 다른 상황이 망가진다(실측 교훈). 그래서 **상황을 나눠 각각 다른 전술**을 쓴다.

전술의 목록은 `Tactic` enum(`control/tactic.py`)에 정의된 16종(LEAD_PURSUIT, GUN_TRACK,
ONE_CIRCLE, TWO_CIRCLE, HIGH_YOYO, ADAPTIVE …)이다.

### 3.2 유도 — guidance (전술 → 목표값)

`control/guidance.py`가 전술 + 관측을 받아 **Setpoint**(목표값 묶음)를 만든다:
- **ψ\***(psi star) — 향해야 할 **방위**(나침반 각, 도).
- **h\*** — 목표 **고도**(피트).
- **V\*** — 목표 **속도**(노트).

예: `LEAD_PURSUIT`(앞당겨 쏘기)는 적의 *미래 위치*를 예측해 ψ\*를 그쪽으로 잡는다.
`GUN_TRACK`은 시선각속도(LOS rate) 기반 비례항법(PN, Proportional Navigation)으로 조준을 좁힌다.

### 3.3 자동조종 + LQR — 목표를 조종면으로

여기가 새 엔진의 심장이다. **목표값(ψ\*,h\*,V\*) → 조종면 명령 u**로 바꾼다. 두 겹(cascade)이다:

**바깥 루프 (outer)** — 느린 자세 목표 산출:
- 고도 오차 → **목표 자세각 θ_cmd** (PI 제어).
- 방위 오차 → **목표 뱅크각 φ_cmd** (협조선회 공식 `φ = atan(ψ̇·V/g)`).
  - *협조선회*: 비행기는 차처럼 못 돈다. **기울이고(뱅크) + 당겨야(받음각↑)** 비로소 선회한다.
- 속도 오차 → **throttle**.

**안쪽 루프 (inner) = LQR** — 자세를 정확·안정하게:
- **LQR**(선형 2차 조절기): 비행기 운동을 운영점 근처에서 *직선처럼 근사(선형화)*한 뒤,
  "추종 오차와 조종면 사용량을 동시에 최소화"하는 **최적 게인 K**를 수학으로 푼다
  (CARE라는 행렬방정식의 해). 결과: `u = u₀ − K·(현재상태 − 목표상태)`.
- **gain scheduling**(게인 스케줄링): 고도·속도가 변하면 비행역학도 변하므로, 격자(예: 고도
  3점 × 속도 3점)마다 K를 미리 풀어 두고 현재 조건에 맞게 *보간*해 쓴다.

> **"비선형인데 선형으로 풀어도 되나?"** — 된다. 운영점 근처에선 비선형 동역학이 직선과
> 거의 같고(테일러 1차), 그 직선 시스템이 안정(Hurwitz)이면 *원래 비선형도 국소적으로 안정*임이
> 증명돼 있다(Lyapunov 간접법). 자세한 증명은 LQR 리포트 §3·§6.

### 3.4 INDI — 더 어려운 영역의 강건한 옵션

**INDI**(Incremental Nonlinear Dynamic Inversion, 증분 비선형 동적 역변환)는 LQR 대신 끼울 수 있는
*두 번째 안쪽 루프*다. LQR은 모델(비행역학)을 *가정*해 게인을 고정하는데, 모델이 틀리면(손상·고받음각)
둔해진다. INDI는 **각가속도를 직접 측정**해 그 차이만큼 조종면을 *증분*으로 보정한다 → 모델이 절반만
맞아도 따라간다.

- 옵션 A = LQR, 옵션 B = INDI. `controller="lqr"|"indi"` 한 인자로 교체.
- 검증(`NEW_ENGINE_INDI_VALIDATION_REPORT.md`): 단순기동은 둘 다 우수(차이 없음). **복합 고기동 +
  모델 불확실성**에서 INDI가 ~4배 정밀·~7배 빠른 정착 — "어려운 영역의 강건성".

### 3.5 물리 — JSBSim F-16

`control/plant.py`가 **JSBSim**(오픈소스 비행역학 시뮬레이터)의 F-16 6자유도 모델을 감싼다.
조종면 u를 넣고 한 스텝 전진하면 새 상태(위치·자세·속도)가 나온다. 물리는 120Hz로 가장 잘게 돈다.

---

## 4. 어떻게 이기나 — 심판(judge)과 WEZ

`engine/judge.py`가 원본 규칙을 100% 복제한다:
- **WEZ**(Weapon Engagement Zone, 무장교전구역): `ATA < 12°` 이고 거리 500–3000ft면 적에게
  데미지(초당 최대 25HP, 각도·거리에 비례).
- **Hard Deck**: 고도 1000ft 미만 = 패배(지면 충돌 위험).
- 승패 우선순위: Hard Deck → 체력 0 → 시간초과 시 체력 우위.

즉 **적 기수 앞 12° 안에, 적정 거리에서, 오래 머무르면** 이긴다. 그래서 §3의 모든 계층이
*그 기하를 만들려고* 협력한다.

---

## 5. bridge — 기존 시스템에 끼우기

새 엔진은 처음엔 *고립된 연구 모듈*이었다. **bridge**(`bridge/core_adapter.py`)가 이를
기존 SDK에 **그대로 끼울 수 있게** 한다:

- 기존 매치 실행 코드는 `BehaviorTreeMatch(.yaml, .yaml).run()`을 쓴다.
- bridge가 *같은 모양*의 클래스를 제공하되 내부만 새 엔진으로 돌린다 → **import 한 줄 교체**.
- `python scripts/run_match.py ... --backend lqr|indi|legacy` 로 엔진을 골라 쓴다.
- 적 BT(`.yaml`)는 `yaml_bt.py`가 해석해 그대로 사용(손 포팅 없이 ~970 적 호환).

검증: `python -m new_match_engine.bridge.verify_swap` → 세 백엔드 동일 인터페이스 PASS.

---

## 6. 용어 사전 (빠른 참조)

| 용어 | 뜻 |
|---|---|
| BT (Behavior Tree) | 행동트리 — 조건/액션 노드로 전술을 고르는 규칙 트리 (`.yaml`) |
| Tactic | 전술 enum (LEAD_PURSUIT, GUN_TRACK, TWO_CIRCLE …) |
| Setpoint | 목표값 묶음 (ψ\* 방위, h\* 고도, V\* 속도) |
| LQR | 선형 2차 조절기 — 최적 게인 K로 자세 안정. `u=u₀−K(x−x*)` |
| INDI | 증분 비선형 동적 역변환 — 각가속도 측정 기반 강건 제어 |
| gain scheduling | 운영점(고도·속도)별 K를 보간해 사용 |
| 협조선회 | 뱅크 + 당김으로 고도 유지하며 선회 (`φ=atan(ψ̇V/g)`) |
| ATA / AA | 내 기수→적 각 / 적 꼬리 기준 각 |
| WEZ | 무장교전구역 (ATA<12°, 500–3000ft → 데미지) |
| Hard Deck | 최저 고도(1000ft) — 미만 시 패배 |
| JSBSim | 오픈소스 6-DOF 비행역학 시뮬레이터(F-16) |
| bridge | 새 엔진을 legacy core 자리에 끼우는 드롭인 어댑터 |

---

## 7. 직접 해보기

```bash
# 캐노니컬 평가 — 우리 정책(TreePolicy) vs .yaml 적, beam 시작
python new_match_engine/bt/run_match.py ace

# bridge 로 .yaml vs .yaml (엔진 선택)
python -m new_match_engine.bridge.run_legacy aggressive ace --controller indi

# 기존 SDK 흐름에 새 엔진 끼우기
python scripts/run_match.py --agent1 aggressive --agent2 ace --backend lqr

# 교환이 제대로 됐는지 검증
python -m new_match_engine.bridge.verify_swap
```

---

## 8. 한 줄 take-home

> 공중전을 **상황 판단(dispatch) → 목표(guidance) → 투명 제어(LQR/INDI) → 물리(JSBSim)**
> 의 4계층으로 풀고, 각 계층이 *설명·증명 가능*하며, **bridge**로 기존 시스템에 그대로 끼운다.
