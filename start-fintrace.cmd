@echo off
setlocal
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo Install Node.js 22 or newer from the official Node.js website first.
  pause
  exit /b 1
)
if not exist node_modules (
  call npm ci
  if errorlevel 1 exit /b 1
)
if not exist apps\web\dist\index.html (
  call npm run build
  if errorlevel 1 exit /b 1
)
echo Open http://localhost:4310 in your browser. Press Ctrl+C to stop.
call npm run dev
