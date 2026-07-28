@echo off
rem Stops LumiBox. Database data is preserved -
rem everything will be in place next time you run start.bat.
rem
rem ASCII-only on purpose: Cyrillic in a .bat breaks cmd.exe parsing.

cd /d "%~dp0"

echo.
echo   Stopping LumiBox...
docker compose stop

echo.
echo   Stopped. Your data is preserved.
echo   To start again:  start.bat
echo.
pause
