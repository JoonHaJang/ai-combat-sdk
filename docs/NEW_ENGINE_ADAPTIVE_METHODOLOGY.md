# NEW ENGINE — ADAPTIVE 정책 개발 방법론 (통제된 루프)

> 작성 2026-06-13. 목적: dogfight 일반해를 **ADAPTIVE virtual-point** 구조로 도출하되,
> *주먹구구 금지* — 모든 단계가 **분석 → 가정 → 실험 → 검증** 루프로 원인·결론이 파악된
> 상태에서 진행·문서화된다. graphify 적극 사용. ([[mpc-failure-analysis]] 교훈 계승.)

---

## 0. 제1원리 (사용자 지시 2026-06-13)

**ADAPTIVE는 강한 base를 *대체*하지 않는다. base를 ADAPTIVE의 *부분집합(특수해)*으로 포함한다.**

```
ADAPTIVE(obs) = base_vp(obs) + Σ_s w_s(obs) · Δ_s(obs)
   · base_vp     = 현 배포 base(RF argmax → tactic → virtual-point). 검증된 격추기.
   · w_s(obs)    = 상황 s soft 멤버십 (전부 *관측-차* sigmoid, 절대값 금지).
   · Δ_s(obs)    = 상황 s 보정 virtual-point.
   · 불변식:  base-승리 상황에선 w_s = 0  →  ADAPTIVE ≡ base   (★ 부분집합 보장)
```

**전략**: base(부분집합)에서 출발 → 무승부 상황에만 Δ_s 활성 → *부분집합을 점점 넓혀* GOAL(전체집합=
모든 상황 격파)에 수렴. 각 확장은 **base-승리 무회귀**를 검증한 뒤에만 채택.

## 1. 통제된 루프 규율

| 단계 | 규율 |
|---|---|
| 분석 | graphify + 데이터(W/L/D, 클러스터)로 *현상의 원인* 규명. 추측 금지. |
| 가정 | 반증가능한 1문장 가정 (예: "circle 상황에서 Δ=tight-turn이 무승부를 닫는다"). |
| 실험 | 단일변수 격리. canonical neutral beam([[match-canonical-initial-condition]]). replay+report 필수([[feedback-replays-mandatory]]). |
| 검증 | base-승리 무회귀 + 목표 무승부 개선. *원인→결론* 명시. 실패도 기록. |

## 2. 관측-차(상대값) 원칙 (사용자 2026-06-13)

게이트·cost는 **아군–적군 관측 차이의 함수**로만. 절대거리/고도/속도 금지 — *틱-의존·비불변*
(고속이면 같은 거리를 몇 틱에 지남). 데이터 실증: 상황분리 feature 중요도 `dist=0.03`(거의 0).
허용 변수: `tau_s=dist/closure`(time-to-merge), `ata, aa, HCA`(각차), `es_diff, Δvc, Δomega`.

## 3. 데이터-도출 상황 (5개, exp_situation_design)

dagger 12367상태 KMeans silhouette → **5상황**. 분리 feature: hca>ata>aa>closure>es_diff.
- c1 OFFENSIVE/정렬(43%, 격추 잘됨) · c0 중립 · c4 EXTEND · **c2 rate+이탈(19% 무능)** · **c3 2circle rate(37% 무능)**.
- ★ VERTICAL_PURSUIT가 5상황 전부 1위 = base의 정체. 고-regret = c2/c3 = 무승부처(A3 lag-angle, D2 extend).

## 4. 실험 로그 (누적 — 원인·결론)

| ID | 가정 | 결과 | 결론 |
|---|---|---|---|
| held-out(e19) | 8/8이 일반화? | 7승/5격추/2무 | 누수 — in-sample 점수. 무승부=A3,D2 |
| force tactic(C′,e22) | 단일 tactic이 무승부 닫나 | 전부 실패 | tactic선택 문제 아님 |
| relabel(e_relabel) | CANDS+LEAD_TURN 재라벨? | VERTICAL 여전 1위 | on-policy 편향 — per-state라벨 한계 |
| INDI 튜닝(e25) | INDI가 닫나 | C3로 LQR 동등(3격추) 회복, 무승부 여전 | INDI=제어 동등, 무승부 미해결. C3 default 승격 |
| ADAPTIVE v1(e26) | 5상황 blend 대체 | base 격추 상실(회귀) | ★ *대체*가 틀림 → base를 부분집합으로(본 문서 §0) |
| ADAPTIVE v2(e27) | base+게이트보정(무승부 상황만) | ace·C2 격추 보존, **B2 판정→격추 상향**, A3 머지 19.2→13.2km, D2 중립 | ★★ **부분집합 성립 + 확장 작동.** base 무회귀+B2 상향. A3 종결 follow-through만 남음 |

**메타 관찰**: A3/D2 무승부는 lead-turn·tight-turn·재라벨·INDI·blend 전부에 저항. *판정승 상한(genuine ceiling)*
가능성 추적 중 — 단, §0 부분집합 구조로 base 보존하며 재도전.

## 4.5 SOTA 정합 + 우리 차별점 (2026-06-13, 문헌)

전 세계(DARPA ACE/AlphaDogfight, 각국 공군연구소)가 푸는 문제. 최근 연구 대비:
- **계층 구조가 SOTA 정답**: AlphaDogfight 우승(Heron, 인간 5-0)이 *계층 RL*(top 전략선택+bottom 기동). 우리 ADAPTIVE(상황→virtual-point)+LQR/INDI가 동형. (IEEE 9950612, arXiv 2105.00990, H3E 등)
- **robustness 지표=exploitability**(arXiv 2208.05083): 고정적/단순 self-play=과적합(=우리 누수). adversarial 정책에 파국(=우리 C2). 해법=PBT(다양 population+exploiter)+exploitability 측정(frozen 정책에 best-response 적 학습→이기나).
- **non-transitive(Nash)**: 단일정책 전적지배 불가 → A3/D2 교착=게임이론적 ceiling(실패 아님).
- **변하는 복합 상황 처리**: 매 틱 *기하* 재인식(latch·적ID 금지)→독립 decoupled 전문가→soft 선택. = 우리 relational ADAPTIVE 그대로. (latch=C2가 친 곳.)

★ **우리 차별점(사용자 2026-06-13)**: 기존 계층 RL=블랙박스 NN(고성능·*비설명*). 우리 고유제약=**explainability(BT·투명·인용가능, 약속1)** = ACE의 *trust* 목표 직결인데 SOTA NN이 약함. → 기여 = **SOTA급 robustness를 *설명가능* 정책으로**. 모든 ADAPTIVE 결정=읽히는 BFM 규칙(if HCA>90∧not-closing→lead-cutoff).

## 5. 작업 로그

### loop N (완료, exp_e27) — 부분집합 성립 검증 ✅
- 가정: `base + 게이트보정`(무승부 상황만) → base 격추 보존 + 무승부 개선.
- 검증: ace·C2 격추 보존, B2 판정→**격추 상향**, A3 머지 19.2→13.2km(보정 36%), D2 중립. **부분집합 + 확장 작동.**
- 원인: 보정이 offensive/chase(base-승리)엔 8~15%만 발동→base 보존. circle/rate(A3)엔 36% 발동→머지 tighten.

### loop N+1 (완료, exp_e27) — A3 종결 follow-through
- 1차 시도(ata<30→GUN_TRACK)는 *dead code*였음: rate 게이트가 ata>35 요구 → 각 잡히면 게이트 꺼져 gun 분기 도달불가. (방법론이 버그 잡음 — 결과가 E27과 byte-동일.)
- 수정(HCA-only 게이트 → gun 도달가능) 후에도 **A3 여전 무**. 부분집합은 보존(ace/B2/C2 격추).
- **원인 규명(A3 replay)**: min거리 999m(WEZ 914m 바로 밖)·ata 45°·Es 5574 vs 5965(동일)·turnR 2646 vs 2798(동일).
  = **공력대등·동에너지·동반경 = 대칭 교착.** A3 lag-angler가 최종 사격해 거부. **양쪽 다 못 쏨.**
- **결론**: ★ A3 무 = tactic/제어 갭 아님, **neutral beam 대등기체 본질적 대칭 교착 = genuine BFM ceiling.**
  ADAPTIVE는 깰 수 없는 대칭에 막힘. 단 싸움 질을 19km 직진통과→1km 동에너지 선회전으로 근본 개선(advantage 99%).
- ★ 진짜 성과: **부분집합 작동 검증 + B2 판정→격추 상향** = base⊇subset 확장 방향이 옳음.

### loop N+2 (진행, exp_e28) — 전체집합 확장
- 전환: A3/D2(ceiling) 집착 중단. B2 격추 상향이 핵심 신호 → subset+보정이 *전체 17적*의 격추↑·무↓ 내나.
- 실험: ADAPTIVE subset vs base, held-out 9 + 대표 8, 동일 harness(INDI C3). 단일변수=보정 on/off.
- 가정: 부분집합이라 base 무회귀 + 여러 판정/무 → 승/격추 상향. = "부분집합을 넓혀 전체집합으로".

### loop N+2b (완료, exp_e29) — self-play (ADAPTIVE vs base) [사용자 제안]
- base-vs-base=us판정 99:98(거의 교착) / **ADAPTIVE-vs-base=무 0:0**(보정이 강한 대등기체엔 edge 無) / swap=base 미세우위 / **ADAPTIVE-vs-ADAPTIVE=63:99, 37dmg 교환**.
- 통찰: ① ADAPTIVE는 base를 못 이김(scripted엔 격추 만들지만 강한 대등기체엔 X). ② **보정이 *engagement·사격을 생성*** (base-vs-base 죽은교착 vs ADAPTIVE-vs-ADAPTIVE 37dmg). ③ **고분산** — 양쪽 공격적이면 초기 미세비대칭을 큰 결과로 증폭(us 37 맞음).
- 결론: "대칭 교착 ceiling"은 *공격으로 안 깨지고*, 공격하면 *서로 깨져 고분산 교환*. 보정=약/scripted 적엔 유리, 대등공격자엔 노출. **self-play 37dmg 궤적=결함 데이터원**(누가 어디서 노출되나→보정 수정).

### ★★ loop N+2 결과 (완료, exp_e28) — 전체집합 마일스톤
- **base 11승/5격추/6무 → ADAPTIVE 15승/7격추/2무** (+4승 +2격추 −4무).
- 무승부 6→2: A2·aggressive·A1·simple 무→판정. **남은 무 = A3·D2뿐(ceiling 정합).**
- 신규격추 +4(B1·defensive·C3·D1), 격추상실 −2(D3 scissors·ace — 둘 다 고HCA인데 base 이미 격추중→rate게이트 오발동).
- ★ 결론: **base⊆ADAPTIVE 점진확장이 전체집합서 작동**(17중 8 상향). 회귀 2개=부분집합 위반(명확 수정점).

### loop N+3 (완료, 가설 실패) — closure suppressor 역효과
- 가정: rate보정을 "base 닫는중 아닐 때(closure<40)"만 발동 → D3·ace 복구.
- 결과: **ADAPTIVE 11승5격추6무 = base와 동일(전 개선 상실).** D3·ace **복구 실패** + draw전환 4개(A2·aggr·A1·simple) 상실 + E1 신규회귀.
- 결론: **closure는 "base 마무리"의 틀린 판별자.** draw전환은 간헐 closure>40에 억제됨, D3/ace 회귀는 closure 무관(고-HCA 기동 중 cutoff가 base 궤적 방해). → **N+2(15/7/2) 복원 = 현재 최선.** (실패도 데이터: closure 기각.)

### loop N+4 (다음 후보) — D3·ace surgical fix
- 가정: 회귀 판별자 = *recent-WEZ*(최근 base가 ata<12°·WEZ거리 도달했나). 도달중이면(D3·ace 마무리) 보정 억제, 미도달(draw·B1)이면 발동.
- 단 B1(부분 WEZ 39dmg)과 D3/ace(full WEZ) 분리 미묘 — 신호 정밀화 한두 루프 필요 예상.
- 대안: N+2를 *현 최선*으로 받고(2 회귀는 여전히 승), 일반화(더 많은 적·spawn) 또는 commit 우선.
