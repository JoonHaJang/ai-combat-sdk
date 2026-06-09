# 1장 부록(연구편). 정책 학습의 열린 질문과 실험 설계

이 문서는 1장 본문(문제와 동기)의 연구 동반 문서다. 본문이 "무엇을 왜 만들었는가"를
설명한다면, 이 문서는 그 설계 결정 가운데 아직 정량적으로 검증되지 않은 부분을 연구질문으로
세우고, 그것을 푸는 실험을 설계한다. 대상은 본문 4.3 상황분류, 4.5 라벨링, 4.6 정책 모델,
4.7 커버리지다.

표기는 책 전체 규약을 따른다. 별표 강조, 이모지, 한자를 쓰지 않는다.


## 쉬운 요약 (먼저 읽기)

이 연구가 한 일을 한 문단으로 말하면 이렇다. 우리 AI 조종사는 "지금 상황을 보고 어떤 기동을
할지" 정하는 정책을 데이터로 배운다. 그 정책을 만드는 방식에 그동안 확인하지 않고 넘어간 가정이
몇 개 있었다. 이 연구는 그 가정들을 하나씩 실제로 시험했다.

확인하려던 질문 네 가지를 쉬운 말로 적으면:

1. 상황을 몇 개의 정해진 칸(공격/방어/중립)으로 나눠서 푸는 게 맞나, 아니면 칸을 나누지 말고
   숫자(각도, 거리 등)를 그대로 보고 배우는 게 맞나.
2. 우리가 "정답"으로 쓰는 라벨(이 상황에서 이 기동을 하면 얼마나 이기나)이 믿을 만한가.
3. 정답을 배우는 모델로 어떤 것이 가장 좋은가. 정확한 모델과 사람이 이해하기 쉬운 모델 사이에
   무엇을 고를까.
4. 우리가 연습시킨 상황들이 실제 싸움에서 마주칠 상황을 충분히 덮는가.

알아낸 것을 쉬운 말로 적으면:

1. 칸으로 나누지 않고 숫자를 그대로 보는 쪽(연속)이 더 낫다. 상황은 칸칸이 끊어진 게 아니라
   이어진 스펙트럼이라, 적게 나누면 손해다.
2. 라벨을 만드는 과정에 숨은 버그가 있었다. 같은 상황을 두 번 채점하면 점수가 최대 53점이나
   달랐다(만점 100). 원인을 찾아 고쳤고, 이제는 두 번 채점해도 완전히 같다.
3. 정확도만 보면 부스팅(XGBoost)이 약간 앞서고 지금 쓰는 RandomForest와 거의 같다. 사람이
   이해하기 쉬운 모델(EBM, 규칙형)은 약간의 정확도를 내주고 설명력을 얻는다. RandomForest 는
   "유일한 정답"이 아니라 정확도, 속도, 설명력의 균형점이다.
4. 우리가 새로 설계한 적 약 60종이면 정책 품질이 더 안 좋아지지 않는 수준에 도달한다. 다만
   훈련에서 마주친 상황과 실제 배포에서 마주치는 상황 사이에 차이가 있어, 적의 수가 아니라
   시작 배치(기하)를 더 넓혀야 한다.

이 요약 뒤의 R, P, Q 절은 같은 내용을 근거와 수치로 자세히 적은 것이다. 처음 읽는 사람은 이
요약과 각 절 첫 문단만 읽어도 흐름을 따라올 수 있다.


## R0. 왜 이 문서가 필요한가 — 미검증 지점

clean-slate로 현재 상태를 점검하면, 본문이 단정한 것 가운데 측정으로 뒷받침되지 않은 것이 있다.

- discrete 대 연속. 본문 약속 2는 "상황을 나눠서 본다"는 이산 분류를 전제한다. 그러나 배포된
  정책(tree_policy.py)은 손-규칙 4개와 연속 가치회귀(RandomForest)를 섞은 하이브리드다. 순수
  이산 정책과 순수 연속 정책을 같은 조건에서 맞붙인 실험은 한 적이 없다. 즉 이 선택은 풀린 적이
  없는 열린 질문이다.
- 수치의 신선도. 본문 초안의 "CV R2 0.72, 분류 0.42, 중요도 aa 0.38, dist 0.29"는 현재
  데이터로 재현되지 않는다. 아카이브 데이터셋(10,233 상태)에서 다시 재면 가치 회귀 CV R2는
  약 0.39, 1위 feature는 aa가 아니라 ata(약 0.36에서 0.38)다. 옛 수치는 폐기하고 실측으로
  교체해야 한다.
- 커버리지 미입증. 학습 상태가 배포 시 실제 방문 상태를 충분히 덮는지 정량화된 적이 없다.
- 적 풀 적절성. legacy 풀 992개(archetypes 174 + opponent_pool 795 + examples 23)는 모두
  로드되지만, 합성 격자 probe 결과 고유 행동은 292종뿐이고 112개는 격자 전체에서 단일 tactic만
  내는 퇴화(그중 37개는 항상 PURE_PURSUIT)다. 중복과 퇴화가 커서 "1:1 dogfight를 덮는다"는
  커버리지 주장을 받치지 못한다.

따라서 작업의 방향은 "본문 수치를 채운다"가 아니라, 연구질문을 세우고 설계된 실험으로 답을 낸 뒤
그 답으로 본문을 갱신하는 것이다.


## R1. 연구질문 (AIPILOT 관점)

| RQ | 질문 | 본문 | 입증하려는 주장 |
|---|---|---|---|
| RQ1 | BFM tactic 선택에 명시적 이산 상황분류가 필요한가, 아니면 기하 feature 위 연속 가치학습이 같은 상황의존 행동을 동등 이상으로, 더 투명하게 복원하는가 | 4.3 | 교범의 이산 상황이 학습가능한 구조로 실재하는지 |
| RQ2 | 결정론 white-box forward-sim 데미지 라벨이 재현가능하고 상황별 물리적으로 옳은 best-tactic을 주며 근사/myopic 라벨을 능가하는가. 순위가 안정되는 horizon은 | 4.5 | "추측 없는 정답" 라벨이라는 근거 |
| RQ3 | 저차원 tabular 가치회귀에서 글래스박스(EBM)와 최적 규칙(GOSDT)이 블랙박스(XGBoost) 및 incumbent(RandomForest) 정확도를 따라잡으며 검증 가능한 결정구조를 주는가 | 4.6 | 정확도와 투명성의 프런티어를 정량화 |
| RQ4 | 설계된 적 풀과 LHS spawn의 학습분포가 배포 방문 상태를 충분히 덮는가. 미지 적과 미방문 영역으로 일반화하는가. 데이터 규모에 따라 어떻게 스케일하는가 | 4.7 | 커버리지가 우연이 아니라 설계임을 입증 |
| RQ5 | 학습 정책을 사람이 읽는 규칙으로 표현하고 단조성/안전성을 형식 점검할 수 있는가 | 16장 | 투명성과 형식검증을 정책층까지 확장 |

이 연구의 novelty는 모델 자체가 아니라 두 가지다. 첫째, 결정론 white-box 게임이 몬테카를로 없이
정확한 fitted-Q 라벨을 가능케 한다는 점. 둘째, 비행 정책에 투명성을 1급 요구로 두고 그
정확도-투명성 프런티어를 BFM 과제 위에서 정량화한다는 점이다.


## R2. 적 풀 설계 — 1:1 dogfight 문제 커버

1:1 WVR dogfight 문제는 두 축으로 분해된다.

- 기하 축(시작 상황): head-on, offensive, defensive, neutral, one-circle, two-circle 머지.
  LHS spawn이 담당한다.
- 행동 축(적 doctrine): 적이 어떤 교리로 싸우는가. 새로 설계하는 적 풀이 담당한다.

두 축의 곱이 1:1 문제 공간이다. legacy 풀의 중복을 버리고, 3장 BFM 교리에 근거한 행동 archetype을
체계적으로 생성한다.

### R2.1 archetype 분류 (3장 대응)

| archetype | doctrine | 핵심 분기 | 강요 상황 | 요구 파훼 |
|---|---|---|---|---|
| A1 PurePursuer | 순수 추격 | 항상 Pursue | 끌려감, 시저스 유도 | out-rate, overshoot 강요 |
| A2 GunTracker | 선도+WEZ 사격 | WEZ→GunAttack, else LeadPursuit | 정밀 사격 위협 | 각 깨기, 에너지 |
| A3 LagAngler | 지연 추격 | 중거리→LagPursuit | 지속 후방 압박 | rate reversal |
| B1 EnergyFighter | BnZ, E-M | 에너지/고도 우위→HighYoYo, Climb, 이탈-재교전 | 수직 줌 | 코너 유지, 수직 추격 |
| B2 Extender | 이탈 거부 | closure<0, 원거리→Extension | 장거리 이탈 | 수직 추격, cutoff |
| C1 TwoCircleRate | two-circle | merge→TwoCircle, 코너속도 | 선회율 싸움 | 코너속도 우위 |
| C2 OneCircleRadius | one-circle | merge→OneCircle, 최소반경 | 반경 싸움 | one-circle 우위 |
| C3 Lufbery | 지속선회 | Loop, level turn 교착 | 도넛 교착 | 수직 탈출 |
| D1 Reactive | 방어 | aa>임계→BreakTurn, else 중립 | 우리 공격 시 방어 | 통제구역 유지 |
| D2 LastDitch | 방어 나선 | 근접 위협→SpiralDive, Break | 막판 회피 | 인내 후 재공격 |
| D3 Scissors | 평시저스 | 근접 merge→ScissorsAccel | 시저스 | 속도 죽이기, lag |
| E1 AdaptiveAce | 상황의존 | 전 상황 ladder | 전 상황 | 종합 최강 |
| E2 Passive | 무저항 | Straight, MaintainAltitude | 무저항 | 기본 격추 sanity |

13 archetype이 우리 13 tactic을 각각 자극하고 gun, scissors, energy, neutral, defensive, pursuit
교리를 망라한다.

### R2.2 변주 — 커버리지 확대

연구에서 커버리지가 결정적이므로 archetype마다 변주를 충분히 둔다. 변주는 네 개의 파라미터 축의
격자로 정의한다.

- 공격성: WEZ 진입 거리와 commit 거리 임계 (소심, 표준, 공격, 극공격)
- 에너지 편향: 상승/요요 전환 고도 임계 (저, 중, 고)
- 방어 trigger: 방어 기동을 켜는 aa 임계 (둔감, 표준, 민감)
- 선회 성향: 코너속도 목표와 one/two-circle 선택 임계

archetype당 약 10변주를 목표로 한다. 13 x 10 = 약 130개 설계 적 + 앵커 4개(simple, aggressive,
defensive, ace, 기존 결과 연속성). 규모는 컴퓨트 예산(R5)에 맞춰 조정한다.

### R2.3 생성과 검증

- 형식: .yaml BT. yaml_bt 인터프리터로 실행하고 bt-editor로 편집 가능. 어휘는 이미 35조건과
  37액션으로 완비됐다. .yaml 호환과 토너먼트 제출 경로를 유지한다.
- 위치: new_match_engine/opponents/zoo/ (앵커 9개와 분리한 설계 suite).
- 생성 후 검증(L0 재실행): 고유 행동 시그니처 수가 적 수에 근접(중복 0 목표), 퇴화 0, 13 tactic
  자극, archetype 사이 행동거리 충분, archetype 내 변주가 군집이 아니라 스프레드를 이룸.


## R3. 실험 설계 (RQ를 푸는 절차)

공통 프로토콜: 최신 코드 기준 단일 권위 데이터셋, R2의 설계 적 풀, 적 단위 train/test 분리,
5-fold CV, 고정 seed로 결정론 보장.

| 단계 | RQ | 방법 | 지표 | 산출물 |
|---|---|---|---|---|
| E0 데이터 | 전체 | 설계 적 x LHS spawn → forward-sim 라벨. 적 train/test 분리 + legacy 292-고유를 독립 OOD 보존 | 적수, 상태수, 7-D 범위, feature 공간 점유율, class 균형 | 권위 npz + meta |
| E1 상황구조 | RQ1 | (a) feature 공간 군집 silhouette 대 k (b) 세 정책 head-to-head: 순수 이산(손분할 + 데이터군집), 순수 연속, 하이브리드. 손-규칙 통제 | silhouette, win-rate, regret, 투명성 등급 | 군집 그림 + 정책 비교표 |
| E2 라벨 | RQ2 | 재현성(재실행 동일) + horizon H 스윕 + base 정책 민감도 + 정책반복 수렴 + IC 섭동 강건성 + 근사 대 진짜데미지 | best-tactic 순위 안정성(myopia 임계), 라벨 flip 비율 | H 스윕 곡선, 강건성 표 |
| E3 모델 | RQ3 | XGBoost, EBM, GOSDT + RandomForest, Linear. 동일 데이터/CV. 모두 배포 결정지표로 평가 | regret(우선), balanced top-1, 가치 R2(정의되는 곳만), 지연/크기, permutation 중요도, win-rate | 프런티어 그림 + 모델 비교표 |
| E4 커버리지 | RQ4 | 7-D 범위, train 대 배포방문 분포 중첩/OOD 비율, 적/상태 스케일링 곡선, held-out 적과 OOD 풀 win-rate | 점유율, 외삽 R2, 스케일링, OOD win-rate | 커버리지 그림 + 스케일링 곡선 |
| E5 검증 | RQ5 | GOSDT 규칙 추출 + EBM 단조성/형식 점검 | 규칙 수, 단조위반, SMT 통과 | 규칙 리스트 |

RQ1을 공정히 풀기 위해, 이산 정책은 두 종류로 만든다. 손분할(situation.py 임계)에 기반한 것과
데이터 군집에 기반한 것이다. 이렇게 해야 "이산 대 연속"이 "특정 손분할 대 연속"으로 좁혀지는
오류를 피한다. 세 정책 모두 같은 손-규칙(안전 상승 등) 유무를 통제해 비교한다.


## R4. 평가 지표 — 결정 품질 우선

배포에서 유일하게 중요한 것은 argmax로 고른 tactic이므로, 지표는 결정 품질을 우선한다.

- regret: 모델이 고른 tactic의 forward-sim 가치와 oracle best-tactic 가치의 차. 작을수록 좋다.
  multi-output R2가 좋아도 argmax가 틀리면 regret이 드러낸다.
- balanced top-1: best-tactic 일치율을 class 불균형 보정해서 본다. 다수 tactic(PURE_PURSUIT)에
  의한 착시를 막는다.
- 가치 R2: 회귀 모델에 한해 보조 지표로만 보고한다. 분류형(GOSDT)에는 정의되지 않으므로 모델
  간 head-to-head의 주지표로 쓰지 않는다.
- 전투 마진: win-rate에 더해 HP 차, WEZ dwell, 최초 WEZ 도달 시간을 본다. win-rate는 포화될 수
  있어 마진으로 분해해야 모델을 변별한다.
- 투명성 등급: 결정구조가 사람이 읽고 인용·검증 가능한 정도. 규칙 수, 단조성, shape 함수 제공
  여부로 정성 등급화.
- OOD win-rate: legacy 292-고유 독립 셋에서의 성능. 설계 suite 안에서의 성능과 분리 보고한다.

옛 수치(CV 0.72, 0.42, aa 0.38, dist 0.29)는 폐기하고 위 지표의 실측으로 대체한다.


## R5. 레드팀 — 위협과 완화

설계의 내적/외적 타당성 위협을 명시하고 완화책을 둔다.

| 위협 | 내용 | 완화 |
|---|---|---|
| T1 커버리지 착시 | archetype 다양성이 곧 상태공간 커버리지는 아님 | 커버리지를 feature 8-D 점유율로 측정, 빈 셀 보고, spawn과 함께 빈 곳 채움 |
| T2 strawman 적 | 손설계 적이 약하면 win-rate와 라벨이 부풀려짐 | 적 round-robin으로 강도 스프레드(Elo) 산출, 약-강 분포 확인, 행동이 의도대로 실행되는지 검증 |
| T3 어휘 순환성 | 적이 우리와 같은 tactic 어휘·엔진을 씀 | 범위를 "우리 BFM 어휘로 표현되는 doctrine"으로 정직히 한정, legacy 292-고유를 독립 OOD로 일반화 probe |
| T4 분할 누수 | 같은 archetype 변주가 train/test에 동시 존재하면 일반화 과대평가 | leave-variant-out과 leave-archetype-out 둘 다. legacy OOD는 학습에 절대 미사용 |
| T5 이산/연속 혼동 | 하이브리드의 손-규칙이 비교를 오염 | 손-규칙 통제, 데이터군집 이산도 별도 비교 |
| T6 라벨 부트스트랩 | H 꼬리에 base 정책 사용 → fitted-Q 1-step | base 민감도(pursuit 대 학습) 측정, 재라벨 정책반복 수렴 확인 |
| T7 결정론의 과신 | 측정 0 집합의 정확 IC에서만 참 | IC를 epsilon 섭동해 라벨/승패 flip 비율 측정, 경계 근처 불안정 정량화 |
| T8 지표 타당성 | 평균 R2는 argmax 오류를 가림 | regret과 balanced top-1을 주지표로 |
| T9 win-rate 포화 | 이미 15-16/16로 변별력 낮음 | 더 강한 적(T2) + 마진 분해 + OOD로 변별 |
| T10 패러다임 혼합 | GOSDT는 분류, 타깃은 가치회귀 | 모든 모델을 배포 결정지표로 공정 평가, 패러다임 차이를 명시 |
| T11 컴퓨트 | 변주 증가로 매치 폭증 | 예산 명시, 병렬, 1차 소규모 후 스케일링 곡선으로 확장 정당화 |
| T12 archetype 중복 | 일부 archetype은 한 분기만 다름 | 생성 후 행동거리로 distinctness 검증, 중복 archetype 통합 |
| T13 배포분포 의존성 | 커버리지의 목표분포가 정책에 의존(닭과 달걀) | 여러 정책이 방문하는 상태의 합집합으로 목표분포 근사, 분포 이동 명시 |


## R6. 규모와 재현

- 컴퓨트 예산: 1차는 소규모(적 약 40, spawn 약 16, 상태 약 20)로 파이프라인을 검증하고, 스케일링
  곡선으로 적/상태 수를 늘리며 수렴을 본다. 멀티프로세싱으로 매치를 병렬화한다.
- 결정론: JSBSim, LQR, 적 BT 모두 난수 없음. 고정 seed로 spawn과 적 샘플을 재생성한다. 같은
  입력은 같은 출력을 낸다.
- 산출물 보존: 권위 데이터셋 npz와 meta, 모델 비교표, 그림, 매치 리포트를 한 run으로 묶어 보존한다.


## R7. 산출물과 책 반영

실험이 끝나면 다음을 갱신한다.

- 4.3: RQ1 결과로 이산 대 연속의 답을 본문에 반영. 군집 구조 그림 추가.
- 4.5: RQ2 결과로 horizon, 라벨 재현성, 근사 대 진짜 비교를 실측으로 기술.
- 4.6: 모델 비교표(정확도-투명성 프런티어)를 실측으로 교체. RandomForest "유일한 균형점" 단정을
  측정 기반 결론으로 수정. 후보 표에 XGBoost, EBM, GOSDT 추가.
- 4.7: 커버리지 점유율, 스케일링 곡선, OOD 일반화를 실측으로 기술.
- 12장: 데이터 규모, RF 하이퍼파라미터, 5-fold 프로토콜, permutation 중요도, feature/tactic 목록을
  실측으로 동기화.

이 문서는 그 실험이 끝날 때까지 작업의 단일 기준선이다.


## P. 진행 기록 (실측 누적)

실험을 진행하며 측정값과 결정을 여기에 누적한다. 날짜는 2026-06-08 기준.

### P.0 후보 모델 확정

trio 확정: XGBoost(정확도 천장), EBM(글래스박스), FIGS(최대 투명). GOSDT는 Windows에서 wheel
빌드 실패로, 같은 최대투명 자리이며 회귀 가능한 FIGS(Fast Interpretable Greedy-tree Sums, Tan et
al. AISTATS 2022, Rudin 그룹)로 대체했다. 참조선은 RandomForest(incumbent)와 Ridge(linear floor).
설치 확인: xgboost 3.2.0, interpret(EBM), imodels(FIGS).

### P.1 L0 legacy 적 풀 감사 (exp_opp_audit.py)

합성 obs 격자 1440점 probe로 legacy 992개(archetypes 174 + opponent_pool 795 + examples 23)를
측정.

- 로드 992/992 성공.
- 고유 행동 시그니처 292종뿐 (700개는 행동 중복, 최다 40개 동일).
- 퇴화(격자 전체 단일 tactic) 112개(11%). 그중 37개는 항상 PURE_PURSUIT(미지원 어휘 default 추정).
- 적당 고유 tactic 평균 3.0개. 풀이 자극하는 tactic 13종.

판정: legacy 풀은 작동하나 중복·퇴화가 커서 커버리지 주장을 못 받친다. 설계 풀로 대체.

### P.2 설계 적 풀 생성 (gen_opponent_zoo.py)

13 archetype × 파라미터 변주 → opponents/zoo/ 에 111개 .yaml 생성. archetype별 변주 수:
A1 10, A2 12, A3 12, B1 12, B2 9, C1 6, C2 6, C3 9, D1 12, D2 6, D3 3, E1 12, E2 2.
변주 축: 공격성(gun_ata, gun_range), commit 거리, 방어 trigger(def_aa), 에너지(climb_alt).

L0 재검증: 로드 111/111. 정적 격자 고유 시그니처 34종. 정적 수치가 낮은 것은 격자가 거칠어
연속 임계값(commit, climb_alt 등)이 격자점 사이에 묻히기 때문이며(T1: 커버리지는 방문상태로
측정해야 함), 실제 매치의 연속 궤적에서는 변주가 갈린다. 진짜 중복 하나(A3 default==branch)는
수정했다. 동적 다양성은 E0/E4의 방문상태 커버리지로 측정한다.

### P.3 E0 데이터 생성 (exp_e0_dataset.py)

clean-slate 1차. 적 115종(zoo 111 + 앵커 4) × LHS spawn × forward-sim 라벨. 라벨은
base=PURE_PURSUIT tail(옛 정책 의존 제거; base 민감도는 E2). 결정론 고정 seed. meta 에
opp_name/archetype/spawn 보존(누수 없는 분리용). smoke(spawn1, 상태3, H10) 파이프라인 정상 확인.
본 1차: 적 115종 × spawn 6(LHS) × 상태 10 → 6,739 라벨상태 × 8 feature × 10 tactic.
best-tactic 분포는 10 tactic 중 9종이 등장(PURE_PURSUIT 1126, LEAD_PURSUIT 1122,
VERTICAL_PURSUIT 1111, TWO_CIRCLE 828, ONE_CIRCLE 728, ADAPTIVE 699, HIGH_YOYO 478,
LAG_PURSUIT 463, GUN_TRACK 184). 옛 8-tactic 데이터셋이 PURE_PURSUIT로 편향됐던 것에 비해
균형이 크게 개선됐다. 저장: results_research_dataset.npz (meta 포함).

### P.4 E1 결과 — RQ1 이산 대 연속 (exp_e1_situation.py)

(A) feature 공간 군집 구조. KMeans silhouette는 k=2..8에서 0.23..0.29로, 최고가 k=6(0.292)이며
모두 0.5 미만이다. 즉 뚜렷한 이산 BFM 군집은 없고 구조가 연속적이다. 손-분류(situation.py
재현)는 CHASE 3005, CIRCLE 3655, DEFENSIVE 79로 한쪽에 쏠린다.

(B) 정책 regret 비교 (leave-archetype-out GroupKFold, regret 낮을수록 좋음).

| 정책 | regret | top-1 |
|---|---|---|
| floor(단일 tactic) | 2.60 | 0.166 |
| 이산(손 3상황) | 2.58 | 0.169 |
| 이산(데이터 군집 k=6) | 2.12 | 0.252 |
| 연속(RandomForest) | 1.63 | 0.368 |

RQ1 답: 연속 가치학습이 명확히 우위다. 손-분할 3상황은 단일 tactic floor와 사실상 동일(정보
손실)하고, 데이터 군집이 그보다 낫지만, 연속 회귀가 regret 1.63으로 가장 낮다. 즉 dogfight tactic
선택에 명시적 이산 분류는 불필요하며, 교범의 이산 상황은 학습가능한 연속 구조로 더 잘 표현된다.
이는 본문 약속 2를 "상황을 이산 라벨로 나눈다"에서 "상황의존성을 연속 feature로 학습한다"로
수정해야 함을 뜻한다.

### P.5 E2 결과 — 라벨 결정론 버그 발견과 수정 (핵심)

E2 재현성 검사에서 같은 상태/같은 tactic을 두 번 평가했는데 결과가 최대 53.8 HP(H=40 기준) 달랐다.
"결정론이라 1회 sim이 참값"이라던 본문 4.9의 핵심 주장과 정면으로 어긋난다. 정밀 probe로 원인을
분리했다.

| 검사 | 결과 |
|---|---|
| 같은 _Sim 재사용, 같은 tactic 5회 (H=30) | [89.7, 81.2, 91.4, 86.3, 85.7], range 10.2 HP |
| eval 마다 새 plant 격리, 5회 | 전부 89.7, range 0.0 |
| restore_state 직후 obs 비교 | 동일 (restore 자체는 충실) |

근본 원인: forward-sim 평가기 _Sim 이 plant 객체를 모든 eval 에서 재사용하는데, restore_state 가
run_ic 로 운동상태(12개)만 되돌리고 FCS 액추에이터/필터, 엔진 spool 등 내부상태는 리셋하지 않는다.
그래서 한 상태에서 tactic A를 평가한 뒤 tactic B를 평가하면, B의 출발 FCS/엔진 상태가 A의 잔여로
오염된다. 라벨이 평가 순서에 의존하게 되어 10~95 HP의 노이즈가 들어갔다. 이는 레드팀 T7(결정론
과신)의 실제 사례이며, 엔진 자체는 결정론이지만 라벨 생성 절차가 비결정이었다.

수정: _Sim.eval 이 매 호출마다 plant/pilot 을 새로 만들어 고정 trim 베이스라인에서 출발하도록 했다
(offline_solver.py). 검증 결과 같은 _Sim 재사용에서도 range 0.000. 비용은 생성 21ms 추가로
195→215ms/eval(약 10퍼센트). 이 수정으로 모든 후속 라벨이 정확히 재현 가능해졌다.

영향: P.3 의 1차 데이터셋(6,739 상태)과 P.4 의 E1 결과는 오염된 라벨로 생성됐다. 수정 후 깨끗한
라벨로 E0 를 재생성하고 E1~E4 를 다시 측정한다(P.6 이후). horizon 스윕도 깨끗한 라벨로 재측정한다
(1차 측정에서는 H=10/20 이 H=60 과 21퍼센트만 일치해 강한 myopia 가 시사됐으나, 오염 노이즈와
교란돼 절대값은 재측정이 필요하다).

### P.6 클린 재측정 — E0, E1, E2, E4 (결정론 수정 후)

수정된 라벨로 E0 를 재생성하고 E1, E2, E4 를 다시 측정했다(E3 는 P.7).

E0 클린. 6,662 라벨상태(적 115 × spawn 6). 6.9분(0.60s/매치). best-tactic 분포는 10 tactic 중
9종 등장(VERTICAL_PURSUIT 1487, PURE_PURSUIT 1262, LEAD_PURSUIT 1116, ADAPTIVE 695,
TWO_CIRCLE 686, ONE_CIRCLE 571, LAG_PURSUIT 427, HIGH_YOYO 230, GUN_TRACK 184, BREAK_TURN 4).
BREAK_TURN 이 best 로 거의 안 나오는 것은 점수가 가한−받은 데미지라 순수 방어가 점수를
극대화하지 않기 때문이며 물리적으로 타당하다.

E1 클린 (RQ1). silhouette 는 k=2..8 에서 0.24..0.31, 최고 k=7(0.306) 으로 여전히 0.5 미만 —
뚜렷한 이산 군집 없음. 정책 regret(leave-archetype-out):

| 정책 | regret | top-1 |
|---|---|---|
| floor(단일 tactic) | 3.46 | 0.224 |
| 이산(손 3상황) | 2.91 | 0.187 |
| 이산(데이터 군집 k=7) | 2.59 | 0.224 |
| 연속(RandomForest) | 1.72 | 0.455 |

RQ1 결론(클린에서 더 뚜렷): 연속 가치학습이 regret 1.72 로 floor 3.46 의 절반, 손-분류 2.91 보다
크게 우위. 손-분류 3상황은 floor 대비 top-1 이 오히려 낮다(0.187 < 0.224). 이산 분류는 불필요하며
교범 상황은 연속 구조로 학습하는 것이 옳다.

E2 클린 (RQ2). 재현성 최대차 0.00(수정 확인). horizon 스윕 best-tactic H=60 일치율:
H=10 → 0.33, H=20 → 0.46, H=40 → 0.79, H=60 → 1.00. 짧은 horizon 은 best-tactic 을 크게 오판하며
(H=10 은 1/3 만 일치) H=40 이상에서 안정화된다. 라벨에 H 약 60s 가 필요하다는 본문 4.5 의 선택을
정량적으로 뒷받침한다(myopia 임계 약 40s).

E4 클린 (RQ4).
- feature 점유율: 핵심 4D(ata,aa,hca,dist) 거친 256 셀 중 143 점유(56퍼센트). 약 44퍼센트가
  미방문 — 커버리지에 구멍이 있다.
- train 대 배포방문 분포: 배포 정책 매치에서 방문한 461 상태의 train 최근접거리 중앙값이 1.06
  표준편차로, train 자체 분포보다 바깥에 치우쳐 분포 이동이 있다(레드팀 T13 의 chicken-egg 실증
  — 커버리지의 목표분포가 배포 정책에 의존). 학습 spawn 이 배포 궤적을 조밀히 덮지 못한다.
- 스케일링: 적 수 vs leave-archetype-out regret 이 10종 2.12, 30종 2.15, 60종 1.73, 115종 1.74 로
  약 60 적에서 포화. 설계 적 60종 규모면 정책 품질이 평탄해진다.

RQ4 결론: 적 다양성은 약 60종에서 충분(설계 풀로 달성)하나, feature 공간 점유는 56퍼센트에 그치고
배포 분포 이동이 있어 커버리지는 적 축이 아니라 spawn(기하) 축과 배포 궤적 정렬에서 보강이
필요하다.

### P.7 E3 결과 — 모델 프런티어 (RQ3)

후보 3(XGBoost, EBM, FIGS) + 참조선 2(RandomForest, Ridge)를 같은 6,662 상태에서
leave-archetype-out GroupKFold(5)로 비교. regret 우선(배포 결정 품질).

| 모델 | regret | top-1 | bal_top1 | value_R2 | fit(s) | 패러다임/투명성 |
|---|---|---|---|---|---|---|
| (다수결 floor) | 3.48 | 0.223 | - | - | - | 기준선 |
| Ridge(linear) | 2.44 | 0.219 | 0.152 | 0.139 | 0.01 | 완전투명, 과소적합 |
| RandomForest | 1.72 | 0.455 | 0.404 | 0.424 | 0.16 | 앙상블, 중요도 |
| XGBoost | 1.66 | 0.446 | 0.377 | 0.473 | 2.45 | 정확도 천장, 중요도 |
| EBM(glassbox) | 1.96 | 0.427 | 0.388 | 0.222 | 452.3 | 글래스박스(가법 shape) |
| FIGS(rules) | 2.30 | 0.292 | 0.209 | 0.224 | 1.61 | 규칙 합, 최대투명 |

RQ3 결론:
- 정확도 천장은 XGBoost(regret 1.66, R2 0.473)이나 RandomForest(1.72)와 사실상 동률이며 RF 가
  top-1 0.455 로 가장 높고 15배 빠르다.
- 글래스박스 EBM 은 regret 1.96 으로 트리 앙상블에 0.24 차로 근접하고 bal_top1 0.388 로 경쟁력
  있으나, 학습이 452s/fit 로 매우 느리다(가법 multi-output 비용). 투명성을 작은 정확도 비용으로
  얻지만 학습 비용이 크다.
- 최대투명 FIGS(규칙)는 regret 2.30 으로 Ridge 와 트리 사이. 규칙 15개 제약이 10-출력 BFM 가치를
  담기엔 부족해 투명성의 정확도 대가가 분명하다.
- Ridge 는 floor 를 겨우 넘어 AND-상호작용을 못 담는 한계를 확인.

따라서 본문 4.6 의 "RandomForest 가 유일한 균형점" 단정은 수정해야 한다. 정확도만 보면 XGBoost 가
같거나 약간 낫고, 투명성만 보면 EBM/FIGS 가 낫다. RandomForest 가 정당한 이유는 "측정상 최선의
실용 균형"이다 — 거의 최저 regret + 최고 top-1 + XGBoost 대비 15배, EBM 대비 약 2800배 빠른 학습
+ 중요도 제공. 프런티어는 실재하며(투명성과 정확도는 맞바꿈), 우리 선택은 그 위의 한 합리적 점이다.

feature 중요도(permutation, 편향 적은 정직한 방식):

| feature | permutation | impurity |
|---|---|---|
| ata | 0.552 | 0.147 |
| dist | 0.552 | 0.220 |
| hca | 0.279 | 0.181 |
| es_diff | 0.259 | 0.128 |
| aa | 0.191 | 0.157 |
| opp_omega | 0.089 | 0.070 |
| closure | 0.052 | 0.046 |
| ego_omega | 0.033 | 0.051 |

permutation 기준 1위는 ata 와 dist(둘 다 0.55)이며, 이는 WEZ 조건(ATA 12도 미만, 거리 500에서
3000피트)을 직접 구성하는 두 양이라 물리적으로 타당하다. 본문 초안의 "aa 0.38, dist 0.29"는 명백한
오류다(1위는 aa 가 아니라 ata, 그리고 ata 와 dist 가 동률 최상위). impurity 중요도는 순서가 달라
(dist, hca, aa, ata) permutation 과 어긋나며, 고cardinality 편향이 있는 impurity 보다 permutation 을
보고해야 한다.


### P.8 결과 레드팀 — 발견 자체를 의심하기

설계뿐 아니라 결과도 레드팀했다. 각 발견의 약한 고리와 그 처리를 적는다.

- 갭1 (RQ1 용량 혼동). 이산 정책은 작은 lookup, 연속 RF 는 고용량 모델이다. 차이가 "이산이라서"가
  아니라 "용량이 작아서"일 수 있다. 처리: E5(P.9)에서 군집 수 k 를 늘리며 regret 을 봤다. k=60
  까지 regret 이 줄지만 2.08 에서 포화하고 연속 1.72 에 도달하지 못한다. 즉 용량이 격차의 대부분을
  설명하나 잔차가 남아 연속이 견고히 우위다. 정직한 결론은 "거친 손-이산(3~7칸)이 손해"이며
  "이산이라는 형식 자체가 항상 나쁜 것은 아니다".
- 갭2 (RQ3 라벨 regret ≠ 배포 성능). E3 는 라벨 위 regret 만 쟀다. 실제 매치 win-rate 는 다를 수
  있다. 처리: E6(P.10)에서 모델을 정책으로 배포해 매치 win-rate 와 마진을 직접 측정한다.
- regret 의 크기 해석. 최선 모델 regret 1.72 HP 는 격추 100 HP 에 비해 작다. top-1 도 0.455 로
  낮다(10 tactic). 이는 많은 상태에서 여러 tactic 의 가치가 비슷해 선택이 결과를 크게 안 바꾼다는
  뜻이다. 즉 정책의 가치는 소수의 결정적 상태에 몰려 있다. regret 이 작다고 정책이 무의미한 게
  아니라, "선택이 중요한 상태"에서의 차이를 봐야 한다(E6 win-rate 로 보강).
- RQ2 한계. horizon 스윕은 H=60 을 기준으로 삼아 60s 가 수렴인지(H=90,120) 확인 못 했고,
  적 1종(ace)·24 상태로 표본이 작다. 라벨 tail 은 base=PURE_PURSUIT 로, 배포 정책(fitted-Q)과
  달라 base 민감도(T6)는 미측정.
- RQ3 공정성. 모델별 하이퍼파라미터를 동일 예산으로 튜닝하지 않았다(XGBoost 300 트리 대 FIGS
  규칙 15개). EBM 452s/fit 는 multi-output 구현 비용으로 절대값은 신뢰도가 낮다(상대 순위만 사용).
- RQ4 과장. OOD "100퍼센트"는 임계(train 99분위 자기거리)가 엄격해서 나온 수치다. 방문상태의
  train 최근접거리 중앙값 1.06 표준편차는 큰 이동은 아니다. "분포 이동 있음"까지가 정직한 주장이고
  "완전 미커버"는 과장이다. 스케일링도 10종(2.12)이 30종(2.15)보다 낮은 비단조가 있어 잡음이 있고,
  작은 부분집합은 archetype 그룹 수가 적어 GroupKFold 가 불안정하다.
- 공통 한계. 데이터는 단일 spawn 설정(6 LHS)·단일 seed·base=pursuit 라벨이다. 절대 수치보다
  방향(연속>이산, 프런티어 존재, 적 60종 포화)을 결론으로 삼아야 한다.

### P.9 E5 결과 — RQ1 용량 공정화 (exp_e5_capacity.py)

이산 군집 수 k 를 늘리며 regret(leave-archetype-out):

| 정책 | regret |
|---|---|
| floor (k=1) | 3.46 |
| 이산 군집 k=3 | 2.61 |
| 이산 군집 k=7 | 2.62 |
| 이산 군집 k=15 | 2.27 |
| 이산 군집 k=30 | 2.13 |
| 이산 군집 k=60 | 2.08 |
| 이산 군집 k=120 | 2.14 |
| 연속 (RF, k 무한) | 1.72 |

k 가 커지면 이산 regret 이 3.46 에서 2.08 로 줄지만 약 k=60 에서 포화하고 연속 1.72 에는 못
미친다(k=120 은 데이터 부족으로 오히려 악화). 결론: 손-이산이 진 주된 이유는 분해능 부족이며,
충분히 잘게 나누면 상당 부분 회복된다. 그러나 잔차 격차(약 0.36 HP)가 남아 연속이 우위인 것은
형식의 이점(부드러운 보간 + feature 상호작용)이 맞다. 실무 결론은 동일하다 — 소수 손-이산 상황은
쓰지 말 것.


### P.10 E6 결과 — 배포 win-rate와 손-규칙의 가치 (exp_e6_winrate.py)

같은 clean 데이터로 학습한 세 정책을 대표 적 8종과 canonical neutral 180s 매치(replay 전부 저장,
new_match_engine/replays/research_winrate/).

| 정책 | win | 결정적 매치 데미지(TwoCircle / defensive) | ace |
|---|---|---|---|
| 연속RF (손-규칙 없음, 안전만) | 6/8 | 44 / 93 | 무(0) |
| 하이브리드RF (연속 + 손-규칙 4개) | 5/8 | 17 / 63 | 승 |
| 연속XGB (손-규칙 없음) | 6/8 | 41 / 100 | 승 |

핵심: 순수 연속RF(6/8)가 하이브리드RF(5/8)보다 win-rate 가 높고, 결정적 매치에서 데미지도 더
크다(TwoCircle 44 대 17, defensive 93 대 63). 즉 손-규칙 4개는 전반적으로 도움이 안 되거나
오히려 해롭다. 이는 P.4/P.9 의 "연속 우위"가 라벨 regret 뿐 아니라 실제 배포 win-rate 로도
확인됨을 뜻한다(레드팀 갭2 해소). 또한 라벨 regret 순위(XGB≈RF)가 win-rate(둘 다 6/8)로 이어져
E3 의 타당성도 확인된다.

승리 질 정정(중요 — 실제 승률). win-rate 의 "판정승"은 실력승이 아니다. 판정 우선순위가
Hard Deck > Health=0 > HP우위라, 적이 1000ft 하드덱 아래로 자멸하거나 HP 동률에 가까운
타이브레이크로도 "승"이 된다. 24매치를 실제 결과로 재분류하면(report 의 HP·데미지·종료시각 근거):

| 정책 | 판정 win | 격추(적 HP=0) | 결정타승(데미지≥40) | 미세판정승 | 하드덱 자멸승 | 무승부 | 실력승 |
|---|---|---|---|---|---|---|---|
| 연속RF | 6/8 | 0 | 2 | 2 | 2 | 2 | 2/8 |
| 하이브리드RF | 5/8 | 0 | 1 | 4 | 0 | 3 | 1/8 |
| 연속XGB | 6/8 | 1 | 1 | 4 | 0 | 2 | 2/8 |

핵심: 24매치 전체에서 실제 격추(적 HP=0)는 단 1건(연속XGB 대 defensive)뿐이다. 판정 win-rate
6/8 은 하드덱 자멸승과 미세 HP 우위로 부풀려졌다. 실력승(격추+결정타 데미지≥40)으로 보면 연속RF
2/8, 연속XGB 2/8, 하이브리드RF 1/8 이다. 예: 연속RF 대 GunTracker 는 dur 114s·HP 100:100·dmg 0
인데 WIN — 적이 하드덱 자멸한 것이고 우리 Es 도 4992 로 거의 고갈됐다(운에 가깝다).

따라서 정직한 1차 지표는 win-rate 가 아니라 실격추(적 HP=0)와 결정타 데미지다. 현재 실력승은
약 2/8 에 머물고 진짜 격추는 1/24 다. 연속이 하이브리드보다 실력승에서도 앞서는 것(2 대 1)은
유지된다. 이 정직한 수치가 T.3 to-be 성공기준("무승부·하드덱승이 아닌 실격추")과 8/8 병목
(닫기 실패·에너지 고갈)을 그대로 가리킨다.

replay 이벤트 보강(blue hit). 진단 중, 매치 로그는 프레임별 HP 를 기록하는데도 acmi 의 HIT
이벤트가 거의 안 떴다. 원인은 HIT 조건이 "직전 프레임 대비 1HP 초과 감소"여서, 느린 연속 피해
(프레임당 1HP 미만)가 누적 격추여도 한 번도 안 잡힌 것이다. 기준을 "마지막 HIT 이벤트 시점 HP"로
바꿔 누적 피해를 잡도록 고치고, 하드덱 진입(HARD DECK — LOSS)과 격추(DESTROYED) 이벤트도
추가했다(replay.py). 이제 Tacview Event Log 에 legacy 처럼 피격·하드덱·격추가 표시된다.

단 예외: ace 상대로는 하이브리드RF·연속XGB 가 이기고 연속RF 는 비겼다. head-on latch(ADAPTIVE)
같은 일부 손-규칙이 특정 강적엔 유효할 수 있다. 따라서 결론은 "손-규칙 전면 제거"가 아니라
"규칙별로 기여를 분리 측정해 음수면 제거"다(S.1 의 leave-one-rule-out 실험). 표본이 8종으로 작아
방향성 결론이며, 더 큰 적 풀로 재확인이 필요하다.

이 결과로 BT 진화 방향이 데이터로 정해진다: 안전 상승만 남기고 나머지 손-규칙은 ablation 으로
검증해 연속 정책에 흡수(S.1). replay 24건이 저장돼 각 매치의 궤적·WEZ·기동패턴을 눈으로 더블체크할
수 있다.

replay 더블체크(필수 자산). 저장된 report 로 적이 교리대로 싸우는지 눈으로 확인했다. 예: 연속RF 대
B1_EnergyFighter 매치에서 적 비에너지 Es=24,158 대 우리 14,463 으로, EnergyFighter 가 실제로
고에너지로 줌했다(설계대로 거동, strawman 아님). 동시에 우리는 그 매치에서 데미지 1 에 그쳐
에너지 파이트가 약점임이 드러났다(S.5 가 다룰 공백). 연속RF 대 C1_TwoCircleRate 는 WEZ 7회
dwell 30.5s, 데미지 44 로 선회율 싸움에서 제압했다. 숫자만으로 못 보는 이 거동 검증이 replay 의
목적이며, 앞으로 모든 실험은 대표 매치의 acmi+report+plot 을 남긴다.


## Q. 종합 결론과 본문 반영안

### Q.1 연구질문 답

- RQ1(상황표현): 답은 연속이다. feature 공간에 뚜렷한 이산 군집이 없고(silhouette < 0.31), 연속
  가치회귀가 이산 분류보다 regret 절반(1.72 대 2.6~2.9). 이산 손-분류는 단일 tactic floor 수준.
- RQ2(라벨): 라벨은 결정론 수정 후 정확히 재현 가능(range 0)하며, best-tactic 은 H 약 40s 이상에서
  안정(H=10 은 1/3 만 일치). 단, 1차 절차에 결정론 버그가 있었음을 발견·수정했다.
- RQ3(모델): 정확도-투명성 프런티어가 실재. XGBoost≈RF 가 정확도 우위, EBM/FIGS 가 투명 우위.
  RF 는 유일최적이 아니라 측정상 최선의 실용 균형. 배포 win-rate(E6)도 RF·XGB 6/8 로 라벨 순위와
  일치.
- RQ4(커버리지): 적 다양성은 약 60종에서 포화. 그러나 feature 점유 56퍼센트, 배포 분포 이동 존재.
  커버리지 보강은 적 축이 아니라 spawn 기하 축과 배포궤적 정렬에서.
- RQ5(검증): 미수행(다음 패스). EBM shape 함수와 FIGS 규칙 추출이 가능함은 P.7 로 확인.
- BT 진화(E6): 순수 연속RF(6/8) ≥ 하이브리드RF(5/8). 손-규칙 4개는 전반적으로 무익~유해(ace
  예외). 안전 상승만 남기고 규칙별 ablation 으로 검증해 연속 정책에 흡수하는 것이 다음 방향(S.1).

### Q.2 본문 수치 교체안 (옛 값 폐기 → 실측)

| 위치 | 옛 값(폐기) | 실측 교체 |
|---|---|---|
| 4.3 약속2 | "상황을 이산 라벨로 나눈다" | "상황의존성을 연속 feature 로 학습"(RQ1) |
| 4.5 horizon | H 불명시 | H=60s 라벨, myopia 임계 약 40s |
| 4.5 결정론 | "1회 sim = 참값" | 라벨 결정론은 plant 격리 후 성립(버그 수정 기록) |
| 4.6 중요도 | aa 0.38, dist 0.29 | permutation: ata 0.55, dist 0.55, hca 0.28(1위는 ata) |
| 4.6 CV | CV R2 0.72 / 분류 0.42 | regret 우선: RF 1.72, top-1 0.455(폐기 후 결정지표로) |
| 4.6 모델표 | RF "유일 균형점" | XGBoost·EBM·FIGS 프런티어 추가, RF = 측정상 최선 실용 균형 |
| 4.7 커버리지 | 정성 주장 | 적 60종 포화, 점유 56퍼센트, 배포 분포이동(수치) |

### Q.3 재현 (스크립트)

```
python new_match_engine/bt/exp_opp_audit.py      # L0 적 풀 감사
python new_match_engine/bt/gen_opponent_zoo.py   # R2 설계 적 풀 111개
python new_match_engine/bt/exp_e0_dataset.py 6 10 50 25   # E0 데이터(결정론 수정 포함)
python new_match_engine/bt/exp_e1_situation.py   # E1 이산 대 연속
python new_match_engine/bt/exp_e2_labels.py      # E2 재현성·horizon
python new_match_engine/bt/exp_e3_models.py      # E3 모델 프런티어
python new_match_engine/bt/exp_e4_coverage.py    # E4 커버리지
```

### Q.4 남은 일 (다음 패스)

- RQ5: FIGS 규칙 출력과 EBM shape 함수를 사람이 읽는 정책으로 추출, 단조성/안전성 SMT 점검.
- 커버리지: spawn 기하 축 확대 + 배포궤적 정렬 재라벨링으로 분포이동 축소.
- 규모: H 스윕 H>60 확인(60s 가 수렴인지), 적/상태 확대 스케일링 재확인.
- 본문 4.3~4.7 + 12장에 Q.2 실측 반영(검토 후).


## U. 챔피언 대 실험정책 — 왜 최근 BT가 더 강한가 (E7)

사용자 지적: 이번 실험 정책이 우리 최근 BT(배포 챔피언)보다 약해 보인다. 이를 측정으로 확인하려고
배포 챔피언(tree_policy.TreePolicy = policy_value.pkl 8-tactic + 손-규칙)과 이번 실험의 연속RF
(clean H=25 라벨)를 같은 적 8종·canonical neutral·300s 로 맞붙였다(E7).

| 정책(300s) | 판정승 | 실력승(격추+데미지≥40) | 격추(HP=0) | 적별 데미지 |
|---|---|---|---|---|
| champion | 7/8 | 3/8 | 0 | GunT 9, Ener 1, TwoC 60, Scis 50, Adap 3, aggr 9, defe 69, ace 0 |
| cleanRF | 6/8 | 2/8 | 2 | GunT 0, Ener 0, TwoC 100, Scis 1, Adap 0, aggr 0, defe 100, ace 0 |

결과는 단순한 우열이 아니다. 두 정책의 강점이 다르다.

- 챔피언은 넓게 교전한다. 8적 중 6적에 데미지를 내고(에너지파이터·건트래커·aggressive 포함),
  판정 7/8·결정타 3/8 로 더 많은 적을 제압한다. 그러나 깎기만 하고(TwoC 60, defe 69) 끝내지
  못해 실제 격추는 0 이다.
- cleanRF 는 좁지만 치명적이다. 교전하는 두 적(TwoCircle, defensive)은 둘 다 100 데미지로 격추하나,
  나머지 4적(GunTracker, EnergyFighter, Adaptive, aggressive)에는 데미지 0 으로 교전 자체를 못 건다.

즉 우리 실험 정책의 약점은 "끝내기(terminal)"가 아니라 "다양한 상황에 교전을 거는 폭"이다.
오히려 끝내기는 cleanRF 가 더 낫다(격추 2 대 0).

### U.1 챔피언이 더 강한(넓은) 이유

- 라벨 horizon. 챔피언 학습 라벨은 H=60 + fitted-Q(강한 base). 이번 실험은 H=25(E2 가 H=25 는
  best-tactic 46퍼센트만 일치한다고 증명한 값) + base=PURE_PURSUIT. 짧은 horizon·약한 base 는
  setup 이 긴 교전(에너지 파이트, 건트래커 각 싸움)을 라벨이 보상하지 못한다. 그래서 cleanRF 는
  25초 안에 결판나는 쉬운 기하(TwoCircle, defensive)만 학습하고 나머지엔 교전을 못 건다.
- 손-규칙 dispatch. 챔피언은 head-on ADAPTIVE latch·GUN_TRACK·VERTICAL_PURSUIT 를 GA 로 튜닝해
  다양한 시작 기하에서 교전을 만든다. cleanRF 는 안전 상승만 있어 그 폭이 없다.
- 평가 길이. 같은 cleanRF 도 180s 에선 격추 0, 200s·300s 에선 격추 2 였다. duration 이 sustained
  WEZ(챔피언의 figure-8 23틱 격추)를 좌우한다.

### U.2 이번 실험이 반영하지 못한 것

1. horizon H=25 로 학습 — 우리 자신의 E2 가 부족하다고 증명한 값. H 이상은 60 이어야 한다.
2. base=PURE_PURSUIT — 챔피언의 fitted-Q(강한 base bootstrap)를 안 썼다. setup→capitalize 시퀀스가
   라벨에 안 잡힌다.
3. 평가 180s 중심 — 챔피언 regime 인 300s 가 아니었다. 격추가 길이에 민감하다.
4. 챔피언을 비교군에 안 넣었다(E7 로 뒤늦게 교정). baseline 누락.
5. 단일 neutral spawn·단일 seed.

### U.3 그럼에도 실험이 옳게 밝힌 것

- 연속 가치학습은 끝내기(터미널 격추)에서 오히려 챔피언보다 낫다(격추 2 대 0). 즉 RQ1 의 "연속
  우위"는 유효하며, cleanRF 의 약점은 연속 방식이 아니라 학습 라벨(horizon·base)과 교전 폭이다.
- 따라서 옳은 방향은 챔피언을 버리는 것도, 실험 정책을 버리는 것도 아니다. 챔피언의 폭(긴 horizon
  + fitted-Q base + 유효 dispatch)과 cleanRF 의 터미널 치명성(연속 가치)을 결합하는 것이다.

### U.4 올바른 방법론 (결정)

1. 라벨: H 이상 60, commit 유지, base = 현 챔피언(fitted-Q bootstrap), 정책반복으로 수렴(S.3).
2. 평가: canonical 300s, 지표는 격추+결정타 데미지(판정승 아님), 챔피언을 항상 baseline 으로 포함.
3. dispatch: 챔피언의 유효 규칙(특히 head-on ADAPTIVE)은 per-rule ablation 으로 가치 확인 후 유지/
   흡수(S.1). E6 에서 손-규칙이 약했던 것은 약한 base RF 와 결합했기 때문이며, 강한 base 와 결합한
   챔피언에선 폭을 준다.
4. 가치: 에너지·생존 항 추가(S.5)로 교전 못 거는 적(에너지 파이터)까지 폭을 넓힘.

이로써 "왜 최근 BT 가 강한가"는 "넓은 교전(긴 horizon·fitted-Q·튜닝 dispatch)" 때문이고, "이번
실험이 못 반영한 것"은 그 셋(horizon, base, 평가 길이)임이 측정으로 확정된다. 실험의 연속 가치
방식 자체는 유효하다(터미널 격추 우위).

### U.5 방법론 적용 결과 — H=60 + 챔피언 base 재학습 (E7b)

U.4 를 그대로 적용했다. 라벨을 H=60 + base=현 챔피언(fitted-Q bootstrap)으로 재생성하고
(results_research_h60.npz, 6,897 상태; 라벨 분포가 VERTICAL_PURSUIT·ADAPTIVE 쪽으로 이동 —
긴 setup 이 보상됨), 그 위에 연속RF 를 학습해(cleanRF_H60) 같은 8적·300s 로 다시 비교했다.

| 정책(300s) | 판정승 | 실력승(격추+≥40) | 격추(HP=0) | 적별 데미지 |
|---|---|---|---|---|
| champion | 7/8 | 3/8 | 0 | GunT 9, Ener 1, TwoC 60, Scis 50, Adap 3, aggr 9, defe 69, ace 0 |
| cleanRF_H25 | 6/8 | 2/8 | 2 | GunT 0, Ener 0, TwoC 100, Scis 1, Adap 0, aggr 0, defe 100, ace 0 |
| cleanRF_H60 | 6/8 | 6/8 | 4 | GunT 0, Ener 57, TwoC 100, Scis 100, Adap 95, aggr 0, defe 100, ace 100 |

결과는 예측대로다. cleanRF_H60 은 폭과 치명성을 동시에 얻었다.

- 실력승 6/8 — 챔피언 3/8, H25 2/8 의 두세 배. 격추 4 — 챔피언 0, H25 2 보다 많다.
- 폭 회복: H25 가 0 데미지였던 EnergyFighter(57)·Scissors(100)·AdaptiveAce(95)에 교전을 걸었다.
- 블로커 격파: ace 를 100 데미지로 격추했다(dur 216s, HP 100:0, WEZ 4회 dwell 32.9s,
  figure-8 lemniscate 패턴). 챔피언·H25 가 모두 비겼던(ace d) 오랜 neutral-vs-ace 교착을 처음 깼다.
- 남은 약점: GunTracker·aggressive 두 적은 여전히 무승부(0 데미지). 정면 nose-chaser 에 대한
  닫기·에너지가 다음 과제다(S.5).

검증: 이로써 to-be 가설("챔피언의 폭 + 연속의 치명성 결합")이 측정으로 확인됐다. 방법론 결정
U.4(H≥60 + 챔피언 base fitted-Q)가 핵심이었고, 모델·분류가 아니라 라벨 horizon·base 가 병목이었다는
진단이 옳았다. replay 는 research_champion/cleanRF_H60__* 에 HIT·격추 이벤트와 함께 저장됐다.

### U.6 남은 무승부 2건 진단 — 에너지 고갈 (가설·검증·도출 실험)

cleanRF_H60 이 못 이긴 둘은 GunTracker 와 aggressive(둘 다 정면 nose-chaser)다. 진짜 무승부인지,
원인이 무엇인지 replay 로 진단했다.

검증(report 근거):

| 매치 | 결과 | HP | 거리 min | Es(끝) | bleed | 지배 tactic |
|---|---|---|---|---|---|---|
| cleanRF_H60 vs GunTracker | DRAW 300s | 100:100, dmg 0 | 379m | 3,485 | 12,826ft | VERTICAL_PURSUIT 424s, CLIMB 311s |
| cleanRF_H60 vs aggressive | DRAW 300s | 100:100, dmg 0 | 349m | 3,358 | 12,829ft | VERTICAL_PURSUIT 439s, CLIMB 311s |

둘 다 진짜 무승부(300s 완주, HP 100:100, WEZ 0회)이고 원인이 같다. 가까이(min 349~379m)는 가나
WEZ(ATA<12·사거리)에 한 번도 못 든다. 그 이유는 에너지 고갈이다 — 비에너지 Es 가 3,300~3,500 까지
떨어지고(거의 실속·하드덱 직전), 에너지를 약 12,800ft 태웠다. 지배 tactic 이 VERTICAL_PURSUIT 로,
정면 nose-chaser 를 수직 추격하다 에너지를 소진하고 저에너지라 사격 솔루션을 못 만든다.

대조: 같은 정책이 ace 는 격추했는데, ace 매치에선 Es 12,240 으로 에너지를 유지하며 figure-8 로
sustained WEZ 32.9s 를 만들었다. 즉 차이는 적이 아니라 에너지 관리다.

가설: 현재 가치함수는 점수 = 가한−받은 데미지(+potential shaping)라 에너지 손실을 직접 벌하지
않는다. 그래서 단기 추격(VERTICAL_PURSUIT)이 에너지를 태워도 라벨이 막지 않아, 정면 nose-chaser
상대로 과추격→에너지 고갈→미교전에 빠진다.

도출 실험(S.5): 라벨 목적함수에 에너지 보존 항을 더한다. potential 기반(Ng et al. 1999)으로
Φ 에 비에너지 우열(Es_diff)을 넣어 최적정책 불변성을 유지하면서, 에너지를 태우는 경로의 가치를
낮춘다. 이 라벨로 재학습해 같은 8적·300s·E7 프레임으로 평가하고, GunTracker·aggressive 무승부가
교전·격추로 바뀌어 8/8(실력승)에 다가가는지 측정한다. 에너지 항 가중치는 별도 계수로 두어
sweep 가능하게 한다.

### U.7 S.5 결과 — 에너지 항은 free win 이 아니라 trade-off (OWN_K=0.5)

_phi 에 절대 자기에너지 항을 추가하고(env NME_ENERGY_OWN_K, potential 기반 → 최적정책 불변),
OWN_K=0.5 로 라벨을 재생성(results_research_h60_energy.npz, 6,818 상태)해 재학습·평가했다. 라벨
분포가 HIGH_YOYO(에너지 보존 수직기동) 66→695 로 급증해, 에너지를 태우는 VERTICAL_PURSUIT
대신 보존하는 기동이 보상됨을 확인했다.

| 정책(300s) | 판정승 | 실력승 | 격추 | 적별 데미지 |
|---|---|---|---|---|
| champion | 7/8 | 3/8 | 0 | GunT 9, Ener 1, TwoC 60, Scis 50, Adap 3, aggr 9, defe 69, ace 0 |
| cleanRF_H60 | 6/8 | 6/8 | 4 | GunT d, Ener 57, TwoC 100, Scis 100, Adap 95, aggr d, defe 100, ace 100 |
| cleanRF_H60en (OWN_K=0.5) | 6/8 | 4/8 | 4 | GunT W(6), Ener 100, TwoC d, Scis 18, Adap 100, aggr L, defe 100, ace 100 |

결과는 가설을 부분 확인하되 순감이다.

- 개선(가설 방향 맞음): EnergyFighter 57→격추 100, GunTracker 무승부 d→W(6) 교전, Adaptive→격추.
  에너지 보존이 에너지 스타일 적에 효과.
- 회귀: TwoCircle 격추 100→무승부, Scissors 100→18, aggressive 무승부→패배(L). 근접 rate-fight
  와 정면 압박에서 너무 소극적이 돼 오히려 졌다.

해석: 단일 전역 에너지 계수(0.5)는 과보정이다. 에너지 관리는 상황의존적이다 — 에너지 파이터엔
보존이 옳지만, rate-fighter·aggressive 엔 commit(에너지 소비)이 옳다. 전역 패널티는 이를 못 가린다.
이는 본 프로젝트의 핵심 논지(상황의존)와 일치하며, 두 가지 후속을 가리킨다. 첫째, 계수를 낮춰
(예: 0.2) 회귀 없이 nose-chaser 만 돕는 sweet-spot 이 있는지(U.8). 둘째, 전역이 아니라 상황별
에너지 가중(공격 국면은 약하게, 수세·고갈 위험 시 강하게)이 필요할 수 있다.

정직한 결론: S.5 의 에너지 항은 nose-chaser 일부(EnergyFighter, GunTracker)를 돕지만 전역 0.5 는
순감이다. 8/8 은 계수 sweep 또는 상황별 에너지로만 가능하며, 단일 항으로 공짜 해결은 안 된다.

### U.8 에너지 계수 sweep — 전역 에너지로는 nose-chaser 무승부 못 푼다

OWN_K 를 0.2 로 낮춰 다시 측정해 0.5·0(없음)과 비교했다.

| 정책 | 실력승 | 격추 | GunTracker | aggressive | TwoC | Scis | ace |
|---|---|---|---|---|---|---|---|
| cleanRF_H60 (OWN_K=0) | 6/8 | 4 | d | d | 100 | 100 | 100 |
| H60en OWN_K=0.2 | 5/8 | 3 | d | d | 100 | 100 | 74 |
| H60en OWN_K=0.5 | 4/8 | 4 | W(6) | L | d | 18 | 100 |

결과는 명확하다. 어느 계수도 nose-chaser 무승부(GunTracker, aggressive) 둘을 깨끗이 풀지 못한다.
0.2 는 그 둘을 건드리지도 못한 채(여전히 d, d) 다른 적에서 소폭 회귀(ace 100→74, Adaptive 95→35)
하고, 0.5 는 GunTracker 를 W 로 바꾸는 대신 aggressive 를 패배로 만들고 TwoCircle·Scissors 를
무너뜨린다. 최고는 여전히 에너지 항 없는 cleanRF_H60(실력승 6/8)이다.

진단 정정: U.6 은 무승부 원인을 "에너지 고갈"로 봤으나, 에너지 패널티가 못 고치는 것으로 보아
에너지 고갈은 원인이 아니라 증상이다. 정면 nose-chaser 에 사격 각을 못 만들어 계속 추격하다
에너지를 태우는 것이고, bleed 를 벌하면 더 소극적이 될 뿐 여전히 못 닫는다. 진짜 원인은 종말 폐쇄
(터미널 추적·기하)다. 이는 제어·유도층의 문제이며, 다음 두 실험으로 분리 검증한다. (a) 내측
제어기를 INDI 로 바꿔 추적 정밀이 닫기를 돕는지(U.9, E8). (b) GUN_TRACK 의 lead/PN cutoff 강화로
ATA<12 를 실제로 닫는지(S 후속). 전역 에너지 항은 to-be 의 도구가 아니다.

### U.9 INDI 대 LQR 내측 제어기 (E8)

같은 정책 cleanRF_H60 을 내측 제어기만 LQR/INDI 로 바꿔 같은 8적·300s 로 A/B 했다.

| 내측 | 판정승 | 실력승 | 격추 | 적별 데미지 |
|---|---|---|---|---|
| LQR | 6/8 | 6/8 | 4 | GunT d, Ener 57, TwoC 100, Scis 100, Adap 95, aggr d, defe 100, ace 100 |
| INDI | 8/8 | 1/8 | 1 | GunT W(0), Ener 5, TwoC 26, Scis 100, Adap 8, aggr W(0), defe 5, ace 17 |

겉보기엔 INDI 가 판정 8/8(전승)로 더 좋아 보이지만, 실력승은 6/8→1/8, 격추 4→1 로 붕괴했다.
데미지가 전부 폭락하고(TwoC 100→26, defensive 100→5, ace 100→17), GunTracker·aggressive 의 "승"은
dmg 0 즉 적이 하드덱 자멸한 hollow win 이다. 정직한 1차 지표(실격추)로 보면 INDI 는 LQR 보다
훨씬 나쁘다.

원인은 제어기 train-deploy 불일치다. 정책 가치는 LQR 을 내측에 둔 forward-sim 으로 라벨링·학습됐다
(_Sim 의 Pilot=LQR). 그 정책을 INDI 로 배포하면 plant 응답(과도·정착)이 달라져 tactic→결과 매핑이
어긋난다(off-distribution). 그래서 같은 tactic 이 의도한 WEZ 폐쇄를 못 만들고 데미지가 붕괴한다.
이는 16장(INDI 우위는 깊은 고받음각+모델불확실에서만; 일반 envelope 에선 LQR≈INDI)과 일관되며,
나아가 한 교훈을 더한다 — 내측 제어기를 바꾸려면 그 제어기로 라벨을 다시 만들어야 한다. 무승부의
병목은 내측 추적 정밀이 아니라 외측 유도·기하이고, 내측 교체는 공짜 개선이 아니라 분포 이동이다.

### U.10 외측 유도 — VERTICAL_PURSUIT 에너지 바닥 (LQR, 라벨 재생성)

U.6/U.9 가 가리킨 외측 유도를 손봤다. VERTICAL_PURSUIT 가 적 고도를 추종(h=적고도)해 nose-chaser
가 다이브하면 따라 하강 나선에 빠지던 것을, 에너지 바닥(h=max(적고도, HARD_DECK+4000))으로 막아
적이 더 내려가도 우리는 에너지를 유지하게 했다(guidance.py). 유도가 바뀌었으므로 라벨을 새 유도로
재생성하고(results_research_h60_floor.npz, train-deploy 일치) 재학습·평가했다(같은 8적·300s).

| 정책(300s) | 판정 | 실력승 | 격추 | GunTracker | aggressive | 그 외 |
|---|---|---|---|---|---|---|
| cleanRF_H60 (바닥 없음) | 6/8 | 6/8 | 3 | d | d | Ener 57, defe 61, ace 100 |
| cleanRF_H60fl (에너지 바닥) | 6/8 | 6/8 | 3 | d | d | Ener 88, defe 100, ace 100 |

에너지 바닥은 의도대로 작동했다. GunTracker 매치에서 우리 Es 가 3,485→4,892 로 올라 적(2,065)보다
높아졌고(바닥 없음에선 적이 더 높았다), 평균 거리도 3,481→1,560m 로 훨씬 가까워졌다(52퍼센트가
1.5km 내). EnergyFighter·defensive 는 개선됐다(57→88, 61→100 격추).

그러나 cleanRF_H60fl 의 GunTracker·aggressive 는 여전히 무승부다. 처음엔 이를 두고 "각도 무승부
균형(V.4)"이라 해석했으나, replay 를 더 들여다보니 그 단정은 틀렸다. 같은 8적 표에서 챔피언은
GunTracker·aggressive 를 둘 다 W(9)로 이긴다 — TWO_CIRCLE·ONE_CIRCLE 선회율 싸움으로 적을
Es 1,950 까지 바닥내 하드덱으로 압박해(121s 조기 종료) 자멸시킨다. 즉 승리 라인이 실재한다.

원인 재진단(정정): 무승부는 게임의 필연이 아니라 우리 배포 정책의 tactic 오선택이다. GunTracker
상대 한 상태에서 forward-sim 가치를 직접 재면 TWO_CIRCLE 가 +10.2 로 최고이고 VERTICAL_PURSUIT
는 +0.5 다 — 라벨은 옳은 답(TWO_CIRCLE)을 안다. 그런데 배포된 RF 는 매치에서 방문하는 상태들에서
VERTICAL_PURSUIT(942s)를 골라 무승부에 빠진다. 즉 라벨이 아는 승리 tactic 을 배포 정책이 재현하지
못한다 — 이는 일반화·커버리지 갭(RQ4 의 train-deploy 분포 이동)이지 미분게임 무승부(V.4)가 아니다.
V.4 는 깨끗한 gun-kill 의 어려움엔 여전히 유효하나, 이 매치의 무승부 원인으로는 과한 적용이었다.

따라서 다음 수는 cutoff 기하 발명이 아니라, 배포 정책이 nose-chaser 에 TWO_CIRCLE(선회율 압박)을
고르게 만드는 것이다 — 방문 상태 재라벨(DAgger 류, S.4)로 분포를 정합하거나, GunTracker 형
상태의 학습 표본을 늘린다. 한편 에너지 바닥은 EnergyFighter(57→88, dmg 88·WEZ 22s 격추급)·
defensive(61→100)를 개선하고 우리를 에너지 우위로 두므로 순이득이라 유지한다.

### U.11 DAgger 재라벨 — 격추 3→6 (S.4)

U.10 의 정정(배포 정책이 옳은 tactic 을 못 고름)을 DAgger(Ross, Gordon, Bagnell, 2011, "A
Reduction of Imitation Learning and Structured Prediction to No-Regret Online Learning",
AISTATS)로 다뤘다. 현재 배포 정책(cleanRF_H60fl)으로 매치를 돌려 그 정책이 실제 방문하는 상태
5,470 개를 모으고, 각각을 forward-sim(H=60, base=챔피언)으로 라벨해 floor 데이터(6,897)에 합쳐
재학습했다(results_research_dagger.npz, 12,367 상태). 핵심은 학습분포를 배포분포에 정합하는 것이다.

| 정책(300s) | 판정 | 실력승 | 격추 | 적별 데미지 |
|---|---|---|---|---|
| champion | 7/8 | 3/8 | 0 | GunT 9, Ener 1, TwoC 60, Scis 50, Adap 3, aggr 9, defe 69, ace 0 |
| cleanRF_H60fl | 6/8 | 6/8 | 3 | GunT d, Ener 88, TwoC 98, Scis 42, Adap 100, aggr d, defe 100, ace 100 |
| cleanRF_dagger | 6/8 | 6/8 | 6 | GunT d, Ener 100, TwoC 100, Scis 100, Adap 100, aggr d, defe 100, ace 100 |

DAgger 는 교전하는 6적을 전부 100 데미지 격추로 끌어올렸다(Ener 88→100, Scis 42→100, TwoC
98→100). 격추가 3→6 으로, 챔피언(0)·이전 best(3)를 크게 넘는 최고 살상력이다. 그러나
GunTracker·aggressive 는 여전히 무승부다.

한 번의 DAgger 가 nose-chaser 를 못 푼 이유는 horizon 이다. GunTracker 방문상태 1,293 개의
best-tactic 라벨을 보면 VERTICAL_PURSUIT 416 대 TWO_CIRCLE+ONE_CIRCLE 499 로, 추격 상태에서는
H=60 forward-sim 이 여전히 추격을 종종 최선으로 본다 — TWO_CIRCLE 의 하드덱 압박 승리는 약 120s
뒤에 나오는데 H=60 라벨은 거기까지 못 본다. 즉 greedy 가치정책이 국소 최선(추격)에 머물러 전역
최선(선회율 압박)으로 commit 하지 못한다. 챔피언은 선회율 압박을 손-dispatch 로 commit 해 이긴다.

정직한 8/8 현황: 어떤 단일 정책도 8/8 이 아니다. 챔피언은 7/8(ace 무승부, 격추 0), DAgger 정책은
6/8(nose-chaser 2 무승부, 격추 6)이다. ace 격파(figure-8 지속)와 nose-chaser 격파(선회율 압박)는
tactic 이 달라 greedy 정책이 한 모드만 잡는다. 8/8 의 남은 길은 (a) horizon 확장(H=90+)으로
선회율 압박의 하드덱 승리를 라벨에 credit 하거나, (b) DAgger 다회 반복으로 분포를 더 밀거나,
(c) ace-모드와 nose-chaser-모드를 함께 담는 정책이다. 현 시점 최고 정책(cleanRF_dagger)은 실격추
6/8 로, 출발점인 챔피언(실격추 3/8, 격추 0)보다 명백히 강하다.

### U.12 조합 분석 — 적별 승리 케이스로 본 8/8 상한

지금까지 만든 모든 정책(champion, cleanRF_H25/H60/H60fl/dagger, contRF/contXGB, INDI)의 8적
replay 를 한 매트릭스로 모아, 적마다 어느 정책이 격추하는지 분석했다(분석 원칙은 메모리
situation-conditional-vision 의 상황별 tactic — 도구는 replay report 집계, situation_matrix 계열).

| 적 | 격추(KILL/dmg≥40) 가능 정책 | 비고 |
|---|---|---|
| EnergyFighter | dagger | 격추 |
| TwoCircle | H25, H60, dagger, contRF | 격추 |
| Scissors | H60, dagger, INDI | 격추 |
| Adaptive | H60fl, dagger | 격추 |
| defensive | 거의 전 정책 | 격추 |
| ace | H60, H60fl, dagger, contXGB | 격추 |
| GunTracker | 없음 (champion/H25/contRF/INDI 가 판정승=하드덱) | 격추 불가 |
| aggressive | 없음 (동일) | 격추 불가 |

분석 결론:

- 6/8 적은 적어도 한 정책이 격추한다. 적별 최선을 조합하면 6 격추가 동시에 가능하다.
- GunTracker·aggressive 는 어떤 정책도 깨끗이 격추(HP=0)하거나 결정타(≥40)를 못 준다. 그러나
  champion·H25·contRF·INDI 는 선회율 압박으로 적을 하드덱까지 몰아 판정승한다.
- 따라서 8/8 은 지표 정의에 따라 갈린다. 판정승 기준 8/8 은 상황의존 조합으로 달성 가능하다 —
  nose-chaser(GunTracker, aggressive)엔 champion 식 rate-fight(하드덱 강제), 나머지 6 엔 dagger
  연속정책(격추). 격추 기준 8/8 은 nose-chaser 2 가 불가하다(V.4 대칭 gun-kill 의 본질적 한계).

이는 본 프로젝트의 핵심 논지(상황의존, situation-conditional-vision)를 데이터로 재확인한다. 단일
greedy 정책이 두 모드(ace-격추 figure-8, nose-chaser-압박 rate-fight)를 동시에 못 잡으므로, 상위
모드 dispatch 로 둘을 결합하는 것이 8/8(판정승)의 정공법이다. 이 조합 정책의 빌드·검증이 다음
단계다(U.13 예정).


## V. 학술적 해석 — BT 진화의 이론적 근거

BT 가 손튜닝 dispatch 챔피언 → 연속 가치정책(H60+fitted-Q) → 에너지 shaping → INDI 시험으로
진화하며 얻은 각 결과는 우연이 아니라 이론으로 예측·설명된다. 이 절은 그 근거를 인용과 함께 묶는다.

### V.1 연속이 이산을 이기는 이유 — 함수근사 이론

RQ1·E5 의 "연속 우위(이산은 k=60 에서도 regret 2.08 로 연속 1.72 미달)"는 함수근사 이론으로
설명된다. 조각상수(이산 분할) 근사는 분할을 늘려도 사라지지 않는 근사오차를 남기며, 결정면이
연속일 때 유한 분할은 정보를 잃는다(Sutton and Barto, Reinforcement Learning, 2nd ed., 2018, ch.9
함수근사; 타일코딩 대 연속 근사). BFM 상황은 본래 연속체다 — one-circle 과 two-circle 은 HCA 의
연속 스펙트럼 양 끝이지 이산 범주가 아니다(Shaw, Fighter Combat). 따라서 소수 손-이산 상황은
구조적으로 손해다.

### V.2 horizon 과 fitted-Q — 배치 강화학습

U.4 의 "H=25→H=60 + 챔피언 base 가 폭과 ace 격추를 만든 것"은 배치 강화학습의 정설로 설명된다.
짧은 horizon 은 myopic 가치추정이며(우리 E2: H<40 에서 best-tactic 불안정), figure-8 의 sustained
WEZ 격추는 장기 신용할당(long-horizon credit assignment) 문제다. 강한 base 로 tail 을 잇는 fitted-Q
는 근사 정책반복의 한 스텝이다 — 트리 앙상블로 Q 를 회귀하는 우리 방식은 Ernst, Geurts,
Wehenkel(2005, "Tree-Based Batch Mode Reinforcement Learning", JMLR)의 fitted-Q iteration 과
정확히 같은 골격이고, 강한 base 는 Lagoudakis and Parr(2003, LSPI)의 정책반복처럼 가치추정을
최적 쪽으로 한 걸음 옮긴다. 그래서 라벨 horizon·base 가 병목이었지 모델·분류가 아니었다.

### V.3 에너지 shaping 이 실패한 이유 — potential 불변 정리

U.7·U.8 의 "에너지 항이 능력을 못 더한 것"은 튜닝 실패가 아니라 정리의 귀결이다. potential 기반
보상 shaping 은 최적정책을 바꾸지 못함이 증명돼 있다(Ng, Harada, Russell, 1999, "Policy Invariance
under Reward Transformations", ICML). 즉 에너지 potential 은 학습 동역학(gradient)만 바꿀 뿐, 진짜
데미지 라벨이 지지하지 않는 닫기 능력을 추가할 수 없다. 그래서 계수를 어떻게 줘도 능력이 안 늘고
오히려 소극적으로만 변했다. 능력은 shaping 이 아니라 라벨(horizon·base) 또는 행동공간(유도)에서
와야 한다 — 이 예측이 sweep 실패로 그대로 확인됐다.

### V.4 nose-chaser 무승부 — 추격-회피 미분게임의 무승부 균형

남은 2건(GunTracker, aggressive)은 제어 결함이 아니라 게임의 값일 수 있다. 두 nose-chaser 의 대칭
중립 머지는 추격-회피 미분게임이며(Isaacs, Differential Games, 1965; "game of two cars",
homicidal chauffeur), 대칭 상황에서는 어느 쪽도 자신을 노출하지 않고는 격추를 강제할 수 없어
안장점(saddle point)이 무승부가 될 수 있다. 우리 정책이 대칭 aggressive 상대로 지지 않고(무패)
이기지도 못하는 것(무승부)은 균형해일 수 있다. 이기려면 대칭을 깨는 비대칭(에너지·위치·기량
우위)이 필요하다. 이는 8/8 을 재정의한다 — 완전 대칭 거울 상대에겐 강제승이 존재하지 않을 수
있고, 무승부가 올바른 결과다(메모리 new-engine-neutral-conversion-fail 의 "vs ace draw=기하"를
게임이론으로 정식화).

정직한 한정(U.10 정정): 이 미분게임 논증은 깨끗한 gun-kill 의 어려움에는 적용되나, 실제 매치
무승부의 원인으로 곧장 쓰면 과하다. 챔피언은 같은 GunTracker·aggressive 를 선회율 압박(TWO_CIRCLE)
으로 하드덱까지 몰아 이긴다. 즉 승리 라인이 실재한다. 우리 정책의 무승부는 게임의 값이 아니라
배포 정책이 그 승리 tactic 을 못 고른 일반화 갭이다(U.10). V.4 는 "대칭일수록 강제승이 어렵다"는
경향의 근거이지, 특정 nose-chaser 무승부의 면죄부가 아니다.

### V.5 INDI 가 무승부를 못 푼 이유 — 구속조건은 외측 + 제어기 분포이동

U.9 에서 INDI 는 판정 8/8 이지만 실력승 1/8 로 붕괴했다. 두 가지가 겹친다. 첫째, INDI 의 우위는
깊은 고받음각+모델불확실에서 나오는데(Smeur, Chu, de Croon, 2016; Sieberling et al., 2010) 전투
envelope 는 거기 잘 안 들어가, 닫기의 구속조건은 내측 추적 정밀이 아니라 외측 유도 기하(각·거리
동시)다(16장과 일관). 둘째, 더 결정적으로, 정책 가치를 LQR 내측으로 라벨링했기에 INDI 배포는
제어기 train-deploy 분포이동이다 — 같은 tactic 의 plant 응답이 달라져 학습된 가치가 깨지고 데미지가
붕괴한다. 즉 내측 교체는 공짜 개선이 아니라 분포이동이며, 바꾸려면 그 제어기로 재라벨해야 한다.
어느 쪽이든 내측 제어로는 무승부가 안 풀린다.

### V.6 종합 — 8/8 은 어디까지가 ML 문제이고 어디부터 게임의 값인가

6/8 까지는 올바른 ML 방법론(연속 가치 + 적절한 horizon·base)으로 달성했다. 남은 2/8 은 성질이
다르다. 이론이 가리키는 바는 셋이다. 첫째, shaping 으로는 못 푼다(V.3, 정리). 둘째, 내측 제어로도
못 푼다(V.5, envelope). 셋째, 대칭 nose-chaser 의 무승부는 게임의 값일 수 있다(V.4). 따라서 8/8 의
남은 길은 둘뿐이다 — (a) 외측 유도에서 진짜 비대칭(cutoff/PN lead 로 각+거리 동시 폐쇄)을 만들어
게임을 비대칭으로 바꾸거나, (b) 완전 대칭 상대엔 무승부가 정답임을 인정하고 실격추 지표를 비대칭
가능 적에 한정하는 것이다. 이 해석은 다음 실험(GUN_TRACK PN cutoff)을 명확한 가설로 만든다.


## W. 전략 서사 — 챔피언에서 6격추 정책까지

이 절은 흩어진 실험(P~V)을 하나의 전략 이야기로 묶는다. 출발은 손튜닝 챔피언이었고, 끝은 6적을
실제 격추하는 학습 정책이다. 어떻게 여기까지 왔는가, 그리고 각 단계의 전략 원칙은 무엇이었나.

### W.0 출발점 — 손튜닝 챔피언과 네 개의 미검증 가정

배포 챔피언(tree_policy = RF + 손-규칙 4개)은 8적 중 6적을 깎되 한 적도 격추하지 못했고(판정
7/8, 실격추 3/8, 격추 0), 정면 nose-chaser 는 하드덱 압박으로만 이겼다. 더 근본적으로, 그 설계엔
검증되지 않은 가정 넷이 있었다 — 상황을 이산으로 나눠야 하나(4.3), 라벨이 믿을 만한가(4.5), 어떤
모델이 최선인가(4.6), 커버리지가 충분한가(4.7).

### W.1 전략 1 — 가정을 가정으로 두지 않고 측정한다 (RQ1~4)

먼저 네 가정을 실험으로 깼다. 연속 가치학습이 이산 분류를 이겼고(RQ1), 모델 프런티어를 정량화했으며
(RQ3), 커버리지를 측정했다(RQ4). 그 과정에서 라벨 생성 절차의 결정론 버그를 발견·수정했다(RQ2,
같은 상태 채점이 53HP 흔들리던 것을 plant 격리로 0 으로). 원칙: 단정 대신 측정, 그리고 정직한
지표(판정승이 아니라 실격추, replay 더블체크).

### W.2 전략 2 — 입력을 설계한다 (적 풀)

legacy 적 992 개는 중복·퇴화가 커서 커버리지를 못 받쳤다. 3장 BFM 교리에 근거한 설계 적 111 개로
대체해, "1대1 dogfight 를 덮는다"를 우연이 아니라 설계로 만들었다.

### W.3 전략 3 — 병목은 모델이 아니라 라벨이었다 (H60 + 챔피언 base)

이번 연구의 전환점. 라벨 horizon 을 H=25 에서 H=60 으로 올리고 tail 을 챔피언으로 잇는 fitted-Q
bootstrap 으로 바꾸자, 같은 연속 모델이 폭과 치명성을 함께 얻었다(cleanRF_H60, 실격추 6/8). 이때
처음으로 ace 를 figure-8 로 격추했다(오랜 neutral-vs-ace 교착 격파). 교훈: 능력은 모델 교체가 아니라
라벨 품질(horizon·base)에서 왔다.

### W.4 전략 4 — 실패도 이론으로 설명하고 병목을 좁힌다

남은 nose-chaser 2 무승부에 두 가지를 시도해 둘 다 이론대로 실패했다. 전역 에너지 항(shaping)은
Ng 정리상 최적정책을 못 바꾸므로 능력을 못 더했고(순감), INDI 내측은 LQR 로 라벨한 정책에
분포이동이라 데미지가 붕괴했다(판정 8/8 이나 실격추 1/8). 두 실패가 병목을 외측 유도·정책 선택으로
좁혔다.

### W.5 전략 5 — 증상과 원인을 가르고, 틀리면 정정한다

외측 유도에 에너지 바닥을 넣어 하강 나선을 막자 에너지·거리는 우위가 됐지만 무승부는 그대로였다.
이로써 에너지가 원인이 아님을 배웠다. 처음엔 이를 미분게임 무승부(V.4)로 단정했으나, replay 감사에서
챔피언이 같은 적을 선회율 압박으로 이기는 것과 forward-sim 이 TWO_CIRCLE 를 최선으로 라벨하는 것을
확인하고 정정했다 — 무승부는 게임의 값이 아니라 배포 정책의 tactic 오선택(분포이동)이었다.

### W.6 전략 6 — 분포를 정합한다 (DAgger)

배포 정책의 방문 상태를 라벨해 학습분포를 배포분포에 맞추자(DAgger), 교전하는 6적이 전부 격추로
바뀌었다(격추 3→6). 출발점 챔피언(격추 0)을 명백히 넘는 살상력이다.

### W.7 지금 위치와 남은 길

현 최고 정책 cleanRF_dagger 는 실격추 6/8·격추 6 으로, 챔피언(3/8·0)보다 강하다. 남은 둘
(GunTracker, aggressive)은 horizon 한계다 — 선회율 압박의 하드덱 승리가 H=60 너머에 있어 greedy
가치가 추격에 머문다. 8/8 의 길은 horizon 확장(H=90+), DAgger 다회, 또는 ace-모드와 nose-chaser-모드를
함께 담는 정책이다. 핵심 교훈 하나로: 강함은 모델이 아니라 라벨(horizon·base·분포)에서 왔고, 정직한
지표와 자기수정이 매 단계 방향을 바로잡았다.


## T. To-Be — 목표 시스템 (발견에서 도출)

P~Q 가 현재 상태(as-is)와 그 진단이라면, 이 절은 모든 발견을 적용했을 때 도달할 목표 상태(to-be)를
하나의 그림으로 정의한다. S 절의 로드맵은 as-is 에서 이 to-be 로 가는 경로다.

핵심 목표를 한 줄로: 챔피언의 교전 폭(긴 horizon + fitted-Q base + 유효 dispatch)과 실험 연속정책의
터미널 치명성(연속 가치 격추)을 결합한 정책(U 절 근거).

### T.1 as-is 대 to-be (차원별)

| 차원 | as-is (현재) | to-be (목표) | 근거 |
|---|---|---|---|
| 상황 표현 | 손-규칙 4개 + 연속 RF 하이브리드 | 안전 1개 + 순수 연속 가치정책 | RQ1, E6(연속 6/8 ≥ 하이브리드 5/8) |
| 정책 모델 | RandomForest(옛 8-tactic, 오염 라벨) | clean 라벨 학습 + 프런티어상 명시 선택(RF 기본, 출판용 EBM/FIGS 후보) | RQ3 프런티어 |
| 라벨 | base=pursuit, H=60, 결정론 버그 | fitted-Q 정책반복, H 수렴확인, 결정론 보장, 에너지/생존 항 포함 | RQ2, S.3, S.5 |
| 가치함수 | 가한−받은 데미지(공격 편향) | 데미지 + 에너지/생존(potential 기반) | BREAK_TURN 공백, 에너지 고갈 패배 |
| 커버리지 | 적 60종 포화·점유 56%·분포이동 | spawn 기하 축 확대 + 배포궤적 정렬(DAgger류)로 점유·정합↑ | RQ4 |
| 종말 폐쇄 | ATA 22°까지 가나 WEZ 미진입(닫기 실패) | lead/PN cutoff 로 ATA<12·사거리 폐쇄 → WEZ dwell 확보 | 패배 진단(미교전) |
| 검증 | 제어층만 형식검증(16장) | 정책층까지 — 규칙/shape 추출 + 단조성·안전 SMT | RQ5, S.6 |
| 적 풀 | legacy 992(중복·퇴화) | 설계 zoo 111(교리 망라) + 강도 스프레드 | L0, R2 |
| 재현/감사 | 데이터만, replay 누락했던 적 있음 | 모든 실험이 replay+report+plot 저장 | feedback-replays-mandatory |

### T.2 목표 정책의 형태 (한 문단)

to-be 정책은 이렇다. 매 tick 8개 기하 feature 를 읽어, clean·에너지인지 라벨로 학습한 연속 가치
모델이 tactic 별 가치를 예측하고 argmax 로 고른다. 손-규칙은 물리 안전(하드덱 상승) 하나만 남는다.
유도층은 고른 tactic 을 setpoint 로 바꾸되, 종말에는 lead/PN cutoff 로 ATA<12·WEZ 사거리를 실제로
닫는다. 모델은 정확도-투명성 프런티어 위에서 목적(배포는 RF, 출판·검증은 EBM/FIGS)에 따라
선택하며, 그 결정구조는 규칙/shape 로 추출돼 단조성·안전이 기계 점검된다.

### T.3 성공 기준 (측정 가능)

- 전투: 설계 적 대표 + 앵커에서 win-rate 8/8, 그리고 무승부 아닌 실격추(WEZ dwell 확보, 에너지
  Es 고갈 없음).
- 라벨: 재현성 range 0(유지), horizon 수렴 확인, 정책반복 win-rate 단조 향상.
- 커버리지: feature 점유율과 배포 분포 정합(OOD 비율) 개선.
- 투명: 정책을 규칙/shape 로 표현 + 단조성 위반 0, 안전 명제 SMT 통과.
- 재현: 모든 실험 replay 자산 완비.

이 to-be 는 새 가정을 도입하지 않는다. 모든 항목이 P~Q 의 측정된 발견에서 직접 나온다. 8/8 의
주병목은 분류가 아니라 종말 폐쇄와 에너지 관리(T.1 의 두 행)임을 패배 진단이 가리킨다.


## S. 연구 후 로드맵 — as-is 에서 to-be 로 가는 경로

이 절은 위 발견이 우리의 최신 BT(tree_policy.py 의 하이브리드 정책 = 손-규칙 4개 + 연속 RF)를
어떻게 바꾸는지, 그리고 각 변화가 어떤 실험으로 검증되는지를 갭 없이 잇는다(T 절 to-be 로 가는
경로). 각 항목은
"발견 → 함의 → BT 변경 → 검증 실험" 형식이다.

### S.1 손-규칙을 줄이고 연속 정책으로 — RQ1 직결

- 발견: 연속 가치학습이 이산 분류를 이긴다(P.4, P.9). 그런데 현재 BT 는 여전히 손-규칙 4개
  (안전 상승, head-on ADAPTIVE latch, evasive VERTICAL_PURSUIT, 근접 GUN_TRACK)로 일부 상황을
  하드코딩한다.
- 함의: 손-규칙은 작은 이산 분류와 같다. RQ1 이 맞다면 이들 중 학습으로 대체 가능한 것은 빼는 게
  더 투명하고 일관된다. 단, 안전 상승(하드덱)은 물리 안전이라 유지.
- BT 변경: 손-규칙을 안전 1개만 남기고 나머지 3개를 연속 정책에 흡수.
- 검증 실험(E6 가 1차): 정책을 연속RF 대 하이브리드RF 로 배포해 win-rate·마진 비교(P.10). 이어서
  손-규칙 하나씩 끄는 leave-one-rule-out 매치로 각 규칙의 실제 기여를 분리 측정. 기여 음수면 제거,
  양수면 그 상황을 라벨이 못 잡는다는 뜻이므로 라벨/feature 보강.

### S.2 정확도-투명성 프런티어 위에서 배포 모델 선택 — RQ3 직결

- 발견: XGBoost≈RF(정확도), EBM/FIGS(투명) 프런티어 존재(P.7).
- 함의: 교과서 출판과 형식검증이 목표이므로, 투명 모델의 실제 전투 비용을 알아야 선택할 수 있다.
- BT 변경: 배포 모델을 RF 로 두되, EBM/FIGS 변형을 후보로 유지.
- 검증 실험: EBM·FIGS 를 정책으로 배포한 win-rate 를 RF 와 비교(E6 확장). 투명 모델의 win-rate
  손실이 작으면 출판용으로 EBM/FIGS 채택.

### S.3 라벨을 정책반복으로 끌어올리기 — RQ2 직결

- 발견: 라벨은 결정론 수정 후 재현 가능하고 H 약 40s 이상에서 안정(P.5, P.6). 단 tail 이
  PURE_PURSUIT 로 고정돼 fitted-Q 1-step 에 머문다.
- 함의: tail 을 학습 정책으로 바꿔 재라벨하면 라벨이 더 정확한 가치에 수렴할 수 있다(정책반복).
- BT 변경: 없음(라벨 절차 개선). 결과 정책은 더 정확해짐.
- 검증 실험: base=학습정책으로 1~3회 재라벨 → 매 회 win-rate 측정해 수렴 확인(policy iteration).
  동시에 H=90,120 스윕으로 60s 수렴 여부 확정.

### S.4 커버리지를 배포 분포에 정렬 — RQ4 직결

- 발견: 적 60종이면 포화하나, 학습 상태와 배포 방문 상태에 분포 이동이 있다(P.6 E4).
- 함의: 적을 더 늘리는 것보다, 배포 정책이 실제로 방문하는 상태를 라벨해 메우는 게 효율적이다
  (DAgger 류 분포 정합).
- BT 변경: 없음(데이터 수집 전략). 정책 일반화 향상.
- 검증 실험: 배포 정책으로 매치 → 방문 상태 수집 → 라벨 → 재학습을 반복하며 OOD 비율과
  win-rate 추적. spawn 기하 축(거리·고도·에너지 비대칭)도 LHS 범위 확대.

### S.5 가치 정의에 생존/에너지 반영 — 관측된 BREAK_TURN 공백

- 발견: BREAK_TURN 이 best 로 거의 안 나온다(P.6). 점수가 가한−받은 데미지라 순수 방어가
  점수를 못 올리기 때문이다.
- 함의: 현재 가치는 공격 편향이다. 방어·생존·에너지 보존의 가치를 과소평가해, 강한 공격수
  (aggressive)·동등 교착(neutral vs ace)에서 약점이 될 수 있다.
- BT 변경: 없음(라벨 목적함수 보강). 방어 국면 정책이 개선됨.
- 검증 실험: 생존 보너스/에너지 항을 목적함수에 더한 라벨로 재학습 → 방어 시나리오 win-rate 와
  피격 감소 측정. shaping 이 최적정책을 바꾸지 않도록 potential 기반(Ng 1999) 유지.

### S.6 투명 정책의 형식검증 — RQ5 (미수행)

- 발견: EBM shape 함수·FIGS 규칙은 사람이 읽을 수 있다(P.7).
- 함의: 정책을 규칙/수식으로 추출하면 단조성("가깝고 정면일수록 공격적")과 안전성을 기계로 점검
  가능 — 16장 형식검증을 제어층에서 정책층으로 확장.
- 검증 실험: FIGS 규칙·EBM shape 추출 → 단조성 위반 탐지 + 안전 명제 SMT(Z3) 점검.

### S.7 로드맵 순서와 본 연구 후 프로젝트 과제

다음 패스 권장 순서(의존성 기준): S.1 손-규칙 ablation(E6 이후 바로) → S.3 정책반복·H 수렴
→ S.4 분포정합 재라벨 → S.5 생존 가치 → S.2 투명 모델 배포 비교 → S.6 형식검증.

본 연구 이후 프로젝트 과제(연구와 별개의 산출물 작업):
- 본문 4.3~4.7, 12장에 Q.2 실측 반영(검토 후). 옛 수치 폐기.
- 군집 그림·프런티어 그림·스케일링 곡선·H 스윕 곡선을 본문 그림으로 작도.
- 적 풀(zoo 111)·실험 스크립트(exp_*.py)를 재현 부록으로 문서화.
- replay 표준화: 모든 실험이 archetype/정책별 대표 매치의 acmi+report+plot 을 남기도록 고정
  (더블체크 자산).

논리 연결 점검: 위 S.1~S.6 은 모두 P 절의 측정된 발견에서 직접 파생되며 새 가정을 도입하지 않는다.
각 실험은 기존 코드(offline_solver, tree_policy, exp_*.py)의 작은 변경으로 실행 가능하다.
