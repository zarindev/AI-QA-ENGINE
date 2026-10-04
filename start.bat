@echo off
rem Start QA Pilot at http://localhost:8000 (or the next free port) and open the browser.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  exit /b 1
)
.venv\Scripts\python.exe backend\serve.py %*
