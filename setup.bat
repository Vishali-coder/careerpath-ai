@echo off
title CareerPath AI - Setup and Launch
color 0A

echo.
echo ============================================
echo   CareerPath AI - Setup and Launch
echo ============================================
echo.

:: ── STEP 1: Check Python ──────────────────────────────────────────────────────
echo [1/6] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [FAIL] Python not found.
    echo        Install from: https://www.python.org/downloads/
    echo        Check "Add Python to PATH" during install.
    goto :fail
)
echo [OK] Python found:
python --version
echo.

:: ── STEP 2: Check required files ─────────────────────────────────────────────
echo [2/6] Checking required files...

if not exist "app.py" (
    color 0C
    echo [FAIL] app.py not found. Are you in the right folder?
    goto :fail
)
echo [OK] app.py found

if not exist "requirements.txt" (
    color 0C
    echo [FAIL] requirements.txt not found.
    goto :fail
)
echo [OK] requirements.txt found

if not exist "templates\index.html" (
    color 0C
    echo [FAIL] templates\index.html not found.
    goto :fail
)
echo [OK] templates\index.html found
echo.

:: ── STEP 3: Install / verify packages ────────────────────────────────────────
echo [3/6] Installing required packages...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    color 0C
    echo [FAIL] Package installation failed.
    echo        Try running as Administrator.
    goto :fail
)
echo [OK] All packages installed
echo.

:: ── STEP 4: Verify imports ────────────────────────────────────────────────────
echo [4/6] Verifying Python imports...
python -c "from flask import Flask; from flask_cors import CORS; import requests, sqlite3, json, re, time, hashlib; print('[OK] All imports successful')"
if errorlevel 1 (
    color 0C
    echo [FAIL] Import check failed. Run install_requirements.bat first.
    goto :fail
)
echo.

:: ── STEP 5: Syntax check app.py ──────────────────────────────────────────────
echo [5/6] Checking app.py for syntax errors...
python -m py_compile app.py
if errorlevel 1 (
    color 0C
    echo [FAIL] Syntax error found in app.py.
    echo        Run: python -m py_compile app.py
    goto :fail
)
echo [OK] app.py syntax is valid
echo.

:: ── STEP 6: Launch the app ───────────────────────────────────────────────────
echo [6/6] All checks passed! Launching CareerPath AI...
echo.
echo ============================================
echo   App running at: http://localhost:5000
echo   Press CTRL+C to stop the server
echo ============================================
echo.

:: Open browser after 2 seconds
start "" timeout /t 2 /nobreak >nul
start "" "http://localhost:5000"

python app.py
goto :end

:fail
echo.
echo ============================================
echo   Setup failed. Fix the error above and
echo   run setup.bat again.
echo ============================================
echo.
pause
exit /b 1

:end
pause
