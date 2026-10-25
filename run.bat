@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
    set "PYW=pyw -3"
) else (
    set "PY=python"
    set "PYW=pythonw"
)

%PY% --version >nul 2>nul
if errorlevel 1 goto nopython

%PY% -c "import PySide6" >nul 2>nul
if not errorlevel 1 goto run
echo Installing PySide6 - first run only, please wait...
%PY% -m pip install -r requirements.txt
if not errorlevel 1 goto run
%PY% -m pip install --user -r requirements.txt
if errorlevel 1 goto installfail

:run
start "" %PYW% main.py
exit /b 0

:nopython
echo Python was not found. Install Python 3.9 or newer from https://www.python.org/downloads/
pause
exit /b 1

:installfail
echo Could not install PySide6. Check your internet connection and try again.
pause
exit /b 1
