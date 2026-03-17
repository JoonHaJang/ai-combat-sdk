# VSCode/Windsurf 환경 설정 가이드

> 💡 **SDK 설치 후 VSCode 환경 설정 방법입니다.**

---

## 🎯 추천 에디터

### VSCode (Visual Studio Code)
- **다운로드**: https://code.visualstudio.com/
- **장점**: 무료, 가볍고 빠름, 풍부한 확장 프로그램
- **추천 대상**: 모든 사용자

### Windsurf
- **다운로드**: https://codeium.com/windsurf
- **장점**: AI 코딩 어시스턴트(Cascade) 내장, VSCode 기반
- **추천 대상**: AI 도움을 받고 싶은 사용자

---

## 🚀 환경 설정 (최초 1회)

### 1. Python 가상환경 생성 및 활성화

VSCode 터미널(`Ctrl + `` `)에서:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

터미널 앞에 `(.venv)` 가 표시되면 정상입니다.

### 2. 패키지 설치

```powershell
pip install -r requirements.txt
```

### 3. VSCode 설정 파일 생성

프로젝트 루트에 `.vscode/settings.json` 파일 생성:

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}\\.venv\\Scripts\\python.exe",
  "python.terminal.activateEnvironment": true,
  "files.associations": {
    "*.yaml": "yaml"
  }
}
```

**효과**:
- ✅ 터미널 열 때마다 가상환경 자동 활성화
- ✅ Python 인터프리터 자동 선택
- ✅ YAML 파일 자동 인식

---

## 📦 권장 확장 프로그램

`Ctrl + Shift + X`에서 설치:

1. **Python** (`ms-python.python`) - Python 실행 및 가상환경 감지
2. **Pylance** (`ms-python.vscode-pylance`) - 코드 자동완성
3. **YAML** (`redhat.vscode-yaml`) - YAML 문법 검사
4. **Markdown All in One** (`yzhang.markdown-all-in-one`) - 문서 미리보기

또는 `.vscode/extensions.json` 파일 생성 후 VSCode 재시작:

```json
{
  "recommendations": [
    "ms-python.python",
    "ms-python.vscode-pylance",
    "redhat.vscode-yaml",
    "yzhang.markdown-all-in-one"
  ]
}
```

---

## 🎮 기본 사용법

### 프로젝트 열기

1. VSCode/Windsurf 실행
2. `File` → `Open Folder`
3. `ai-combat-sdk` 폴더 선택

### 터미널 열기

- **단축키**: `Ctrl + `` ` (백틱)
- **메뉴**: `Terminal` → `New Terminal`

터미널이 열리면 자동으로 가상환경이 활성화됩니다:
```
(.venv) PS D:\ai-combat-sdk>
```

### 에이전트 작성

1. 좌측 탐색기에서 `submissions` 폴더 우클릭
2. `New Folder` → `my_agent` 입력
3. `my_agent` 폴더 우클릭 → `New File` → `my_agent.yaml` 입력
4. YAML 파일 작성

### 테스트 실행

터미널에서:
```powershell
python scripts/run_match.py --agent1 my_agent --agent2 simple
```

---

## 💡 유용한 단축키

| 기능 | 단축키 |
|------|--------|
| 터미널 열기/닫기 | `Ctrl + `` ` |
| 파일 검색 | `Ctrl + P` |
| 전체 검색 | `Ctrl + Shift + F` |
| 명령 팔레트 | `Ctrl + Shift + P` |
| 사이드바 토글 | `Ctrl + B` |
| 저장 | `Ctrl + S` |

---

## 🤖 Windsurf 전용: Cascade AI 사용법

1. **Cascade 패널 열기**: `Ctrl + L`
2. **질문 예시**:
   ```
   "이 에이전트의 행동트리를 분석해줘"
   "공격적인 전술을 추가하려면 어떻게 해야 해?"
   ```
3. 한국어로 질문 가능, 코드 수정 자동 적용

---

## 🔧 문제 해결

### "Python 인터프리터를 찾을 수 없습니다"

1. `Ctrl + Shift + P` → "Python: Select Interpreter"
2. `.venv\Scripts\python.exe` 선택

### 터미널에서 가상환경이 활성화되지 않음

1. `.vscode/settings.json`에 `"python.terminal.activateEnvironment": true` 확인
2. VSCode 재시작

### PowerShell 실행 정책 오류

관리자 PowerShell에서:
```powershell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## 📚 다음 단계

- **[GUIDE.md](GUIDE.md)** - 첫 에이전트 만들기
- **[NODE_REFERENCE.md](NODE_REFERENCE.md)** - 노드 레퍼런스
