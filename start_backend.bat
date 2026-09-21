@echo off
title Backend - AI Change Request Analyzer
cd /d "%~dp0backend"

if not exist ".venv\Scripts\python.exe" (
    echo No virtual environment found - setting one up now and installing
    echo dependencies. This only happens once and can take a minute or two.
    echo.
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

if not exist ".env" (
    echo No backend\.env found - creating one from backend\.env.example.
    echo IMPORTANT: open backend\.env afterward and fill in SECRET_KEY and
    echo an AI provider key, or AI Analysis will not work.
    copy ".env.example" ".env" >nul
)

echo.
echo Starting backend server (http://localhost:8000)...
echo Keep this window open. Close it to stop the backend.
echo.
python -m uvicorn app.main:app --reload
echo.
echo Backend stopped or failed to start. See any error above.
pause
