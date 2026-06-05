# SUPERPLAN — BFM 수학 정리의 BT 통합

> ⚠️ **본 문서는 phase별 진행 이력(역사 기록)입니다.** 본 문서의 일부 내용은
> 이미 폐기되었습니다 (이산 EnergyTrap 분기, AdversaryStateEstimator 등).
> **현재 상태와 미래 설계 입력은 [CURRENT_STATE_AND_DESIGN.md](./CURRENT_STATE_AND_DESIGN.md) 참조.**
> 폐기된 섹션은 그 문서 5절 "폐기된 접근"에 격리되어 있습니다.
>
> **참조 문서**: `BFM_MATHEMATICAL_FOUNDATIONS.md` (정리 1~8과 출전)
> **(원래) 목표**: canonical × offensive의 DRAW를 수학적 정리 기반으로 WIN 전환,
> 동시에 다른 77% WIN 시나리오 회귀 없음 보장.
> **(원래) 방법**: 경험칙 BT 분기를 정리-기반 명시적 분기로 교체하거나 보강.

---

## 0. 진단 요약 (Why Are We Here)

### 0.1 진행 상황 (Phase별 측정)

| 시점 | 시나리오 수 | WIN | LOSS | DRAW | 비고 |
|------|-------------|-----|------|------|------|
| 초기 (다양 ATA, 175 케이스) | 175 | 95% (167) | 0% | 5% (8) | 비현실 초기 조건 (8000ft, 300kts) |
| Canonical 재설계 직후 | 55 | 78% (43) | 2% (1) | 20% (11) | JSBSim 실제 초기 조건 (15000ft, 387kts, ATA=90°) — **현실적 baseline** |
| Phase 2 (정리 5+6, 이산 EnergyTrap) | 55 | 89% (49) | 0% (0) | 11% (6) | 사용자 지적으로 폐기 — fine-tuning 방식 |
| **τ 연속 적응 제어 (정리 5/6/7/8)** | 55 | **91% (50)** | **0% (0)** | **9% (5)** | obs 직접 매핑 — 추정기 0개, 이산 분기 0개 |

### 0.2 τ 적응 제어 결과 분석

**모든 canonical(ATA=90°, 3297ft, 387kts) × 5 적정책 = 5/5 WIN.** 실전 매치 초기 조건의
모든 적 정책 변형에서 승리. 남은 5 DRAW의 원인:

- canonical_close × offensive (2000ft 시작, 비현실 초기)
- canonical_far × offensive (7000ft 시작, 비현실 초기)
- canonical_enm_fast × passive/defensive/evading (적이 MAX_SPD 420kts 상수 — 물리 한계)

**τ 함수 구조 (28-피처 obs 직접 입력)**:
```
τ_corner = σ((HCA-120)/20) · σ((V-355)/8) · σ(active_turning/5)
τ_yoyo   = max(s_chase, s_lock) · gauss(ATA, μ=70°, σ=30°)
τ_ldt    = gauss(ATA, μ=65°, σ=15°) · σ((dist-3000)/1500) · σ((LOS_rate-8)/5)
```

**제어 합성**:
```
d_speed = (1-τc)·sprint + τc·brake-to-corner
d_gamma = (1-τy)·PN_pitch + τy·yoyo_bangbang  (alt_gap AND own.γ trigger)
d_hdg   = w_pn·PN + w_dive·intercept_aim + w_lag·90°_offset
```

**핵심 — adversary state estimator 사용 0개**. 모든 적응성은 obs의 시간차분 (alt_gap rate,
LOS rate, HCA rate, turn rate)에서 직접 산출.

**왜 175 → 55 케이스로 감소했는가**: 사용자 지적대로 실제 JSBSim 매치는 항상
ATA=90°, dist=3297ft, spd=387kts, alt=15000ft에서 시작한다. 비현실적 초기 ATA
(예: ATA=160° 시작)는 게임 진행 중 도달 가능한 중간 상태이지 시작점이 아니므로,
검증의 신뢰성을 위해 canonical 분기 시나리오로 제한했다.

### 0.2 Phase 2 효과 분석

DRAW의 본질을 우리는 5단계 토론으로 좁혔다:

| 단계 | 가정 | 결론 |
|------|------|------|
| 1. 단순 2D bound orbit 분석 | MAX_TR=21° 상수 | ATA 90° 락 (잘못된 단순화) |
| 2. 적응형 선회 도입 | ω = ω(V) | 속도 변경으로 락 깸 |
| 3. 3D 도그파이트 인정 | γ 자유도 | 평면 분석 무효 |
| 4. Black-box 적 인정 | π_e 고정 미지 | minimax 정리 무효, V_BR > 0 가능 |
| 5. 비-Kepler 궤적 인정 | C¹ 임의 곡선 | 닫힌 궤도 가정만의 결과 |

**진짜 진단**:
- canonical × offensive DRAW = **BT가 offensive의 명시적 sub-optimality를 exploit하지 않음**
- 게임 이론 한계가 아니라 **모델링 결함**

**해결 경로**:
- 정리 1~8을 BT 분기로 명시화
- 각 분기의 진입 조건을 부등식으로 강제
- 각 분기의 액션을 정리의 trajectory로 구현

---

## 1. 정리 → BT 분기 매핑 매트릭스

| 정리 | 진입 조건 | 액션 | offensive exploit | BT 분기명 (제안) |
|------|-----------|------|-------------------|-----------------|
| 정리 5 (Boyd Ps) | own.V ∈ [350, 380], enemy.V > V_c, own.Ps_margin > 0 | 코너 안착 + 코너 유지 | 적이 V_c 위 가속 → 적 Ps 손실 | `EnergyTrap_ForceCorner` |
| 정리 6 (Shaw 2-circle) | HCA > 120°, dist ∈ [3000, 6000] | 즉시 코너 + ω_max 추구 | 적 ω 우리보다 작아짐 | `TwoCircleDominance` |
| 정리 7 (LDT) | ATA ∈ [40, 90°], dist > 3000, enemy_PN_signature | Phase 1 lag → Phase 2 lead | 적 PN 응답 0.4s 지연 | `LagDisplacementTurn` |
| 정리 8 (High Yo-Yo) | closure > 30, ATA ∈ [20, 70°], own.Ps > 0, alt_gap_potential > 1500ft | bang-bang climb→inverted dive | 적 alt-track 0.8s 지연 | `HighYoYoBait` |
| 정리 2 (PN 최적성) | ATA < 30°, dist < 3500, cl > 0 | Augmented PN (가속 보정 항 포함) | 우리가 정확한 lead | `AugmentedPN_Tracking` |
| 정리 4 (Two Cars) | ω_us / ω_them > 1.1 | lag 후 cut-off | ω 비대칭 발생 | (정리 5+6의 부산물) |
| 정리 1 (Bernoulli) | enemy 직선 비행 + V_us > V_e | 직선 추격 | passive/evading 적 | (기존 LeadPursuit 유지) |
| 정리 3 (Homicidal) | enemy 회피자 모델 | sticky region 진입 | 회피자 sub-optimal | (기존 OffensivePursuit 유지) |

**구현 우선순위**:
1. 🔴 `EnergyTrap_ForceCorner` (정리 5) — canonical × offensive 의 핵심
2. 🔴 `HighYoYoBait` (정리 8) — 적 alt-track 약점 직접 노림
3. 🟠 `LagDisplacementTurn` (정리 7) — PN 포화 회피
4. 🟡 `TwoCircleDominance` (정리 6) — 5번과 결합 효과
5. 🟢 `AugmentedPN_Tracking` (정리 2) — 정확도 향상

---

## 2. 단계별 실행 계획

### Phase 1 — 측정 인프라 (1단계, 즉시)

**목표**: offensive 정책의 sub-optimality를 정량 측정 가능하게.

새 진단 도구 `sim_dogfight_verify.py`에 추가:

```python
def compute_enemy_signature(log):
    """log에서 적의 정책 signature 추출 — 미래 BT 분기의 진입 조건."""
    return {
        "alt_track_tau_s":     measure_alt_response_time(log),    # 적 d_gamma 시간상수
        "hdg_track_tau_s":     measure_hdg_response_time(log),    # 적 d_hdg 시간상수
        "accel_pattern":       measure_speed_derivative(log),     # 가속 패턴 (offensive: +2)
        "lead_coefficient":    fit_pn_gain(log),                  # 적 PN N값 추정
        "vertical_response_lag": ...,                             # high yo-yo 도입 시 응답 lag
    }
```

**산출물**:
- 5개 적 정책의 signature 테이블 (사후 측정)
- 각 정책별 약점 정량화 (예: offensive τ_alt = 0.8s, ε_PN = 0)

**검증**: 수동 시뮬레이션 + signature vs 정책 코드 직접 비교 일치.

### Phase 2 — `EnergyTrap_ForceCorner` 구현 (정리 5+6)

**목표**: canonical 시작 직후 우리만 V_c (350kts) 안착, 적은 V_c 위로 가속하게 유도.

#### 2.1 신규 BT 분기 (YAML)
```yaml
- type: Sequence
  name: EnergyTrapForceCorner
  children:
    - type: Condition
      name: HighHCA
      params:
        hca_min_deg: 120.0
    - type: Condition
      name: AboveCorner
      params:
        speed_min_kts: 360.0
    - type: Action
      name: HardBrake_to_Corner
      params:
        target_speed_kts: 350.0
        decel_kts_per_s: 15.0
```

#### 2.2 신규 Action: `HardBrake_to_Corner`

```python
class HardBrakeToCorner(BaseAction):
    """
    수학적 근거: 정리 5 (Boyd Ps) + 정리 6 (Shaw 2-circle).
    
    HCA > 120° (2-circle fight) AND own.V > V_c (코너 위) 조건에서
    -15 kts/s로 V_c 안착. 적이 +2 kts/s로 가속 중이라면 5초 후:
      적 ω = 16°/s, 우리 ω = 21°/s → 비율 1.31× 우위.
    """
    def update(self, obs):
        target = self.target_speed_kts
        cur    = obs["ego_vc_kts"]
        if cur > target + 5:
            return ActionCommand(d_speed=-self.decel_kts_per_s)
        else:
            return ActionCommand(d_speed=0)  # 코너 유지
```

#### 2.3 신규 Condition: `HighHCA`, `AboveCorner`
```python
class HighHCA(BaseCondition):
    def evaluate(self, obs):
        return (obs["hca_deg"] * 180.0) > self.hca_min_deg

class AboveCorner(BaseCondition):
    def evaluate(self, obs):
        return obs["ego_vc_kts"] > self.speed_min_kts
```

#### 2.4 BT 우선순위 위치
`HardDeck` → `GunEngagement` → `EnergyTrapForceCorner` → 기존 분기

(코너 진입은 다른 어떤 추격 BFM보다 선행되어야 정리 5+6이 valid)

#### 2.5 sim_dogfight 검증 시나리오
- canonical × offensive: 30초 후 ω 비율 측정 → 1.3× 이상 확인
- canonical × passive: 회귀 없는지 (이미 WIN이었음) 확인
- canonical_close × offensive (LOSS): 코너 안착이 LOSS 회복하는지

### Phase 3 — `HighYoYoBait` 구현 (정리 8)

**목표**: 적 alt-track 시간상수 τ_alt = 0.8s를 timing exploit.

#### 3.1 신규 BT 분기

```yaml
- type: Sequence
  name: HighYoYoBait
  children:
    - type: Condition
      name: ClosureAbove
      params:
        closure_min_kts: 30.0
    - type: Condition
      name: ATAInRange
      params:
        ata_min_deg: 20.0
        ata_max_deg: 70.0
    - type: Condition
      name: PsMarginPositive
      params:
        ps_min_fts: 0.0
    - type: Action
      name: VerticalBangBang
      params:
        climb_target_gamma_deg: 50.0
        enemy_alt_tau_s: 0.8       # 측정값 기반 (Phase 1)
        inversion_extra_s: 0.5      # 안전 여유
```

#### 3.2 신규 Action: `VerticalBangBang`

```python
class VerticalBangBang(BaseAction):
    """
    수학적 근거: 정리 8 (Pontryagin 수직 BFM 최적 제어).
    
    Phase 1: max pull (γ → +50°), 4-6초
    Phase 2: 정점에서 inverted roll (180°)
    Phase 3: max push (γ → -45°), 적의 6시 후방 dive
    
    Timing:
      t_climb = 우리 γ → +50° 도달 시간 ≈ 50/(MAX_TR×0.65) = 50/13.7 ≈ 3.6s
      t_inversion = t_climb + enemy_alt_tau_s + inversion_extra_s
      
    적의 alt-track 시간상수가 τ_alt이면 t_inversion 시점에 적은
    γ ≈ +50° × (1 - exp(-t_climb/τ_alt)) ≈ +50° × 0.99 = +49.5° (거의 따라옴)
    그러나 우리가 즉시 dive 시작하면 적은 다시 -45°로 응답해야 하고,
    응답 시간상수 0.8s 동안 우리는 closure × 0.8s = 600ft 후방 진입.
    """
    def __init__(self):
        self.phase = "climb"
        self.t_phase = 0
    
    def update(self, obs):
        ata = obs["ata_deg"] * 180
        gamma = obs["gamma_deg"]   # 신규 obs 필요
        
        if self.phase == "climb":
            if gamma >= 45.0:
                self.phase = "inversion"
                self.t_phase = 0
            else:
                return ActionCommand(d_gamma=MAX_TR*0.65, d_speed=0)
        
        elif self.phase == "inversion":
            if self.t_phase >= self.inversion_extra_s:
                self.phase = "dive"
                self.t_phase = 0
            else:
                self.t_phase += DT
                return ActionCommand(d_roll=180.0)  # 즉각 inverted
        
        elif self.phase == "dive":
            if obs["dist"] < 2500 and ata < 30:
                self.phase = "tracking"
            return ActionCommand(d_gamma=-MAX_TR*0.7, d_speed=10)
        
        else:  # tracking
            return ActionCommand(use_default_pn=True)
```

#### 3.3 sim_dogfight 검증
- canonical × offensive: 정점 timing 검증 (3.6s+0.8s+0.5s = 4.9s)
- 결과 측정: t=4.9s에서 적 γ vs 우리 γ → 우리 dive 시작 시 적이 따라오지 못하는가?

### Phase 4 — `LagDisplacementTurn` 구현 (정리 7)

**목표**: PN 포화 회피, displacement → lead 단계 진입.

#### 4.1 신규 BT 분기

```yaml
- type: Sequence
  name: LagDisplacementEntry
  children:
    - type: Condition
      name: ATAInRange
      params:
        ata_min_deg: 40.0
        ata_max_deg: 90.0
    - type: Condition
      name: DistanceAbove
      params:
        threshold_ft: 3000
    - type: Action
      name: LagPursuit_TwoPhase
      params:
        lag_offset_deg: -90.0       # bear에서 90° 옆 (lag)
        transition_threshold: 1.4   # dist·sin(ATA) ≥ R·1.4
```

#### 4.2 신규 Action: `LagPursuit_TwoPhase`

```python
class LagPursuit_TwoPhase(BaseAction):
    """
    Phase 1 (Lag): bear + sign·90° 방향으로 비행
    Phase 2 (Pure): displacement 충족 시 bear 직접 추격
    
    수학적 근거: 정리 7 (Shaw LDT).
    Phase 1→2 조건: dist · sin(ATA) ≥ R_us · √2
    """
    def __init__(self):
        self.phase = "lag"
    
    def update(self, obs):
        ata = obs["ata_deg"] * 180
        dist = obs["distance_ft"]
        bear = obs["bear_deg"]
        radius = obs["turn_radius_ft"]
        
        displacement = dist * math.sin(math.radians(ata))
        
        if self.phase == "lag":
            if displacement >= radius * math.sqrt(2):
                self.phase = "pure"
            else:
                # Lag offset: 적 LOS 후방 90°
                side = 1 if obs["relative_bearing_deg"] > 0 else -1
                target = (bear + side * 90.0) % 360
                err = ang_diff(target, obs["ego_hdg_deg"])
                return ActionCommand(d_hdg=err/(DT*2.5), d_speed=0)
        
        # Phase 2: Pure pursuit (no lead)
        err = ang_diff(bear, obs["ego_hdg_deg"])
        return ActionCommand(d_hdg=err/(DT*2.5), d_speed=0)
```

### Phase 5 — `AugmentedPN_Tracking` 구현 (정리 2)

**목표**: 일정 가속 적에 대한 PN miss 거리 최소화.

#### 5.1 기존 LeadPursuit / SmartGunAttack에 augmented 항 추가

```python
def augmented_pn_command(own, geo, target_accel_estimate, N=3):
    """
    수학적 근거: 정리 2 augmented PN.
      a_lat = N · V_c · λ̇ + (N/2) · a_T,perp
    
    target_accel_estimate: 적의 lateral acceleration (관측 기반 추정)
    """
    los_rate = geo["los_rate"]
    closure = geo["closure"]
    a_pn = N * closure * los_rate
    a_aug = (N / 2) * target_accel_estimate
    return a_pn + a_aug
```

#### 5.2 적 가속 추정자 (online estimator)

```python
class TargetAccelEstimator:
    """과거 N틱의 적 속도 변화율로 lateral accel 추정."""
    def __init__(self, window=10):
        self.history = deque(maxlen=window)
    
    def update(self, enemy_state):
        self.history.append(enemy_state)
        if len(self.history) >= 3:
            # 중심차분으로 가속도 계산
            v_prev = self.history[-3]["vel"]
            v_curr = self.history[-1]["vel"]
            return (v_curr - v_prev) / (2 * DT)
        return np.zeros(3)
```

---

## 3. 검증 프로토콜

### 3.1 단위 테스트 (각 분기별)

각 신규 분기에 대해:
1. **활성화 조건 검증**: 진입 조건이 정확한 (V, h, ATA, HCA) 영역에서만 활성화되는가?
2. **수학적 일치 검증**: 액션 trajectory가 정리의 명시적 해와 일치하는가?
3. **회귀 방지**: 기존 시나리오 (passive, orbiting, defensive, evading)에서 활성화 안 되는가?

### 3.2 정량 측정 (시뮬레이터)

각 Phase 완료 후 sim_dogfight_verify.py 실행하여 다음 지표 측정:

```python
metrics = {
    # canonical × offensive 핵심
    "canonical_offensive_outcome": "DRAW" or "WIN" or "LOSS",
    "canonical_offensive_first_wez_tick": int,        # 첫 WEZ 진입 시점
    "canonical_offensive_min_ata_deg": float,         # ATA 최솟값
    "canonical_offensive_max_omega_ratio": float,     # ω_us / ω_them 최댓값
    
    # Phase 2 정리 5+6 검증
    "energytrap_corner_arrival_tick": int,            # V_c 안착 시점
    "energytrap_omega_advantage_t30s": float,         # 30초 시점 ω 비율
    
    # Phase 3 정리 8 검증
    "yoyo_climb_apex_tick": int,                      # 정점 도달
    "yoyo_alt_offset_at_dive_start_ft": float,        # dive 시작 시 적과의 alt 차
    "yoyo_dive_intercept_lag_offset_ft": float,       # 적 6시 후방 offset
    
    # Phase 4 정리 7 검증
    "ldt_phase1_to_phase2_displacement_ft": float,    # transition 시 displacement
    "ldt_phase2_pn_saturated": bool,                  # Phase 2에서 PN 포화 X
    
    # 회귀 방지
    "all_other_outcomes": [(scenario, policy, outcome)],
    "regression_count": int,                          # 기존 WIN → DRAW 또는 LOSS
}
```

### 3.3 success criteria

각 Phase의 통과 조건:

| Phase | 통과 조건 |
|-------|-----------|
| 1 (signature) | 5개 정책 모두 τ_alt, τ_hdg, accel_pattern 측정 완료 |
| 2 (정리 5+6) | canonical_offensive_max_omega_ratio ≥ 1.20 AND regression_count = 0 |
| 3 (정리 8) | canonical_offensive_first_wez_tick ≤ 50 AND regression_count = 0 |
| 4 (정리 7) | ldt_phase2_pn_saturated = False AND canonical_offensive_outcome = WIN |
| 5 (정리 2) | 평균 miss distance 감소 ≥ 30% |

**최종 목표**: WIN ≥ 95% (현재 78%), LOSS = 0, DRAW ≤ 5%.

---

## 4. 위험 요소와 완화책

| 리스크 | 영향 | 완화책 |
|--------|------|--------|
| 신규 분기가 다른 시나리오에서 오발동 | 기존 WIN 회귀 | 진입 조건 부등식을 보수적으로 (margin 충분히), Phase별 회귀 테스트 |
| 적 signature 측정이 noise | 잘못된 exploit | 측정 window 충분히 (≥10 틱), 신뢰구간 도입 |
| Yo-yo timing이 적 응답에 따라 다름 | 적이 다른 적이면 fail | enemy_alt_tau를 학습 가능한 파라미터로 (TacticalLookup 활용) |
| 코너 안착 중에 적이 우리 6시 진입 | 일시 위험 | 코너 안착 중 DEFEND 모드 fallback 유지 |
| Augmented PN이 noise로 jitter | 사격 미스 | 가속 추정자에 low-pass filter |
| BT 분기가 너무 많아져 우선순위 충돌 | 의도치 않은 분기 발동 | Phase별로 1개씩 순차 추가, 각 추가 후 회귀 검증 |

---

## 5. 산출물

### 5.1 신규 파일

```
examples/adaptive_eagle_v11_code/
├── BFM_MATHEMATICAL_FOUNDATIONS.md        ✓ 완료 (참조 문서)
├── SUPERPLAN_BFM_MATH_INTEGRATION.md      ✓ 완료 (이 문서)
├── nodes/
│   ├── custom_actions.py                  ← 수정
│   │   + HardBrakeToCorner
│   │   + VerticalBangBang
│   │   + LagPursuit_TwoPhase
│   │   + AugmentedPN
│   │   + TargetAccelEstimator
│   └── custom_conditions.py               ← 수정
│       + HighHCA
│       + AboveCorner
│       + ATAInRange
│       + ClosureAbove
│       + PsMarginPositive
│       + DistanceAbove (기존 활용 가능)
├── adaptive_eagle_v11_code.yaml           ← 수정
│   + EnergyTrapForceCorner 분기
│   + HighYoYoBait 분기
│   + LagDisplacementEntry 분기
└── sim_dogfight_verify.py                 ← 보강
    + compute_enemy_signature()
    + theorem-by-theorem metrics
    + 회귀 방지 assertion
```

### 5.2 검증 결과 보고서

각 Phase 완료 시:
- `phase_N_results.md`: 측정 metric, 통과/실패, 회귀 분석
- 첨부 데이터: log 파일, 그래프 (ATA-시간, ω-시간, alt 트래킹 비교)

---

## 6. 구현 순서 (실행 권장)

```
Week 1: Phase 1 (signature 측정 인프라)
        - 측정 도구 추가
        - 5개 정책 signature 측정 완료
        - offensive의 τ_alt, τ_hdg, accel_pattern 정량 확정

Week 2: Phase 2 (정리 5+6 — EnergyTrap)
        - HardBrakeToCorner action 구현
        - HighHCA, AboveCorner condition 구현
        - YAML 분기 추가
        - sim_dogfight 검증, ω 비율 측정

Week 3: Phase 3 (정리 8 — HighYoYo)
        - VerticalBangBang action 구현
        - 새 obs (gamma_deg, los_rate) 노출
        - Pontryagin 시점 계산
        - sim_dogfight에서 alt offset 측정

Week 4: Phase 4 (정리 7 — LDT)
        - LagPursuit_TwoPhase 구현
        - displacement 진입 조건 검증
        - PN 포화 측정

Week 5: Phase 5 (정리 2 — Augmented PN)
        - TargetAccelEstimator 구현
        - 기존 PN 분기에 aug 항 추가
        - miss distance 측정

Week 6: 통합 검증
        - 11 시나리오 × 5 정책 = 55 케이스 전체 재실행
        - WIN ≥ 95% 목표 확인
        - 회귀 없음 확인
        - 결과 보고서 작성
```

---

## 7. 합의 사항 (사용자 확인 필요)

이 superplan을 진행하기 전에 다음을 확인:

1. **우선순위**: Phase 2 (정리 5+6) 부터 시작이 맞는가?
   - 대안: Phase 3 (정리 8) 부터 시작 (yo-yo가 더 visual하게 효과 측정 용이)
   - 추천: Phase 1 (측정) 후 Phase 2 (가장 단순한 변경)

2. **scope**: 5개 Phase 모두 진행 vs 핵심 2~3개만?
   - canonical × offensive DRAW 해소만 목표면 Phase 1+2+3 충분
   - WIN ≥ 95% 목표면 5개 모두 필요

3. **회귀 허용**: 기존 WIN 시나리오에서 1~2개 DRAW 허용 가능?
   - 엄격: 회귀 0개 (보수적 진입 조건 필요)
   - 완화: 1~2개 회귀 허용 (더 공격적 분기 가능)

4. **검증 강도**: 회당 55케이스 전체 vs 핵심 시나리오 (canonical 시리즈만)?
   - 핵심만: Phase 진행 빠름, 부작용 발견 늦음
   - 전체: 안전하지만 시간 소요 (각 Phase당 시뮬 1500틱 × 55 = 82500틱)

5. **수학 검증 깊이**: 각 분기의 정리와의 일치를 별도 단위 테스트로 검증?
   - 권장: 정리 8 (yo-yo)는 timing이 critical → 단위 테스트 필수
   - 정리 5+6은 단순 → 통합 테스트로 충분

---

## 8. 다음 액션

사용자 검토 후, 다음 중 선택:

- [A] **Phase 1 부터 시작**: signature 측정 인프라 구현
- [B] **Phase 2 직행**: EnergyTrap_ForceCorner 즉시 구현 (signature 없이도 offensive +2kts/s 가정)
- [C] **수정 요구**: superplan의 특정 부분 (우선순위, scope, 분기 정의 등) 수정 후 진행
- [D] **추가 토론**: 정리 적용 방식이나 위험 분석에 추가 검토 필요

선택을 알려주면 그에 맞게 진행한다.
