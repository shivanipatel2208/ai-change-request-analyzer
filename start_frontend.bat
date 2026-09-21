@echo off
title Frontend - AI Change Request Analyzer
cd /d "%~dp0frontend"

if not exist "node_modules" (
    echo No dependencies installed yet - running npm install now.
    echo This only happens once and can take a minute or two.
    echo.
    call npm install
)

if not exist ".env" (
    copy ".env.example" ".env" >nul
)

echo.
echo Starting frontend server (http://localhost:5173)...
echo Keep this window open. Close it to stop the frontend.
echo.
call npm run dev
echo.
echo Frontend stopped or failed to start. See any error above.
pause
