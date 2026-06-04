# Tactic Enum 명세 (새 매치 엔진)

> **이 문서가 단위·부호·절대/상대의 유일한 진실(single source of truth).**
> 코드 어디서든 전술 관련 수치를 정의할 때 이 문서를 참조하고, 변경 시 이 문서를 먼저 수정한다.

---

## 0. 단위 시스템 (불변 규칙)

코드베이스 기존 관례(`units.py`, `task.py`, `docs §15`) 와 일관:

| 물리량 | 단위 | 비고 |
|---|---|---|
| **각도** | **도(°, degree)** | 라디안은 JSBSim 내부(plant.py)에서만 사용. 경계에서 변환. |
| **heading** | **도(°), 0~360, 진북 기준** | 절대값. 반시계=증가 아님 — 항공 관례(시계방향 증가). |
| **상대 각도** (ATA, AA, HCA, rel_b 등) | **도(°)** | 부호/범위는 아래 §2 별도 정의. |
| **고도** | **피트(ft), MSL** | 절대값. AGL 아님. |
| **속도(칼리브레이티드)** | **노트(kts)** | vc_kts. 단, JSBSim plant 내부는 fps. |
| **거리** | **피트(ft)** | 1 NM 이하 ft, 이상 NM — 표시만. 내부 계산은 ft 단일화. |
| **선회율** | **도/초(°/s)** | 부호: 좌선회=음수(−), 우선회=양수(+). |
| **에너지** | **비에너지 ft** (He = h + v²/2g) | ft 단위. g=32.174 ft/s². |
| **시간** | **초(s)** | tick dt = 0.1s (매치 750틱/75초). |

---

## 1. 입출력 경계 단위 요약

```
JSBSim plant (내부)     LQR / guidance (계산)    BT / obs (외부)
───────────────────     ─────────────────────    ──────────────
alpha, beta : rad   →   rad (내부)           →   deg (출력·로그)
phi, theta  : rad   →   rad (내부)           →   deg
psi         : rad   →   rad (내부)           →   deg 0~360
V           : fps   →   fps (LQR x 벡터)     →   kts (obs/BT)
h           : ft    →   ft                   →   ft
p,q,r       : rad/s →   rad/s                →   deg/s (로그)
aileron 등  : [-1,1] ←  [-1,1] (LQR u)      ←   —
throttle    : [0.2,1.0] ← [0,1] (LQR clamp) ←   —
```

**경계 변환 책임**: `autopilot.py` 가 BT(kts/ft/deg) ↔ LQR(fps/ft/rad) 변환을 전담.
LQR 내부는 순수 fps/ft/rad. BT/guidance는 순수 kts/ft/deg.

---

## 2. 각도 부호·범위 정의 (오해 방지)

| 변수명 | 범위 | 부호 | 절대/상대 | 출처 |
|---|---|---|---|---|
| `heading_deg` | 0~360° | 없음(절대) | **절대** | task.py `% 360.0` |
| `psi_star_deg` | 0~360° | 없음(절대) | **절대** | setpoint — 목표 heading |
| `rel_b` (relative_bearing) | −180~+180° | 우=**+**, 좌=**−** | **상대**(우리 기준) | obs dict §15.3 |
| `ata_deg` | 0~180° | **없음(절대값)** | 상대 | arccos → 항상 ≥0 |
| `aa_deg` | 0~180° | **없음(절대값)** | 상대 | arccos → 항상 ≥0 |
| `omega_opp_signed` | −∞~+∞ °/s | 우=**+**, 좌=**−** | 절대(지구 기준) | §16.4 재구성, 90% |
| `roll_deg` | −180~+180° | 우=**+**, 좌=**−** | **우리 선회방향** | 검증 100% |
| `d_psi` (heading rate) | °/s | 우=**+**, 좌=**−** | 상대 변화율 | LQR 출력 기반 |
| `Δh_ft` (고도 변화 setpoint) | ft | 상승=**+**, 강하=**−** | **상대**(현재 고도 기준) | guidance 출력 |
| `Δv_kts` (속도 변화 setpoint) | kts | 가속=**+**, 감속=**−** | **상대**(현재 속도 기준) | guidance 출력 |

---

## 3. Tactic Enum 정의 (13개 확정)

> **변경 이력**: Immelmann/Split-S 제거 (실전 희소·에너지 비효율 확인),
> SCISSORS 추가 (중립 교착 반전전), LAG_DISPLACEMENT_ROLL 추가 (overshoot 방지 핵심).
> 근거: Wikipedia BFM, The Aviationist (현직 파일럿), NAVAIR 00-80T-105.

```python
class Tactic(IntEnum):
    # ── 공격 계열 ──────────────────────────────────────────────────────
    LEAD_PURSUIT          = 0   # 적 진행방향 앞에 nose — gun solution 준비
    PURE_PURSUIT          = 1   # nose → 현재 적 위치 — closure 유지
    LAG_PURSUIT           = 2   # nose → 적 뒤 — 선회전 유지·에너지 보존
    LAG_DISPLACEMENT_ROLL = 3   # overshoot 직전 lift-vector 이탈 — 포지션 유지·에너지 최소 손실
    GUN_TRACK             = 4   # ATA < 20°, WEZ 내 — 연속 정밀 lead angle
    # ── 중립 선회 계열 ─────────────────────────────────────────────────
    ONE_CIRCLE            = 5   # 양측 반대 방향 선회 (angles fight)
    TWO_CIRCLE            = 6   # 양측 같은 방향 선회 (radius fight)
    SCISSORS              = 7   # overshoot 교착 → 반전 반복 (방향전환 속도 승부)
    # ── 수직 계열 ──────────────────────────────────────────────────────
    HIGH_YOYO             = 8   # 에너지 과잉·overshoot → 상승+감속, 선회전 유지
    LOW_YOYO              = 9   # closure 부족·에너지 저하 → 강하+가속, 선회전 유지
    # ── 방어 계열 ──────────────────────────────────────────────────────
    BREAK_TURN            = 10  # max-G defensive break 90° — WEZ 이탈
    EXTENSION             = 11  # 이탈 직진 — 에너지 회복, 속도 최대
    # ── 기본/전환 ──────────────────────────────────────────────────────
    LEVEL_FLIGHT          = 12  # 전환·초기화·기본값
```

### 제거된 항목 (사유 기록)

| 기동 | 제거 사유 |
|---|---|
| `IMMELMANN` | 실전 희소. 정상에서 속도 급감 → 취약. HIGH_YOYO + ONE_CIRCLE로 커버 가능 |
| `SPLIT_S` | Wikipedia: "rarely a viable option in combat" — 운동+위치에너지 이중 손실 |

---

## 4. 각 Tactic 상세 명세

### 공통 setpoint 포맷

```
setpoint = (
    psi_star_deg : float,   # 목표 heading, 0~360°, 절대
    h_star_ft    : float,   # 목표 고도, ft MSL, 절대
    v_star_kts   : float,   # 목표 속도 (vc), kts, 절대
)
```

> **절대값 setpoint** — guidance가 매 tick 재계산. BT는 tactic만 선택,
> 구체 수치는 guidance 계층이 현재 obs geometry에서 자동 산출.

---

### 4.0 LEAD_PURSUIT

**BFM 교범**: NAVAIR 00-80T-105 §4-3 "Lead Pursuit"

| 항목 | 값 / 식 | 단위 | 절대/상대 |
|---|---|---|---|
| `psi_star` | `heading_deg + lead_angle(ata, dist, v_closure)` | ° | 절대 |
| `h_star` | 현재 고도 (유지) | ft | 절대 |
| `v_star` | `min(v_max_kts, vc_kts + 20)` — 접근 유지 | kts | 절대 |
| `lead_angle` 계산 | `arcsin(v_target * sin(ata) / v_bullet)` ← 간략화: `ata * 0.3` | ° | 상대 |

**진입 조건**: `pos_adv > 0` (aa > ata) AND `dist_ft < 6000` AND `ata_deg < 45`

---

### 4.1 PURE_PURSUIT

**BFM 교범**: NAVAIR 00-80T-105 §4-2 "Pure Pursuit"

| 항목 | 값 / 식 | 단위 | 절대/상대 |
|---|---|---|---|
| `psi_star` | `heading_deg + rel_b` (적 방향으로 직접) | ° | 절대 |
| `h_star` | 현재 고도 | ft | 절대 |
| `v_star` | `vc_kts` (유지) | kts | 절대 |

**진입 조건**: `ata_deg < 30` AND `closure_kts > 0` AND `dist_ft > 1500`

---

### 4.2 LAG_PURSUIT

**BFM 교범**: NAVAIR 00-80T-105 §4-4 "Lag Pursuit"

| 항목 | 값 / 식 | 단위 | 절대/상대 |
|---|---|---|---|
| `psi_star` | `heading_deg + rel_b * 0.5` (lag — 반만 선회) | ° | 절대 |
| `h_star` | 적 고도 − 500 ft (약간 낮게 — 에너지 이득) | ft | 절대 |
| `v_star` | `vc_kts` (유지) | kts | 절대 |

**진입 조건**: `pos_adv > 30°` AND `omega_opp_signed` 큰 경우 (적 강선회 중)

---

### 4.3 LAG_DISPLACEMENT_ROLL

**BFM 교범**: Wikipedia BFM "Lag Displacement Roll", NAVAIR 00-80T-105 §5 (Offensive BFM)
**실전 빈도**: Offensive BFM 핵심 기동 — overshoot 방지에서 가장 자주 사용

| 항목 | 값 / 식 | 단위 | 절대/상대 |
|---|---|---|---|
| `psi_star` | `heading_deg + sign(rel_b) * 120` — lift-vector를 적 후방으로 | ° | 절대 |
| `h_star` | `h_cur_ft + 1500 * sign(rel_b_vertical)` — 수직면 이탈 | ft | 절대 |
| `v_star` | `vc_kts` (유지 — 에너지 손실 최소가 목적) | kts | 절대 |
| `sign(rel_b_vertical)` | 적보다 높으면 +1(상승 유지), 낮으면 −1(강하 회피) | — | 상대 |

**진입 조건**: overshoot 임박 — `aa_deg < ata_deg` (우리 nose가 적을 지남) AND `closure_kts > 50`
**vs LAG_PURSUIT 차이**: LAG_PURSUIT는 선회전 유지(지속적), LAG_DISPLACEMENT_ROLL은 **overshoot 순간 이탈**(일시적 geometry 수정)

---

### 4.4 GUN_TRACK

**BFM 교범**: AFTTP 3-3.F-16 §9 "Gun Employment"
**현재 BT 미구현 — 이것이 5×9×5 분해능 한계 직격 사례**

| 항목 | 값 / 식 | 단위 | 절대/상대 |
|---|---|---|---|
| `psi_star` | 매 tick 연속 갱신: `heading_deg + ata_signed + lead_correction` | ° | 절대 |
| `h_star` | 적 고도 (맞춤) | ft | 절대 |
| `v_star` | `vc_kts − 10` (약간 감속 — 오버슈트 방지) | kts | 절대 |
| `ata_signed` | `ata_deg * sign(rel_b)` | ° | 상대·부호있음 |
| `lead_correction` | `omega_opp_signed * tau_s * 0.5` (적 선회 예측) | ° | 상대 |
| WEZ 조건 | `ata_deg < 12` AND `500 ft < dist_ft < 3000 ft` | — | 엔진 규칙(§11) |

**진입 조건**: `ata_deg < 20` AND `dist_ft < 3000`

---

### 4.5 ONE_CIRCLE

**BFM 교범**: AFTTP 3-3 §6 "One-Circle Flow / Angles Fight"

| 항목 | 값 / 식 | 단위 | 절대/상대 |
|---|---|---|---|
| `psi_star` | 적 선회 **반대** 방향으로 선회. `heading_deg − sign(omega_opp_signed) * 90` | ° | 절대 |
| `h_star` | 현재 고도 | ft | 절대 |
| `v_star` | 에너지 보존: `max(vc_kts, v_corner_kts)` | kts | 절대 |
| `v_corner_kts` | F-16 코너속도 ≈ 320 kts (고정 상수) | kts | 절대 |

**핵심**: `sign(omega_opp_signed)` 사용 → **진영 무관** (§16.4)
**진입 조건**: 양측 반대 방향 선회: `sign(roll_deg) ≠ sign(omega_opp_signed)` (우리 선회 ≠ 적 선회 방향)

---

### 4.6 TWO_CIRCLE

**BFM 교범**: AFTTP 3-3 §7 "Two-Circle Flow / Radius Fight"

| 항목 | 값 / 식 | 단위 | 절대/상대 |
|---|---|---|---|
| `psi_star` | 적 선회 **같은** 방향. `heading_deg + sign(omega_opp_signed) * 90` | ° | 절대 |
| `h_star` | 현재 고도 | ft | 절대 |
| `v_star` | `v_corner_kts` (320 kts) — 최소 선회 반경 | kts | 절대 |

**핵심**: 마찬가지로 `sign(omega_opp_signed)` → 진영 무관
**진입 조건**: 양측 같은 방향: `sign(roll_deg) == sign(omega_opp_signed)`

---

### 4.7 SCISSORS

**BFM 교범**: NAVAIR 00-80T-105 §5-6 "Scissors", Wikipedia BFM "Defensive Scissors"
**실전 빈도**: 중립 선회전 교착 시 핵심 — ONE/TWO_CIRCLE이 overshoot 교착에 빠질 때 진입

| 항목 | 값 / 식 | 단위 | 절대/상대 |
|---|---|---|---|
| `psi_star` | 매 tick 반전 감지 시 방향 전환: `heading_deg + reversal_sign * 60` | ° | 절대 |
| `reversal_sign` | `+1` 또는 `−1`, overshoot 감지(`aa_deg < ata_deg`)마다 반전 | — | 상태 유지 |
| `h_star` | 고도 여유 있으면(`h_ft > HARD_DECK_FT + 3000`): `±1000ft` 교대 (수직 scissors) | ft | 절대 |
| `h_star` | 고도 여유 없으면: 현재 고도 유지 (수평 scissors) | ft | 절대 |
| `v_star` | `V_CORNER_KTS` (320 kts) — 반전 능력 최대화 | kts | 절대 |

**진입 조건**: ONE/TWO_CIRCLE 중 `aa_deg < ata_deg` 반복 발생 (overshoot 교착)
**vs ONE/TWO_CIRCLE 차이**: circle은 단방향 지속, scissors는 **반전 반복** — heading이 진동함
**이기는 조건**: 더 빠른 방향 전환 능력 (corner speed 유지가 관건)

---

### 4.8 HIGH_YOYO

**BFM 교범**: NAVAIR 00-80T-105 §5-2 "High Yo-Yo"

| 항목 | 값 / 식 | 단위 | 절대/상대 |
|---|---|---|---|
| `psi_star` | 현재 heading 유지 (상승 중엔 heading 변화 최소화) | ° | 절대 |
| `h_star` | `h_cur_ft + 3000` (상승 목표) | ft | 절대 |
| `v_star` | `vc_kts − 40` (감속, 에너지→고도 전환) | kts | 절대 |
| `Δh` (상대 표현) | `+3000 ft` | ft | **상대** (현재 고도 기준) |

**진입 조건**: overshoot 위험 (`aa_deg < 30` AND `ata_deg > 30`) OR 에너지 과잉 (`vc_kts > 420`)

---

### 4.9 LOW_YOYO

**BFM 교범**: NAVAIR 00-80T-105 §5-3 "Low Yo-Yo"

| 항목 | 값 / 식 | 단위 | 절대/상대 |
|---|---|---|---|
| `psi_star` | 현재 heading 유지 | ° | 절대 |
| `h_star` | `h_cur_ft − 2000` (강하 목표) | ft | 절대 |
| `v_star` | `vc_kts + 40` (가속, 고도→에너지) | kts | 절대 |
| `Δh` (상대 표현) | `−2000 ft` | ft | **상대** |

**진입 조건**: closure 부족 (`closure_kts < 0`) AND 에너지 부족 (`vc_kts < 280`)

---

### 4.10 BREAK_TURN

**BFM 교범**: AFTTP 3-3 §8 "Defensive Break Turn"

| 항목 | 값 / 식 | 단위 | 절대/상대 |
|---|---|---|---|
| `psi_star` | `heading_deg + 90 * sign_break` | ° | 절대 |
| `sign_break` | `−sign(rel_b)` — 적 반대방향으로 break | — | rel_b 기반 |
| `h_star` | 현재 고도 | ft | 절대 |
| `v_star` | `v_corner_kts` (320 kts) — max-G 조건 | kts | 절대 |

**진입 조건**: 적이 WEZ 근접 — `aa_deg < 30` AND `dist_ft < 3000` AND `closure_kts > 100`

---

### 4.11 EXTENSION

**BFM 교범**: AFTTP 3-3 §10 "Extension / Separation"

| 항목 | 값 / 식 | 단위 | 절대/상대 |
|---|---|---|---|
| `psi_star` | `heading_deg + 180 * sign(rel_b)` (적 반대방향 직진) | ° | 절대 |
| `h_star` | 현재 고도 (유지) | ft | 절대 |
| `v_star` | `v_max_kts` (최대 속도, ~420 kts) | kts | 절대 |

**진입 조건**: 에너지 임계 이하 (`vc_kts < 250`) OR 불리 상황 지속 (`pos_adv < −30°` 연속 5초)

---

### 4.12 LEVEL_FLIGHT

전환·초기화·기본값.

| 항목 | 값 / 식 | 단위 | 절대/상대 |
|---|---|---|---|
| `psi_star` | 현재 `heading_deg` (유지) | ° | 절대 |
| `h_star` | 현재 `ego_altitude_ft` (유지) | ft | 절대 |
| `v_star` | trim 속도 `350 kts` | kts | 절대 |

---

## 5. Setpoint 갱신 규칙

```
매 BT tick (10Hz, dt=0.1s):

1. BT가 Tactic enum 하나 선택
2. guidance 계층이 현재 obs → (psi_star_deg, h_star_ft, v_star_kts) 계산
   - psi_star: 0~360° 절대 heading (wrap 처리: % 360.0)
   - h_star:   ft MSL 절대 고도 (clamp: HARD_DECK_FT < h < 50000)
   - v_star:   kts 절대 속도 (clamp: 150 < v < 500)
3. LQR.command(x, x_star) 계산
   - x_star 변환: psi → rad, h → ft(그대로), V → fps (v_kts * KNOT_TO_FT_S)
4. u = [thr, elev, ail, rud] → JSBSim fcs properties
```

---

## 6. 진입 조건 판단 변수 (obs 출처 명시)

| 변수 | obs key | 단위 | 절대/상대 | 분해능 |
|---|---|---|---|---|
| `ata_deg` | `ata_deg` | ° | 상대·절대값 (0~180) | §16 ✅ |
| `aa_deg` | `aa_deg` | ° | 상대·절대값 | §16 ✅ |
| `rel_b` | `relative_bearing_deg` | ° | 상대·부호있음 | §16 ✅ |
| `closure_kts` | `closure_kts` | kts | 상대(+접근/−이격) | §16 ✅ |
| `dist_ft` | `distance_ft` | ft | 절대 | §16 ✅ |
| `vc_kts` | `ego_vc_kts` | kts | 절대 | §16 ✅ |
| `h_ft` | `ego_altitude_ft` | ft | 절대 MSL | §16 ✅ |
| `roll_deg` | `roll_deg` | ° | 우리 선회방향 부호 | §16 100% |
| `omega_opp_signed` | computed (§16.4) | °/s | 적 선회방향 부호 | §16 90% |
| `pos_adv` | `positional_advantage_deg` | ° | aa−ata, 상대 | §16 ✅ |

---

## 7. 상수 (코드에서 magic number 금지 — 여기서만 정의)

```python
# 엔진 규칙 상수 (judge.py / wez_engine.py 기반, 변경 금지)
HARD_DECK_FT       = 1000.0       # ft MSL
WEZ_MIN_FT         = 500.0        # ft
WEZ_MAX_FT         = 3000.0       # ft
WEZ_ATA_DEG        = 12.0         # °

# F-16 성능 상수 (§10 실측 기반)
V_CORNER_KTS       = 320.0        # kts — 최소 선회 반경 속도
V_MAX_KTS          = 420.0        # kts — 최대 속도 (≈ vel4, 398kt + 마진)
V_TRIM_KTS         = 350.0        # kts — 기본 trim 속도
V_MIN_KTS          = 150.0        # kts — 실속 마진

# Guidance 파라미터 (튜닝 가능)
YOYO_CLIMB_FT      = 3000.0       # ft — HIGH_YOYO 상승량
YOYO_DESCENT_FT    = 2000.0       # ft — LOW_YOYO 강하량
YOYO_DV_KTS        = 40.0         # kts — 요요 속도 변화량
BREAK_HEADING_DEG  = 90.0         # ° — BREAK_TURN 전환각
EXT_HEADING_DEG    = 180.0        # ° — EXTENSION 반전각
SCISSORS_TURN_DEG  = 60.0         # ° — SCISSORS 반전 선회각
SCISSORS_VERT_FT   = 1000.0       # ft — SCISSORS 수직 진동량 (고도 여유 있을 때)
SCISSORS_H_MIN_FT  = 3000.0       # ft — 수직 scissors 허용 최소 고도 여유 (HARD_DECK 기준)
LDR_TURN_DEG       = 120.0        # ° — LAG_DISPLACEMENT_ROLL lift-vector 이탈각
LDR_CLIMB_FT       = 1500.0       # ft — LAG_DISPLACEMENT_ROLL 수직 이탈량
```

---

## 8. 다음 구현 단계

1. `new_match_engine/control/tactic.py` — 위 enum + 상수 정의
2. `new_match_engine/control/guidance.py` — tactic → setpoint 계산 (§4 식 구현)
3. `new_match_engine/control/autopilot.py` — setpoint + LQR → u (단위 변환 전담)
4. `new_match_engine/control/verify.py` — 각 tactic step 응답 검증
