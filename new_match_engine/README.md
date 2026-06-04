# F-16 투명·인용가능 제어 연구 스택 (LQR / NDI)

> **목적**: 매치 엔진(`.pyd` RNN/AIPILOT)과 **분리된** 별도 연구 스택. BT가 주는 고수준
> setpoint(heading / altitude / speed)를, **블랙박스가 아닌 모델기반·결정론·인용가능**한
> 저수준 제어기(gain-scheduled LQR, 필요시 NDI)로 비행시킨다.
> 학습 정책(RNN)의 두 결함 — **(a) 비해석성, (b) 불확실 시 평균 수렴(mode-averaging)** — 을
> 제거하고, 안정성을 **수식으로 증명**하며 교과서로 **인용**한다.

## 왜 이 스택인가 (설계 동기)

| RNN 저수준의 문제 | 본 스택의 답 |
|---|---|
| 왜 그렇게 움직이는지 설명 불가 | LQR 게인 K가 숫자로 명시 + 안정성(고유값/마진) 증명 |
| 불확실 시 평균 기동으로 뭉갬 | setpoint당 **결정론적 유일 응답** |
| §10 감속 불가(throttle 바닥) | throttle을 제어입력으로 → 속도 setpoint = 감속 명령 |
| §10 좌우 비대칭(−13/+10) → 진영 불균형 | 대칭 오차피드백 → 좌우 대칭 (진영 무관) |
| 엔진 재학습 시 BT 재튜닝 | 제어법칙이 모델기반이라 재학습 불필요 |

## Plant 선택 — JSBSim 그 자체

AeroBench(다른 F-16 plant)·f16-flight-dynamics(GPL, plant만)와 달리 **standalone JSBSim
(`pip jsbsim 1.3.0`) + 로컬 F-16 XML**(native FLCS 포함)을 plant로 쓴다.
- **인용 그대로 성립**: *"The model runs in JSBSim, open-source software generally considered
  very accurate for modeling aerodynamics [15][16]."*
- 매치 엔진과 **같은 공력 계열** → 추후 제어기 이식 시 sim-to-sim gap 최소.
- LGPL (GPL보다 관대).

## 아키텍처

```
BT (고수준 전술 결정)
   │  Tactic enum (13개: LEAD_PURSUIT, GUN_TRACK, ONE_CIRCLE, SCISSORS …)
   ▼
guidance.py  (tactic + obs → ψ*, h*, V*)       ← 연속 setpoint 산출
   │  단위: 도/ft/kts  (TACTIC_SPEC.md §0 기준)
   │  GUN_TRACK: PN guidance (LOS rate 기반, gedeschaines/propNav 참조)
   │  LEAD_PURSUIT: Deviated Pure Pursuit (AIAA JGCD 2018)
   ▼
autopilot.py (단위 변환 전담: kts/ft/deg ↔ fps/ft/rad)
   │  x_star 구성 → gain-scheduled LQR.command(x, x_star)
   ▼  내부루프  gain-scheduled LQR   u = −K(q̄,α)·(x − x*)
   │      (BFM 극한서 LQR 부족하면 내부루프만 NDI/INDI 승급)
   ▼
JSBSim F-16 (6-DOF, native FLCS 안정성증강 포함)
```

## 모듈

| 파일 | 역할 | 상태 |
|---|---|---|
| `control/tactic.py` | Tactic enum 13개 + 모든 상수 (단위 단일 진실) | ✅ |
| `control/guidance.py` | tactic → (ψ\*,h\*,V\*) setpoint 계산 | ✅ |
| `control/plant.py` | JSBSim F-16 래퍼 — load/trim/step/state/input | ✅ |
| `control/linearize.py` | 운영점 (A,B) 유한차분 + 고전 모드 검증 | ✅ |
| `control/lqr.py` | scipy ARE → K, gain-scheduled 3×3 빌드 | ✅ |
| `control/autopilot.py` | 단위 변환 + x_star 구성 + LQR 실행 루프 | 🔄 구현 중 |
| `control/verify.py` | 안정성 증명 + step 응답 | ⏳ |
| `TACTIC_SPEC.md` | 단위·부호·setpoint 공식 명세 (single source of truth) | ✅ |

## 설계점 스케줄 (LQR)

- 스케줄 변수: **동압 q̄ (또는 Mach) × 받음각 α (또는 고도)**
- 격자 예: Mach {0.4, 0.6, 0.8} × alt {5k, 15k, 25k} ft
- 각 점: JSBSim trim → 유한차분 (A,B) → `solve_continuous_are(A,B,Q,R)` → K
- 런타임: 현재 (q̄, α)로 인접 K 보간

## 검증 (증명 + 경험)

- **형식적**: 점별 closed-loop 고유값 좌반평면, gain/phase margin → 안정성 증명
- **경험적**: step 응답(heading/alt/speed), 그리고 매치 엔진 이식 후 `probe_bt_rnn_map`로
  §10-등가 매핑이 **선형·대칭·감속가능**해졌는지 확인

## 인용 (citation set)

- B. L. Stevens, F. L. Lewis, E. N. Johnson, *Aircraft Control and Simulation*, 3rd ed., Wiley
  — F-16 비선형 모델 + LQR 설계 (교과서 표준)
- JSBSim (LGPL) — 공력 모델 plant
- (NDI 승급 시) Enns et al. 1994; Bordignon & Bacon 2002 (X-35B); INDI survey 2025

## 인용 (citation set)

- B. L. Stevens, F. L. Lewis, E. N. Johnson, *Aircraft Control and Simulation*, 3rd ed., Wiley — F-16 LQR
- JSBSim (LGPL) — 공력 plant
- gedeschaines/propNav (Python) — PN guidance 패턴 참조
- Zarchan, *Tactical and Strategic Missile Guidance*, AIAA 1990 — PN 이론
- Palumbo et al., JHU APL Technical Digest 2010 — LOS rate, APPN
- Kim & Bhattacharya, AIAA JGCD 2018 — Deviated Pure Pursuit (LEAD_PURSUIT)
- NAVAIR 00-80T-105 — BFM 교범 (Yoyo, Scissors, Lag Disp. Roll)
- AFTTP 3-3.F-16 — Gun Employment, Circle Fight
- (NDI 승급 시) Bordignon & Bacon 2002 (X-35B); INDI survey 2025

## 현황

- [x] plant.py — JSBSim F-16 load/trim/step + first-light 검증
- [x] linearize.py — (A,B) + phugoid/dutch-roll 모드 검증
- [x] lqr.py — 단일점 K + 3×3 gain-scheduled (9점 전부 stable)
- [x] tactic.py — Tactic enum 13개 + 상수
- [x] guidance.py — 전 tactic setpoint 계산 + 단위 검증
- [ ] **autopilot.py** — 단위 변환 + LQR 실행 루프  ← 현재
- [ ] verify.py — 안정성 증명 + step 응답
- [ ] guidance.py GUN_TRACK: PN 고도화 (현재 heuristic)
- [ ] NDI 승급 (조건부)
