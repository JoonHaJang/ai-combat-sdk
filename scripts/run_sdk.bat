@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

:: AI Combat SDK 실행 스크립트
:: VSCode/Windsurf 또는 PowerShell에서 프로젝트를 엽니다.

cd /d "%~dp0.."

:: 가상환경 확인
if not exist ".venv\Scripts\activate.bat" (
    echo [오류] 가상환경이 설치되어 있지 않습니다.
    echo.
    echo install_sdk.bat를 먼저 실행하세요.
    pause
    exit /b 1
)

echo ========================================
echo   AI Combat SDK 실행
echo ========================================
echo.
echo 어떻게 실행하시겠습니까?
echo.
echo 1. VSCode에서 열기 (권장)
echo 2. Windsurf에서 열기
echo 3. PowerShell 터미널만 열기
echo 4. 취소
echo.
set /p CHOICE="선택 (1-4): "

if "!CHOICE!"=="1" (
    where code >nul 2>&1
    if %errorLevel% equ 0 (
        echo VSCode 실행 중...
        start "" code "%CD%"
        echo.
        echo ✓ VSCode가 실행되었습니다.
        echo.
        echo 💡 VSCode 사용 팁:
        echo   - Ctrl+` 로 터미널 열기
        echo   - 가상환경이 자동으로 활성화됩니다
        echo   - submissions 폴더에서 에이전트 작성
        echo.
    ) else (
        echo [오류] VSCode가 설치되어 있지 않습니다.
        echo.
        echo VSCode 설치: https://code.visualstudio.com/
        echo.
        pause
        exit /b 1
    )
) else if "!CHOICE!"=="2" (
    where windsurf >nul 2>&1
    if %errorLevel% equ 0 (
        echo Windsurf 실행 중...
        start "" windsurf "%CD%"
        echo.
        echo ✓ Windsurf가 실행되었습니다.
        echo.
        echo 💡 Windsurf 사용 팁:
        echo   - Ctrl+` 로 터미널 열기
        echo   - 가상환경이 자동으로 활성화됩니다
        echo   - Cascade AI와 함께 에이전트 개발
        echo.
    ) else (
        echo [오류] Windsurf가 설치되어 있지 않습니다.
        echo.
        echo Windsurf 설치: https://codeium.com/windsurf
        echo.
        pause
        exit /b 1
    )
) else if "!CHOICE!"=="3" (
    echo PowerShell 실행 중...
    echo.
    echo 주요 명령어:
    echo   python scripts/run_match.py --agent1 my_agent --agent2 simple
    echo   python tools/validate_agent.py submissions/my_agent/my_agent.yaml
    echo.
    start powershell -NoExit -Command "& {cd '%CD%'; .\.venv\Scripts\Activate.ps1; Write-Host '가상환경 활성화 완료! (.venv)' -ForegroundColor Green; Write-Host ''; Write-Host '주요 명령어:' -ForegroundColor Yellow; Write-Host '  python scripts/run_match.py --agent1 my_agent --agent2 simple'; Write-Host '  python tools/validate_agent.py submissions/my_agent/my_agent.yaml'; Write-Host ''}"
) else if "!CHOICE!"=="4" (
    echo 취소되었습니다.
    exit /b 0
) else (
    echo 잘못된 선택입니다.
    pause
    exit /b 1
)

timeout /t 3 >nul
