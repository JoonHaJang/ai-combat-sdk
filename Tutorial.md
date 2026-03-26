# AI Combat SDK 초기 세팅 튜토리얼

이 문서는 AI Combat SDK를 처음 시작하는 분들을 위한 완벽한 초기 세팅 가이드입니다.

---

## 목차

1. [사전 준비사항](#사전-준비사항)
2. [GitHub Fork 생성](#github-fork-생성)
3. [로컬에 저장소 클론](#로컬에-저장소-클론)
4. [원격 저장소 설정](#원격-저장소-설정)
5. [가상 환경 설정](#가상-환경-설정)
6. [의존성 설치](#의존성-설치)
7. [설정 확인](#설정-확인)
8. [다음 단계](#다음-단계)

---

## 사전 준비사항

시작하기 전에 다음 프로그램들이 설치되어 있어야 합니다:

### 필수 프로그램

1. **Python 3.14**
   - 다운로드: https://www.python.org/downloads/
   - ⚠️ 설치 시 **"Add Python to PATH"** 체크박스를 반드시 선택하세요!
   - 설치 확인:
     ```powershell
     python --version
     ```

2. **Git**
   - 다운로드: https://git-scm.com/download/win
   - 설치 확인:
     ```powershell
     git --version
     ```

3. **VSCode** (권장)
   - 다운로드: https://code.visualstudio.com/
   - 또는 Windsurf IDE 사용 가능

---

## GitHub Fork 생성

Fork는 원본 저장소를 본인의 GitHub 계정으로 복사하는 것입니다. 이를 통해 원본에 영향을 주지 않고 자유롭게 수정할 수 있습니다.

### 단계별 가이드

1. **원본 저장소 방문**
   - 브라우저에서 https://github.com/songhyonkim/ai-combat-sdk 접속

2. **Fork 버튼 클릭**
   - 페이지 우측 상단의 **"Fork"** 버튼 클릭
   - GitHub 계정에 로그인되어 있어야 합니다

3. **Fork 생성 확인**
   - Fork가 생성되면 `https://github.com/[본인계정]/ai-combat-sdk`로 이동됩니다
   - 예시: `https://github.com/JoonHaJang/ai-combat-sdk`

✅ **완료!** 이제 본인의 GitHub 계정에 저장소 사본이 생성되었습니다.

---

## 로컬에 저장소 클론

이제 GitHub에 있는 저장소를 본인의 컴퓨터로 다운로드합니다.

### 1. 작업 디렉토리로 이동

PowerShell 또는 터미널을 열고 작업할 폴더로 이동합니다:

```powershell
cd c:\Users\Joon\Desktop\AI-pilot\AI_Pilot
```

> 💡 **팁**: 본인의 작업 경로에 맞게 수정하세요!

### 2. 원본 저장소 클론

```powershell
git clone https://github.com/songhyonkim/ai-combat-sdk.git
```

### 3. 클론된 디렉토리로 이동

```powershell
cd ai-combat-sdk
```

### 4. 디렉토리 구조 확인

```powershell
dir
```

다음과 같은 폴더들이 보여야 합니다:
- `config/` - 매치 설정 파일
- `docs/` - 문서
- `examples/` - 예제 에이전트
- `scripts/` - 실행 스크립트
- `src/` - 핵심 엔진
- `submissions/` - 참가자 제출 디렉토리
- `requirements.txt` - Python 의존성 목록
- `README.md` - 프로젝트 설명

---

## 원격 저장소 설정

클론한 저장소를 본인의 Fork와 연결해야 합니다.

### 원격 저장소 개념 이해

- **`origin`**: 본인의 Fork (작업 내용을 푸시할 곳)
- **`upstream`**: 원본 저장소 (최신 업데이트를 가져올 곳)

### 1. origin을 본인의 Fork로 변경

```powershell
git remote set-url origin https://github.com/[본인계정]/ai-combat-sdk.git
```

**예시:**
```powershell
git remote set-url origin https://github.com/JoonHaJang/ai-combat-sdk.git
```

### 2. upstream 원격 저장소 추가

```powershell
git remote add upstream https://github.com/songhyonkim/ai-combat-sdk.git
```

### 3. 설정 확인

```powershell
git remote -v
```

**올바른 출력 예시:**
```
origin    https://github.com/JoonHaJang/ai-combat-sdk.git (fetch)
origin    https://github.com/JoonHaJang/ai-combat-sdk.git (push)
upstream  https://github.com/songhyonkim/ai-combat-sdk.git (fetch)
upstream  https://github.com/songhyonkim/ai-combat-sdk.git (push)
```

✅ **완료!** 이제 원격 저장소가 올바르게 설정되었습니다.

---

## 가상 환경 설정

Python 가상 환경은 프로젝트별로 독립된 Python 패키지 환경을 만들어줍니다.

### 1. 가상 환경 생성

```powershell
python -m venv .venv
```

> 💡 `.venv`는 가상 환경 폴더 이름입니다. 이 폴더는 `.gitignore`에 포함되어 있어 Git에 업로드되지 않습니다.

### 2. 가상 환경 활성화

**Windows PowerShell:**
```powershell
.venv\Scripts\activate
```

**Windows CMD:**
```cmd
.venv\Scripts\activate.bat
```

**Linux/Mac:**
```bash
source .venv/bin/activate
```

> ⚠️ **PowerShell 실행 정책 오류 발생 시**
> 
> "스크립트를 실행할 수 없습니다" 오류가 발생하면 다음 명령어를 실행하세요:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> 확인 메시지가 나오면 `Y`를 입력하고 Enter를 누른 후, 다시 `.venv\Scripts\activate`를 실행하세요.

### 3. 활성화 확인

터미널 프롬프트 앞에 `(.venv)`가 표시되면 성공입니다:

```
(.venv) PS C:\Users\Joon\Desktop\AI-pilot\AI_Pilot\ai-combat-sdk>
```

> ⚠️ **중요**: 앞으로 모든 작업은 가상 환경이 활성화된 상태에서 진행해야 합니다!

---

## 의존성 설치

프로젝트에 필요한 Python 패키지들을 설치합니다.

### 1. pip 업그레이드 (권장)

```powershell
python -m pip install --upgrade pip
```

### 2. 의존성 설치

```powershell
pip install -r requirements.txt
```

설치되는 주요 패키지:
- `numpy` - 수치 연산
- `pyyaml` - YAML 파일 파싱
- `gymnasium` - 강화학습 환경
- 기타 필요한 라이브러리들

### 3. 설치 확인

```powershell
pip list
```

설치된 패키지 목록이 표시되면 성공입니다.

---

## 설정 확인

모든 설정이 올바르게 되었는지 확인합니다.

### 1. 예제 에이전트 검증

```powershell
python tools/validate_agent.py examples/simple.yaml
```

**성공 시 출력:**
```
✓ Agent validation successful!
```

### 2. 테스트 대전 실행

```powershell
python scripts/run_match.py --agent1 simple --agent2 aggressive
```

💡 **설명**: `simple` 에이전트와 `aggressive` 에이전트가 1:1 공중전을 펼칩니다.

**대전 진행 중 출력 정보:**
- 각 스텝별 상황 (고도, 속도, 거리, ATA, AA 등)
- Gun WEZ 진입 시 데미지 발생
- 최종 승패 결과 및 통계

대전이 실행되고 결과가 표시되면 모든 설정이 완료된 것입니다!

### 3. 리플레이 파일 확인

```powershell
dir replays
```

`.acmi` 확장자 파일이 생성되었다면 성공입니다. 이 파일은 [TacView](https://www.tacview.net/)로 열어서 3D로 전투 상황을 분석할 수 있습니다.

**TacView 다운로드**: https://www.tacview.net/ (무료 버전 사용 가능)

---

## 🎉 초기 세팅 완료!

축하합니다! 모든 초기 세팅이 완료되었습니다. 이제 본격적으로 AI 에이전트 개발을 시작할 수 있습니다.

---

## 다음 단계

축하합니다! 🎉 초기 세팅이 완료되었습니다. 이제 본격적으로 AI 에이전트를 개발할 차례입니다.

### 1. 첫 번째 에이전트 만들기

`submissions/my_agent/` 폴더를 생성하고 `my_agent.yaml` 파일을 작성하세요:

```powershell
mkdir submissions\my_agent
```

**`submissions/my_agent/my_agent.yaml` 예시:**

```yaml
name: "my_agent"
description: "나의 첫 번째 AI 전투기"

tree:
  type: Selector
  children:
    # 1. Hard Deck 회피 (필수!)
    - type: Sequence
      children:
        - type: Condition
          name: BelowHardDeck
          params:
            threshold_ft: 3281
        - type: Action
          name: ClimbTo
          params:
            target_altitude_ft: 9843

    # 2. 공격 상황 → 선도 추적
    - type: Sequence
      children:
        - type: Condition
          name: IsOffensiveSituation
        - type: Action
          name: LeadPursuit

    # 3. 방어 상황 → 급선회 회피
    - type: Sequence
      children:
        - type: Condition
          name: IsDefensiveSituation
        - type: Action
          name: BreakTurn

    # 4. 기본 추적
    - type: Action
      name: Pursue
```

### 2. 에이전트 검증

```powershell
python tools/validate_agent.py submissions/my_agent/my_agent.yaml
```

### 3. 테스트 대전

```powershell
python scripts/run_match.py --agent1 my_agent --agent2 simple
```

### 4. 다중 라운드 테스트

```powershell
python scripts/run_match.py --agent1 my_agent --agent2 eagle1 --rounds 5
```

---

## 추가 학습 자료

### 필수 문서

1. **[docs/GUIDE.md](docs/GUIDE.md)**
   - 튜토리얼
   - 전략 개발 가이드
   - 커스텀 노드 작성법
   - 로깅 및 디버깅

2. **[docs/NODE_REFERENCE.md](docs/NODE_REFERENCE.md)**
   - 전체 노드 레퍼런스
   - 파라미터 설명
   - 사용 예시

3. **[docs/VSCODE_SETUP.md](docs/VSCODE_SETUP.md)**
   - VSCode/Windsurf 환경 설정
   - 추천 확장 프로그램

### 예제 에이전트 분석

`examples/` 폴더의 에이전트들을 분석하며 학습하세요:

- `simple.yaml` - 기본 추적 전략
- `aggressive.yaml` - 공격적 전략
- `defensive.yaml` - 방어적 전략
- `eagle1/eagle1.yaml` - 고급 전략

---

## 원본 저장소 업데이트 동기화

SDK가 업데이트되면 다음 명령어로 최신 버전을 받아올 수 있습니다:

### 1. upstream에서 최신 변경사항 가져오기

```powershell
git fetch upstream
```

### 2. 현재 브랜치에 병합

```powershell
git merge upstream/main
```

### 3. 본인의 Fork에 푸시

```powershell
git push origin main
```

> ✅ `submissions/`, `replays/`, `tournament_data/` 폴더는 `.gitignore`에 의해 보호되므로 안전합니다.

---

## 작업 내용 저장하기

### 1. 변경사항 확인

```powershell
git status
```

### 2. 변경사항 스테이징

```powershell
git add .
```

특정 파일만 추가:
```powershell
git add submissions/my_agent/my_agent.yaml
```

### 3. 커밋

```powershell
git commit -m "feat: Add my_agent with basic BFM strategy"
```

### 4. GitHub에 푸시

```powershell
git push origin main
```

---

## 문제 해결

### 가상 환경 활성화가 안 될 때

**PowerShell 실행 정책 오류:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Python 버전 확인

```powershell
python --version
```

Python 3.14가 아니라면 올바른 버전을 설치하세요.

### 패키지 설치 오류

```powershell
pip install --upgrade pip
pip install -r requirements.txt --no-cache-dir
```

### Git 원격 저장소 오류

원격 저장소 재설정:
```powershell
git remote remove origin
git remote add origin https://github.com/[본인계정]/ai-combat-sdk.git
```

---

## 유용한 명령어 모음

### 에이전트 관련

```powershell
# 에이전트 검증
python tools/validate_agent.py submissions/my_agent/my_agent.yaml

# 단판 대전
python scripts/run_match.py --agent1 my_agent --agent2 simple

# 다중 라운드 대전
python scripts/run_match.py --agent1 my_agent --agent2 eagle1 --rounds 5

# 토너먼트 실행
python scripts/run_tournament.py
```

### Git 관련

```powershell
# 상태 확인
git status

# 변경사항 확인
git diff

# 커밋 히스토리
git log --oneline

# 브랜치 확인
git branch

# 원격 저장소 확인
git remote -v
```

### 가상 환경 관련

```powershell
# 활성화 (Windows)
.venv\Scripts\activate

# 비활성화
deactivate

# 설치된 패키지 목록
pip list

# 패키지 업데이트
pip install --upgrade [패키지명]
```

---

## 지원 및 커뮤니티

- **GitHub Issues**: 버그 리포트 및 질문
- **예제 코드**: `examples/`, `submissions/` 폴더 참고
- **문서**: `docs/` 폴더의 상세 가이드

---

## 체크리스트

초기 세팅이 완료되었는지 확인하세요:

- [ ] Python 3.14 설치 완료
- [ ] Git 설치 완료
- [ ] GitHub에서 Fork 생성 완료
- [ ] 로컬에 저장소 클론 완료
- [ ] 원격 저장소 설정 완료 (origin, upstream)
- [ ] 가상 환경 생성 및 활성화 완료
- [ ] 의존성 설치 완료
- [ ] 예제 에이전트 검증 성공
- [ ] 테스트 대전 실행 성공
- [ ] 리플레이 파일 생성 확인
- [ ] (선택) Dogfight 2 실행 및 `--dogfight2` 시각화 확인

모든 항목이 체크되었다면 축하합니다! 

---

## 🎮 Dogfight 2 실시간 시각화

TacView(사후 분석) 외에 실시간 3D 시각화를 원한다면 Dogfight 2를 사용할 수 있습니다.
Dogfight 2 소스코드는 저장소에 이미 포함되어 있으므로 **별도 clone 없이 바로 사용 가능합니다.**

> 💡 `requirements.txt`에 harfang과 tqdm이 포함되어 있으므로 의존성 설치도 별도 작업이 없습니다.

### 실행

**터미널 1 — Dogfight 2 시작:**

```powershell
cd dogfight-sandbox-hg2\source
..\..\..\.venv\Scripts\python main.py
```

게임이 시작되면 **"Network mode"** 미션을 선택합니다 (첫 번째 미션).

**터미널 2 — 매치 실행 + 3D 시각화:**

```powershell
.venv\Scripts\python scripts/run_match.py --agent1 eagle1 --agent2 viper1 --dogfight2
```

### 연결 테스트

```powershell
.venv\Scripts\python scripts/test_df2_connection.py
```

### 주요 옵션

| 옵션 | 설명 |
|------|------|
| `--dogfight2` | DF2 시각화 활성화 |
| `--df2-host HOST` | DF2 서버 IP (기본: 자동 감지) |
| `--df2-port PORT` | DF2 서버 포트 (기본: 50888) |

> 💡 `--dogfight2` 없이도 일반 시뮬레이션은 정상 동작합니다. TacView만으로도 충분한 분석이 가능합니다.

---

**이제 하늘을 지배할 당신만의 AI 전투기를 개발할 준비가 완료되었습니다!**

---

*Copyright © 2026 AI Combat Team. All rights reserved.*
