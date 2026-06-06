# 우리 BT 정책 명세서 — 정의와 동작 (TreePolicy)

> **목적**: "우리 BT가 *어떻게 정의*되어 있고, *어떻게 동작*하는지"를 처음 보는 사람도 끝까지
> 따라올 수 있게 **위(쉬운 한 줄) → 가운데(흐름) → 아래(코드 한 줄씩)** 순서로 설명한다.
> 코드: `new_match_engine/bt/tree_policy.py`. 관련: [학생용 입문서](NEW_ENGINE_STUDENT_GUIDE.md) ·
> [아키텍처](NEW_ENGINE_ARCHITECTURE.md) · [Tactic 명세](../new_match_engine/TACTIC_SPEC.md).

---

# 1부 — 최상위 (가장 쉬운 한 장)

## 1.1 한 문장
**우리 BT = "지금 적과의 상황을 보고, 할 전술 하나를 고르는 결정기."** 매 결정 시점(0.1초마다)
호출되어 `Tactic`(전술) 한 개를 돌려준다. 그게 전부다.

```
   적과의 상황(관측)  ──►  [ 우리 BT = TreePolicy ]  ──►  전술 1개 (Tactic)
   (거리·각도·속도…)                                       (예: GUN_TRACK)
```

## 1.2 고른 전술은 그다음에
전술 하나가 정해지면, 그 아래 단계들이 그걸 *실제 비행*으로 바꾼다(이 문서 6부):
```
Tactic ─► guidance(목표 만들기) ─► LQR/INDI(조종면 계산) ─► JSBSim(실제 비행)
```

## 1.3 딱 3가지만 기억
1. 우리 BT는 **그림으로 그린 트리가 아니라**, "상황 → 전술"을 고르는 **하이브리드 결정기**(규칙 + 학습된 모델)다.
2. 매 tick **딱 하나의 전술**을 고른다. 무겁지 않다(μs, 온라인 예측·rollout 없음).
3. **우리 정책(TreePolicy)** 과 **적이 쓰는 `.yaml` BT** 는 *다른 것*이다(2부에서 구분).

---

# 2부 — 헷갈리지 말 것: "BT" 3종 구분

이 프로젝트에서 "BT"라는 말이 세 군데서 쓰여 혼동된다. 명확히 나눈다:

| 이름 | 정체 | 어디 | 누가 씀 |
|---|---|---|---|
| **① 우리 정책 = TreePolicy** | 상황→전술 결정기(규칙+학습). **이 문서의 주인공** | `bt/tree_policy.py` | *우리* 기체 |
| **② 적 `.yaml` BT** | Selector/Sequence/Condition/Action 으로 그린 행동트리 파일 | `opponents/*.yaml` | *적* 기체 |
| **③ `.yaml` 해석기 = yaml_bt** | ②의 `.yaml`을 읽어 전술로 바꾸는 인터프리터 | `bt/yaml_bt.py` | ②를 실행 |

- **우리 기체**는 ①(TreePolicy)로 전술을 고른다.
- **적 기체**는 ②(`.yaml`)를 ③(yaml_bt)이 해석해 전술을 고른다.
- 사람이 ②를 *그려서 만드는 도구*가 **bt-editor**(드래그앤드롭 웹 편집기).

> 즉 "우리 마지막 BT가 어떻게 정의·동작하나"의 답은 **①TreePolicy**다. 아래는 전부 ① 이야기.

---

# 3부 — 큰 그림: 결정 1회의 흐름 (중간 수준)

매 결정 tick마다 `TreePolicy.select(우리기체, 적기체)` 가 호출된다. 내부는 **우선순위 사다리**다:
위에서부터 조건을 검사해 *맨 먼저 걸리는* 가지가 전술을 정하고 끝낸다(아래로 안 내려감).

```
select(p1, p2):
   관측 계산 (거리·각도·속도·에너지…)
   │
   ├─[1] 너무 낮은 고도?            → CLIMB        (안전 최우선)
   ├─[2] 정면충돌(head-on) 매치?    → ADAPTIVE     (한 번 걸리면 그 경기 내내 고정)
   ├─[3] 적이 멀고 안 닫힘(도망)?   → VERTICAL_PURSUIT
   ├─[4] 적이 가깝고 대충 정렬?     → GUN_TRACK    (마무리 사격)
   └─[5] 그 외 전부               → 학습된 모델이 점수로 최적 전술 선택
```

- **[1]~[4] = 손으로 정한 규칙(상황 독립 dispatch)** — "이런 상황엔 이 전술"이 명백한 경우.
- **[5] = 학습된 모델(회귀)** — 규칙으로 딱 못 자르는 일반 상황은 데이터로 배운 모델이 결정.

이 "규칙 우선 + 나머지는 학습" 구조가 우리 BT의 **정의의 핵심**이다.

---

# 4부 — 우리 BT는 어떻게 *정의*되었나

## 4.1 하이브리드: 규칙 + 학습
우리 BT는 두 조각의 합이다.
- **규칙 조각**(코드로 명시): 안전·정면·도망·근접 4가지 명백한 상황 → 해당 전술 직접 지정.
- **학습 조각**(파일로 저장): 나머지 일반 상황 → 오프라인에서 학습한 **value 회귀 모델**이 결정.

## 4.2 학습 조각은 어떻게 만들었나 (오프라인 파이프라인)
온라인(경기 중)에는 *예측·rollout을 전혀 하지 않는다*. 대신 **경기 전에 미리** 무거운 계산으로
"어떤 상황에서 어떤 전술이 좋은가"를 배워서 가벼운 모델로 구워 둔다. 순서:

```
1) 데이터 수집      : 다양한 상황에서 매치를 돌려 (상황특징, 전술, 결과) 기록
2) 라벨링          : 각 상황에서 전술별로 forward-sim 해 "이 전술의 가치(점수)" 측정
3) 회귀 학습        : sklearn 으로 feature → (전술별 점수) 회귀 모델 학습
4) 굽기(deploy)    : 모델을 policy_value.pkl 로 저장 → 경기 중엔 predict 1번(μs)
```
- 도출 코드: `bt/offline_solver.py`(+ `build_situation_dataset.py`, `cluster_situations.py`).
- 산출물: **`bt/policy_value.pkl`** = `{reg: 회귀모델, feats: 입력특징목록, tactics: 전술목록}`.
- 철학(사용자 비전): *무거운 계산은 오프라인에, 배포 정책은 가볍게.*

## 4.3 규칙 조각은 왜 손으로 넣었나
학습 모델만으로는 *특정 상황의 명백한 정답*을 놓치거나 흔들렸다(계측 결과). 그래서
"이건 무조건 이 전술"인 4가지를 **학습보다 위(우선순위)에** 손으로 박았다 — 안전·정면·도망·근접.
이게 **상황 독립 dispatch**(상황마다 독립적으로 옳은 전술을 강제)의 실체다.

## 4.4 입력 특징 8개 (모델이 보는 것)
학습 조각(회귀)이 보는 상황 특징(feature)은 정확히 8개다:

| # | 특징 | 뜻 | 단위 |
|---|---|---|---|
| 1 | `ata_deg` | 내 기수 → 적 각도 (0=정조준) | ° |
| 2 | `aa_deg` | 적 꼬리 기준 내 위치각 | ° |
| 3 | `hca` | 두 기체 진행방향 사잇각 | ° |
| 4 | `distance_ft` | 거리 | ft |
| 5 | `closure_kts` | 접근속도(+접근/−이격) | kts |
| 6 | `es_diff` | 에너지(고도+속도) 우열 | ft 등가 |
| 7 | `ego_r_dps` | 내 yaw rate(선회방향·속도) | °/s |
| 8 | `enm_r_dps` | 적 yaw rate | °/s |

---

# 5부 — 우리 BT는 어떻게 *동작*하나 (코드 한 줄씩)

`tree_policy.py` 의 `select()` 를 위에서부터 그대로 따라간다. (실제 코드와 1:1)

## 5.0 진입
```python
def select(self, p1, p2) -> Tactic:
    o = compute_obs(p1, p2)        # 적과의 기하·상태 관측 (거리·각도·속도·에너지…)
```
- `p1`=우리, `p2`=적. `o`(Observation)에 §4.4의 특징이 다 들어 있다.

## 5.1 [1단계] 안전 — 너무 낮으면 무조건 상승
```python
    if o.ego_alt_ft < self.safe_deck_ft:    # safe_deck_ft = 2500 ft
        return Tactic.CLIMB
```
- 고도가 **2500ft 미만**이면 다른 모든 판단을 *무시하고* `CLIMB`(상승). 지면 충돌(Hard Deck 1000ft) 회피가 최우선.
- *왜 위에?* 아무리 좋은 공격 기회라도 추락하면 패배라서.

## 5.2 [2단계] 정면충돌(head-on) 래치 → ADAPTIVE
```python
    self._tick += 1
    if (self._tick < 50 and o.ata_deg < 40.0 and o.aa_deg > 130.0
            and o.distance_ft < 9000.0):
        self._engaged = True
    if self._engaged:
        return Tactic.ADAPTIVE
```
- **감지**: 경기 *초반*(첫 50틱 ≈ 5초)에 `ata<40°`(내가 적을 거의 향함) + `aa>130°`(적도 나를 향함=정면) + `거리<9000ft` 이면 → "정면충돌 매치"로 판정해 **`_engaged` 래치(latch)를 켠다.**
- **래치(latch)** = 한 번 켜지면 *그 경기 내내* `ADAPTIVE` 를 고정 반환.
- *왜 래치?* 정면 매치는 **τ-블렌딩(ADAPTIVE)** 으로 일관되게 풀어야 이긴다(계측: 연속 commit=4/4, 도중 전환=1/4). 단 *초반 5초에만* 감지 → 중반에 우연히 정면이 돼도 래치 안 함(중립 추격 무회귀).

## 5.3 [3단계] 도망(evasive-extend) → VERTICAL_PURSUIT
```python
    if o.distance_ft > 4500.0 and o.ata_deg < 50.0 and o.closure_kts < 30.0:
        return Tactic.VERTICAL_PURSUIT
```
- **조건**: `거리>4500ft`(멀다) + `ata<50°`(내가 적을 겨눔) + `closure<30kts`(거의 안 닫힘=적이 도망/extend).
- → `VERTICAL_PURSUIT`(적 고도를 따라가는 수직 추격). *왜?* 수평 추격은 적이 수직(zoom)으로 빠질 때 놓친다(계측). 다가오는 적(closure>0)에는 *발동 안 함* → 무회귀.

## 5.4 [4단계] 근접 마무리 → GUN_TRACK
```python
    if o.distance_ft < 2800.0 and o.ata_deg < 45.0:
        return Tactic.GUN_TRACK
```
- **조건**: `거리<2800ft`(WEZ 사거리 근처) + `ata<45°`(대충 정렬).
- → `GUN_TRACK`(적 선회를 예측한 연속 정밀 lead 로 `ata<12°` 락 시도). *왜?* 근접에선 사거리엔 들어가도 overshoot 로 각이 안 맞아 WEZ 0이 되곤 함(각+거리 동시 실패). GUN_TRACK 이 그 둘을 동시에 맞춘다.

## 5.5 [5단계] 그 외 — 학습된 회귀 모델
```python
    x = [[o.ata_deg, o.aa_deg, _hca(o), o.distance_ft, o.closure_kts,
          _es_diff(o), o.ego_r_dps, o.enm_r_dps]]      # §4.4 특징 8개
    scores = self.reg.predict(x)[0]                    # 전술별 예측 "점수"
    return Tactic[self.tactics[int(scores.argmax())]]  # 점수 최고 전술 선택
```
- 1~4단계에 *아무것도 안 걸린* 일반 상황: 특징 8개를 **학습된 회귀모델 `reg`** 에 넣어
  **전술별 점수**를 받고, **가장 높은 점수의 전술**(argmax)을 고른다.
- 이게 §4.2에서 오프라인으로 구운 `policy_value.pkl` 가 실제로 쓰이는 지점.

## 5.6 우선순위 = 안전망 사다리
정리하면 select 는 **위에서 아래로 "맨 먼저 걸리는 것"** 이 이긴다:
`안전 ▶ 정면래치 ▶ 도망 ▶ 근접 ▶ 학습모델`. 위 4개는 *확실한 상황의 강제*, 마지막이 *일반 상황의 학습 결정*.

---

# 6부 — 고른 전술이 *실제 비행*이 되기까지 (실행 체인)

`select()` 가 돌려준 `Tactic` 하나가 아래를 거쳐 조종면 움직임이 된다(자세한 건
[아키텍처 문서](NEW_ENGINE_ARCHITECTURE.md)):

```
Tactic  ─►  guidance.py            : 전술 + 관측 → 목표값 Setpoint(방위 ψ*, 고도 h*, 속도 V*)
        ─►  autopilot.py + LQR/INDI: 목표값 → 조종면 u=[throttle,elevator,aileron,rudder]
        ─►  plant.py (JSBSim F-16) : u 로 6자유도 한 스텝 비행
        ─►  judge.py / WEZ         : ATA<12°·500~3000ft 면 데미지, 1000ft 미만이면 패배
```
- 한 경기 = 위 루프를 제어 20Hz(0.05초)로 반복, BT 결정은 10Hz(0.1초)마다.
- 전술의 *의미*는 [TACTIC_SPEC](../new_match_engine/TACTIC_SPEC.md), guidance 공식은 학생용/아키텍처 문서.

---

# 7부 — 직접 보기 / 재현

```bash
# 우리 BT(TreePolicy) vs 적 .yaml — canonical 평가 (beam 시작)
python new_match_engine/bt/run_match.py ace        # ace 와 1경기 (replay+report 저장)
python new_match_engine/bt/run_match.py            # 4적(simple/aggressive/defensive/ace)

# 결정 로직 자체를 읽기
#   bt/tree_policy.py  (select = 이 문서 5부)
#   bt/policy_value.pkl (학습 조각 = 4.2)
```
- 매 경기 `replays/pol_*/` 에 `match.acmi`(Tacview) + `report.txt`(7층 분석) + `plot.png` 저장.

---

# 8부 — 한계와 다음 (정직)

| # | 한계 | 비고 |
|---|---|---|
| H1 | 규칙 4개의 임계값(2500/40/130/9000/4500/2800/45…)은 *계측으로 손튜닝* | 데이터 기반 재도출 여지 |
| H2 | 학습 조각은 오프라인 데이터 분포에 의존 | 새 적/상황엔 일반화 한계 |
| H3 | head-on 래치는 *spawn 기반* | 비정면 spawn 의 정면 전개는 별도 |
| H4 | `policy_value.pkl` 바이너리 의존(canonical 전용) | bridge(--backend)는 이걸 안 씀(적·우리 둘 다 .yaml 가능) |

> 더 깊은 동작 원리: [학생용 입문서](NEW_ENGINE_STUDENT_GUIDE.md) · [아키텍처](NEW_ENGINE_ARCHITECTURE.md) ·
> 제어( Tactic→비행 ): [LQR 리포트](NEW_ENGINE_LQR_CONTROL_REPORT.md).
