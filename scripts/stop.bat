@echo off
REM Остановка boasi_s на Windows.
REM Git Bash ищется так же, как в start.bat (WSL-овский bash не годится).

setlocal enabledelayedexpansion
cd /d "%~dp0.."

REM Пауза только при запуске двойным кликом (в %cmdcmdline% нет /c).
set "INTERACTIVE=1"
REM /c:"..." — литеральный поиск: без двоеточия findstr принял бы
REM /c за собственный переключатель и детектор всегда давал бы "интерактивно".
echo %cmdcmdline% | findstr /i /c:"/c" >nul && set "INTERACTIVE=0"

set "BASH="
for %%P in (
    "%ProgramFiles%\Git\bin\bash.exe"
    "%ProgramFiles%\Git\usr\bin\bash.exe"
    "%ProgramFiles(x86)%\Git\bin\bash.exe"
    "%ProgramFiles(x86)%\Git\usr\bin\bash.exe"
    "%LOCALAPPDATA%\Programs\Git\bin\bash.exe"
) do (
    if not defined BASH (
        if exist %%P set "BASH=%%~P"
    )
)

if not defined BASH (
    for /f "delims=" %%B in ('where bash 2^>nul') do (
        if not defined BASH (
            echo %%B | findstr /i /c:"\Windows\System32\bash.exe" >nul
            if errorlevel 1 (
                echo %%B | findstr /i /c:"WindowsApps" >nul
                if errorlevel 1 set "BASH=%%B"
            )
        )
    )
)

if defined BASH (
    "!BASH!" --version >nul 2>&1
    if errorlevel 1 set "BASH="
)

if not defined BASH (
    echo Git Bash не найден. Остановите процессы вручную:
    echo   netstat -ano ^| findstr :8000
    echo   taskkill /F /PID ^<pid^>
    pause
    exit /b 1
)

"!BASH!" "scripts/start.sh" stop
echo.
if "%INTERACTIVE%"=="1" (
    echo   Службы остановлены. Это окно можно закрыть.
    echo.
    pause
)