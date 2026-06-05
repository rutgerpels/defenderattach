@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv 2>nul
    if errorlevel 1 python -m venv .venv
    if errorlevel 1 exit /b %errorlevel%
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b %errorlevel%

python -m pip install -r requirements.txt
if errorlevel 1 exit /b %errorlevel%

set "PYTHONPATH=%CD%\src"
set "APP_HOST=127.0.0.1"
set "APP_PORT=8050"
set "APP_DEBUG=true"

start "" "http://127.0.0.1:8050"
python app.py
