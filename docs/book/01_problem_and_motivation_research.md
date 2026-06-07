# 1장 부록(연구편). 정책 학습의 열린 질문과 실험 설계

이 문서는 1장 본문(문제와 동기)의 연구 동반 문서다. 본문이 "무엇을 왜 만들었는가"를
설명한다면, 이 문서는 그 설계 결정 가운데 아직 정량적으로 검증되지 않은 부분을 연구질문으로
세우고, 그것을 푸는 실험을 설계한다. 대상은 본문 4.3 상황분류, 4.5 라벨링, 4.6 정책 모델,
4.7 커버리지다.

표기는 책 전체 규약을 따른다. 별표 강조, 이모지, 한자를 쓰지 않는다.


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
