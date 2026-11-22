@echo off
rem MyFA Desk launcher. Double-click to start; leave the window open while you play.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 myfa_desk.py %*
) else (
    python myfa_desk.py %*
)
if errorlevel 1 (
    echo.
    echo Python not found or the app stopped with an error. Install Python from python.org and tick "Add python.exe to PATH".
)
pause
