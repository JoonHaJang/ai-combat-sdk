# Cycle 2 Diagnosis

## 결과 요약
- **최고 점수**: 223.49 (gen 8, eval 303/400)
- **최고 W/D/L**: 22/15/3 (샘플: 40 matches)
- **WR (샘플)**: ~55% (Full Pool Validation 대기 중)
- **실행 시간**: 약 9-10시간 (budget=400, workers=48)

## Cycle 1 대비 개선
| 지표 | Cycle 1 | Cycle 2 |
|------|---------|---------|
| CMA-ES score | - (측정 안 함) | 223.49 |
| 샘플 W/L | - | 22/3 |
| Phase 3 fix | ❌ enable_energy=False | ✅ enable_energy=True |
| Energy branch | ❌ 이중 조건 (발화 안 함) | ✅ 2개 독립 branch |

## BEST 점수 수렴 패턴
```
gen 1  eval 29  → 189.26  *** (첫 양수 돌파)
gen 3  eval 112 → 189.96
gen 6  eval 207 → 207.54
gen 8  eval 303 → 223.49  *** (최종 BEST)
gen 9~10        → 개선 없음 (수렴)
```
→ gen 8 이후 97개 eval 동안 갱신 없음: 현재 BT 구조에서 로컬 최적점 도달.

## 개선 사항 (다음 Phase)

### 속도 문제
- max_steps=1500 → 800 권장 (대부분 매치 600 steps 내 종료)
- multi-fidelity eval: 10-match 필터 → 상위 30%만 full eval
- 예상 속도: 12h → 3-4h/cycle

### EIM 통합 확장
- 현재: NEUTRAL_CIRCLE 1개 intent만 CMA-ES 파라미터로 응답
- 목표: PURSUIT, NEUTRAL_SCISSORS, GUN_ATTACK 추가 (+10 dims)
- CMA-ES가 어느 intent에 반응할지 자동 결정

### SE 품질 (GAP-1~5)
- Unit tests, CI/CD, data parity 테스트 부재
- tests/ 디렉토리 + .github/workflows/ci.yml 구축 예정

## Cycle 3 계획
- warm-start: `--init-from logs/cycle_2/best_params.json`
- Phase C (속도 개선) 적용 후 실행
- 목표: WR 58%+
