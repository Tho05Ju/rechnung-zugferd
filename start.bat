@echo off
rem Doppelklick zum Starten (Windows). Oeffnet das Tool im Browser: http://127.0.0.1:5001
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist .venv (
  %PY% -m venv .venv || (echo Python 3.9 oder neuer wird benoetigt: https://www.python.org/downloads/ ^(Haken bei "Add to PATH"^) & pause & exit /b 1)
  .venv\Scripts\python -m pip install -q -r requirements.txt || (echo Installation fehlgeschlagen & pause & exit /b 1)
)
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:5001"
.venv\Scripts\python app.py
pause
