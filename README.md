# AI Combat SDK

**AI Pilot 경진대회 참가자 개발 키트**

행동트리(YAML) 기반으로 공중전 AI를 개발하고, 다른 참가자와 대결하세요!

---

## 🚀 빠른 시작

### 1. 환경 설정

**한 줄 설치 (Windows PowerShell)**
```bash
python -m venv .venv; .venv\Scripts\activate; pip install -r requirements.txt
```

**단계별 설치**
```bash
# 가상환경 생성 및 활성화
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# 의존성 설치
pip install -r requirements.txt
```

### 2. 첫 번째 에이전트 테스트

```bash
# 예제 에이전트 검증
python tools/validate_agent.py examples/simple.yaml

# 챔피언 AI와 대전
python tools/test_agent.py simple --opponent ace
```

### 3. 나만의 에이전트 개발

```bash
# 1. examples/ 폴더에 YAML 파일 작성
# 2. 검증
python tools/validate_agent.py examples/my_agent.yaml

# 3. 테스트 대전
python tools/test_agent.py my_agent --opponent ace --rounds 5
```

📚 **자세한 가이드**: [docs/QUICK_START.md](docs/QUICK_START.md)

---

## 📋 주요 명령어

### 매치 실행
```bash
# 기본 매치 (submissions 또는 examples 폴더에서 자동 탐색)
python scripts/run_match.py --agent1 viper1 --agent2 ace
python scripts/run_match.py --agent1 viper1 --agent2 eagle1

# 다중 라운드
python scripts/run_match.py --agent1 viper1 --agent2 ace --rounds 3
```

### 매치 결과 시각화
1. **Tacview 설치**: [https://www.tacview.net/](https://www.tacview.net/) (무료 버전 사용 가능)
2. **리플레이 분석**: `replays/` 폴더의 `.acmi` 파일을 Tacview로 열기
3. **3D 전투 분석**: 전투 상황을 3D로 재생하며 전술 분석

---

## 📁 디렉토리 구조

```
ai-combat-sdk/
├── examples/           # 🎯 에이전트 YAML 파일 (여기서 작업!)
│   ├── simple.yaml           # 기본 AI
│   ├── ace.yaml              # 챔피언 AI
│   └── aggressive.yaml       # 공격형 AI
│
├── tools/              # 🛠️ 개발 도구
│   ├── validate_agent.py     # 제출 전 검증
│   └── test_agent.py         # 로컬 테스트 대전
│
├── docs/               # 📚 문서
│   ├── QUICK_START.md        # 5분 만에 시작하기
│   ├── NODE_REFERENCE.md     # 사용 가능한 모든 노드
│   └── PARAMETER_REFERENCE.md # 파라미터 상세 설명
│
├── config/             # ⚙️ 설정 파일
├── custom_nodes/       # 🔧 커스텀 노드 (고급)
├── scripts/            # 실행 스크립트
└── replays/            # 리플레이 파일 (.acmi)
```

---

## 📖 문서

| 문서 | 설명 |
|------|------|
| [QUICK_START.md](docs/QUICK_START.md) | 5분 만에 시작하기 |
| [NODE_REFERENCE.md](docs/NODE_REFERENCE.md) | 사용 가능한 모든 노드 |
| [PARAMETER_REFERENCE.md](docs/PARAMETER_REFERENCE.md) | 파라미터 상세 설명 |

---

## 🛠️ 개발 도구

| 도구 | 설명 | 사용법 |
|------|------|--------|
| `validate_agent.py` | 제출 전 검증 | `python tools/validate_agent.py my_agent.yaml` |
| `test_agent.py` | 로컬 테스트 대전 | `python tools/test_agent.py my_agent --rounds 5` |

---

## 🎯 에이전트 개발 가이드

### 기본 구조

```yaml
name: "my_agent"
description: "나만의 전투 전략"

tree:
  type: Selector
  children:
    - type: Sequence
      children:
        - type: Condition
          name: EnemyInRange
          params:
            max_distance: 2000
        - type: Action
          name: LeadPursuit
    
    - type: Action
      name: Pursue
```

### 주요 노드

**Condition (조건)**
- `EnemyInRange(max_distance)` - 적이 거리 내에 있는지
- `IsOffensiveSituation` - 공격 유리한 상황
- `IsDefensiveSituation` - 방어 필요한 상황
- `BelowHardDeck(threshold)` - 최저 고도 이하인지

**Action (행동)**
- `Pursue` - 기본 추적
- `LeadPursuit` - 선도 추적 (공격)
- `Evade` - 회피 기동
- `ClimbTo(altitude)` - 목표 고도로 상승
- `BreakTurn` - 급선회 회피

📚 **전체 노드 목록**: [docs/NODE_REFERENCE.md](docs/NODE_REFERENCE.md)

---

## 📝 제출 방법

1. `examples/` 폴더에 에이전트 YAML 파일 작성
2. `python tools/validate_agent.py my_agent.yaml`로 검증
3. 여러 상대와 테스트: `python tools/test_agent.py my_agent --opponent ace`
4. 대회 포털에 YAML 파일 업로드

---

## ❓ FAQ

**Q: 에이전트가 Hard Deck 위반으로 패배해요**
```yaml
# 최우선으로 고도 관리 추가
tree:
  type: Selector
  children:
    - type: Sequence
      children:
        - type: Condition
          name: BelowHardDeck
          params:
            threshold: 1500
        - type: Action
          name: ClimbTo
          params:
            target_altitude: 3000
    # ... 나머지 전술
```

**Q: 어떤 전략이 효과적인가요?**
- 거리별 전술 분리 (근/중/원거리)
- 상황별 대응 (공격/방어/정면)
- 고도 우위 확보
- 안전 장치 우선 (Hard Deck 회피)

**Q: 리플레이는 어떻게 보나요?**
- `replays/` 폴더의 `.acmi` 파일을 Tacview로 열기
- Tacview: https://www.tacview.net/

---

## 🏆 예제 에이전트

| 에이전트 | 전략 | 난이도 |
|----------|------|--------|
| `simple` | 기본 추적 | ⭐ |
| `aggressive` | 적극적 공격 | ⭐⭐ |
| `defensive` | 방어 중심 | ⭐⭐ |
| `ace` | 챔피언 AI | ⭐⭐⭐ |

---

## 📞 지원

- **GitHub Issues**: 버그 리포트 및 질문
- **문서**: `docs/` 폴더 참조
- **예제**: `examples/` 폴더 참고

---

**🛩️ 하늘을 지배할 당신의 AI를 개발하세요!**

Copyright © 2026 AI Combat Team. All rights reserved.
