@echo off
REM This version is meant to run automatically when you log into Windows
REM (placed in your Startup folder) - it does the same setup as
REM start_all.bat, but starts both servers minimized in the background and
REM does NOT open a browser automatically, so you don't get a popup every
REM single time you log in. Just open http://localhost:5173 in a browser
REM whenever you're ready.

cd /d "%~dp0"

if not exist "backend\.venv\Scripts\python.exe" (
    pushd backend
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
    call deactivate
    popd
)

if not exist "backend\.env" (
    copy "backend\.env.example" "backend\.env" >nul
)

if not exist "frontend\node_modules" (
    pushd frontend
    call npm install
    popd
)

if not exist "frontend\.env" (
    copy "frontend\.env.example" "frontend\.env" >nul
)

start /min "Backend - AI Change Request Analyzer" cmd /k "cd /d %~dp0backend && call .venv\Scripts\activate.bat && python -m uvicorn app.main:app --reload"
timeout /t 3 /nobreak >nul
start /min "Frontend - AI Change Request Analyzer" cmd /k "cd /d %~dp0frontend && npm run dev"
