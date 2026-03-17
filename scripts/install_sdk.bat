@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

:: AI Combat SDK 자동 설치 스크립트 (Windows)
:: 프로그래밍 초보자도 쉽게 사용할 수 있도록 모든 과정을 자동화합니다.

echo ========================================
echo   AI Combat SDK 자동 설치 프로그램
echo ========================================
echo.

:: 관리자 권한 확인
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [경고] 관리자 권한이 필요합니다.
    echo.
    echo 해결 방법:
    echo 1. 이 파일을 우클릭
    echo 2. "관리자 권한으로 실행" 선택
    echo.
    pause
    exit /b 1
)

:: 1단계: Python 3.14 확인
echo [1/6] Python 3.14 확인 중...
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo.
    echo Python 3.14 설치 방법:
    echo 1. https://www.python.org/downloads/ 접속
    echo 2. Python 3.14 다운로드
    echo 3. 설치 시 "Add Python to PATH" 체크
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo    Python 버전: %PYTHON_VERSION%

:: Python 버전 확인 (3.14.x)
echo %PYTHON_VERSION% | findstr /r "^3\.14\." >nul
if %errorLevel% neq 0 (
    echo [경고] Python 3.14가 필요합니다. (현재: %PYTHON_VERSION%)
    echo.
    echo 계속하시겠습니까? (Y/N)
    set /p CONTINUE=
    if /i not "!CONTINUE!"=="Y" exit /b 1
)

:: 2단계: Git 확인
echo [2/6] Git 확인 중...
git --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [오류] Git이 설치되어 있지 않습니다.
    echo.
    echo Git 설치 방법:
    echo 1. https://git-scm.com/download/win 접속
    echo 2. Git for Windows 다운로드 및 설치
    echo 3. 설치 후 이 스크립트를 다시 실행
    echo.
    pause
    exit /b 1
)
for /f "tokens=3" %%i in ('git --version 2^>^&1') do set GIT_VERSION=%%i
echo    Git 버전: %GIT_VERSION%

:: 3단계: 설치 위치 선택
echo [3/6] 설치 위치 선택...
echo.
echo SDK를 설치할 폴더를 선택하세요.
echo 기본값: %USERPROFILE%\Documents\ai-combat-sdk
echo.
set "INSTALL_DIR=%USERPROFILE%\Documents\ai-combat-sdk"
set /p CUSTOM_DIR="다른 경로를 원하면 입력하세요 (Enter=기본값): "
if not "!CUSTOM_DIR!"=="" set "INSTALL_DIR=!CUSTOM_DIR!"

echo    설치 경로: !INSTALL_DIR!
echo.

:: 기존 폴더 확인
if exist "!INSTALL_DIR!" (
    echo [경고] 이미 폴더가 존재합니다: !INSTALL_DIR!
    echo 기존 폴더를 삭제하고 새로 설치하시겠습니까? (Y/N)
    set /p OVERWRITE=
    if /i "!OVERWRITE!"=="Y" (
        echo    기존 폴더 삭제 중...
        rmdir /s /q "!INSTALL_DIR!"
    ) else (
        echo 설치를 취소합니다.
        pause
        exit /b 0
    )
)

:: 4단계: Git Clone
echo [4/6] SDK 다운로드 중...
echo    저장소: https://github.com/songhyonkim/ai-combat-sdk.git
git clone https://github.com/songhyonkim/ai-combat-sdk.git "!INSTALL_DIR!"
if %errorLevel% neq 0 (
    echo [오류] Git clone 실패
    pause
    exit /b 1
)
echo    ✓ 다운로드 완료

:: 5단계: 가상환경 생성
echo [5/6] 가상환경 생성 중...
cd /d "!INSTALL_DIR!"
python -m venv .venv
if %errorLevel% neq 0 (
    echo [오류] 가상환경 생성 실패
    pause
    exit /b 1
)
echo    ✓ 가상환경 생성 완료

:: 6단계: 의존성 설치
echo [6/6] 필수 패키지 설치 중...
echo    (시간이 걸릴 수 있습니다. 잠시만 기다려주세요...)
call .venv\Scripts\activate.bat
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if %errorLevel% neq 0 (
    echo [경고] 일부 패키지 설치 실패. 수동 확인이 필요합니다.
)
echo    ✓ 패키지 설치 완료

:: 작업 공간 생성
echo.
echo [추가 설정] 작업 공간 생성 중...
if not exist "submissions" mkdir submissions
echo    ✓ submissions 폴더 생성

:: 바탕화면 바로가기 생성
echo.
echo 바탕화면에 바로가기를 생성하시겠습니까? (Y/N)
set /p CREATE_SHORTCUT=
if /i "!CREATE_SHORTCUT!"=="Y" (
    echo Set oWS = WScript.CreateObject("WScript.Shell") > CreateShortcut.vbs
    echo sLinkFile = "%USERPROFILE%\Desktop\AI Combat SDK.lnk" >> CreateShortcut.vbs
    echo Set oLink = oWS.CreateShortcut(sLinkFile) >> CreateShortcut.vbs
    echo oLink.TargetPath = "!INSTALL_DIR!" >> CreateShortcut.vbs
    echo oLink.WorkingDirectory = "!INSTALL_DIR!" >> CreateShortcut.vbs
    echo oLink.Description = "AI Combat SDK" >> CreateShortcut.vbs
    echo oLink.Save >> CreateShortcut.vbs
    cscript //nologo CreateShortcut.vbs
    del CreateShortcut.vbs
    echo    ✓ 바탕화면 바로가기 생성 완료
)

:: VSCode 확장 프로그램 추천 설치
echo.
echo [추가 설정] VSCode 확장 프로그램 설치 중...
if exist "!INSTALL_DIR!\.vscode" (
    echo    ✓ .vscode 폴더 이미 존재
) else (
    mkdir "!INSTALL_DIR!\.vscode"
    (
        echo {
        echo   "recommendations": [
        echo     "ms-python.python",
        echo     "ms-python.vscode-pylance",
        echo     "redhat.vscode-yaml",
        echo     "yzhang.markdown-all-in-one"
        echo   ]
        echo }
    ) > "!INSTALL_DIR!\.vscode\extensions.json"
    echo    ✓ VSCode 확장 프로그램 추천 목록 생성
)

:: VSCode 설정 파일 생성
if not exist "!INSTALL_DIR!\.vscode\settings.json" (
    (
        echo {
        echo   "python.defaultInterpreterPath": "${workspaceFolder}\\.venv\\Scripts\\python.exe",
        echo   "python.terminal.activateEnvironment": true,
        echo   "files.associations": {
        echo     "*.yaml": "yaml"
        echo   },
        echo   "yaml.schemas": {
        echo     "submissions/**/*.yaml": "AI Combat Agent"
        echo   }
        echo }
    ) > "!INSTALL_DIR!\.vscode\settings.json"
    echo    ✓ VSCode 설정 파일 생성
)

:: 에디터 감지 및 실행 옵션
echo.
echo ========================================
echo   설치 완료!
echo ========================================
echo.
echo 설치 경로: !INSTALL_DIR!
echo.

:: VSCode 또는 Windsurf 감지
set "EDITOR_FOUND="
set "EDITOR_NAME="
set "EDITOR_CMD="

where code >nul 2>&1
if %errorLevel% equ 0 (
    set "EDITOR_FOUND=1"
    set "EDITOR_NAME=VSCode"
    set "EDITOR_CMD=code"
)

where windsurf >nul 2>&1
if %errorLevel% equ 0 (
    set "EDITOR_FOUND=1"
    set "EDITOR_NAME=Windsurf"
    set "EDITOR_CMD=windsurf"
)

if defined EDITOR_FOUND (
    echo !EDITOR_NAME!가 감지되었습니다.
    echo !EDITOR_NAME!에서 프로젝트를 여시겠습니까? (Y/N)
    set /p OPEN_EDITOR=
    if /i "!OPEN_EDITOR!"=="Y" (
        echo    !EDITOR_NAME! 실행 중...
        start "" !EDITOR_CMD! "!INSTALL_DIR!"
        echo.
        echo 💡 팁: !EDITOR_NAME!에서 확장 프로그램 설치를 권장합니다.
        echo    (우측 하단 알림에서 "Install" 클릭)
        echo.
    )
) else (
    echo VSCode 또는 Windsurf가 설치되어 있지 않습니다.
    echo.
    echo 추천 에디터:
    echo - VSCode: https://code.visualstudio.com/
    echo - Windsurf: https://codeium.com/windsurf
    echo.
)

echo 다음 단계:
echo 1. VSCode/Windsurf에서 프로젝트 열기
echo 2. submissions 폴더에 에이전트 작성
echo 3. 터미널에서 테스트: python scripts/run_match.py --agent1 my_agent --agent2 simple
echo.
echo 도움말:
echo - 초보자 가이드: docs\EASY_INSTALL.md
echo - 노드 레퍼런스: docs\NODE_REFERENCE.md
echo.
pause

:: 에디터가 열리지 않았으면 탐색기로 폴더 열기
if not defined OPEN_EDITOR (
    explorer "!INSTALL_DIR!"
) else if /i not "!OPEN_EDITOR!"=="Y" (
    explorer "!INSTALL_DIR!"
)
