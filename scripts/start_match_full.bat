@echo off
REM ============================================================
REM  AI Combat Full Launch
REM  1) FlightGear Blue + Red 자동 실행
REM  2) 매치 실행 (FlightGear + Tacview 실시간)
REM
REM  사용법:
REM    start_match_full.bat eagle1 simple_fighter
REM    start_match_full.bat eagle1 simple_fighter 300
REM  인자:
REM    %1 = agent1 이름 (기본: eagle1)
REM    %2 = agent2 이름 (기본: simple_fighter)
REM    %3 = max-steps  (기본: 300)
REM ============================================================

set AGENT1=%~1
set AGENT2=%~2
set MAX_STEPS=%~3

if "%AGENT1%"=="" set AGENT1=eagle1
if "%AGENT2%"=="" set AGENT2=ace
if "%MAX_STEPS%"=="" set MAX_STEPS=300

set PYTHON=.venv\Scripts\python.exe
set SCRIPT=scripts\run_match.py

cd /d "%~dp0.."

echo ============================================================
echo  AI Combat Match: %AGENT1% vs %AGENT2% (%MAX_STEPS% steps)
echo  FlightGear + Tacview 실시간 스트리밍
echo ============================================================

%PYTHON% %SCRIPT% ^
  --agent1 %AGENT1% ^
  --agent2 %AGENT2% ^
  --max-steps %MAX_STEPS% ^
  --auto-launch-fg ^
  --fg-wait 50 ^
  --tacview-realtime

pause
