@echo off
REM Launch the service-level Defender attach Streamlit app.
cd /d "%~dp0"
python -m streamlit run streamlit_app.py
