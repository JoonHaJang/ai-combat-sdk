# LAB 1. 직접 해보기 — BT 만들기, 시나리오 대결, replay 분석, GUI

이 실습서는 앞 장(특히 3장 BFM 상황, 11장 의사결정 BT, 15장 시나리오)에서 배운 것을 손으로 직접
해보게 한다. 선수지식 없이 따라올 수 있도록 명령 한 줄, 결과 한 줄을 모두 적었다. 다섯 실습으로
구성된다.

- LAB 1.1 환경 준비
- LAB 1.2 적 BT 만들기 (.yaml 손작성 + 자동 생성기)
- LAB 1.3 BT GUI 비주얼라이저(bt-editor)로 트리 보고 편집하기
- LAB 1.4 시나리오로 만들어 BT 대 BT 대결하기
- LAB 1.5 replay 저장과 자동 보고서·plot, Tacview 재생

표기는 책 규약을 따른다(별표 강조, 이모지, 한자 없음). 명령은 프로젝트 루트
ai-combat-sdk 에서 실행한다고 가정한다.


## LAB 1.1 환경 준비

목표: 엔진을 한 번 돌려 설치가 정상인지 확인한다.

1. 파이썬 의존성. 엔진은 JSBSim, numpy, scipy, scikit-learn 을 쓴다. 처음이면 설치한다.

```
python -m pip install jsbsim numpy scipy scikit-learn pyyaml
```

2. 첫 매치 한 번 돌려보기. 표준 평가 진입점은 new_match_engine/bt/run_match.py 다. 우리 배포 정책
(TreePolicy)이 기본 적 4종(simple, aggressive, defensive, ace)과 표준 중립 빔에서 싸운다.

```
cd new_match_engine/bt
python run_match.py
```

기대 결과: 4경기가 끝나고 각 경기의 승패와, 경기별 replay 폴더 경로가 출력된다. 폴더는
new_match_engine/replays/canon_<적>_NNNN/ 아래에 생긴다. 한 경기만 빨리 보려면 적 이름을 준다.

```
python run_match.py ace
```

여기까지 되면 엔진과 우리 정책이 정상이다. 이제 부품을 하나씩 만져본다.


## LAB 1.2 적 BT 만들기

배경: 적 조종사는 행동트리(BT)로 정의되며, 우리 엔진은 그것을 .yaml 파일로 읽는다(11장,
new_match_engine/bt/yaml_bt.py). BT 는 Selector(첫 성공 가지 채택)와 Sequence(조건 모두 통과 시
액션)로 이뤄지고, 잎은 Condition(관측 평가)과 Action(우리 Tactic 으로 매핑)이다. 어휘는 조건 35종,
액션 37종으로 정해져 있다(1장 4.4.1, 4.4.2 표).

### 1.2.1 손으로 .yaml 적 한 명 만들기

가장 단순한 적, "항상 추격하되 하드덱이면 상승"을 만들어 본다. 새 파일
new_match_engine/opponents/zoo/MY_Chaser.yaml 을 만들고 다음을 적는다.

```
name: MY_Chaser
tree:
  type: Selector
  children:
    - type: Sequence
      children:
        - type: Condition
          name: BelowHardDeck
          params: {threshold_ft: 1200}
        - type: Action
          name: ClimbTo
    - type: Action
      name: Pursue
```

읽는 법. 맨 위 Selector 가 위에서 아래로 본다. 첫 가지 Sequence 는 "고도 1200ft 미만이면 ClimbTo".
조건이 거짓이면 이 가지는 실패하고 Selector 가 다음 가지(Action Pursue)로 넘어간다. 즉 평소엔
Pursue, 추락 위험이면 ClimbTo. Action 이름은 우리 Tactic 으로 매핑된다(Pursue → PURE_PURSUIT,
ClimbTo → CLIMB).

### 1.2.2 내 적이 상황별로 무엇을 하는지 확인하기

만든 BT 가 상황에 따라 어떤 tactic 을 내는지는 도감 도구로 한눈에 본다.

```
cd new_match_engine/bt
python exp_opp_catalog.py
```

기대 결과: 각 archetype 이 일곱 상황(정면머지, 중립빔, 우리가공격, 우리가방어, 원거리, 저고도,
에너지열세)에서 내는 tactic 표가 출력된다. 적의 행동이 단순한지(한 tactic 고정) 복합인지(상황별
변화) 바로 보인다. 적 도감 전체 설명은 docs/reference/OPPONENT_BT_CATALOG.md 에 있다.

### 1.2.3 적 풀을 자동 생성하기

손으로 한 명씩 만들 수도 있지만, 3장 BFM 교리에 근거한 적 풀 전체(13 archetype x 변주, 약 111명)는
생성기로 한 번에 만든다.

```
cd new_match_engine/bt
python gen_opponent_zoo.py
```

기대 결과: new_match_engine/opponents/zoo/ 아래에 A1_PurePursuer_00.yaml 같은 .yaml 들이 생긴다.
각 파일은 archetype(추격/에너지/선회율/방어 등)과 파라미터 변주(공격성, 방어 trigger, 에너지
임계)를 담는다. 생성 직후 적절성 점검(중복, 퇴화, tactic 커버리지)은 감사 도구로 한다.

```
python exp_opp_audit.py
```


## LAB 1.3 BT GUI 비주얼라이저 (bt-editor)

배경: .yaml 을 손으로 보는 대신, 드래그앤드롭으로 트리를 보고 편집하는 웹 GUI 가 있다(프로젝트
루트 bt-editor/). Vite + React 로 만들어졌다.

### 1.3.1 실행

```
cd bt-editor
npm install        # 처음 한 번만
npm run dev
```

기대 결과: 로컬 개발 서버 주소(보통 http://localhost:5173)가 출력된다. 브라우저로 그 주소를 연다.

### 1.3.2 사용

- 좌측 노드 팔레트에서 Selector, Sequence, Condition, Action 을 끌어다 캔버스에 놓는다.
- 노드를 선으로 이어 트리를 만든다. Condition/Action 의 이름과 params 는 노드 속성에서 고른다.
  어휘(조건 35종, 액션 37종)는 엔진과 1:1로 맞춰져 있어, 편집기에서 만든 트리는 그대로 엔진이
  실행한다.
- 완성한 트리를 .yaml 로 내보내(export) new_match_engine/opponents/zoo/ 에 두면 LAB 1.4 에서
  바로 대결시킬 수 있다.

요점: 편집기에서 만든 .yaml = 엔진이 읽는 .yaml. GUI 로 그리고, 코드로 돌린다.


## LAB 1.4 시나리오로 만들어 BT 대 BT 대결

배경: 시나리오는 두 기체의 시작 배치다(15장). 코드에서는 spawn 함수이며,
new_match_engine/engine/scenarios.py 의 SITUATIONS 에 정해져 있다. 표준 평가는 반드시 중립 빔
(spawn_adt_neutral: 90도 빔, 3000ft, 정반대 진행)을 쓴다 — 이게 원본 평가 초기조건이다.

쓸 수 있는 시나리오:
- spawn_adt_neutral: 중립 빔(표준 평가).
- spawn_offensive: 우리가 적 6시 뒤(공격 위치).
- spawn_defensive: 적이 우리 6시 뒤(방어 위치).
- spawn_headon: 정면 접근(머지).

### 1.4.0 우리 BT는 어디에 있나 (중요)

먼저 비대칭을 분명히 하자. 적과 우리 편은 형태가 다르다.

- 적(.yaml BT). 적 조종사는 LAB 1.2 의 .yaml 파일이다. yaml_bt 인터프리터가 트리를 순회해 Tactic 을
  낸다(손으로 짠 if-then 규칙).
- 우리 편(학습된 정책). 우리 조종사는 .yaml 이 아니라 학습된 정책이다. 위치는
  new_match_engine/bt/tree_policy.py 의 TreePolicy 클래스다. 이것은 학습된 RandomForest
  (new_match_engine/bt/policy_value.pkl)가 8개 기하 feature 를 받아 tactic 가치를 예측하고 argmax 로
  고르는 부분과, 안전 상승 같은 소수 손-규칙(dispatch)으로 이뤄진다. 즉 "우리 BT"는 데이터로 배운
  정책이다(11장).

정리하면 run_match.py 의 한 경기는 "우리 TreePolicy(학습 정책) 대 적 .yaml BT"다. 둘 다 매 tick
관측을 받아 Tactic 을 내고, 그 뒤 유도·제어·JSBSim 은 똑같이 공유한다. 우리 쪽 Tactic 결정만
학습된 정책이라는 점이 다르다.

참고로, 이 책 U·X 절에서 만든 8/8 단일 BT(적 정체 모르고 8명 모두 이기는 정책)는 또 다른 파일
new_match_engine/bt/exp_e10_unified.py 의 UnifiedPolicy 다. TreePolicy(기본 배포 정책)보다 한 단계
발전한 것으로, dagger 가치정책 + 적 롤로 nose-chaser 를 가리는 이른 감지 + champion 전환을 합친다.
run_match.py 는 기본 TreePolicy 를 쓰고, 8/8 정책을 돌리려면 exp_e10_unified.py 를 실행한다.

```
cd new_match_engine/bt
python exp_e10_unified.py 300    # 8/8 단일 BT(UnifiedPolicy) 대 대표 8적
```

### 1.4.1 우리 정책 대 한 적 BT 대결

가장 간단한 대결은 run_match.py 다. 우리 배포 정책(TreePolicy, 위 1.4.0)이 .yaml 적과 표준 빔에서
한 경기를 한다.

```
cd new_match_engine/bt
python run_match.py ace          # 우리 TreePolicy(학습 정책) vs ace.yaml(적 BT)
```

LAB 1.2 에서 만든 MY_Chaser 와 붙이려면 적 이름만 바꾼다(파일이 opponents/zoo 또는 opponents 에
있어야 한다).

```
python run_match.py MY_Chaser
```

기대 결과: 승패와 replay 폴더 경로가 출력된다.

### 1.4.2 적 BT 대 적 BT 대결 (우리 정책 없이)

두 .yaml 적을 서로 붙이려면 작은 스크립트를 쓴다. 핵심은 Match 객체에 두 tactic 함수를 주는 것이다.
아래를 new_match_engine/bt/my_bt_vs_bt.py 로 저장한다.

```
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from yaml_bt import load_bt
from obs import compute_obs
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files

A = load_bt(os.path.join("..", "opponents", "ace.yaml"))          # 청군 BT
B = load_bt(os.path.join("..", "opponents", "aggressive.yaml"))   # 홍군 BT
gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
p1, p2 = spawn_adt_neutral()
m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
          control_hz=20, bt_hz=10, log_hz=60)
res = m.run(tactic_fn1=lambda o: A(compute_obs(p1, p2)),
            tactic_fn2=lambda o: B(compute_obs(p2, p1)), duration_s=300.0)
print("winner:", res.winner, "HP", res.health1, res.health2, "dmg", res.damage_dealt1)
rd = next_run_dir(os.path.join("..", "replays"), prefix="bt_vs_bt")
write_acmi_plot(res.log, os.path.join(rd, "match.acmi"), title="ace_vs_aggressive")
write_csv(res.log, os.path.join(rd, "match.csv"))
analyze_match_files(os.path.join(rd, "match.acmi"),
                    meta_path=os.path.join(rd, "match.csv"), out_dir=rd, title="ace_vs_aggressive")
print("replay:", rd)
```

```
cd new_match_engine/bt
python my_bt_vs_bt.py
```

기대 결과: 승자, 양측 HP, 가한 데미지가 출력되고 replay 폴더가 생긴다. A 와 B 의 .yaml 만 바꾸면
어떤 두 적이든 붙일 수 있다.

설명. compute_obs(p1, p2) 는 우리(청군) 관점 관측, compute_obs(p2, p1) 은 적(홍군) 관점 관측이다.
각 BT 함수는 자기 관점 관측을 받아 Tactic 을 낸다. Match 가 그 Tactic 을 유도(setpoint)와 제어(LQR)로
실현하고 JSBSim 으로 6자유도 비행을 굴린다. 매 tick WEZ(사격권)와 데미지, 하드덱을 판정한다.

### 1.4.3 상황 x tactic 매트릭스 (어떤 상황에 어떤 tactic 이 유리한가)

3장의 상황별로 우리 tactic 들을 전수 비교해 유리도를 누적하는 도구가 있다.

```
cd new_match_engine/bt
python situation_matrix.py
```

기대 결과: 상황 x tactic 표와 CSV 가 나온다. 어떤 상황에서 어느 기동이 유리한지 데이터로 본다
(데이터 기반 상황별 전술의 근거).


## LAB 1.5 replay 저장과 자동 보고서, plot, Tacview 재생

배경: 모든 매치는 세 산출물을 남기도록 자동화돼 있다(이중 점검용). LAB 1.4 의 스크립트가 이미
이 셋을 만든다.

- match.acmi — Tacview 재생 파일(3D 궤적, 이벤트 로그).
- match.csv — 프레임별 전체 상태(분석용).
- report.txt + plot.png — 자동 정량 보고서와 3D 궤적 그림.

### 1.5.1 자동 보고서가 만들어지는 원리

매치가 끝나면 다음 한 줄이 보고서와 그림을 만든다(LAB 1.4 스크립트 안에 있다).

```
analyze_match_files(acmi_path, meta_path=csv_path, out_dir=폴더, title="...")
```

이 함수(tools/plot_match_3d_nme.py)가 acmi 와 csv 를 읽어 report.txt(7층 정량: 결과, 교전성, 위치/BFM,
에너지, 기동패턴, 제어, 판정)와 plot.png(3D 궤적, figure-8 검출, WEZ dwell, 에너지)를 출력한다.

### 1.5.2 보고서 읽기

방금 만든 폴더의 report.txt 를 연다. 예:

```
type new_match_engine\replays\bt_vs_bt_0001\report.txt    (Windows)
cat  new_match_engine/replays/bt_vs_bt_0001/report.txt     (bash)
```

핵심 줄:
- 결과: outcome(WIN/DRAW), HP us:opp, dmg dealt/taken.
- 교전성: WEZ(us) 횟수와 dwell(사격권 체류 시간), 거리 분포.
- 에너지: 양측 비에너지 Es, 에너지 소진(bleed).
- 기동패턴: figure-8 lemniscate 등 검출된 궤적 형태.
- 판정: 격추 성립 근거 또는 미교전 원인.

### 1.5.3 Tacview 로 3D 재생

match.acmi 를 Tacview(무료 뷰어)로 열면 두 기체의 3D 궤적이 재생된다. Event Log 패널에 tactic 전환,
GUN WEZ firing, HIT(피격), HARD DECK, DESTROYED(격추) 이벤트가 시간순으로 표시된다(우리 청군은
Blue, 적 홍군은 Red). 숫자만으로 못 보는 거동을 눈으로 더블체크하는 용도다. acmi 포맷 규약(15Hz
다운샘플, Name=F-16, Color)은 acmi 자동 생성기(new_match_engine/engine/replay.py)가 지킨다.

요점: 모든 실험은 acmi + csv + report + plot 을 남긴다. 데이터(숫자)와 궤적(눈)을 항상 함께 본다.


## 정리 — 이 LAB 으로 익힌 것

1. 적 BT 를 .yaml 로 손작성하고, 생성기로 풀 전체를 만들고, 도감으로 상황별 행동을 확인했다.
2. bt-editor GUI 로 트리를 그리고 편집했다 — GUI 의 .yaml = 엔진의 .yaml.
3. 시나리오(spawn)로 우리 정책 대 적, 적 대 적을 대결시켰다.
4. 매치가 자동으로 남기는 replay(acmi) + 보고서(report.txt) + 그림(plot.png)을 읽고 Tacview 로
   재생했다.

다음 단계로, 이 도구들로 11장의 정책을 직접 학습시키거나(오프라인 라벨 생성 -> 학습 -> 평가), 3장의
상황을 새 시나리오로 만들어 약점을 찾는 실험을 설계할 수 있다.

### 자주 쓰는 명령 요약

```
python new_match_engine/bt/run_match.py [적이름]     # 우리 TreePolicy(학습 정책) vs .yaml 적
python new_match_engine/bt/exp_e10_unified.py 300    # 8/8 단일 BT(UnifiedPolicy) vs 대표 8적
python new_match_engine/bt/gen_opponent_zoo.py       # 적 풀 자동 생성(13 archetype x 변주)
python new_match_engine/bt/exp_opp_catalog.py        # 적 상황별 tactic 도감 표
python new_match_engine/bt/exp_opp_audit.py          # 적 풀 적절성 감사
python new_match_engine/bt/situation_matrix.py       # 상황 x tactic 유리도 매트릭스
cd bt-editor && npm run dev                           # BT GUI 비주얼라이저
```
