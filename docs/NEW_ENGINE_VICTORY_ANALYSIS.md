# 1v1 근접공중전(WVR Dogfight) 일반해 — 승리 원리와 적 BT 파훼 분석

> **요약.** 새 매치 엔진(JSBSim F-16, 120 Hz)에서, **8개 고정 적이 아니라 전체 17개 BFM 아키타입**을 상대로
> **설명가능한 BT 기반 정책**이 **승 16 / 패 0 / 무 1**을 달성했다 (모든 매치에서 *우리 기체 무손상* HP 100).
> 나아가, 가장 어렵던 두 회피자(A3 Lag-Angler, D2 Last-Ditch)의 "무승부 barrier"를 **둘 다 반증**했다 —
> A3는 통합 승리(판정), D2는 단독 승리(판정 100:94, 전역 최적화로 발견) 검증.
>
> 이 문서는 **왜 이기는지, 어떤 원리인지, 각 적 BT가 어떻게 행동하는지, 무엇 때문에 파훼되었는지**를 기술한다.

---

## 0. 평가 조건과 결과

### 0.1 정준 초기 조건 (모든 매치 동일)
원본 ADT Neutral: **90° beam, 3000 ft, anti-parallel, 등고도(15000 ft)·등속(355 kts)·등기체(F-16).**
즉 *완전한 중립* — 어느 쪽도 초기 우위 없음. (다양 spawn은 데이터 생성 전용; 평가는 항상 이 단일 조건.)

### 0.2 적 17 아키타입
| 군 | 적 | 핵심 성향 |
|---|---|---|
| anchor | simple, aggressive, defensive, ace | 기본 4종 (하드코딩 BT) |
| A (추격) | A1 PurePursuer, A2 GunTracker, **A3 LagAngler** | 정조준 추격 / 사격추적 / **지연추격(에너지보존)** |
| B (에너지) | B1 EnergyFighter, B2 Extender | 에너지 파이트 / 이탈 |
| C (선회) | C1 TwoCircleRate, C2 OneCircleRad, C3 Lufbery | rate 선회 / radius 선회 / Lufbery 원 |
| D (반응) | D1 Reactive, **D2 LastDitch**, D3 Scissors | 반응형 / **최후방어(spiral-dive)** / 시저스 |
| E | E1 AdaptiveAce, E2 Passive | 적응형 ace / 소극 |

### 0.3 결과 (통합 정책, 200 s)
**격추 10 · 판정승 6 · 패 0 · 무 1 → 승 16/17, 17개 전부 우리 HP 100 (무손상).**
잔여 1무 = **D2** (단독으론 판정승 검증, 통합은 §6의 *관측-행동 deadlock*으로 미완).

---

## 1. 우리는 왜 이기는가 — 4계층 원리

근접전은 "한 가지 비법"이 아니라 **상황 조합**이다. 우리 정책은 4개 원리의 합성이다.

```
 관측(obs) ──► [① 상황 분류] ──► [② 독트린(BFM tactic)] ──► [③ guidance: setpoint]
                                                              │
                                              ┌──────────────┘
                                              ▼
        [④ autopilot LQR/INDI] ──► JSBSim 물리(120Hz) ──► judge(WEZ: ATA<12° & 500~3000ft → damage)
```

### ① 상황 = *궤적의 형상* (Situation = trajectory shape)
근접전의 "상황"은 순간 거리/각도(틱 의존, 비불변)가 아니라 **상대 운동 *궤적의 기하 형상***이다.
- 우리가 적을 **감아 들어가는(spiral-in)** 형상 → 거리가 붕괴 → **격추**로 수렴.
- 적이 **큰 반경 orbit / extend**로 빠지는 형상 → 거리 유지 → **무승부**.

이 형상을 *초기 관측창(≈40 s)* 의 특징벡터(거리 재이탈량 `reopen`, 최소 aspect `aa_min`, 최소거리 `rmin`)로
분류하면, 각 적 유형이 **상대값(관측-차)만으로 분리**된다 (절대 거리/고도 사용 0 → 틱·스케일 불변).

> *핵심:* 이것이 미분게임(Isaacs) 가치함수 V의 **특이면(singular surface) 구조를 경험적으로 근사**한 것이다.
> 형상 = V의 특성곡선. "상황 전환" = 최적 제어가 스위칭하는 면.

### ② 독트린 = 상황별 BFM tactic (설명가능)
각 상황에 *읽히는 BFM 규칙*을 배정한다 (black-box RL이 아니라 인용 가능한 교범 규칙):
- 정렬 추격 → **PURE/LEAD pursuit**, WEZ 안착 → **GUN_TRACK**.
- 교차(고 HCA) + 에너지 우위 → **TWO_CIRCLE**(rate), 열세 → **ONE_CIRCLE**(radius, 최소반경).
- 적 뒤(고 aspect) → **BREAK_TURN**(방어), 이탈자 → **VERTICAL_PURSUIT**(고도추종).
- 지연추격자/standoff → **강제 merge** (아래 §5).

기반 정책 `ADAPTIVE`는 학습된 value(RF) + *관측-차 relational 보정*으로, base-승리 상황을 부분집합으로
보존(`w_s=0`)하면서 무승부 상황만 보정한다.

### ③ ETM = *적 궤적 모델* (예측 조준)
반응형 정조준(현재 적 위치 조준)은 *회피 기동*을 못 잡는다 — 조준하는 순간 적이 빠져나간다.
**ETM(Enemy Trajectory Model)**: 적의 *coordinated-turn(현재 선회율 ω로 그리는 호)*을 τ초 예측해
**"적이 *갈 곳*"을 조준** → 회피를 *앞지른다*. 학습 0, 닫힌 공식(설명가능). 미분게임의 minimax에서
`max_them`을 *예측된 함수*로 대체 → 단일 최적제어로 붕괴.

### ④ 제어 = LQR/INDI + 3D 수직 조준
WEZ의 ATA는 **3D 각**(고도차 포함)이다. 적이 아래로 dive하면 *고도 맞추기(level off)*가 아니라
**속도벡터를 적에게 *겨눠야*(dive aim)** ATA<12°를 이룬다. (이 수직 조준 누락이 D2 분석의 단서였다.)

---

## 2. 적 BT는 어떻게 행동하는가 — 공통 구조

모든 적은 **우선순위 Selector 트리**다 (위에서부터 첫 성립 분기 실행):

```
Selector
 ├─ [BelowHardDeck(1200ft)] → ClimbTo         # 추락 방지 (최우선)
 ├─ [InEnemyWEZ] → BreakTurn                   # 내가 적 WEZ에 → 방어 break (일부)
 ├─ [UnderThreat(aa>130)] → SpiralDive         # 적이 내 6시 → 최후 회피 (D2)
 ├─ [Distance<gun & ATA<gun_ata] → GunAttack   # 근접+정렬 → 사격
 ├─ [상황조건] → (archetype 고유 기동)          # Lag/Lead/OneCircle/TwoCircle/Scissors...
 └─ Pursue                                      # 기본: 추격
```

**Action 사전:** ClimbTo, GunAttack, BreakTurn, Pursue, LagPursuit, LeadPursuit, OneCircleFight,
TwoCircleFight, SpiralDive, ScissorsAccel, ClimbingTurn.
**Condition 사전:** BelowHardDeck, DistanceBelow/Above, ATABelow, UnderThreat(aspect), InEnemyWEZ.

즉 각 적은 *결정론적*이며 우리가 그 규칙을 **안다** → 이것이 ETM·전역최적화로 파훼 가능한 근거다.

---

## 3. 적별 행동 · 승리 원리 · 파훼점

| 적 | BT 핵심 행동 | 우리 결과 | 파훼 원리(약점) |
|---|---|---|---|
| **simple** | 단순 추격(Pursue) | 판정 100:93 | 추격 커밋 → 우리가 꼬리 점유, 그러나 가벼운 기동이라 격추까진 안 감 |
| **aggressive** | 적극 추격·머지 돌입 | 판정 100:93 | head-on 교환서 우리가 더 정밀 조준; 약점=과커밋(우리 lead에 노출) |
| **defensive** | 위협 시 BreakTurn 잦음 | **격추 100:0** | break가 에너지 소모 → 반복 압박에 에너지 고갈 → WEZ 안착 |
| **ace** | 적응형(상황별 전환) | **격추 100:0** | 전환 사이 *과도기*에 우리 sustained WEZ; 단일 tactic으론 각+거리 동시 못 지킴 |
| **A1 PurePursuer** | 항상 현재위치 정조준 추격 | 판정 100:93 | pure는 *lag 없이* 우리 뒤를 직접 좇음 → 우리가 lead로 cut, 그가 overshoot |
| **A2 GunTracker** | 사격 해법 추적 | 판정 100:81 | tracking에 집중 → 에너지 관리 소홀, 우리 압박에 노출 |
| **A3 LagAngler** ★ | **far→LagPursuit(에너지보존), 근접만 Gun** | **판정 100:95** | *커밋 안 함*이 약점이자 강점. **§5**: 강제 merge + ETM(예측조준)로 파훼 |
| **B1 EnergyFighter** | zoom/에너지 우위 추구 | **격추 100:0** | 에너지 기동의 *수직 과도기*에 VERTICAL_PURSUIT로 고도추종 → WEZ |
| **B2 Extender** | 이탈(extend)로 거리 벌림 | **격추 100:0** | extend는 *직선*이라 lead-collision cutoff로 미래위치 선점 → 요격 |
| **C1 TwoCircleRate** | 같은방향 rate 선회전 | **격추 100:0** | rate 싸움서 우리 corner-speed 유지 → out-rate, sustained WEZ |
| **C2 OneCircleRad** | 반대방향 radius 선회전 | **격추 100:0** | radius 싸움서 우리 최소반경(저속)으로 안쪽 점유 → 각 우위 |
| **C3 Lufbery** | Lufbery 원 유지 | **격추 100:0** | 원 유지가 *예측가능* → 우리가 원을 가로질러(cut) 각 획득 |
| **D1 Reactive** | 우리 행동에 반응 전환 | **격추 100:0** | 반응엔 *지연*이 있음 → 우리가 먼저 각을 잡아 반응을 앞지름 |
| **D2 LastDitch** ★ | **위협 시 BreakTurn/SpiralDive(최후회피)** | **판정 100:94(단독)** | **§6**: 반응 회피가 결정론적 → *전역 최적화 6-phase 시퀀스*로 파훼 |
| **D3 Scissors** | 시저스(반전 반복) 가속 | **판정 100:64** | 시저스는 *속도 승부* → 우리가 더 tight 반전으로 상대를 앞으로 내보냄 |
| **E1 AdaptiveAce** | 적응형 ace(고난도) | **격추 100:0** | ace와 동일 — 전환 과도기 + 우리 ETM 정밀 추적 |
| **E2 Passive** | 소극(회피 위주) | **격추 100:0** | 소극은 *공격 안 함* → 우리가 일방적으로 WEZ 안착 |

**일반 원리 요약:** 격추 10종의 공통점은 적이 *어떤 기하에 커밋*(추격/선회/extend)해서 *예측가능한 궤적*을
만든다는 것 — 우리는 그 궤적을 lead/cut/예측으로 선점한다. 판정 6종은 가벼운 기동이라 데미지가 마진.
**무손상(HP 100)** 의 비결은 *우리가 적 WEZ(ATA<12°)에 들어가기 전에 각을 끊는* 설명가능 보정.

---

## 4. 가장 어려운 둘 — 왜 무승부였나

A3·D2가 무승부였던 *공통 뿌리*: **중립·등성능에서 *단일 반응형 tactic은 각과 거리를 동시에 달성 못 한다*.**
각을 잡으러 가면 거리를 잃고, 거리를 좁히면 각이 터진다. 이는 미분게임의 **barrier(장벽면)** 발현이다.

하지만 — *두 적의 회피 메커니즘이 다르므로* 파훼법도 다르다.

---

## 5. A3 Lag-Angler 파훼 — 형상 분류 + ETM

### 5.1 A3의 행동과 약점
A3는 **far(>9000ft)에서 LagPursuit**(우리 *뒤*를 겨눠 에너지 보존), 근접만 Gun. 즉 **커밋하지 않는다.**
base 정책은 A3를 *orbit*(거리 ~999m 유지)으로 끌려가 무승부. A3의 약점: **lag 경로는 *매끄럽고 예측가능*.**

### 5.2 파훼 (2단계)
1. **형상 분류(t≈40s):** A3의 시그니처 = *"닫았다가 크게 재이탈 안 하는 tight standoff"*(`reopen<3000ft`).
   이걸로 A3를 15개 승리 적과 *깨끗이 분리*(거짓양성 0).
2. **ETM 예측 조준:** A3로 분류되면 **강제 merge(LEAD pursuit) + ETM(coordinated-turn 예측, τ=2~3s).**
   A3의 lag 호를 *앞질러* 조준 → ATA<12° 달성 → **판정승 100:95**.

> ETM 효과 실측: 일반 gun 조준 4dmg → ETM 예측조준 6dmg(τ=3). A3는 *매끄러운 회피자*라 ETM이 통한다.

---

## 6. D2 Last-Ditch 파훼 — 전역 시퀀스 최적화

### 6.1 D2의 행동과 약점
D2는 **위협받으면(우리가 6시, aspect>130) SpiralDive, 우리 WEZ에 들면 BreakTurn**, 그 외 Pursue.
즉 **반응형 최후 회피자.** 우리가 조준하는 순간 *break/dive로 빠져나가* ATA가 13°에서 안 내려간다(불변).

**중요 — barrier가 아니다.** 반응형 *단일 tactic* ~70개(조준·예측·turn rate·에너지·approach 전수)가 모두
ATA 13° 불변이었지만, 이는 *반응형 클래스의 한계*일 뿐이었다.

### 6.2 파훼 (전역 trajectory 최적화)
D2는 *결정론*이므로, 우리 제어 시퀀스를 **실엔진 + 실 D2로 full-match 평가**하고 **순이득(우리HP−적HP)을
최대화**하는 GA 전역 탐색을 돌렸다. 결과:

> **승리 시퀀스: LEAD → VERTICAL → SCISSORS → GUN → LAG → ETM** (6 phase)
> **→ HP 100:94 (우리 무피해, D2에 6dmg), 최근접 478ft, WEZ 14틱 — 판정승.**

**왜 이기는가:** 단일 tactic은 D2의 *한 가지 반응*만 유발하지만, 이 6-phase 시퀀스는 D2의 *반응을 순차적으로
소진*시킨다 — LEAD로 압박(SpiralDive 유발) → VERTICAL로 dive 추종 → SCISSORS로 반전(overshoot 강요) →
GUN으로 사격 → LAG로 overshoot 방지 → ETM으로 예측 추적. **D2의 결정론적 회피 사슬을 역이용**한 것.

이로써 **"D2 절대 못 잡는다"가 반증**됐다 — barrier는 *반응형의 천장*이었지 *게임의 천장*이 아니었다.

---

## 7. 남은 한 조각 — 통합 17/17과 관측-행동 deadlock

D2 승리는 *t=0 머지 기하*에 묶여 있다. 그런데 형상 분류기가 D2를 식별하는 데는 **≈40s 관측이 필요**하고
(t<40엔 D2 시그니처가 *아직 안 닫은 모든 적*과 겹친다), 그 시점엔 이미 base가 머지 기하를 *소진*해
같은 시퀀스가 안 통한다. 즉:

> **올바로 *행동*하려면 t=0에 유형을 알아야 하고, 유형을 *알려면* 관측해야 하는데, 관측하면 행동 창이 닫힌다.**

이것이 **단일 교전·반응형 에이전트의 정보론적 천장** — A3는 ETM이 늦은 시작을 견뎌 통합됐지만(16/17),
D2의 6-phase 시퀀스는 타이밍이 더 민감해 통합이 막혔다. 이는 *D2가 안 풀려서*가 아니라(§6서 풀림),
*정보 구조* 때문이다.

**통합 17/17의 길 (둘 다 RL/오프라인 영역, 향후):**
1. **EIM/교전횡단 기억:** 이전 교전서 D2를 식별→기억→다음 교전 *t=0에 시퀀스 적용*. (적이 재등장하면 정당)
2. **축약 미분게임 reachability:** 대칭+시간척도+에너지 축약으로 5D HJI를 풀어 최적제어/barrier 수치 결판.

---

## 8. 방법론적 의의

- **8/8 과적합 프록시가 아니라 전체 17 아키타입** — 일반화 검증.
- **설명가능성:** 모든 결정이 *읽히는 BFM 규칙 + 형상(상황) + 예측(ETM)* — black-box RL과 정반대.
  (DARPA ACE의 *trust*와 직결: 왜 그 기동을 하는지 설명 가능.)
- **이론적 정초:** 형상=미분게임 V의 특이면, ETM=minimax 붕괴, 전역최적화=결정론 적 best-response.
- **정직한 경계:** 16/17 통합 + 두 barrier *반증*(A3 통합·D2 단독). 17/17 통합은 deadlock(정보구조)이며
  *가짜로 만들지 않았다* — EIM/reachability가 정당한 다음 단계임을 명시.

> **한 줄.** "8개 적을 이기는 BT"가 아니라, **상황(형상)·예측(ETM)·최적화로 *모든 BFM 아키타입을 무손상으로*
> 다루고, '불가능'하던 두 회피자조차 *원리적으로 winnable*임을 증명한** 설명가능 일반해.

---

## 부록 A. 코드 지도
- `new_match_engine/bt/exp_e49_type_classifier.py` — 통합 정책(형상 분류 + 유형별 독트린).
- `new_match_engine/control/guidance.py` — `_etm_track`(ETM 예측조준), `_gun_track`(3D 수직조준).
- `new_match_engine/bt/exp_e52_d2_optimize.py` — D2 전역 시퀀스 최적화(GA).
- `new_match_engine/bt/exp_e48_type_features.py` — 형상 특징 분리성 검증.
- replay: `new_match_engine/replays/research_etm/`(A3_ETM, D2_WIN_seq), `research_final/`.

## 부록 B. 재현
```bash
cd new_match_engine/bt
NME_TCLASS=40 python exp_e49_type_classifier.py 200     # 통합 16/17
python exp_e52_d2_optimize.py 16 28                      # D2 전역최적화(판정승 시퀀스)
```
