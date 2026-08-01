@echo off
setlocal
cd /d "%~dp0"

if not exist "manage.py" (
  echo [ERROR] manage.py not found.
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
if "%PORT%"=="" set "PORT=9000"

python manage.py migrate --fake-initial --noinput
start "KFlow Homepage Django" cmd /c "python manage.py runserver 127.0.0.1:%PORT% --noreload"

timeout /t 1 >nul
start "" "http://127.0.0.1:%PORT%"

exit /b 0
