@echo off
title AI Change Request Analyzer - Launcher
echo ============================================
echo   Starting AI Change Request Analyzer
echo ============================================
echo.

cd /d "%~dp0"

REM ---------- Backend setup (only does real work the first time) ----------
if not exist "backend\.venv\Scripts\python.exe" (
    echo [Backend] No virtual environment found - setting one up and
    echo [Backend] installing dependencies. This only happens once and
    echo [Backend] can take a minute or two. Please wait...
    echo.
    pushd backend
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
    call deactivate
    popd
    echo.
    echo [Backend] Setup complete.
    echo.
)

if not exist "backend\.env" (
    echo [Backend] No backend\.env found - creating one from backend\.env.example.
    echo [Backend] IMPORTANT: open backend\.env afterward and fill in SECRET_KEY
    echo [Backend] and an AI provider key, or AI Analysis will not work yet.
    copy "backend\.env.example" "backend\.env" >nul
    echo.
)

REM ---------- Frontend setup (only does real work the first time) ----------
if not exist "frontend\node_modules" (
    echo [Frontend] Dependencies not installed yet - running npm install.
    echo [Frontend] This only happens once and can take a minute or two.
    echo.
    pushd frontend
    call npm install
    popd
    echo.
    echo [Frontend] Setup complete.
    echo.
)

if not exist "frontend\.env" (
    copy "frontend\.env.example" "frontend\.env" >nul
)

REM ---------- Launch both servers, each in its own window ----------
echo Starting backend and frontend in separate windows...
echo.
start "Backend - AI Change Request Analyzer" cmd /k "cd /d %~dp0backend && call .venv\Scripts\activate.bat && python -m uvicorn app.main:app --reload"
timeout /t 3 /nobreak >nul
start "Frontend - AI Change Request Analyzer" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo Waiting for both servers to finish starting...
timeout /t 8 /nobreak >nul

echo Opening the app in your default browser...
start "" "http://localhost:5173"

echo.
echo ============================================
echo   Both servers are running, each in its own window:
echo     Backend:  http://localhost:8000
echo     Frontend: http://localhost:5173
echo.
echo   Keep those two windows open while you use or present the app.
echo   Closing a window stops that server.
echo   This launcher window can be closed now.
echo ============================================
pause
