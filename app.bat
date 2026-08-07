@echo off
REM Double-click this to launch the app without typing anything into a
REM terminal yourself.
cd /d "%~dp0"
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "Airbrakes V3 Ground Station" /b pythonw "%~dp0app.py"
) else (
    start "Airbrakes V3 Ground Station" /b python "%~dp0app.py"
)