# Cycle 1 → Cycle 2 변경사항

## 대상 Phase: Phase 3 (탐색 공간 & 최적화)

## 변경 파일: `tools/adaptive_optimizer.py`

### 변경 1: enable_energy 초기값 True로
```python
# Before
"enable_energy": False,

# After
"enable_energy": True,
```
이유: CMA-ES가 에너지 branch를 처음부터 탐색하도록 강제.

### 변경 2: 에너지 branch 조건 단순화
```python
# Before (이중 조건 — 거의 미발동)
IsHighEnergy AND IsOffensiveGeometry → energy_action

# After (단일 조건)
IsLowEnergy → SmartClimbingTurn  (에너지 부족 시 회복 우선)
```
이유: 에너지가 낮을 때 무조건 회복 기동 → 고도/에너지 열위 상황 탈출.
