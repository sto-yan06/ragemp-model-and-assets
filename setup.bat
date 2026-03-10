@echo off
title RageMP Lore-Friendly Vehicle Workshop - Setup
echo.
echo  =============================================
echo   Lore-Friendly Vehicle Workshop - Setup
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

:: Check 7-Zip (needed for RAR/7z archives)
if exist "C:\Program Files\7-Zip\7z.exe" (
    echo [OK] 7-Zip found
) else if exist "C:\Program Files (x86)\7-Zip\7z.exe" (
    echo [OK] 7-Zip found (x86)
) else (
    echo [WARNING] 7-Zip not found. RAR/7z archives won't extract.
    echo          Install from https://7-zip.org/
)

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
if not exist "downloads\vehicles" mkdir "downloads\vehicles"
if not exist "new_dlc_exported" mkdir "new_dlc_exported"
if not exist "logs" mkdir "logs"
echo [OK] Directories created

echo.
echo  =============================================
echo   Setup Complete!
echo  =============================================
echo.
echo  Start the dashboard:
echo     npm run preview
echo.
echo  Then open http://127.0.0.1:3000 in your browser
echo  and click "Scrape Lore-Friendly" to start downloading vehicles.
echo.
echo  =============================================
echo.
pause
