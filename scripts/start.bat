@echo off
REM =====================================================================
REM  Запуск boasi_s для Windows.
REM
REM  Важно: в PATH Windows есть три "bash":
REM    - C:\Windows\System32\bash.exe      — это WSL, а не Git Bash;
REM    - ...\WindowsApps\bash.exe           — заглушка Store;
REM    - C:\Program Files\Git\...\bash.exe  — единственный нужный нам.
REM  Поэтому ищем Git Bash по известным путям и проверяем его запуском,
REM  а не доверяем первому результату `where bash`.
REM =====================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0.."

set "BASH="

REM --- 1. Известные расположения Git for Windows ---
for %%P in (
    "%ProgramFiles%\Git\bin\bash.exe"
    "%ProgramFiles%\Git\usr\bin\bash.exe"
    "%ProgramFiles(x86)%\Git\bin\bash.exe"
    "%ProgramFiles(x86)%\Git\usr\bin\bash.exe"
    "%LOCALAPPDATA%\Programs\Git\bin\bash.exe"
    "%LOCALAPPDATA%\Programs\Git\usr\bin\bash.exe"
) do (
    if not defined BASH (
        if exist %%P set "BASH=%%~P"
    )
)

REM --- 2. Рядом с git.exe, если он есть в PATH ---
if not defined BASH (
    for /f "delims=" %%G in ('where git 2^>nul') do (
        if not defined BASH (
            if exist "%%~dpG..\bin\bash.exe" set "BASH=%%~dpG..\bin\bash.exe"
            if not defined BASH (
                if exist "%%~dpG..\usr\bin\bash.exe" set "BASH=%%~dpG..\usr\bin\bash.exe"
            )
        )
    )
)

REM --- 3. Из PATH, но только настоящий bash: WSL и WindowsApps исключаем ---
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

REM --- 4. Проверяем, что найденный bash действительно работает ---
if defined BASH (
    "!BASH!" --version >nul 2>&1
    if errorlevel 1 set "BASH="
)

if not defined BASH (
    echo.
    echo   ==========================================================
    echo    Git Bash не найден.
    echo.
    echo    Установите Git for Windows: https://git-scm.com/download/win
    echo    Либо запустите вручную в Git Bash:
    echo        cd /d "%~dp0.."
    echo        bash scripts/start.sh %*
    echo   ==========================================================
    echo.
    pause
    exit /b 1
)

echo   Используется: "!BASH!"
echo.

"!BASH!" "scripts/start.sh" %*
set "RC=%ERRORLEVEL%"

REM Пауза только при ошибке: иначе окно "висит" и кажется, что запуск не идёт.
if not "%RC%"=="0" (
    echo.
    echo   Запуск не удался, код возврата: %RC%
    pause
)
exit /b %RC%