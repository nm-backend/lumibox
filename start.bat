@echo off
rem ============================================================
rem  LumiBox - one-command launcher for Windows
rem
rem  Why this file exists: launching used to require creating .env
rem  by hand, generating a secret key, starting containers, running
rem  migrations, seeding the catalog and drawing covers. Missing any
rem  step produced an empty site with no hint of what went wrong.
rem  Now a double-click is enough.
rem
rem  IMPORTANT: this file is intentionally ASCII-only. Cyrillic text
rem  in a .bat breaks cmd.exe parsing - the file is read in the OEM
rem  codepage before "chcp" takes effect, and commands turn to garbage.
rem ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.echo   LumiBox - starting up
    echo   ====================
echo.

rem ---------- 1. Docker ----------
docker info >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Docker Desktop is not running.
    echo.
    echo   What to do:
    echo     1. Open Docker Desktop
    echo     2. Wait until the whale icon stops blinking
    echo     3. Run this file again
    echo.
    pause
    exit /b 1
)
echo   [OK] Docker is running

rem ---------- 2. .env file ----------
if exist ".env" (
    echo   [OK] .env already exists - leaving it alone
) else (
    echo   [..] Creating .env and generating passwords...

    for /f "usebackq delims=" %%i in (`docker run --rm python:3.13-slim python -c "import secrets; print(secrets.token_urlsafe(50))"`) do set "GEN_SECRET=%%i"
    for /f "usebackq delims=" %%i in (`docker run --rm python:3.13-slim python -c "import secrets; print(secrets.token_hex(16))"`) do set "GEN_DBPASS=%%i"

    if "!GEN_SECRET!"=="" (
        echo   [ERROR] Could not generate a secret key. Is Docker working?
        pause
        exit /b 1
    )

    > .env echo # Generated automatically by start.bat. Not committed to git.
    >> .env echo.
    >> .env echo DJANGO_SECRET_KEY=!GEN_SECRET!
    >> .env echo DJANGO_DEBUG=True
    >> .env echo DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
    >> .env echo.
    >> .env echo DATABASE_URL=postgres://lumibox:!GEN_DBPASS!@localhost:5433/lumibox
    >> .env echo REDIS_URL=redis://localhost:6380/0
    >> .env echo.
    >> .env echo POSTGRES_USER=lumibox
    >> .env echo POSTGRES_PASSWORD=!GEN_DBPASS!
    >> .env echo POSTGRES_DB=lumibox
    >> .env echo.
    >> .env echo # Admin account is created on first start. Change the password after login.
    for /f %%p in ('docker run --rm python:3.13-slim python -c "import secrets;print(secrets.token_urlsafe(18))"') do set "ADMINPASS=%%p"
    >> .env echo DJANGO_SUPERUSER_EMAIL=admin@lumibox.local
    >> .env echo DJANGO_SUPERUSER_USERNAME=admin
    >> .env echo DJANGO_SUPERUSER_PASSWORD=%ADMINPASS%

    echo   [OK] .env created
)

rem ---------- 3. Build and run ----------
echo.
echo   [..] Building and starting containers.
echo        First run takes 2-5 minutes - images are being downloaded.
echo.

docker compose up --build -d
if errorlevel 1 (
    echo.
    echo   [ERROR] Containers failed to start.
    echo   See why:  docker compose logs
    echo.
    pause
    exit /b 1
)

rem ---------- 4. Wait until the site answers ----------
echo.
echo   [..] Waiting for the site to respond...

set /a ATTEMPT=0
:WAIT_LOOP
set /a ATTEMPT+=1
curl -s -o nul http://localhost:8001/ >nul 2>&1
if not errorlevel 1 goto READY
if !ATTEMPT! geq 60 goto TIMEOUT
rem "ping", not "timeout": timeout fails with "Input redirection is not
rem supported" whenever stdin is redirected (CI, pipes, automated runs).
rem ping -n 3 waits ~2 seconds and works in every context.
ping -n 3 127.0.0.1 >nul 2>&1
goto WAIT_LOOP

:TIMEOUT
echo.
echo   [WARNING] The site did not respond within 2 minutes.
echo   Check the logs:  docker compose logs web
echo.
pause
exit /b 1

:READY
echo   [OK] Site is responding
echo.
echo   ============================================
echo     Done. LumiBox is running.
echo   ============================================
echo.
echo     Site:      http://localhost:8001/
echo     Admin:     http://localhost:8001/admin/
echo     Swagger:   http://localhost:8001/api/docs/
echo     ReDoc:     http://localhost:8001/api/redoc/
echo.
echo     Admin login: see DJANGO_SUPERUSER_* in the .env file
echo     (default: admin@lumibox.local)
echo.
echo     To stop the project:  stop.bat
echo.

start "" http://localhost:8001/
pause
