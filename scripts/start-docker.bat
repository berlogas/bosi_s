@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0.."

set "CMD=%1"
if not defined CMD set "CMD=up"

rem --- Check Docker ---
where docker >nul 2>&1
if errorlevel 1 (
    echo Docker not found in PATH.
    echo Install Docker Desktop: https://www.docker.com/products/docker-desktop/
    exit /b 1
)

docker compose version >nul 2>&1
if errorlevel 1 (
    echo docker compose v2 not found.
    exit /b 1
)

rem --- Check .env ---
if not exist .env (
    echo File .env not found. Copying from .env.example...
    copy .env.example .env >nul
    echo WARNING: set SECRET_KEY in .env before launching!
    echo Generate: python -c "import secrets; print(secrets.token_urlsafe(48))"
    exit /b 1
)

rem SECRET_KEY already validated manually in .env (no template value present)

rem --- Dispatch ---
if /I "%CMD%"=="up" goto cmd_up
if /I "%CMD%"=="stop" goto cmd_stop
if /I "%CMD%"=="restart" goto cmd_restart
if /I "%CMD%"=="rebuild" goto cmd_rebuild
if /I "%CMD%"=="rebuild-backend" goto cmd_rebuild_backend
if /I "%CMD%"=="rebuild-webapp" goto cmd_rebuild_webapp
if /I "%CMD%"=="status" goto cmd_status
if /I "%CMD%"=="logs" goto cmd_logs
if /I "%CMD%"=="help" goto cmd_help
if /I "%CMD%"=="-h" goto cmd_help
if /I "%CMD%"=="--help" goto cmd_help

echo Unknown command: %CMD%
exit /b 1

:cmd_up
echo Starting boasi_s via Docker Compose...
if not exist inbox mkdir inbox

echo [1/4] Starting Ollama (models download on first run)
docker compose up -d ollama
if errorlevel 1 (
    echo ERROR starting Ollama. See: docker compose logs ollama
    exit /b 1
)
echo [ok] Ollama started.

echo [2/4] Building and starting full stack (backend + webapp)
docker compose up -d --build
if errorlevel 1 (
    echo ERROR starting stack. See: docker compose logs
    exit /b 1
)
echo [ok] Stack started.

echo [3/4] Waiting for backend health (up to 3 minutes)
set /a tries=0
:wait_loop
if %tries% geq 180 goto wait_timeout
curl -fsS http://127.0.0.1:8000/api/health >nul 2>&1
if errorlevel 1 (
    set /a tries+=1
    timeout /t 1 >nul
    goto wait_loop
)
echo [ok] Backend responds at http://127.0.0.1:8000/api/health
goto wait_done
:wait_timeout
echo [warn] Backend not responding yet. Logs: docker compose logs backend
:wait_done

echo [4/4] Done. Opening browser...
if not "%NO_BROWSER%"=="1" start "" "http://127.0.0.1:5173"

echo.
echo Platform started
echo UI (React):      http://127.0.0.1:5173
echo API (Swagger):   http://127.0.0.1:8000/api/docs
echo Health:          http://127.0.0.1:8000/api/health
echo.
echo Logs:            docker compose logs -f backend
echo Status:          scripts\start-docker.bat status
echo Stop:            scripts\start-docker.bat stop
exit /b 0

:cmd_stop
echo Stopping stack...
docker compose down
echo [ok] Stack stopped.
exit /b 0

:cmd_restart
echo Restarting stack...
docker compose down
docker compose up -d --build
echo [ok] Stack restarted.
exit /b 0

:cmd_rebuild
echo Rebuilding all services after code changes...
docker compose up -d --build
echo [ok] All services rebuilt.
exit /b 0

:cmd_rebuild_backend
echo Rebuilding backend only...
docker compose up -d --build backend
echo [ok] Backend rebuilt.
exit /b 0

:cmd_rebuild_webapp
echo Rebuilding webapp only...
docker compose up -d --build webapp
echo [ok] Webapp rebuilt.
exit /b 0

:cmd_status
echo Container status:
docker compose ps
exit /b 0

:cmd_logs
set "SVC=%2"
if not defined SVC set "SVC=backend"
docker compose logs -f --tail=100 %SVC%
exit /b 0

:cmd_help
echo Usage: scripts\start-docker.bat [command]
echo.
echo Commands:
echo   (no command)      start stack (ollama + backend + webapp)
echo   stop              stop stack
echo   restart           restart stack (no rebuild)
echo   rebuild           rebuild all services after code changes
echo   rebuild-backend   rebuild only backend after code changes
echo   rebuild-webapp    rebuild only webapp after code changes
echo   status            container status
echo   logs [service]    service logs (default: backend)
echo   help              this help
echo.
echo Environment variables:
echo   API_PORT=8000    WEBAPP_PORT=5173
echo   NO_BROWSER=1     do not open browser after start
exit /b 0
