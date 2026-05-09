@echo off
setlocal enabledelayedexpansion

echo ==================================================
echo   cuoti - Build Script  v3.0
echo   Output: dist\cuoti.exe
echo ==================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://www.python.org
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [1/4] Python OK: %PYVER%

:: Install PyInstaller
echo [2/4] Installing PyInstaller...
python -m pip install pyinstaller --quiet --upgrade
if errorlevel 1 (
    echo [ERROR] pip install failed. Check your network.
    pause & exit /b 1
)
echo       PyInstaller ready.

:: Check required files
echo [3/4] Checking project files...
if not exist "app.py" (
    echo [ERROR] app.py not found. Run this script from the project root.
    pause & exit /b 1
)
if not exist "ui\index.html" (
    echo [ERROR] ui\index.html not found.
    pause & exit /b 1
)
if not exist "cuoti.spec" (
    echo [ERROR] cuoti.spec not found.
    pause & exit /b 1
)
echo       Files OK.

:: Build
echo [4/4] Building exe (30~60 seconds)...
echo.
python -m PyInstaller cuoti.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. See output above.
    pause & exit /b 1
)

:: Done
echo.
echo ==================================================
echo   Build successful!
echo   Location: dist\cuoti.exe
echo   Double-click cuoti.exe to launch the app.
echo   Browser opens automatically.
echo ==================================================
echo.

set /p RUN="Run it now? (y/n): "
if /i "%RUN%"=="y" start "" "dist\cuoti.exe"

pause
