@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

%PY% --version >nul 2>nul
if errorlevel 1 goto nopython

echo Installing build tools...
%PY% -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto failed

echo Building GW2AchievementHelper.exe - this takes a minute or two...
%PY% -m PyInstaller --noconfirm --clean --noconsole --onedir --name GW2AchievementHelper --icon assets\app.ico --version-file version_info.txt --add-data "assets;assets" main.py
if errorlevel 1 goto failed

set "QT=dist\GW2AchievementHelper\_internal\PySide6"
del /q "%QT%\opengl32sw.dll" 2>nul
rmdir /s /q "%QT%\translations" 2>nul
del /q "%QT%\plugins\platforms\qdirect2d.dll" 2>nul
del /q "%QT%\plugins\imageformats\qtiff.dll" 2>nul

echo.
echo Done: dist\GW2AchievementHelper\GW2AchievementHelper.exe
echo Share the whole dist\GW2AchievementHelper folder, the exe needs the _internal folder next to it.
pause
exit /b 0

:nopython
echo Python was not found. Install Python 3.9 or newer from https://www.python.org/downloads/
pause
exit /b 1

:failed
echo Build failed. Scroll up to see the error.
pause
exit /b 1
