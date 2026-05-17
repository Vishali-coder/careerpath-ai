@echo off
title CareerPath AI - Installing Requirements
color 0A

echo.
echo ============================================
echo   CareerPath AI - Package Installer
echo ============================================
echo.

:: Check Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [ERROR] Python is not installed or not in PATH.
    echo         Download Python from: https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

echo [OK] Python found:
python --version
echo.

:: Check pip is available
pip --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [ERROR] pip is not available.
    echo         Run: python -m ensurepip --upgrade
    echo.
    pause
    exit /b 1
)

echo [OK] pip found:
pip --version
echo.

echo Installing packages from requirements.txt...
echo --------------------------------------------
echo.

pip install flask==3.1.3
if errorlevel 1 goto :error

pip install flask-cors==6.0.2
if errorlevel 1 goto :error

pip install requests==2.32.5
if errorlevel 1 goto :error

echo.
echo ============================================
echo   Verifying installations...
echo ============================================
echo.

python -c "import flask; print('[OK] Flask', flask.__version__)"
if errorlevel 1 goto :error

python -c "import flask_cors; print('[OK] Flask-CORS installed')"
if errorlevel 1 goto :error

python -c "import requests; print('[OK] Requests', requests.__version__)"
if errorlevel 1 goto :error

python -c "import sqlite3; print('[OK] SQLite3 (built-in)')"
python -c "import hashlib; print('[OK] Hashlib (built-in)')"
python -c "import json; print('[OK] JSON (built-in)')"

echo.
echo ============================================
echo   All packages installed successfully!
echo   Now run: setup.bat
echo ============================================
echo.
pause
exit /b 0

:error
color 0C
echo.
echo [ERROR] Installation failed. Check the error above.
echo         Try running as Administrator if permission denied.
echo.
pause
exit /b 1
