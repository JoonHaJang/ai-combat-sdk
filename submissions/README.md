# Submissions - 참여자 제출 디렉토리

이 디렉토리는 참여자들이 자신의 AI 에이전트를 제출하는 공간입니다.

---

## 📁 디렉토리 구조

각 에이전트는 독립된 폴더에 다음과 같은 구조로 작성하세요:

```
submissions/
├── my_agent/                  # 에이전트 이름 (영문, 소문자, 언더스코어)
│   ├── my_agent.yaml         # 행동트리 정의 (필수)
│   ├── README.md             # 전략 설명 (권장)
│   └── nodes/                # 커스텀 노드 (선택)
│       ├── __init__.py
│       ├── custom_actions.py
│       └── custom_conditions.py
├── viper1/                    # 예제: 커스텀 노드 사용
└── eagle1/                    # 예제: 기본 노드만 사용
```

---

## 📝 제출 가이드

### 1. 에이전트 이름 규칙

- **영문 소문자 + 숫자 + 언더스코어만 사용**
- 예: `my_agent`, `falcon_1`, `ace_fighter`
- 금지: `My-Agent`, `에이전트1`, `agent!`

### 2. 필수 파일

#### `my_agent.yaml`
행동트리 정의 파일입니다.

```yaml
name: "my_agent"
description: "간단한 설명"

tree:
  type: Selector
  children:
    # Hard Deck 회피 (필수!)
    - type: Sequence
      children:
        - type: Condition
          name: BelowHardDeck
          params:
            threshold: 1000
        - type: Action
          name: ClimbTo
          params:
            target_altitude: 3000
    
    # 나머지 전술
    - type: Action
      name: Pursue
```

### 3. 권장 파일

#### `README.md`
에이전트의 전략과 특징을 설명하세요.

```markdown
# My Agent

**전술:** 공격적 추적

## 전략 개요
...

## 강점
- ...

## 약점
- ...
```

### 4. 선택 파일

#### 커스텀 노드 (`nodes/`)

커스텀 액션이나 조건이 필요한 경우에만 작성하세요.

**`nodes/__init__.py`**
```python
from .custom_actions import *
from .custom_conditions import *
```

**`nodes/custom_actions.py`**
```python
from lib.behavior_tree.nodes.actions import BaseAction
import py_trees

class MyCustomAction(BaseAction):
    def __init__(self, name: str = "MyCustomAction"):
        super().__init__(name)
    
    def update(self) -> py_trees.common.Status:
        obs = self.blackboard.observation
        # 로직 구현
        self.set_action(2, 4, 2)
        return py_trees.common.Status.SUCCESS
```

---

## ✅ 검증

제출 전 반드시 검증하세요:

```bash
# 에이전트 검증
python sdk/tools/validate_agent.py my_agent

# 테스트 대전
python scripts/run_match.py --agent1 my_agent --agent2 simple
```

---

## ⚠️ 주의사항

### Hard Deck 위반 방지

**고도 500m 이하로 내려가면 즉시 패배합니다!**

반드시 Hard Deck 회피 로직을 최우선 순위로 포함하세요:

```yaml
tree:
  type: Selector
  children:
    # 최우선: Hard Deck 회피
    - type: Sequence
      children:
        - type: Condition
          name: BelowHardDeck
          params:
            threshold: 1000
        - type: Action
          name: ClimbTo
          params:
            target_altitude: 3000
    
    # 나머지 전술...
```

### 파일 크기 제한

- YAML 파일: 50KB 이하
- 커스텀 노드: 각 파일 100KB 이하
- 전체 에이전트: 500KB 이하

### 금지 사항

- ❌ 외부 네트워크 접근
- ❌ 파일 시스템 수정
- ❌ 무한 루프
- ❌ 과도한 메모리 사용

---

## 📚 참고 문서

- [빠른 시작 가이드](../sdk/docs/QUICK_START.md)
- [노드 레퍼런스](../sdk/docs/NODE_REFERENCE.md)
- [파라미터 레퍼런스](../sdk/docs/PARAMETER_REFERENCE.md)

---

## 🎯 예제 에이전트

### Viper1 (`viper1/`)
- **커스텀 노드 사용 예시**
- 공격적 추적 + 에너지 관리
- `ViperStrike`, `EnergyManeuver` 커스텀 액션
- `OptimalAttackPosition` 커스텀 조건

### Eagle1 (`eagle1/`)
- **기본 노드만 사용**
- 균형잡힌 방어와 공격
- 초보자 추천

---

## 🏆 제출 방법

### 방법 1: 압축 파일

```bash
# 에이전트 폴더 압축
cd submissions
zip -r my_agent.zip my_agent/

# 또는 tar
tar -czf my_agent.tar.gz my_agent/
```

### 방법 2: GitHub 저장소

```bash
# 자신의 저장소에 푸시
git add submissions/my_agent/
git commit -m "Add my_agent"
git push origin main
```

---

## 💡 팁

### 1. 예제 에이전트 참고
- `viper1/`과 `eagle1/`을 먼저 분석하세요
- 커스텀 노드가 필요한지 판단하세요

### 2. 점진적 개발
1. 기본 노드로 시작
2. 테스트 대전으로 검증
3. 필요시 커스텀 노드 추가
4. 파라미터 튜닝

### 3. 디버깅
- 리플레이 파일(`.acmi`)로 전투 분석
- TacView로 3D 시각화
- 로그 확인

---

**Good luck, pilot! 🚀**
