# M1.3 aggressive 책임 부위 분석 — 2026-05-16

SUPERPLAN_v2 §3 Phase 1 M1.3. 입력: `logs/regression/m12/*_ticks.csv` (n=3 매치 × 3 적).

## Verdict

| 가설 | 결과 | 근거 |
|---|---|---|
| H1 (V_dist ω-zero, long-range) | **CONFIRMED** | aggressive median |gPN_dist|/|gPN_head|@>8000ft = 441161.743 vs simple = 1598.970 |
| H2 (V_target 자발 감속) | **WEAK/REJECTED** | agg u_a<0 frac = 0.249 vs sim = 0.145, agg V_e_clamp = 0.507 |
| H3 (dispatcher routing) | **WEAK/REJECTED** | agg theorem_frac = 0.669, theorem ρ_corner=0.063 vs ρ_pn=0.766 |

## 상세

### simple (n=4500 ticks across 3 matches)

**H1 — ∇V_pn 의 LOS-radial vs LOS-tangential 분해 (range bucket 별)**:

```
  - long_range_>8000ft: n=571 median|gPN_dist|/|gPN_head|=1598.970 mean|gPN_dist|=5.393e-03 mean|gPN_head|=4.105e-06
  - medium_range_3000_8000: n=3276 median|gPN_dist|/|gPN_head|=82.512 mean|gPN_dist|=1.970e-03 mean|gPN_head|=4.429e-05
  - short_range_<3000ft: n=653 median|gPN_dist|/|gPN_head|=0.899 mean|gPN_dist|=2.540e-04 mean|gPN_head|=3.704e-04
```

**H2** — `u_a<0` frac = 0.145, `V_e_clamp` frac = 0.434, intersection = 0.042

**H3 — 분기 점유 + Theorem 안 ρ 평균**:

```
  - theorem_frac=0.196
  - theorem mean ρ: pn=0.605 corner=0.059 ldt=0.043 yoyo=0.293
  - branch occupancy:
    · hybrid:OrbitBreak: 0.408
    · hybrid:EnergyRecovery: 0.266
    · hybrid:Theorem: 0.196
    · hybrid:DefensiveBreak: 0.055
    · hybrid:LagPursuit: 0.046
    · hybrid:OffensivePursuit: 0.022
    · hybrid:GunEngagement: 0.007
```

### defensive (n=4500 ticks across 3 matches)

**H1 — ∇V_pn 의 LOS-radial vs LOS-tangential 분해 (range bucket 별)**:

```
  - long_range_>8000ft: n=3018 median|gPN_dist|/|gPN_head|=1120576.517 mean|gPN_dist|=1.274e-02 mean|gPN_head|=2.565e-07
  - medium_range_3000_8000: n=1400 median|gPN_dist|/|gPN_head|=1288.653 mean|gPN_dist|=1.816e-03 mean|gPN_head|=1.063e-05
  - short_range_<3000ft: n=82 median|gPN_dist|/|gPN_head|=197.127 mean|gPN_dist|=7.864e-04 mean|gPN_head|=4.145e-06
```

**H2** — `u_a<0` frac = 0.091, `V_e_clamp` frac = 0.200, intersection = 0.000

**H3 — 분기 점유 + Theorem 안 ρ 평균**:

```
  - theorem_frac=0.414
  - theorem mean ρ: pn=0.845 corner=0.004 ldt=0.016 yoyo=0.136
  - branch occupancy:
    · hybrid:EnergyRecovery: 0.454
    · hybrid:Theorem: 0.414
    · hybrid:GunEngagement: 0.067
    · hybrid:OffensivePursuit: 0.044
    · hybrid:OrbitBreak: 0.015
    · hybrid:LagPursuit: 0.005
    · hybrid:ZoomClimb: 0.002
```

### aggressive (n=4500 ticks across 3 matches)

**H1 — ∇V_pn 의 LOS-radial vs LOS-tangential 분해 (range bucket 별)**:

```
  - long_range_>8000ft: n=4392 median|gPN_dist|/|gPN_head|=441161.743 mean|gPN_dist|=7.416e-03 mean|gPN_head|=2.179e-07
  - medium_range_3000_8000: n=108 median|gPN_dist|/|gPN_head|=44.143 mean|gPN_dist|=1.891e-03 mean|gPN_head|=7.067e-05
  - short_range_<3000ft: (no ticks)
```

**H2** — `u_a<0` frac = 0.249, `V_e_clamp` frac = 0.507, intersection = 0.104

**H3 — 분기 점유 + Theorem 안 ρ 평균**:

```
  - theorem_frac=0.669
  - theorem mean ρ: pn=0.766 corner=0.063 ldt=0.010 yoyo=0.161
  - branch occupancy:
    · hybrid:Theorem: 0.669
    · hybrid:ZoomClimb: 0.152
    · hybrid:OrbitBreak: 0.140
    · hybrid:EnergyRecovery: 0.038
```


*Phase 2 진입* — confirmed 가설의 수리적 재유도 작업 (SUPERPLAN_v2 §3 Phase 2 A/B).
