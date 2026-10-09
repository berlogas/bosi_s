@echo off
REM =====================================================================
REM  boasi_s — единая точка входа для Windows.
REM
REM  Нужен потому, что `make` в Windows не входит в стандартную поставку:
REM  «make» не является внутренней или внешней командой. Все команды из
REM  Makefile продублированы здесь и делают ровно то же самое.
REM
REM      scripts\boasi.bat backup
REM      scripts\boasi.bat backup-verify backups\boasi-20261008-120000.tar.gz
REM      scripts\boasi.bat restore backups\boasi-20261008-120000.tar.gz
REM      scripts\boasi.bat reset-plan
REM      scripts\boasi.bat health
REM      scripts\boasi.bat help
REM
REM  Ключи вида ARCHIVE=... тоже понимаются (как в make), остальное
REM  передаётся дальше как есть.
REM =====================================================================
setlocal enabledelayedexpansion

REM Русская Windows печатает в cp866/cp1251, а скрипты и Python — в UTF-8.
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"

cd /d "%~dp0.."

set "COMMAND=%~1"
if "%COMMAND%"=="" set "COMMAND=help"
shift

REM --- Разбор аргументов: KEY=VALUE -> переменные окружения, остальное -> PASSTHRU ---
set "PASSTHRU="
:parse_args
if "%~1"=="" goto args_done
for /f "tokens=1* delims==" %%A in ("%~1") do (
    if not "%%B"=="" (
        set "%%A=%%B"
    ) else (
        set "PASSTHRU=!PASSTHRU! %1"
    )
)
shift
goto parse_args
:args_done

REM --- Git Bash: в Windows три "bash", нужен именно Git for Windows ---
set "BASH="
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

REM --- Python из venv ---
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        if not defined PY set "PY=%%P"
    )
)

set "RC=0"

if /i "%COMMAND%"=="help" goto show_help
if /i "%COMMAND%"=="-h" goto show_help
if /i "%COMMAND%"=="--help" goto show_help

REM -------------------------------------------------- установка и данные
if /i "%COMMAND%"=="bootstrap" goto need_bash_bootstrap

if /i "%COMMAND%"=="backup" (
    call :need_bash || goto no_bash
    "!BASH!" scripts/backup.sh !PASSTHRU!
    goto done
)

if /i "%COMMAND%"=="backup-config" (
    call :need_bash || goto no_bash
    set "CONFIG_BACKUP=1"
    "!BASH!" scripts/backup.sh !PASSTHRU!
    goto done
)

if /i "%COMMAND%"=="backup-verify" (
    call :need_bash || goto no_bash
    call :need_archive || goto missing_archive
    "!BASH!" scripts/verify_backup.sh "%ARCHIVE%" !PASSTHRU!
    goto done
)

if /i "%COMMAND%"=="restore" (
    call :need_bash || goto no_bash
    call :need_archive || goto missing_archive
    "!BASH!" scripts/restore.sh "%ARCHIVE%" !PASSTHRU!
    goto done
)

if /i "%COMMAND%"=="restore-list" (
    call :need_bash || goto no_bash
    call :need_archive || goto missing_archive
    "!BASH!" scripts/restore.sh "%ARCHIVE%" --list !PASSTHRU!
    goto done
)

if /i "%COMMAND%"=="reset-plan" goto need_bash_reset_data
if /i "%COMMAND%"=="reset-data" goto need_bash_reset_data
if /i "%COMMAND%"=="reset-users" goto need_bash_reset_users
if /i "%COMMAND%"=="reset-all" goto need_bash_reset_all

REM ------------------------------------------------------------- стек
if /i "%COMMAND%"=="up" (
    docker compose up -d --build
    goto done
)
if /i "%COMMAND%"=="down" (
    docker compose down
    goto done
)
if /i "%COMMAND%"=="logs" (
    docker compose logs -f --tail=100 %PASSTHRU%
    goto done
)
if /i "%COMMAND%"=="health" (
    curl -fsS http://127.0.0.1:8000/api/health || echo backend не запущен
    goto done
)
if /i "%COMMAND%"=="metrics" (
    curl -fsS http://127.0.0.1:8000/api/metrics.json || echo backend не запущен
    goto done
)
if /i "%COMMAND%"=="pull-models" (
    call :need_bash || goto no_bash
    "!BASH!" scripts/pull_models.sh
    goto done
)
if /i "%COMMAND%"=="migrate" (
    pushd backend
    "%PY%" -m alembic upgrade head
    popd
    goto done
)

REM ------------------------------------------------- разработка и прочее
if /i "%COMMAND%"=="create-admin" goto need_python_admin
if /i "%COMMAND%"=="admin" goto need_python_admin

if /i "%COMMAND%"=="test" (
    pushd backend
    "%PY%" -m pytest -q
    popd
    goto done
)
if /i "%COMMAND%"=="lint" (
    "%PY%" -m ruff check backend\app backend\tests
    goto done
)

echo Неизвестная команда: %COMMAND%
echo.
set "RC=1"
goto show_help

REM ------------------------------------------------------------- переходы
:need_bash_bootstrap
call :need_bash || goto no_bash
"!BASH!" scripts/bootstrap.sh !PASSTHRU!
goto done

:need_bash_reset_data
call :need_bash || goto no_bash
if not defined CONFIRM set "CONFIRM=СБРОС ДАННЫХ"
"!BASH!" scripts/reset_state.sh --scope data %PASSTHRU% --yes --confirm "!CONFIRM!"
goto done

:need_bash_reset_users
call :need_bash || goto no_bash
if not defined CONFIRM set "CONFIRM=СБРОС СЕССИЙ"
"!BASH!" scripts/reset_state.sh --scope users %PASSTHRU% --yes --confirm "!CONFIRM!"
goto done

:need_bash_reset_all
call :need_bash || goto no_bash
if not defined CONFIRM set "CONFIRM=ПОЛНЫЙ СБРОС"
"!BASH!" scripts/reset_state.sh --scope all %PASSTHRU% --yes --confirm "!CONFIRM!"
goto done

:need_python_admin
call :need_python || goto no_python
pushd backend
"%PY%" scripts\create_admin.py !PASSTHRU!
popd
goto done

REM --------------------------------------------------------- подпрограммы
:need_bash
if defined BASH exit /b 0
echo.
echo   Git Bash не найден: установите Git for Windows
echo   https://git-scm.com/download/win
echo.
exit /b 1
:no_bash
set "RC=1"
goto done

:need_python
if defined PY exit /b 0
echo Python не найден: поставьте его или создайте venv (make venv / py -3.11 -m venv .venv)
exit /b 1
:no_python
set "RC=1"
goto done

:need_archive
if defined ARCHIVE if not "%ARCHIVE%"=="" exit /b 0
REM не задан явно — берём первый позиционный аргумент.
REM Важно: раньше было “set ARCHIVE=!PASSTHRU: =!” — это замена пробелов на пустое,
REM и в переменной версии ARCHIVE становил равно “=”.
set "ARCHIVE="
for %%A in (%PASSTHRU%) do if not defined ARCHIVE set "ARCHIVE=%%~A"
if not defined ARCHIVE exit /b 1
exit /b 0
:missing_archive
echo Не указан архив. Например:
echo   scripts\boasi.bat %COMMAND% backups\boasi-20261008-120000.tar.gz
echo   или   scripts\boasi.bat %COMMAND% ARCHIVE=backups\boasi-20261008-120000.tar.gz
set "RC=1"
goto done

:show_help
echo.
echo   boasi_s — команды (то же, что в Makefile, но без make)
echo   ==========================================================
echo.
echo   Установка и данные
echo     bootstrap                      первичная установка на новом сервере
echo     backup                         бэкап тома boasi_data ^(БД + файлы + манифест^)
echo     backup-config                  бэкап вместе с .env ^(SECRET_KEY^)
echo     backup-verify ARCHIVE=...       проверить архив, не трогая боевой том
echo     restore ARCHIVE=...            восстановление ^(стек должен быть остановлен^)
echo     restore-list ARCHIVE=...       состав архива и манифест
echo.
echo   Сброс состояния (разрушает данные, нужна фраза CONFIRM=)
echo     reset-plan                     план сброса, ничего не удаляет
echo     reset-data                     сессии, документы, проекты
echo     reset-users                    то же + все входы
echo     reset-all                      полностью пустая платформа
echo.
echo   Стек
echo     up ^| down ^| logs               docker compose ...
echo     health ^| metrics               состояние платформы
echo     pull-models                    скачать модели Ollama
echo     migrate                        применить миграции
echo.
echo   Разработка
echo     create-admin                   создать администратора
echo     test                           тесты backend
echo     lint                           статическая проверка
echo.
echo   Примеры
echo     scripts\boasi.bat backup
echo     scripts\boasi.bat backup-verify backups\boasi-20261008-120000.tar.gz
echo     scripts\boasi.bat restore backups\boasi-20261008-120000.tar.gz
echo     scripts\boasi.bat reset-plan
echo.
exit /b %RC%

:done
exit /b %RC%