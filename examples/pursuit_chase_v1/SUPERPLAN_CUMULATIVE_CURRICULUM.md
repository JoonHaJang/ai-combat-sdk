# SUPERPLAN — Pursuit_Chase Cumulative Curriculum

> **목적**: `pursuit_chase_v1` 이 PLAN §8 목표 — 모든 heuristic 상대 **100% WIN** (결정적,
> FP 비결정성에 robust) — 을 달성할 때까지, 승패를 abstraction-gap 신호로 삼아 *모델*을
> 점진적으로 고친다.
>
> **작성**: 2026-05-14. 사용자 지시("슈퍼플랜으로 정리 후 진행").

---

## 0. 핵심 원칙

1. **승패 = abstraction-gap 측정 신호.** 모델이 제대로면 기존 BT를 다 이겨야 한다. 못 이기면
   점-질량 ∇V 모형과 실제 JSBSim 도그파이트의 괴리가 그만큼 크다는 뜻 — 그 갭을 찾아 닫는다.
2. **하드코딩 금지 (PLAN §8).** 임계값 땜질이 아니라, 모델이 *놓친 변수/상황/도달못한 상태*를
   찾아 value function·dynamics·branch 구조에 편입한다.
3. **누적 커리큘럼 = 오버피팅 방지 장치.** Stage N 은 상대 {1..N} 전부 100% 유지가 조건.
   이전 상대 회귀 불가 제약이 곧 일반화 강제 함수.
4. **G1 게이트 불변.** 모든 ∇V 변경은 analytic = finite-diff ≤1% 통과해야 한다.
5. **"현재의 틀" 유지.** branch dispatcher + ∇V mode 프레임워크 안에서. LUT 재솔브가 필요한
   dynamics 재작성보다 policy-level 수정 우선.
6. **검증은 별도 프로세스로.** match 는 프로세스 단위 FP 결정성 — `--rounds N` 한 프로세스는
   사실상 2개 결과만 봄. 상대당 ≥5회 *개별 프로세스* 실행.
7. **보고는 짧게, 중간중간.** 큰 덩어리 끝낼 때마다 한 줄. 띵킹 길게 끌지 않음.

---

## 0.5 분기 dispatcher 결정 다이어그램 (우선순위 의존)

분기 수가 4→9로 증가 — 회귀 표면 추적용. 위에서 아래로 first-match.

```mermaid
flowchart TD
    Start([obs, alt_ft, prev_branch]) --> Q1{alt < 1200?}
    Q1 -->|Y| HardDeck[/HardDeck: max climb/]
    Q1 -->|N| Q2{enm_in_wez ∨<br/>ATA>100 ∧ dist<3000?}
    Q2 -->|Y| DefensiveBreak[/DefensiveBreak: max-turn away + decel/]
    Q2 -->|N| Q3{ATA>90 ∧ AA<90 ∧<br/>closure<0 ∧ dist>2000?}
    Q3 -->|Y| TurnAround[/TurnAround: max-turn toward/]
    Q3 -->|N| Q4{ATA<12 ∧ in-WEZ<br/>∧ aligned?}
    Q4 -->|Y| GunEngagement[/GunEngagement: m_2 PN ∇V/]
    Q4 -->|N| Q5{V_p<360 ∨<br/>prev=ER ∧ V_p<400?}
    Q5 -->|Y| EnergyRecovery[/EnergyRecovery: m_4 corner ∇V/]
    Q5 -->|N| Q6{overshoot ∨<br/>cl>150 ∧ dist<2500?}
    Q6 -->|Y| LagPursuit[/LagPursuit: m_5 LDT ∇V/]
    Q6 -->|N| Q7{ATA<45 ∧ AA>100<br/>∧ dist<4000?}
    Q7 -->|Y| OffensivePursuit[/OffensivePursuit: m_2 PN ∇V/]
    Q7 -->|N| Q8{30<ATA<110 ∧<br/>|cl|<200 ∧ dist>2000?}
    Q8 -->|Y| OrbitBreak[/OrbitBreak: pn+corner ∇V/]
    Q8 -->|N| TheoremAdaptive[/TheoremAdaptive: τ-blend + LUT/]
```

**해석**: 안전→위협회피→FP-robust 전환→사격→에너지→오버슈트회복→공격→락탈출→default.
**load-bearing**: EnergyRecovery (simple), TurnAround (defensive), τ-blend (long-range chase).

## 1. Stage 별 계획

| Stage | 누적 상대 집합 | 종료 조건 |
|---|---|---|
| 1 | {simple} | simple 5/5 WIN (별도 프로세스) |
| 2 | {simple, defensive} | 둘 다 5/5 WIN |
| 3 | {simple, defensive, aggressive} | 셋 다 5/5 WIN |
| 4 | + ace | 넷 다 5/5 WIN |
| 5+ | + gen_* 아키타입 (필요 시) | 누적 100% |

**Per-stage 루프**: 진단(어디서·왜 무/패) → 모델 갭 식별 → 모델 수정 → G1 검증 →
누적 집합 전체 재테스트(별도 프로세스) → 100% 면 다음 Stage, 아니면 반복.

---

## 2. 진행 상황

### 완료 (기반)
- RT-1/2/3: 환경·LUT 재생성, dx 부호 버그 수정, `grad_V_1circle`(RT-2), SMT cover/∇V-LUT
  cross-check/STL falsification(RT-3). G1/G2 게이트 통과.
- v11 분기 구조 이식: `OrbitBreak`, `LagPursuit`, `DefensiveBreak` 분기 + 분기 명령을
  ∇V-derived (`optimal_control` mode-τ 매핑, PLAN §2.6.5) 로 전환.

### Stage 1 — vs `simple` ✅ COMPLETE (10W/0L/0D, 별도 프로세스, 전부 결정적)
발견한 모델 abstraction gap 과 수정:

| # | 놓친 것 | 수정 | 상태 |
|---|---|---|---|
| 1 | V_e / closure-nulling — m_2 PN 의 speed objective 가 V_corner(선회속도) 였음 | `grad_V_PN` speed 항 `(V_p−V_c)²` → `(V_p−V_e)²` (적 속도 매칭, WEZ station-keep) | ✅ G1 통과 |
| 2 | 3D ATA — ATA 가 `atan2(dx,dy)` 수평각만, dh 무시 → 고도차 시 "조준됨" 오판 | `grad_V_PN` 에 수직 aim 항 `½·ATA_vert²` (`ATA_vert=atan2(dh,r_xy)`) 추가 → gamma 채널 구동 | ✅ G1 통과 |
| 3 | 위협 예측 — DefensiveBreak 가 `enm_in_wez`(reactive, 이미 피격) 만 | predictive 트리거 추가: `ATA>100° ∧ dist<3000` (적 후방반구+근접, v11 IsLostPursuit) | ✅ |
| 4 | 선회-유도항력 accel cap | `optimal_control` accel cap 시도 → **evidence 기각** (4W2L→1W5D, agent 소극화). revert. | ❌ 기각 |
| 5 | 에너지 관리 부재 — value function 에 "싸울 에너지 확보" 항 없음 → agent 만성 에너지 고갈(V_p~329) → 오버슈트·나쁜 각도 | `EnergyRecovery` 분기 — entry `V_p<360` 히스테리시스(exit>400), command `{corner:1.0}` 순수 직진가속 (Boyd EM). 히스테리시스가 360 chatter 차단 → 버퍼 쌓고 교전 | ✅ |

**vs simple 궤적**: 1W4L → (fix1,2) 3W2L → (fix3) 4W2L → (fix5+hysteresis) **10W0L0D**.
**학습**: 에너지 회복은 *순수 직진*이어야 함 (`{corner:1.0}`). 회복 중 선회 섞으면(`{corner:.6,pn:.4}`) 즉시 재고갈 → 0W6L. 히스테리시스 deadband 필수 (chatter 방지).

---

### Stage 2 — vs `defensive` (진행 중, simple 회귀 없음 유지)

| # | 시도 | 결과 | 채택? |
|---|---|---|---|
| RunDown 분기 | 장거리 도망 추격용 `dist>5000` sprint | simple 10W→2W/4L 회귀 (simple 도 dist 14k 도달 — 거리 임계로 구분 불가) | ❌ revert |
| 6 | `grad_V_PN` speed target 을 dist-의존: 근거리 V_e-매칭 / 원거리 V_sprint(420) | G1 통과. defensive 데미지 0→**2승 100/87 결정적**. simple 6W/0L 유지 | ✅ |
| — | V_e clamp [160,420] | 비-stern 기하서 V_e 추정 폭주(측정 1260kts) 방지. correctness 수정 | ✅ |
| — | EnergyRecovery 진입 게이트 (ata<60 / ata<90 / `ata>90∧closure<0`) | **전부 simple 회귀** — EnergyRecovery 는 simple 에 무조건 필요(load-bearing) | ❌ revert |

**Stage 2 현재**: vs simple 6W/0L/0D 유지 ✅. vs defensive **1~2W / 4~5D / 0L** (패배 없음, 결정적 승은 100/87).
**미해결**: defensive 의 장거리 도망 → 추격 결과가 **FP 시드에 따라 basin 분기** (win basin: distmean 11k 침투 / draw basin: distmean 25k 영영 못 닫음). draw/win seed 는 t70 까지 동일, t70-120 에서 한쪽만 적 향해 turn-around 완료 — τ-blend 의 FP 민감도. single-tick 분기 조건으론 안 잡힘.

## 3. 다음 액션 (Stage 2 미해결 — 더 깊은 접근 필요)
1. 후보 A: 초반 turn-around 를 FP-robust 하게 — 약한 τ-blend 대신 강한 결정적 분기 (TurnAround 분기, AA<90 게이트로 simple-추격 배제). 검증 중.
2. 후보 B: dynamics-level — 점-질량 모델의 turn↔energy 결합 (LUT 재솔브 필요).
3. 후보 C: defensive 의 extend 패턴 자체를 exploit (적이 도망 시작 = 우리에게 free energy/positioning 시간).
4. Stage 2 100% 달성 → Stage 3 ({+aggressive}).
5. 전체 목표 달성 시 → 의미 단위 커밋.

## 4. 알려진 본질적 한계 (future stages 대비)

- **단일-tick 분기 조건의 표현력 한계**: `losing_track`/EnergyRecovery 게이트 시도가
  simple vs defensive 를 클린하게 구분 못 함이 입증됨. 다음 stage 에서 ace/aggressive
  추가 시 같은 패턴 예상 — modal 정보(EIM 적 의도 분류, 다-tick window)가 필요할 가능성.
- **τ-blend 의 FP-민감성**: t70-120 같은 큰 mis-point 에서 약한 PN omega 명령이
  seed-dependent. 결정적 분기(TurnAround 류)로 우회하는 게 현재 접근.
- **점-질량 dynamics 의 turn↔energy 누락**: post-hoc accel-cap 은 agent 소극화로 기각됨.
  근본 해결은 dynamics-level 인데 LUT 재솔브 비용 큼.
