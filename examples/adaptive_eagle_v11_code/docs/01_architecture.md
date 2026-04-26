# HCCA v12 — 아키텍처

## 개요

HCCA(Hierarchical Continuous Control Architecture) v12는 5개 레이어로 구성된 연속 제어 AI입니다.
boolean 라우팅 대신 sigmoid 기반 연속 점수로 mode를 선택합니다.

```
L0  상황 인식  → ga, aa_facing, closure_trend, aa_rate 등
L1  위협/기회  → τ_threat, τ_opp, τ_energy, τ_pursuit  (각 sigmoid [0,1])
L2  모드 선택  → softmax + commitment (ATTACK / DEFEND / ENERGY / PURSUE)
L3  기동 계산  → 모드별 N계수, 속도, 고도 지령
L4  이산화     → hdg_idx [0~8], vel [1~5], alt [-1/0/+1]
```

---

## Layer 0 — 보조 공식

| 변수 | 공식 | 의미 |
|------|------|------|
| `ga` | `σ((AA−ATA)/45)` | 2-orbit 기하 우위; >0.5 → 적이 유리 |
| `aa_facing` | `1 − AA/180` | 적기 정면 향함 정도; 1=정면, 0=후방 |
| `closure_trend` | 5-tick EWMA(closure) | closure 추세 |
| `aa_rate_fast` | 5-tick EWMA(ΔAA/Δt) | AA 변화율 |

---

## Layer 1 — 4개 점수

### τ_threat (위협)
```
z = th_w[0]*(closure/th_rdot_scale)*aa_facing
  + th_w[1]*aa_facing
  + th_w[2]*(−aa_rate_fast/10)
  + th_bias
```
기본값: `th_w=[2.0,1.5,1.0,0.5,3.0,1.5]`, `th_bias=−1.5`, `th_rdot_scale=300`

### τ_opp (기회)
```
z = op_w[0]*(1−ATA/90)
  + op_w[1]*(1−AA/180)
  + op_w[2]*ga
  + op_w[3]*(1−max(0,dist−op_wez_max)/op_wez_max)  [WEZ 범위 내일 때]
  − op_w[4]*aa_facing
  + op_bias
  − 1.5*(1−dist/8000)   [B2: 원거리 감쇠]
```
기본값: `op_w=[2.0,1.5,1.5,3.0,1.5]`, `op_bias=−1.5`, `op_wez_max=914`

### τ_energy (에너지)
```
z = en_w[0]*(e_diff/en_ediff_scale)
  + en_w[1]*(Ps/50)
  + en_w[2]*alt_advantage
  + en_bias
```
기본값: `en_w=[2.0,1.5,1.0,1.0,1.0]`, `en_bias=0.0`, `en_ediff_scale=5000`

### τ_pursuit (추격 품질)
```
z = pu_w[0]*(closure/pu_closure_scale)
  − pu_w[1]*(ata_trend/10)
  + pu_w[2]*(hdg_improvement/10)
  + ga
  + pu_bias
```
기본값: `pu_w=[2.0,1.5,1.5,1.0]`, `pu_bias=0.0`, `pu_closure_scale=200`

---

## Layer 2 — 모드 선택

### Safety Override
`τ_threat > critical_threat(0.85)` → **즉시 DEFEND**, softmax 무시

### Softmax 가중치 (B1 fix 포함)
```python
op_suppress = 0.7 * min(1.0, tau_en / 0.3)   # 에너지 위기 시 τ_opp 억압 완화

w_attack  = τ_opp * (1 − τ_th*0.7) * (1 − op_suppress*(1−τ_en)) * max(0.3, τ_en)
w_defend  = τ_th  * (1 − τ_op*0.3)
w_energy  = (1−τ_en) * (1 − τ_th*0.7) * (1 − op_suppress*(1−τ_en))
w_pursue  = τ_pu  * (1 − τ_th*0.5) * max(0.3, τ_en)
```

### Commitment 로직
- `switch_margin = 0.15` — 현재 모드 유지 보너스
- `min_commit = 5 ticks` — 최소 유지 틱
- 장기 ATTACK patience: N틱 이후 PURSUE 전환 가중치 증가

---

## Layer 3 — 모드별 기동

### ATTACK
```
N = atk_n_base(3.5) + (1 − τ_threat) × atk_n_bonus(1.5)   → [2.0, 5.0]
closure < 0 → vel = max(vel_cont, 4.0)  [separation sprint]
overshoot 감지 → N = 0.5  [lag 전환]
```

### DEFEND
```
intensity = σ(τ_threat − 0.5) × 2   [0~1]
dist < 3000 → break turn (hdg ±90°)
dist ≥ 3000 → extension break (hdg side×45° + 가속)
```

### ENERGY
```
e_diff < −erg_deficit_thresh → BUILD (climb)
e_diff > erg_surplus_thresh  → DIVE_ATTACK
Ps < 0                       → YO-YO (고도 이용)
else                         → CRUISE
```

### PURSUE
```
N = pur_n_base(3.0) + (1 − ga) × pur_n_gain(1.5)
stale 조건: abs(closure) < pur_stale_closure(50) AND τ_pu < pur_stale_pursuit(0.65) AND dist < 3000
  → vel = pur_orbit_break, hdg_deg × 0.7  [orbit 탈출]
```

---

## Layer 4 — 이산화

| 출력 | 범위 | 매핑 |
|------|------|------|
| `hdg_idx` | 0~8 | −90°=0, 0°=4, +90°=8 |
| `vel` | 1~5 | 1=idle, 3=corner, 5=max |
| `alt` | −1/0/+1 | 하강/유지/상승 |

저고도 안전: alt < 500ft → alt = +1 강제
