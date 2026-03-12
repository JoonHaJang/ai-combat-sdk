# Submissions

이 폴더는 여러분의 AI 에이전트를 개발하는 작업 공간입니다.

## 📁 디렉토리 구조

```
submissions/
├── my_agent/
│   ├── my_agent.yaml       # 행동트리 정의 (필수)
│   ├── nodes/              # 커스텀 노드 (선택)
│   │   ├── __init__.py
│   │   ├── custom_actions.py
│   │   └── custom_conditions.py
│   └── README.md           # 전략 설명 (선택)
└── another_agent/
    └── another_agent.yaml
```

## 🔒 Git 충돌 방지

이 폴더의 내용은 `.gitignore`에 의해 **버전 관리에서 제외**됩니다.
따라서 SDK를 업데이트(git pull)해도 여러분의 작업물이 손실되거나 충돌하지 않습니다.

## 💡 사용 방법

1. 새 에이전트 폴더 생성: `submissions/my_agent/`
2. 행동트리 파일 작성: `my_agent.yaml`
3. 테스트: `python scripts/run_match.py --agent1 my_agent --agent2 simple`
4. 제출: 웹사이트를 통해 `.yaml` 파일 업로드

## 📦 백업 권장

중요한 작업물은 별도로 백업하거나 개인 Git 저장소에 보관하세요.
