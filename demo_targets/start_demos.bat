@echo off
rem Start the three QA Pilot demo apps in their own windows. Close a window to stop that app.
cd /d "%~dp0"
set PY=..\.venv\Scripts\python.exe
if not exist "%PY%" set PY=python
start "QA Pilot demo - Clinic :8101" "%PY%" clinic_app\app.py %*
start "QA Pilot demo - Car rental :8102" "%PY%" car_rental_app\app.py %*
start "QA Pilot demo - Shop admin :8103" "%PY%" shop_admin_app\app.py %*
echo.
echo   Clinic      http://localhost:8101   admin@carepoint.test / Admin#2026
echo   Car rental  http://localhost:8102   admin@drivenow.test  / Admin#2026
echo   Shop admin  http://localhost:8103   admin@stockroom.test / Admin#2026
echo   (all accounts are listed under "Demo accounts" on each login page)
