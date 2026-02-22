# Eagle1 - AI Combat Agent

**Callsign:** Eagle1  
**전술:** 균형잡힌 방어와 공격

---

## 전략 개요

Eagle1은 방어와 공격의 균형을 맞춘 전술을 사용하는 기본 전투 AI입니다. 커스텀 노드 없이 기본 노드만으로 구현된 초보자용 예시입니다.

## 의사결정 로직

### 1. 안전 우선 (Hard Deck)
고도 1200m 이하로 내려가면 즉시 3000m로 상승합니다.

### 2. 위협 대응
적이 나를 정면으로 조준하고 있으면 (AA < 54도) 방어 기동을 수행합니다.

### 3. 고도 우위
적보다 300m 이상 낮으면 고도 우위를 확보합니다 (목표: +400m).

### 4. 근거리 공격
적과의 거리가 2500m 이하면 Lead Pursuit로 정확한 추적을 수행합니다.

### 5. 기본 추적
위 조건이 모두 해당하지 않으면 기본 Pursue 액션을 수행합니다.

## 강점

- **안전성**: Hard Deck 위반 방지
- **적응성**: 위협 상황에 즉각 대응
- **공격성**: 고도 우위와 정확한 추적

## 약점

- 매우 공격적인 적에게 취약할 수 있음
- 에너지 관리가 최적화되지 않음

## 개선 방안

1. 속도 관리 로직 추가
2. 거리별 전술 세분화
3. 적의 에너지 상태 고려

## 실행 방법

```bash
# Eagle1 vs Simple Fighter
python scripts/run_match.py --agent1 eagle1 --agent2 simple_fighter

# Eagle1 vs Ace Fighter
python scripts/run_match.py --agent1 eagle1 --agent2 ace_fighter --rounds 3
```

---

**Callsign: Eagle1**  
*"Balanced and steady."*
