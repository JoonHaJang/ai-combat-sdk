# AI Combat SDK

**AI Pilot 경진대회 참가자 개발 키트**

---

## 빠른 시작

```bash
# 1. 환경 설정
pip install -r requirements.txt

# 2. 에이전트 검증
python sdk/tools/validate_agent.py my_agent.yaml

# 3. 테스트 대전
python sdk/tools/test_agent.py my_agent --opponent ace_fighter
```

자세한 내용은 [docs/QUICK_START.md](docs/QUICK_START.md) 참조

---

## 디렉토리 구조

```
ai-combat-sdk/
├── examples/           # 🎯 에이전트 YAML (여기서 작업!)
│   ├── my_agent.yaml  
│   ├── ace_fighter.yaml      # 챔피언 AI
│   └── simple_fighter.yaml   # 기본 AI
│
├── config/             # ⚙️ 설정 파일
│   ├── wez_params.yaml       # WEZ 파라미터
│   └── match_rules.yaml      # 매치 규칙
│
├── custom_nodes/       # 🔧 커스텀 노드 (고급)
│   ├── custom_actions.py
│   └── custom_conditions.py
│
├── sdk/
│   ├── docs/           # 📚 문서
│   │   ├── QUICK_START.md
│   │   ├── NODE_REFERENCE.md
│   │   └── OBSERVATION_SPACE.md
│   └── tools/          # 🛠️ 개발 도구
│       ├── test_agent.py
│       └── validate_agent.py
│
├── scripts/            # 실행 스크립트
└── replays/            # 리플레이 파일 (.acmi)
```

---

## 문서

| 문서 | 설명 |
|-----|------|
| [QUICK_START.md](docs/QUICK_START.md) | 5분 만에 시작하기 |
| [NODE_REFERENCE.md](docs/NODE_REFERENCE.md) | 사용 가능한 모든 노드 |
| [OBSERVATION_SPACE.md](docs/OBSERVATION_SPACE.md) | 관측 변수 상세 |

---

## 도구

| 도구 | 설명 | 사용법 |
|-----|------|--------|
| `validate_agent.py` | 제출 전 검증 | `python sdk/tools/validate_agent.py my_agent` |
| `test_agent.py` | 로컬 테스트 | `python sdk/tools/test_agent.py my_agent --rounds 5` |

---

## 제출 방법

1. `examples/` 폴더에 에이전트 YAML 파일 작성
2. `validate_agent.py`로 검증 통과 확인
3. 대회 포털에 YAML 파일 업로드

---

## 라이선스

Copyright © 2026 AI Combat Team. All rights reserved.
