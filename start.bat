@echo off
rem Doppelklick zum Starten (Windows). Oeffnet das Tool im Browser: http://127.0.0.1:5001
cd /d "%~dp0"
set "VENV=%LocalAppData%\RechnungApp\venv"
if not exist "%VENV%\Scripts\python.exe" call install.bat /silent
if not exist "%VENV%\Scripts\python.exe" exit /b 1
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:5001"
"%VENV%\Scripts\python" app.py
pause
