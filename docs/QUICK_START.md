# 빠른 시작 가이드

**5분 만에 첫 번째 AI 전투기 만들기**

---

## 1. 환경 설정

```bash
# 저장소 클론
git clone https://github.com/your-repo/ai-combat-sdk.git
cd ai-combat-sdk

# 가상환경 생성 및 활성화
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# 의존성 설치
pip install -r requirements.txt
```

---

## 2. 첫 번째 에이전트 만들기

`examples/my_first_agent.yaml` 파일을 생성하세요:

```yaml
name: "My First Agent"
version: "1.0"
description: "나의 첫 번째 AI 전투기"

root:
  type: Selector
  children:
    # 1. Hard Deck 회피 (필수!)
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

    # 2. 적 추적
    - type: Action
      name: Pursue
```

---

## 3. 에이전트 검증

```bash
python tools/validate_agent.py my_first_agent
```

출력:
```
🔍 에이전트 검증: my_first_agent.yaml

✅ 검증 통과! 제출 가능합니다.
```

---

## 4. 테스트 대전

```bash
python tools/test_agent.py my_first_agent --opponent simple
```

출력:
```
🎮 에이전트 테스트 시작
   에이전트: my_first_agent
   상대: simple
   라운드: 1

--- Round 1/1 ---
✅ 승리!

📊 결과: 1승 0패 (승률: 100.0%)
```

---

## 5. 다음 단계

- **[NODE_REFERENCE.md](NODE_REFERENCE.md)**: 사용 가능한 모든 노드 목록
- **[PARAMETER_REFERENCE.md](PARAMETER_REFERENCE.md)**: 파라미터 상세 설명
- **[examples/](../../examples/)**: 다양한 예제 에이전트

---

## 디렉토리 구조

```
ai-combat-sdk/
├── examples/           # 에이전트 YAML 파일 (여기에 작성!)
├── submissions/        # 제출용 에이전트 폴더
├── tools/              # 테스트/검증 도구
├── docs/               # 문서
├── config/             # 설정 파일 (WEZ, 매치 규칙)
├── custom_nodes/       # 커스텀 노드 (고급)
├── scripts/            # 실행 스크립트
└── replays/            # 리플레이 파일 (.acmi)
```

---

## TacView로 리플레이 보기

1. [TacView](https://www.tacview.net/) 다운로드 (무료 버전 가능)
2. `replays/*.acmi` 파일 열기
3. 전투 상황 3D로 분석!
