@echo off
setlocal
cd /d "%~dp0"

if not exist "server.py" (
  echo [ERROR] server.py not found.
  pause
  exit /b 1
)

python --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python not found. Please install Python 3 and add to PATH.
  pause
  exit /b 1
)

if "%ADMIN_USERNAME%"=="" set "ADMIN_USERNAME=admin"
if "%ADMIN_PASSWORD%"=="" set "ADMIN_PASSWORD=admin123"
if "%PORT%"=="" set "PORT=8088"

start "KFlow Homepage" cmd /c "python -m app"

timeout /t 1 >nul
start "" "http://127.0.0.1:%PORT%"

exit /b 0
