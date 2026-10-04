@echo off
rem Rebuild the React UI into backend\app\static (only needed if you change the UI; requires Node.js 20+).
cd /d "%~dp0..\frontend"
call npm install --no-audit --no-fund || exit /b 1
call npm run build || exit /b 1
echo UI built into backend\app\static - commit it so users don't need Node.js.
