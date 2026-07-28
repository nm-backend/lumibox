@echo off
rem ============================================================
rem  LumiBox - local run on Windows WITHOUT Docker.
rem  Uses SQLite (no database to install) and no Redis.
rem  Just double-click this file. First run installs everything.
rem  ASCII only on purpose: Cyrillic breaks cmd.exe parsing.
rem ============================================================
setlocal
cd /d "%~dp0"

rem Force our own settings. Without this a DJANGO_SETTINGS_MODULE left over
rem from another project (e.g. kinogo's config.settings.dev) would hijack us
rem and crash with "no such table". This project uses development settings.
set "DJANGO_SETTINGS_MODULE=config.settings.development"

echo ============================================
echo   LumiBox - local run (no Docker)
echo ============================================
echo   Folder: %CD%
echo ============================================
echo.

rem --- 1. Find Python (prefer 3.13, then 3.12) ---
set "PY="
py -3.13 --version >nul 2>&1 && set "PY=py -3.13"
if "%PY%"=="" ( py -3.12 --version >nul 2>&1 && set "PY=py -3.12" )
if "%PY%"=="" ( python --version >nul 2>&1 && set "PY=python" )
if "%PY%"=="" (
    echo [ERROR] Python not found.
    echo Install Python 3.13 from https://www.python.org/downloads/
    echo During setup, tick "Add python.exe to PATH".
    pause
    exit /b 1
)
echo Using Python: %PY%

rem --- 2. Virtual environment (auto-heal a broken/mismatched one) ---
set "VPY=.venv\Scripts\python.exe"
set "NEEDVENV=0"
if not exist "%VPY%" set "NEEDVENV=1"
if "%NEEDVENV%"=="0" (
    rem A .venv left from another Python version has mismatched compiled
    rem binaries and Pillow fails to import (Django error fields.E210).
    rem Detect that and rebuild the venv clean.
    "%VPY%" -c "from PIL import Image" >nul 2>&1 || set "NEEDVENV=1"
)
if "%NEEDVENV%"=="1" (
    if exist ".venv" (
        echo [1/6] Rebuilding virtual environment ^(was broken or wrong Python^)...
        rmdir /s /q .venv
    ) else (
        echo [1/6] Creating virtual environment...
    )
    %PY% -m venv .venv || ( echo [ERROR] Could not create venv & pause & exit /b 1 )
) else (
    echo [1/6] Virtual environment OK
)

rem --- 3. Dependencies ---
echo [2/6] Installing dependencies ^(first run may take a few minutes^)...
"%VPY%" -m pip install --quiet --disable-pip-version-check --upgrade pip
"%VPY%" -m pip install --quiet --disable-pip-version-check -r requirements\base.txt || ( echo [ERROR] pip install failed & pause & exit /b 1 )

rem --- 4. .env with SQLite (created once) ---
if not exist ".env" (
    echo [3/6] Creating .env ^(SQLite^)...
    > .env echo DJANGO_SECRET_KEY=local-dev-key-change-me-0123456789-abcdefghij
    >> .env echo DATABASE_URL=sqlite:///db.sqlite3
    >> .env echo DJANGO_DEBUG=True
) else (
    echo [3/6] .env already exists - keeping it
)

rem --- 5. Database + demo data ---
echo [4/6] Applying migrations...
"%VPY%" manage.py migrate --noinput || ( echo [ERROR] migrate failed & pause & exit /b 1 )
echo [5/6] Loading demo data ^(movies, cast, collections, posters^)...
"%VPY%" manage.py ensure_demo_data

rem --- 6. Admin user (only if none exists) ---set "DJANGO_SUPERUSER_EMAIL=admin@lumibox.local"
set "DJANGO_SUPERUSER_USERNAME=admin"
set "DJANGO_SUPERUSER_PASSWORD=admin12345"
"%VPY%" manage.py createsuperuser --noinput >nul 2>&1
echo.
echo ============================================
echo   Ready.
echo   Site:  http://127.0.0.1:8000/
echo   Admin: http://127.0.0.1:8000/admin/
echo   Login: admin@lumibox.local  /  admin12345
echo.
echo   Keep this window open. Press Ctrl+C to stop.
echo ============================================
echo.
start "" http://127.0.0.1:8000/
"%VPY%" manage.py runserver 127.0.0.1:8000

endlocal
