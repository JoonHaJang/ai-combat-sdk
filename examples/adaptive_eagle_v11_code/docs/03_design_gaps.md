# HCCA v12 — 설계 갭 & 수정 내역

## 수정 완료 (커밋 bc6578b, f90cd94)

### B1: τ_opp 과포화 → ENERGY 모드 억압
**증상**: e_diff=−5000ft 위기에서도 τ_opp=0.73이면 w_energy가 0.49배 억압되어 PURSUE 오선택.

**원인**:
```python
# 수정 전
w_energy = (1−τ_en) * (1 − τ_th*0.7) * (1 − τ_op*0.7)
# τ_op=0.73 → 억압계수 = 1−0.511 = 0.489
```

**수정**:
```python
op_suppress = 0.7 * min(1.0, tau_en / 0.3)
# τ_en이 낮을수록(에너지 위기) op_suppress 약화 → w_energy 보호
```

---

### B2: τ_opp 원거리 페널티 없음 → 원거리 ATTACK 오선택
**증상**: dist=7000ft, AA=100°, ATA=80° → τ_opp=0.80 → ATTACK 선택 (교착 상태인데).

**원인**: dist>op_wez_max(914ft)이면 WEZ 항 기여=0. AA/ATA/ga 항만 합산되어 원거리에서 과대평가.

**수정**:
```python
dist_decay = max(0, 1 − dist / 8000)
# τ_opp에 −1.5*(1−dist_decay) 추가 → 원거리일수록 기회 점수 감소
```

---

### 갭#1+#3: PURSUE stale 조건 결함
**증상**:
- **갭#1** (1-circle 반경 열세): closure=+20kts → 부호 조건(`closure < 0`) 불만족 → stale 미발동
- **갭#3** (flat scissors): closure 진동 ±30kts → 부호 불안정 + τ_pu 임계값 0.35 너무 낮음

**원인**:
```python
# 수정 전
elif closure < self.pur_stale_closure and tau_pu < self.pur_stale_pursuit:
# pur_stale_closure=0, pur_stale_pursuit=0.35
```

**수정**:
```python
# 수정 후 (custom_actions.py ~L2300)
elif abs(closure) < self.pur_stale_closure and tau_pu < self.pur_stale_pursuit and dist < 3000:
    vel_cont = self.pur_orbit_break
    hdg_deg *= 0.7   # heading lock 완화로 orbit 탈출
```

파라미터 변경:
```python
# 수정 전
pur_stale_closure = 0     # 부호 조건 (잘못됨)
pur_stale_pursuit = 0.35  # 임계값 너무 낮음

# 수정 후
pur_stale_closure = 50    # abs(closure) < 50kts → 근-제로 closure 탐지
pur_stale_pursuit = 0.65  # τ_pu < 0.65 → 부진한 추격 탐지
```

---

## 미수정 갭

### 갭#2: 2-circle fight에서 lag-roll 없음
**증상**: ATA=80°, dist=4000ft에서 strong lead pursuit(N=3.67) 지속 → 에너지 소모 과다.

**근본 원인**: PURSUE 모드에 lag pursuit 개념 없음. N은 항상 lead 방향.

**미수정 이유**: dist>3000이면 stale 조건 미발동. 수정을 위해선 N 계산 로직 자체를 변경해야 함.

**수정 방향** (미구현):
```python
# ATA > 60° AND dist > 3000일 때 N 감소 (lag 전환)
if ata > 60 and dist > 3000:
    n_cmd = max(1.0, n_cmd - 2.0 * (ata - 60) / 30)
```

---

## 수정 후 예상 효과

| 케이스 | 수정 전 | 수정 후 |
|--------|---------|---------|
| flat scissors | 무한 PURSUE 유지 | 근접 + 저τ_pu → orbit-break 발동 |
| 1-circle 반경 열세 | closure 부호 조건 실패 | abs 조건으로 탐지 |
| 에너지 위기 | PURSUE 오선택 | B1 fix → ENERGY 선택 |
| 원거리 교착 | ATTACK 오선택 | B2 fix → 원거리 감쇠 |
| 2-circle | lead pursuit 과다 | 미수정 |
