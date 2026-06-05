@echo off
setlocal
REM Launch the service-level Defender attach Streamlit app.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv 2>nul
    if errorlevel 1 python -m venv .venv
    if errorlevel 1 exit /b %errorlevel%
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b %errorlevel%

python -m pip install -r requirements-streamlit.txt
if errorlevel 1 exit /b %errorlevel%

python -m streamlit run streamlit_app.py
