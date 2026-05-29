# R15-K 가설 누적 (3D 시각화 분석 기반)

## 매치 패턴 그룹 (3D trajectory 관찰)

### Pattern A: co-centric 2-circle scissors
- **예**: v7 (+7.3 dmg, 41 WEZ ticks)
- 양쪽 같은 중심의 큰 원 회전, phase difference 만 다름
- ATA 가끔 0°로 spike (fire window) → 짧은 catch 가능
- turn rate 동일 → sustained track 불가

### Pattern B: offset spiral (다른 중심)
- **예**: v51 (0/0, 0 WEZ ticks)
- 두 비행기 다른 중심 spiral → 절대 합치지 않음
- dist 최소 3000ft → WEZ 진입 불가

### Pattern C: linear mutual extend
- **예**: defensive (0/0, 0 WEZ ticks)
- 둘 다 직선 도주, dist 2000→14000ft 단조 증가
- ATA 12° 잘 잡히지만 dist 멀어 WEZ 안 됨

### Pattern D: inside-outside lane
- **예**: ace (baseline +21, H10 깨짐)
- 적이 inner circle (smaller radius), 우리 outer
- ace 가 1-circle 진입 → 우리 lag lane 형성

---

## K 가설 (누적 — 매치 분석 후 일괄 실험)

### K1 — vertical 비대칭 강제 (Pattern A/B 깨기)
- **조건**: sustained scissors detect (40 tick 양측 ATA 60-120 + 양 omega 비슷)
- **action**: alt=4 (max climb) 또는 alt=0 (max dive) 30 tick lock
- **목적**: vertical separation → spiral 진입 강제 → 평면 mirror 깸
- **근거**: 2-circle race 평형은 vertical 비대칭으로 깰 수 있음

### K2 — corner speed lock-in (1-circle 진입, Pattern D 대응)
- **조건**: us pursuing (Off_TC/Off_Lag) + opp turning hard
- **action**: vel=3 (corner speed Mach 0.7 매칭, turn rate 최대) → tight radius
- **목적**: ace inner-circle 매칭, 우리 lag → catch 진입
- **근거**: F-16 corner speed 정확 매칭 시 turn radius 최소

### K3 — cut-off prediction (Pattern C 깨기)
- **조건**: linear opp 감지 (closure 절대값 < 30 + 10 tick 추세 dist 증가 + alt_gap < 500)
- **action**: cut-off lead-turn (적 미래 30° 앞 점으로 hdg commit)
- **목적**: defensive 같은 도주 opp catch
- **근거**: lead pursuit 의 standard. 우리 OffensivePursuit 가 이미 일부 함

### K4 — split-S maneuver 한번 (2-circle break, Pattern A 대응)
- **조건**: 40+ tick 같은 sub_sit 유지 + 우리 dmg=0
- **action**: split-S 강제 — alt=0 (dive max) + hdg flip (현재 반대 방향) + vel=4, 15 tick lock
- **목적**: 적과 다른 plane → adv lock 깨짐 → 재진입
- **근거**: classical scissors break maneuver

---

## 추가 매치 분석 — 13 매치 패턴 그룹 최종 (R15-J3)

### Pattern A — co-centric 2-circle scissors (catch 가능)
| Opp | WEZ ticks | dmg | 비율 (dmg/WEZ) |
|---|---|---|---|
| v11_code | 68 | 11.3 | 0.166 |
| v6h5a | 54 | 8.0 | 0.148 |
| simple | 48 | 5.4 | 0.113 |
| v7 | 41 | 7.3 | 0.178 |
- 양쪽 *같은 중심* 큰 원, phase difference 만 다름
- 매번 phase 일치 시 ATA 0° spike → fire window
- **약점**: 적이 fire 중 빠르게 escape — dmg/tick 비율 0.11-0.18 (max 25 HP/s 의 1-2%)
- **개선 여지**: catch 능력은 있음, fire dwell time 늘리면 효과적

### Pattern A' — figure-8 lemniscate (phase 차이 결정)
| Opp | WEZ ticks | dmg |
|---|---|---|
| v9 | 34 | 7.0 |
| v6 | 17 | 2.0 |
| v6h4 | 17 | 2.0 |
| v10 | **0** | 0 |
- 두 비행기 ∞ 패턴, phase difference 가 catch 능력 결정
- v10 처럼 phase 항상 반대 → 절대 catch 못함

### Pattern B — offset spiral (catch 불가능)
- v51 (0 WEZ, 0 dmg)
- 두 비행기 *다른 중심* spiral → 절대 합치지 않음, dist 최소 3000ft+

### Pattern C — linear mutual extend (catch 불가능)
- defensive (0 WEZ, 0 dmg) — 북쪽 직선 도주
- aggressive (0 WEZ, 0 dmg) — 동쪽 직선 도주
- ATA=12° 잡혔지만 dist 가 18000ft 까지 단조 증가

### Pattern D — inside-outside lane
- ace H10 (0 WEZ, 0 dmg) — H10 에서 catch 손실
- ace baseline (+21 dmg) — inner lane 진입했었음

### Pattern E — 미확정
- v6h5b (0 WEZ in H10, 25.3 dmg in H9, 0.1 in baseline) — 가설별 큰 변동

---

## K 가설 갱신 (시각화 기반 정밀화)

### K1 — vertical asym break (Pattern A/A' 의 catch ratio 향상)
- **목적**: WEZ ticks 가 있지만 dwell 짧은 매치 (v7/v11_code) 의 fire 시간 늘리기
- **조건**: 최근 30 tick 평균 ATA 가 sinusoidal (spike 빈번) + WEZ 진입 적
- **action**: 우리 alt commit 비대칭 — 10 tick climb (alt=4) + 10 tick dive (alt=0) 교대 → vertical separation → high yo-yo 진입 시 sustained ATA lock

### K2 — figure-8 phase shift (Pattern A' v10 같은 case)
- **목적**: phase 항상 반대인 case 깨기 (v10)
- **조건**: 60 tick figure-8 detect (ATA 0° spike 없음 + dist oscillation 큼)
- **action**: 우리 turn 일시 정지 — vel=4 hdg=4 직진 8 tick → phase 90° shift → 재 entry 시 alignment

### K3 — cut-off linear (Pattern C defensive/aggressive)
- **목적**: 직선 도주 catch
- **조건**: 15 tick |closure| < 30 + dist > 3000 + |alt_gap| < 500 + |ATA - 적정 lead| < 30
- **action**: hdg=4 ± 2 (적 적정 lead angle) + vel=4 + alt=2 lock 20 tick → cut-off path

### K4 — vertical commit (Pattern B offset spiral v51)
- **목적**: 절대 정렬 안 되는 offset spiral 깨기
- **조건**: 60 tick |closure| 작 + dist 변화 작 + ATA 50+ 평균
- **action**: alt=4 lock 25 tick (climb high) → 위에서 dive → 적 plane 침입

### K5 — fire dwell maximize (모든 catch 매치의 ratio 향상)
- **목적**: ATA 0° lock 됐을 때 fire continuous
- **조건**: ATA < 12 + 직전 5 tick 연속 ATA < 25 + 500 < dist < 2500
- **action**: ALL ACTION LOCK 10 tick (alt/hdg/vel 변경 금지) — 우리 trajectory 안정 → fire dwell 증가

### K6 — Pattern D inner-lane 진입 (ace catch 회복)
- **목적**: ace baseline +21 dmg 회복
- **조건**: opp 우리보다 inside (적 turn radius 작음, omega_opp > omega_us)
- **action**: 우리 vel=1-2 decrease (corner speed 미만 → turn radius 줄임) → inside 진입

---

## v2 도구 통찰 추가 (2026-05-29)

v2 도구 14 panel 로 매치 상세 본 결과:

### v11_code (최고 catch 가능: 68 dwell, +11.3 dmg)
- **CAS 200-450 kts oscillation** — corner speed (450) 자주 미달 → 그 순간 turn rate 부족 → 적이 escape
- **omega 양쪽 mirror** — turn rate 매우 동기화
- **Es 양쪽 동등** — 에너지 차이 없음
- WEZ dwell max 30 ticks (3초), mean ~22 ticks
- **K5 (fire dwell)** 핵심: dwell time 안정 시 catch ratio 향상

### ace (H10 catch 손실: 0 dwell, 0 dmg)
- **HDG 양쪽 반대 부호** — 우리 -1500° 누적 vs ace +2000° — 즉 2-circle flow (양쪽 반대 회전)
- **alt 큰 변화** (4500→7500m) — ace 가 vertical 활용
- center_dist 240m (가까움), R 0.96 (거의 같음) — A_co_centric 자동 분류
- **dwell 0 ticks** 인데 dist 0-9000 oscillation 빈번 (정렬 안 됨)
- **K1 (vertical asym)** + **K2 (phase shift)** 가 ace 회복 핵심

### v51 (B_offset_spiral: 0 dwell)
- Top-down 보면 두 항공기 *완전 다른 위치 spiral*
- HDG 양쪽 같은 방향 turn but offset 으로 인해 절대 안 합쳐짐
- alt 거의 동일 (4500-5000m) — vertical 차이 없음
- **K4 (vertical commit)** 직접 적용 — alt 분리 후 dive 진입

### v7 (자동 분류 C_linear_extend, 실제 41 dwell)
- 자동 분류 오류: dist late_mean > 1.5x early 일 때만 C 분류했는데 v7 의 large amplitude oscillation 도 trigger
- **분류 알고리즘 개선 필요**: trend 가 monotonic 인지 (slope sign 일정성) 추가 체크 필요

---

## v2 기반 K 가설 갱신 (정밀화)

### K1 (재정의) — vertical asymmetric break (Pattern A/A'/B 공통)
- **목적**: alt 거의 동일 → 우리만 climb/dive 분리 → 적 plane 변경 → spiral disruption
- **조건**: |our_alt - opp_alt| < 200m + 50 tick stuck stalemate
- **action**: 25 tick alt=4 lock (max climb) → 다음 25 tick alt=0 lock (dive) → high yoyo

### K2 — phase shift (Pattern A' + A figure-8/scissors)
- **목적**: HDG 동기화 깨기 (mirror omega 끝내기)
- **조건**: phase_diff std < 30° AND 40 tick 유지 (양쪽 fully synced turn)
- **action**: 10 tick hdg=4 (직진 turn 정지) + vel=4 → 적 phase 만 앞으로 → 90° phase shift

### K3 — cut-off linear (Pattern C 확정 — defensive/aggressive)
- **목적**: monotonic 도주 catch
- **조건**: 15 tick 모두 |closure| < 30 AND dist slope > 50 ft/tick AND |alt_gap| < 500
- **action**: hdg=4±3 (적 lead angle) + alt=2 + vel=4 + 30 tick lock → cut-off path

### K4 — vertical force open (Pattern B offset spiral — v51)
- **목적**: offset spiral 깨기
- **조건**: B_offset 자동 분류 OR (30 tick dist std < 1000 AND ATA mean > 60)
- **action**: alt=4 lock 40 tick (high climb) → 그 후 alt=0 lock 15 tick (dive into) → dive into opp plane

### K5 — fire dwell maximize (모든 catch 매치)
- **목적**: WEZ dwell duration 늘리기 (현 3초 max → 5+초 목표)
- **조건**: ATA<12 + WEZ dist + 직전 5 tick 연속 (확정 catch)
- **action**: ALL ACTION LOCK 15 tick (alt/hdg/vel 변경 금지) → fire dwell + 적 escape 따라가지 않음
- 추가: ata<12 시 vel=3 (corner speed 매칭) → turn rate 최대 lock

### K6 — corner speed lock-in (모든 turn fight)
- **목적**: CAS 200-450 oscillation 막기 (corner speed 유지)
- **조건**: |CAS - 450| > 100 + (sub_sit == Lufbery OR NeutralMerge)
- **action**: 우리 vel adjust — CAS < 400 시 vel=4 (가속) / CAS > 500 시 vel=2 (감속) → 450 유지

### K7 — dive-attack trigger (Es advantage 활용)
- **목적**: K1 climb 후 dive 정확 timing
- **조건**: Es_us - Es_opp > 500m AND opp_alt < our_alt - 300m
- **action**: alt=0 lock + vel=4 + hdg=lead → dive attack

---

## 실험 계획 (갱신)

각 K1-K7 을 격리된 if-then 으로 추가 → H10 baseline 위에 누적 → 20 opps 한번에 측정. 비교 baseline = H10 best (+84.5 net).
K1-K7 모두 활성 시 결과 측정 후, 각각 비활성 toggle 로 individual effect 측정 (ablation).

---

## R15-J10/J11/J12 결과 — Ablation + Combination + Noise 분석

### J10 — Individual K Ablation (1 run each)
| KS | deal | taken | net |
|---|---|---|---|
| K5 only | 117.4 | 40.6 | +76.8 (high variance) |
| K1 only | 102.5 | 53.5 | +49.0 (catch 많지만 taken 큼) |
| K2 only | 84.1 | 1.0 | +83.1 |
| K3 only | 71.3 | 0.9 | +70.4 |
| K7 only | 47.7 | 1.0 | +46.7 |
| K4 only | 29.4 | 58.2 | **-28.8** (역효과) |
| NONE | 73.7 | 0.9 | +72.8 (H10 baseline) |
| ALL | 0.8 | 0.4 | +0.4 (K들 충돌) |

### J11 — Combination (1 run)
- K3 single +84.9 (이번 lucky)
- 조합은 모두 단일 K 보다 떨어짐 (충돌)

### J12 — Noise verification (3 runs each)
| setting | deal mean ± std | taken mean ± std | net mean |
|---|---|---|---|
| NONE | 67.0 ± 1.9 | 0.9 ± 0.1 | +66.1 |
| **K2** | **76.8 ± 11.9** | **0.9 ± 0.2** | **+75.9** ⭐ |
| K3 | 68.1 ± 14.6 | 0.9 ± 0.0 | +67.2 |
| K5 | 103.1 ± 25.7 | 37.3 ± 9.9 | +65.8 |
| K3,K5 | 115.4 ± 8.9 | 43.4 ± 6.5 | +71.9 |

### 최종 선정: K2 only (default)
- **R15_J8_KS="K2"** 환경변수 default
- K1/K3/K4/K5/K7 disabled (mean 효과 없거나 high variance)
- K6 cost bias 유지
- H10 force_OffensivePursuit 유지 (NONE baseline)

### 남은 stalemate (8 opps, Pattern B/C/D)
defensive, aggressive, ace, v6h5a (가끔), v6h5b, v6h_e1c, v10, v51

이들은 본질적 limit — action bin (5×9×5) 의 representation 한계, opp BT 특수 패턴.


