@echo off
title RageMP Vehicle Workshop - Setup
echo.
echo  =============================================
echo   RageMP Vehicle Workshop - First Time Setup
echo  =============================================
echo.

:: Check Node.js
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js not found. Install from https://nodejs.org/
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('node -v') do echo [OK] Node.js %%i

:: Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install from https://python.org/
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo [OK] %%i

echo.
echo [1/3] Installing Node.js dependencies...
call npm install
if %errorlevel% neq 0 (
    echo [ERROR] npm install failed
    pause
    exit /b 1
)
echo [OK] Node.js dependencies installed

echo.
echo [2/3] Installing Python dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [WARNING] Some Python packages may have failed. The dashboard still works.
)
echo [OK] Python dependencies installed

echo.
echo [3/3] Creating required directories...
if not exist "downloads\_metadata" mkdir "downloads\_metadata"
if not exist "downloads\_previews" mkdir "downloads\_previews"
if not exist "new_dlc_exported" mkdir "new_dlc_exported"
if not exist "logs" mkdir "logs"
echo [OK] Directories created

echo.
echo  =============================================
echo   Setup Complete!
echo  =============================================
echo.
echo  NEXT STEPS:
echo.
echo  1. Edit config.json to set your external tool paths:
echo     - blender_path
echo     - gimp_path or paintnet_path
echo     - openiv_path
echo     - codewalker_path
echo.
echo  2. Start the dashboard:
echo     npm run preview
echo.
echo  3. Open http://127.0.0.1:3000 in your browser
echo.
echo  =============================================
echo.
pause
