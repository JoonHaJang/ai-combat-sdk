# HCCA v12 — BFM 기동별 정적 검증 (9케이스)

공통 파라미터: `th_bias=−1.5`, `op_bias=−1.5`, `switch_margin=0.15`, `min_commit=5`, `critical_threat=0.85`

보조 공식: `ga = σ((AA−ATA)/45)`, `aa_facing = 1−AA/180`

---

## Case 1 ✅ — 1-circle fight (균등 선회반경)

**입력**: ATA=20°, AA=70°, dist=3000ft, closure=+50kts, e_diff=0
```
ga = σ(50/45) = 0.752   aa_facing = 0.611
τ_threat = σ(−0.379) = 0.406
τ_opp    = σ(1.427)  = 0.806
τ_energy = 0.500
τ_pursuit = σ(1.972) = 0.878
```
**→ PURSUE 선택** (softmax 0.488)

Layer 3: `N = 3.0 + (1−0.752)×1.5 = 3.37`, 코너 속도, lead pursuit

**판정**: ✅ 코너 속도 lead pursuit. 1-circle 균등 선회에서 정확한 동작.

---

## Case 2 ⚠️ — 1-circle fight (우리 선회반경이 더 큼, ATA 악화 중)

**입력**: ATA=50°, AA=40°, dist=2500ft, closure=+20kts, ata_trend=+3
```
ga = σ(−10/45) = 0.445   aa_facing = 0.778
τ_threat = 0.443
τ_opp    = 0.617
τ_energy = 0.500
τ_pursuit = σ(0.364) = 0.590
```
**→ PURSUE 선택** (τ_pu=0.590 < 0.65이고 abs(20)<50이고 dist<3000)

**수정 후 동작**: stale 조건 발동 → orbit-break 속도 + hdg×0.7로 탈출 시도

**판정**: ⚠️ 갭#1 — B/C 수정(pur_stale 조건 완화)으로 개선됨. High Yo-Yo 전환은 여전히 없음.

---

## Case 3 ✅ — 1-circle 중 적기 break-out

**입력**: ATA=140°, AA=170°, dist=2500ft, closure=−300kts (break 직후)
```
ga = 0.660   aa_facing = 0.056
τ_threat = σ(−4.128) = 0.016
τ_opp    = σ(0.882)  = 0.707
τ_pursuit = σ(−9.2)  ≈ 0.000
```
**→ ATTACK 선택** (τ_pu≈0로 collapse, τ_opp 우세)

Layer 3: `closure<0 → vel=4 (sprint)`, `N = 3.5 + (1−0.016)×1.5 = 4.98`

**판정**: ✅ τ_pursuit 즉시 붕괴 → ATTACK sprint. break-out 대응 정확.

---

## Case 4 ⚠️ — 2-circle fight (HCA>90°, 대향 선회)

**입력**: ATA=80°, AA=90°, dist=4000ft, closure=+50kts, ata_trend=+2
```
ga = σ(10/45) = 0.555   aa_facing = 0.500
τ_threat = 0.358
τ_opp    = 0.609
τ_energy = 0.500
τ_pursuit = σ(1.177) = 0.764
```
**→ PURSUE 선택** (dist=4000 > 3000이므로 stale 조건 미발동)

Layer 3: `N = 3.0 + (1−0.555)×1.5 = 3.67 → lead pursuit`

**판정**: ⚠️ 갭#2 — 2-circle에서 lag-roll 개념 없음. strong lead pursuit으로 에너지 소모.
dist>3000이면 stale 조건 발동 안 됨. 미수정 상태.

---

## Case 5 ✅ — Head-on merge (정면 교전)

**입력**: ATA=5°, AA=5°, dist=8000ft, closure=+600kts
```
aa_facing = 0.972
τ_threat = σ(3.846) = 0.979 > critical_threat(0.85)
```
**→ Safety Override → 즉시 DEFEND**

Layer 3: dist=8000>3000, not in_wez → extension break, vel=4, hdg=side×45°

**판정**: ✅ 정면 8000ft에서 즉각 extension break.

---

## Case 6 ✅ — Post-merge (head-on 1초 후)

**입력**: ATA=160°, AA=170°, dist=1500ft, closure=−600kts
```
aa_facing = 0.056
τ_threat = σ(−1.640) = 0.163
```
**→ ATTACK 선택** (직전 DEFEND override로 mode_ticks=0 리셋)

Commitment: min_commit=5틱 → **5틱간 DEFEND 유지** 후 ATTACK sprint

**판정**: ✅ DEFEND(5틱) → ATTACK(sprint). 근거리 즉각 ATTACK 전환 방지.

---

## Case 7 ⚠️ — 적기 High Yo-Yo (enemy climbing)

**입력**: ATA=35°, AA=60°, dist=3500ft, closure=0, e_diff=−1000ft, energy_trend≈−500
```
ga = 0.635   aa_facing = 0.667
τ_threat = 0.378
τ_opp    = 0.713
τ_energy = σ(−0.9) = 0.289  ← 에너지 위기 근접
τ_pursuit = 0.654
```
**B1 fix 발동**: `op_suppress = 0.7 × min(1, 0.289/0.3) = 0.674`

**→ PURSUE 선택** (τ_en=0.289, erg_deficit_thresh보다 높음)

**판정**: ⚠️ e_diff가 erg_deficit_thresh(−2000ft) 이하로 떨어져야 ENERGY 전환.
초기 ~10초 반응 지연 동안 에너지 열세 심화.

---

## Case 8 ✅ — 적기 defensive break turn

**입력**: ATA=80°, AA=160°, dist=2000ft, closure=−100kts
```
ga = 0.856   aa_facing = 0.111
τ_threat = 0.197
τ_opp    = σ(1.853) = 0.864  (매우 높음)
τ_pursuit = σ(−2.488) = 0.077
```
**→ ATTACK 선택** (τ_pu 급락, τ_opp 급등)

Layer 3: `closure<0 → vel=4`, `N = 3.5 + (1−0.197)×1.5 = 4.70`

**판정**: ✅ τ_pursuit 급락으로 즉시 ATTACK sprint. 올바른 추격 전환.

---

## Case 9 ❌→⚠️ — Flat Scissors (교착, 수정 후)

**입력**: ATA≈60°(±15°진동), AA≈60°, dist=2000ft, closure≈0(±30kts), 60틱+
```
ga = 0.500
τ_pursuit = σ(0.500) = 0.622
```

**수정 전**: `closure < 0` 조건 → closure=+30kts일 때 stale 미발동. τ_pu=0.622 > 0.35 → 조건 불만족. **무한 PURSUE**.

**수정 후**: `abs(closure) < 50` AND `τ_pu < 0.65` AND `dist < 3000`
- abs(30) < 50 ✅
- τ_pu=0.622 < 0.65 ✅
- dist=2000 < 3000 ✅
→ **stale 발동 → orbit-break 속도, hdg×0.7**

**판정**: ⚠️ 갭#3 — 수정으로 scissors 탈출 트리거 작동. 완전한 이탈은 추가 검증 필요.

---

## 종합 결과

| # | 시나리오 | 수정 전 | 수정 후 |
|---|---------|---------|---------|
| 1 | 1-circle 균등 | ✅ | ✅ |
| 2 | 1-circle 반경 열세 | ⚠️ 갭#1 | ⚠️ 부분 개선 |
| 3 | 1-circle 중 break-out | ✅ | ✅ |
| 4 | 2-circle fight | ⚠️ 갭#2 | ⚠️ 미수정 |
| 5 | Head-on merge | ✅ | ✅ |
| 6 | Post-merge | ✅ | ✅ |
| 7 | 적기 High Yo-Yo | ⚠️ | ⚠️ |
| 8 | 적기 break turn | ✅ | ✅ |
| 9 | Flat scissors | ❌ 갭#3 | ⚠️ 개선 |
