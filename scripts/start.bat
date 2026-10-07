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

REM Кодовая страница консоли. Русская Windows по умолчанию использует
REM cp866/cp1251, а Git Bash и Python печатают UTF-8 — из-за этого
REM кириллица в выводе превращается в мусор вида "??=ok".
REM 65001 — это UTF-8.
chcp 65001 >nul

REM chcp меняет только кодовую страницу консоли. Python печатает в канал
REM (stdout — это пайп, а не консоль) и там берёт ANSI-кодировку cp1251,
REM поэтому одного chcp мало: нужен ещё PYTHONIOENCODING.
set "PYTHONIOENCODING=utf-8"

cd /d "%~dp0.."

REM Окно держим открытым только при запуске двойным кликом. При запуске
REM из cmd/PowerShell/автоматизации ждать нажатия клавиши не нужно —
REM иначе скрипт выглядит зависшим. Признак двойного клика: в
REM %cmdcmdline% нет ключа /c.
set "INTERACTIVE=1"
REM /c:"..." — литеральный поиск: без двоеточия findstr принял бы
REM /c за собственный переключатель и детектор всегда давал бы "интерактивно".
echo %cmdcmdline% | findstr /i /c:"/c" >nul && set "INTERACTIVE=0"

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

REM Итог для пользователя и ожидание клавиши только при двойном клике.
if not "%RC%"=="0" (
    echo.
    echo   ==========================================================
    echo    ЗАПУСК НЕ УДАЛСЯ, код возврата: %RC%
    echo    Подробности: ./scripts/start.sh logs backend
    echo   ==========================================================
    echo.
    pause
    exit /b %RC%
)

REM Открываем интерфейс в браузере. К этому моменту скрипт запуска уже
REM дождался ответа /_stcore/health, то есть страница готова к открытию.
REM NO_BROWSER=1 — открывать не надо (автоматические проверки, CI).
if not "%NO_BROWSER%"=="1" (
    REM Для React-интерфейса (команда webapp) открываем его порт, а не Streamlit.
    set "OPEN_PORT=%UI_PORT%"
    if "!OPEN_PORT!"=="" set "OPEN_PORT=80"
    if /i "%~1"=="webapp" (
        if "!WEBAPP_PORT!"=="" set "WEBAPP_PORT=5173"
        set "OPEN_PORT=!WEBAPP_PORT!"
    )
    echo.
    if "!OPEN_PORT!"=="80" (
        echo   Открываю http://127.0.0.1
        start "" "http://127.0.0.1"
    ) else (
        echo   Открываю http://127.0.0.1:!OPEN_PORT!
        start "" "http://127.0.0.1:!OPEN_PORT!"
    )
)

if "%INTERACTIVE%"=="1" (
    echo.
    echo   Службы работают в фоне. Это окно можно закрыть.
    echo   Остановить: scripts\stop.bat
    echo.
    pause
)
exit /b %RC%