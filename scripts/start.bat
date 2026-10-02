@echo off
REM Запуск boasi_s для Windows (двойной клик или из командной строки).
REM Использует Git Bash, если он есть; иначе просит запустить через него.

setlocal
cd /d "%~dp0.."

where bash >nul 2>&1
if %ERRORLEVEL% neq 0 (
  echo.
  echo   Git Bash не найден в PATH.
  echo   Установите Git for Windows или запустите вручную:
  echo       bash scripts/start.sh
  echo.
  pause
  exit /b 1
)

bash scripts/start.sh %*
echo.
pause