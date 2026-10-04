@echo off
rem QA Pilot setup (Windows): virtual environment, dependencies, .env, Chrome check.
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && (py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=py -3")
if not defined PY (
  where python >nul 2>nul && (python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=python")
)
if not defined PY (
  echo Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and run setup.bat again.
  exit /b 1
)

if not exist .venv\Scripts\python.exe %PY% -m venv .venv || goto :fail
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet || goto :fail
.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet || goto :fail
echo Dependencies installed.

if not exist .env (
  copy .env.example .env >nul
  echo Created .env ^(add your ANTHROPIC_API_KEY there, or paste it in the app^).
)
if not exist workspace mkdir workspace

.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'backend'); from app.browser.driver import chrome_available; print('Google Chrome: found' if chrome_available() else 'Google Chrome: NOT FOUND - install it from https://www.google.com/chrome/')"

if not exist backend\app\static\index.html echo Note: the UI build is missing. Run scripts\build_frontend.bat ^(needs Node.js^).
echo.
echo Setup complete. Start QA Pilot with:  start.bat
exit /b 0

:fail
echo Setup failed. See the messages above, or docs\TROUBLESHOOTING.md.
exit /b 1
