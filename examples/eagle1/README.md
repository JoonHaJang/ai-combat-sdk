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

## Dogfight 2 실시간 3D 시각화

Eagle1 대전을 Dogfight 2에서 실시간으로 확인할 수 있습니다.

### 사전 준비

Dogfight 2 (Harfang3D Sandbox)가 설치 및 패치된 상태여야 합니다.
→ [DOGFIGHT2_INTEGRATION.md](../../docs/DOGFIGHT2_INTEGRATION.md) 참고

### 실행 (터미널 2개 필요)

**터미널 1 — Dogfight 2 시작:**
```bash
cd dogfight-sandbox-hg2/source
python main.py
# 게임에서 "Network mode" 미션 선택 (첫 번째 미션)
```

**터미널 2 — Eagle1 매치 실행:**
```bash
# Eagle1 vs Simple Fighter — Dogfight 2 시각화 포함
python scripts/run_match.py --agent1 eagle1 --agent2 simple_fighter --dogfight2

# Eagle1 vs Viper1
python scripts/run_match.py --agent1 eagle1 --agent2 viper1 --dogfight2

# 3라운드 + 시각화
python scripts/run_match.py --agent1 eagle1 --agent2 ace_fighter --rounds 3 --dogfight2

# 호스트/포트를 직접 지정할 경우
python scripts/run_match.py --agent1 eagle1 --agent2 ace_fighter --dogfight2 --df2-host 127.0.0.1 --df2-port 50888
```

### 연결 테스트

```bash
python scripts/test_df2_connection.py
```

> Dogfight 2가 실행 중이지 않으면 `--dogfight2` 플래그 없이도 일반 시뮬레이션은 정상 동작합니다.

---

**Callsign: Eagle1**  
*"Balanced and steady."*
