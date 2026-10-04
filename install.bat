@echo off
setlocal enabledelayedexpansion
rem Installiert die Rechnungs-App auf diesem PC (Python + Pakete + Desktop-Verknuepfung).
rem Die Programmumgebung liegt bewusst in %LocalAppData%\RechnungApp (kurzer Pfad, sonst scheitert factur-x an Windows-Pfadlaengen).
rem Benoetigt Internet, aber keine Administratorrechte (nur fuer die C++-Laufzeit, falls noetig).
cd /d "%~dp0"
title Rechnung - Installation

set "ARCH=amd64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ARCH=arm64"
if /i "%PROCESSOR_ARCHITEW6432%"=="ARM64" set "ARCH=arm64"
set "PYVER=3.12.10"

set "VENV=%LocalAppData%\RechnungApp\venv"
if exist "%VENV%\Scripts\python.exe" goto packages

echo [1/4] Suche Python ...
set "PY="
for %%V in (3.12 3.13 3.11) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if defined PY goto venv

set "SUB=Python312"
if "%ARCH%"=="arm64" set "SUB=Python312-arm64"
if exist "%LocalAppData%\Programs\Python\%SUB%\python.exe" (
    set "PY="%LocalAppData%\Programs\Python\%SUB%\python.exe""
    goto venv
)

echo Python nicht gefunden - lade Python %PYVER% (%ARCH%) von python.org ...
set "PYEXE=%TEMP%\python-%PYVER%-%ARCH%.exe"
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest 'https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-%ARCH%.exe' -OutFile '%PYEXE%'" || goto fail
"%PYEXE%" /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0 || goto fail
set "SUB=Python312"
if "%ARCH%"=="arm64" set "SUB=Python312-arm64"
set "PY=%LocalAppData%\Programs\Python\%SUB%\python.exe"
if not exist "%PY%" goto fail
set "PY="%PY%""

:venv
echo [2/4] Lege Programmumgebung an ...
%PY% -m venv "%VENV%" || goto fail

:packages
echo [3/4] Installiere Pakete (kann einige Minuten dauern) ...
"%VENV%\Scripts\python" -m pip install -q --disable-pip-version-check -r requirements.txt || goto fail

"%VENV%\Scripts\python" -W ignore -c "import flask,pymupdf,reportlab,pikepdf,facturx" >nul 2>&1
if not errorlevel 1 goto shortcut

echo Microsoft Visual C++ Laufzeit fehlt - wird installiert (Windows fragt nach Erlaubnis) ...
set "VC=%TEMP%\vc_redist.%ARCH:amd64=x64%.exe"
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest 'https://aka.ms/vs/17/release/vc_redist.%ARCH:amd64=x64%.exe' -OutFile '%VC%'" || goto fail
"%VC%" /install /quiet /norestart
"%VENV%\Scripts\python" -W ignore -c "import flask,pymupdf,reportlab,pikepdf,facturx" || goto fail

:shortcut
echo [4/4] Erstelle Desktop-Verknuepfung ...
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'),'Rechnung.lnk')); $s.TargetPath='%~dp0start.bat'; $s.WorkingDirectory='%~dp0'; $s.Save()"

echo.
echo Fertig. Starte die App ueber die Verknuepfung "Rechnung" auf dem Desktop
echo oder per Doppelklick auf start.bat.
if /i not "%~1"=="/silent" pause
exit /b 0

:fail
echo.
echo FEHLER: Die Installation ist fehlgeschlagen. Bitte Internetverbindung pruefen und erneut starten.
pause
exit /b 1

