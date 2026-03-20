@echo off
echo ============================================
echo  Starting Dogfight 2 (Harfang3D Sandbox)
echo  Network Port: 50888
echo ============================================
echo.
echo After the game starts:
echo   - Select "Network" mission to enter network mode
echo   - The IP:Port will be shown on screen
echo   - Then run test_df2_connection.py from another terminal
echo.

set VENV_PYTHON=c:\Users\Joon\Desktop\AI-pilot\AI_Pilot\ai-combat-sdk\.venv\Scripts\python.exe
set DF2_DIR=c:\Users\Joon\Desktop\AI-pilot\AI_Pilot\dogfight-sandbox-hg2\source

echo Using Python: %VENV_PYTHON%
echo Dogfight 2 dir: %DF2_DIR%
echo.

cd /d %DF2_DIR%
%VENV_PYTHON% main.py

pause
