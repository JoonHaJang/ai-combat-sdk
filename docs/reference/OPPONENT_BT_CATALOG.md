# 적 BT 도감 — 설계 적 풀(zoo)의 행동 명세

이 문서는 new_match_engine/opponents/zoo 의 설계 적 13 archetype 이 각각 어떤 행동트리(BT)이며,
어떻게 비행하고, 상황(거리·자세·에너지)에 따라 어떻게 tactic 을 바꾸는지 정리한다. 출처는
gen_opponent_zoo.py(BT 구조)와 exp_opp_catalog.py(상황별 tactic 측정)다.

표기는 책 규약을 따른다(별표·이모지·한자 없음).


## 1. 상황별 tactic 표 (한눈에)

각 archetype 대표를 일곱 상황에 넣어 어떤 tactic 을 내는지 측정했다.

| archetype | 정면머지 | 중립빔 | 우리가공격 | 우리가방어 | 원거리 | 저고도 | 에너지열세 |
|---|---|---|---|---|---|---|---|
| A1 PurePursuer | PURE | PURE | PURE | PURE | PURE | PURE | PURE |
| A2 GunTracker | LEAD | PURE | LEAD | PURE | LEAD | LEAD | PURE |
| A3 LagAngler | LAG | PURE | PURE | PURE | LAG | PURE | LAG |
| B1 EnergyFighter | BREAK | HIGH_YOYO | HIGH_YOYO | HIGH_YOYO | HIGH_YOYO | HIGH_YOYO | HIGH_YOYO |
| B2 Extender | BREAK | LEVEL | LEVEL | LEVEL | EXTENSION | LEVEL | LEVEL |
| C1 TwoCircleRate | BREAK | TWO_CIRCLE | TWO_CIRCLE | TWO_CIRCLE | TWO_CIRCLE | TWO_CIRCLE | TWO_CIRCLE |
| C2 OneCircleRad | BREAK | ONE_CIRCLE | ONE_CIRCLE | ONE_CIRCLE | ONE_CIRCLE | ONE_CIRCLE | ONE_CIRCLE |
| C3 Lufbery | BREAK | HIGH_YOYO | HIGH_YOYO | HIGH_YOYO | HIGH_YOYO | HIGH_YOYO | HIGH_YOYO |
| D1 Reactive | BREAK | PURE | PURE | PURE | PURE | PURE | PURE |
| D2 LastDitch | LOW_YOYO | PURE | PURE | PURE | PURE | PURE | PURE |
| D3 Scissors | BREAK | PURE | PURE | PURE | PURE | PURE | PURE |
| E1 AdaptiveAce | BREAK | PURE | LEAD | PURE | LAG | HIGH_YOYO | HIGH_YOYO |
| E2 Passive | LEVEL | LEVEL | LEVEL | LEVEL | LEVEL | LEVEL | LEVEL |

핵심 관찰: 대부분 단일 doctrine 이다 — 상황이 바뀌어도 한 tactic 을 유지한다(B1=HIGH_YOYO,
C1=TWO_CIRCLE 등). 정면머지에서만 방어계열이 BREAK_TURN 으로 갈린다. 상황에 따라 진짜로 tactic 을
바꾸는 적응형은 E1 AdaptiveAce 하나뿐(PURE↔LEAD↔LAG↔HIGH_YOYO). 즉 적끼리는 doctrine 이
구별되지만 각 적은 행동이 단순하다. 이 점은 정책 평가 해석에 중요하다 — 단일 universal tactic 으로
다수 단일-doctrine 적을 이길 수 있으므로, 격추 양상이 비슷하게 보일 수 있다.


## 2. archetype 별 명세 (doctrine · BT · 비행 · 상황 변화)

### A 계열 — 추격(offensive)

A1 PurePursuer. doctrine: 순수 추격. BT: 안전(하드덱→상승) 외엔 항상 Pursue. 비행: 적 현재 위치로
계속 기수 — 동속이면 거리 유지, 끌려가며 시저스 유발. 상황 변화: 없음(전 상황 PURE_PURSUIT).

A2 GunTracker. doctrine: 선도+WEZ 사격. BT: WEZ 거리·각이면 GunAttack, 아니면 LeadPursuit, 그 외
Pursue. 비행: 적 미래위치 선도해 사격각 확보. 상황 변화: 정렬(ata 낮음)이면 LEAD, 옆/뒤(중립·방어)면
PURE 로 약화.

A3 LagAngler. doctrine: 지연 추격. BT: 원거리면 LagPursuit(통제구역 유지), 근거리면 Pursue. 비행:
적 뒤쪽을 겨눠 선회전 유지·에너지 보존. 상황 변화: 원거리·에너지열세에서 LAG, 근접에서 PURE.

### B 계열 — 에너지

B1 EnergyFighter. doctrine: BnZ/E-M. BT: 위협 시 BreakTurn, 저고도면 ClimbingTurn, 에너지우위면
HighYoYo, 기본 HighYoYo. 비행: 수직 줌으로 에너지를 고도로 바꿔 우위 유지·재교전. 상황 변화: 거의
HIGH_YOYO 고정, 정면머지만 BREAK.

B2 Extender. doctrine: 이탈 거부. BT: 위협 시 Break, 원거리·이격이면 Accelerate/Extension, 기본
직진. 비행: 직선 가속으로 거리를 벌려 교전 회피. 상황 변화: 원거리에서 EXTENSION, 그 외 LEVEL(직진).

### C 계열 — 선회전(angles/rate)

C1 TwoCircleRate. doctrine: two-circle. BT: 위협 시 Break, merge·근거리면 TwoCircle. 비행: 코너속도로
도는 선회율 싸움. 상황 변화: 정면머지 BREAK 외 전부 TWO_CIRCLE.

C2 OneCircleRad. doctrine: one-circle. BT: 위협 시 Break, merge·근거리면 OneCircle. 비행: 최소반경
코대코 싸움. 상황 변화: 정면머지 BREAK 외 전부 ONE_CIRCLE.

C3 Lufbery. doctrine: 지속선회 교착. BT: 위협 시 Break, 기본 Loop. 비행: 수평 지속선회 도넛.
상황 변화: 정면머지 BREAK 외 전부 HIGH_YOYO(Loop 매핑).

### D 계열 — 방어

D1 Reactive. doctrine: 반응형 방어. BT: aa 임계 초과(적이 뒤)면 BreakTurn, 아니면 Pursue. 비행:
위협받으면 급선회 회피, 안전하면 추격. 상황 변화: 정면머지(아스펙트 큼) BREAK, 그 외 PURE.

D2 LastDitch. doctrine: 막판 방어. BT: 적 WEZ 진입이면 Break, 위협이면 SpiralDive, 그 외 Pursue.
비행: 피격 직전 나선 강하로 회피. 상황 변화: 정면머지 LOW_YOYO(SpiralDive), 그 외 PURE.

D3 Scissors. doctrine: 평시저스. BT: 시저스/merge 근접이면 ScissorsAccel, 위협이면 Break, 그 외
Pursue. 비행: 연속 반전으로 상대 전진을 늦춤. 상황 변화: 정면머지 BREAK, 그 외 PURE(시저스 조건은
근접 측면에서만).

### E 계열 — 종합/대조

E1 AdaptiveAce. doctrine: 상황의존(최강). BT: WEZ→GunAttack, 위협→Break, 방어국면→HighYoYo,
공격국면 근거리→Lead/원거리→Lag, merge→OneCircle, 저고도→ClimbingTurn, 기본 Pursue. 비행: 국면마다
다른 tactic. 상황 변화: 유일한 진짜 적응형 — 우리가공격 LEAD, 원거리 LAG, 저고도·에너지열세
HIGH_YOYO, 중립 PURE.

E2 Passive. doctrine: 무저항(기준선). BT: 안전 외엔 직진/고도유지. 비행: 거의 직진. 전 상황 LEVEL.


## 3. 해석 — 평가 타당성에 주는 함의

- 적 풀은 doctrine 축(추격/에너지/선회율/방어)을 구별해 덮는다. per-doctrine 응답을 격리 시험하기에
  좋다.
- 그러나 각 적은 대부분 단일-doctrine 으로 단순하다. 상황에 따라 능동적으로 모드를 바꾸는 적응형은
  E1 하나뿐이다. 따라서 "적응형 적에 대한 강건성" 축은 이 풀로는 거의 미검증이며, 후속에서 복합
  적(E1 류 확대)을 늘려야 한다.
- 우리 정책이 다수 적을 한 tactic(VERTICAL_PURSUIT)으로 이기면 격추 양상이 비슷해 보일 수 있는데,
  이는 적이 같아서가 아니라 단일-doctrine 적이 universal chase 에 약하기 때문일 수 있다. 정책의
  상황의존성은 적응형 적(E1)·정면 nose-chaser 에서 진짜로 시험된다.


## 4. 재현

```
python new_match_engine/bt/exp_opp_catalog.py    # 상황별 tactic 표
python new_match_engine/bt/exp_opp_audit.py      # 격자 probe 다양성 감사
python new_match_engine/bt/gen_opponent_zoo.py   # BT 구조 생성(13 archetype × 변주)
```
