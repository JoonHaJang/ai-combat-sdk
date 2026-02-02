# Viper1 - AI Combat Agent

**Callsign:** Viper1  
**전술:** 공격적 추적 + 에너지 관리

---

## 전략 개요

Viper1은 공격적 추적과 에너지 관리를 결합한 전투 AI입니다. 행동트리 기반으로 상황에 따라 적응적으로 전술을 변경하며, 커스텀 노드를 활용하여 독특한 기동을 수행합니다.

---

## 행동트리 구조

### 우선순위 (Selector)

1. **Hard Deck 회피** (최우선)
   - 조건: `BelowHardDeck`
   - 행동: 2000m까지 상승

2. **방어 기동**
   - 조건: `IsDefensiveSituation`
   - 행동: `DefensiveManeuver`

3. **커스텀 공격 기동** ⭐
   - 조건: `IsOffensiveSituation` + `EnemyInRange(3000m)`
   - 행동: `ViperStrike` (커스텀 액션)

4. **고도 우위 확보**
   - 조건: `EnemyInRange(5000m)` + `AltitudeBelow(100m)`
   - 행동: `AltitudeAdvantage(500m)`

5. **기본 추적**
   - 행동: `Pursue`

---

## 커스텀 노드

### 액션 노드 (`custom_actions.py`)

#### 1. `ViperStrike`
**공격적 추적 기동**

특징:
- TAU 기반 정밀 추적
- 거리별 속도 최적화
  - 600m 미만: 감속 (안정적 조준)
  - 600-1200m: 유지
  - 1200-2500m: 가속
  - 2500m 이상: 급가속
- 고도 우위 유지 (적보다 높은 위치 선호)

#### 2. `EnergyManeuver`
**에너지 관리 기동**

특징:
- 에너지 상태 계산: `E = altitude + velocity² / 20`
- 저에너지(< 8000): 속도 증가 + 하강
- 고에너지(> 12000): 고도 전환 + 감속
- 중간 에너지: 균형 유지

### 조건 노드 (`custom_conditions.py`)

#### 1. `HighEnergyState`
- 에너지 > 12000 확인

#### 2. `LowEnergyState`
- 에너지 < 8000 확인

#### 3. `OptimalAttackPosition`
- 거리: 800-2500m (WEZ 범위)
- ATA: < 30도
- 고도 우위 확보

---

## 전술 특징

### 강점
1. **공격성**: 유리한 상황에서 적극적 추적
2. **에너지 관리**: 속도-고도 트레이드오프 최적화
3. **안전성**: Hard Deck 회피 우선
4. **적응성**: 상황별 전술 자동 전환

### 약점
1. 방어 상황에서 탈출 능력 제한적
2. 에너지 계산이 단순화됨
3. 적의 전술 패턴 학습 없음

---

## 실행 방법

```bash
# Viper1 vs Ace Fighter
python scripts/run_match.py --agent1 viper1 --agent2 ace_fighter

# 3라운드 매치
python scripts/run_match.py --agent1 viper1 --agent2 simple_fighter --rounds 3
```

---

## 개발 노트

### 커스텀 노드 개발 가이드

1. **BaseAction 상속**
   ```python
   class MyCustomAction(BaseAction):
       def __init__(self, name: str = "MyCustomAction"):
           super().__init__(name)
       
       def update(self) -> py_trees.common.Status:
           obs = self.blackboard.observation
           # 로직 구현
           self.set_action(delta_altitude_idx, delta_heading_idx, delta_velocity_idx)
           return py_trees.common.Status.SUCCESS
   ```

2. **YAML에서 사용**
   ```yaml
   - type: Action
     name: MyCustomAction
     params:
       param1: value1
   ```

---

## 향후 개선 방안

1. **적 모델링**: 적의 행동 패턴 예측
2. **동적 임계값**: 상대에 따른 파라미터 조정
3. **고급 에너지 관리**: 정확한 비에너지 계산
4. **미사일 회피**: 미사일 발사 감지 및 회피 기동

---

## 라이센스

MIT License

---

**Callsign: Viper1**  
*"Strike fast, strike hard."*
