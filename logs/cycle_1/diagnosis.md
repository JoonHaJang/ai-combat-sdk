# Cycle 1 진단 — 2026-04-12

## 검증 결과 요약
- Full Pool WR: **54.17%** (목표 65% 미달)
- 95% CI: 53.00% ~ 55.34%

## Per-layer WR
| Layer | WR | 상태 |
|---|---|---|
| L5 | 76.5% | ✅ |
| L4 | 73.4% | ✅ |
| L2 | 64.2% | ✅ |
| L6 | 38.3% | ❌ |
| L1 | 23.5% | ❌ |
| L3 | 19.2% | ❌ |

## 완패 상대 (10/10 패)
- L2_DistanceBelow_LagPursuit_ClimbTo
- L2_DistanceBelow_GunAttack_ClimbTo
- L2_EnergyAdvantage_LeadPursuit_Pursue
- L3_phase_LagPursuit_BarrelRoll_LagPursuit
- L5_OBFM_LONG_IGNORE_AGGRESSIVE
- L5_OBFM_LONG_TRADE_AGGRESSIVE
- L6_specific_energy
- L6_overshoot_guard

## 공통 패턴
`EnergyAdvantage`, `DistanceBelow`, `LONG`, `specific_energy` → 에너지/고도 우위 이용 전략에 일관 패배

## 근본 원인 (Phase 2/3 점검)
- energy obs 키 (`energy_advantage`, `energy_diff_ft`) 존재 확인 ✅
- IsHighEnergy / IsLowEnergy 단위 변환 불필요 (raw ft) ✅
- **Phase 2 버그 없음**

**Phase 3 문제**:
1. `enable_energy` default=`False` → CMA-ES가 에너지 branch를 탐색 시작점에서 제외
2. 에너지 branch = `IsHighEnergy` AND `IsOffensiveGeometry` → 이중 조건으로 거의 미발동
   → CMA-ES가 "이 branch는 쓸모없다" 판단 → disable 선택 → 에너지 관리 전혀 없음

## 되먹임 결정
**Phase 3 보강**: 에너지 branch 구조 수정 + 초기값 변경 후 CMA-ES 재실행
- 변경 대상: `tools/adaptive_optimizer.py`
- 변경 내용: `enable_energy` default True, 에너지 branch 조건 단순화
