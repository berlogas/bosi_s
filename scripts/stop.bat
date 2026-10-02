@echo off
REM Остановка boasi_s на Windows.

setlocal
cd /d "%~dp0.."

where bash >nul 2>&1
if %ERRORLEVEL% neq 0 (
  echo Git Bash не найден в PATH. Остановите вручную:
  echo   taskkill /F /FI "WINDOWTITLE eq uvicorn*"
  echo   taskkill /F /FI "WINDOWTITLE eq streamlit*"
  pause
  exit /b 1
)

bash scripts/start.sh stop
echo.
pause