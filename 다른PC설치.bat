@echo off
title ACHRO Setup (another PC)
cd /d "%~dp0"
echo ============================================
echo   ACHRO proxy setup for this computer
echo ============================================
echo.

echo [1/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python is not installed.
    echo        Install Python 3.10+ from https://www.python.org/downloads/
    echo        IMPORTANT: check "Add python.exe to PATH" in the installer, then run this file again.
    pause
    exit /b 1
)
python --version

echo.
echo [2/5] Installing packages...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements_proxy.txt
if errorlevel 1 (
    echo [FAIL] Package install failed. Check your internet connection and run again.
    pause
    exit /b 1
)

echo.
echo [3/5] Installing browser component (used only for the admin memo login, ~150MB)...
python -m playwright install chromium

echo.
echo [4/5] Checking .env settings...
if not exist .env (
    copy .env.example .env >nul
    echo       .env was created from the template.
)
python -c "from dotenv import dotenv_values; v=dotenv_values('.env'); import sys; sys.exit(0 if all(v.get(k) for k in ('IMWEB_API_KEY','IMWEB_SECRET_KEY','IMWEB_SITE_CODE','IMWEB_GROUND_CLIENT_ID','IMWEB_GROUND_CLIENT_SECRET')) else 1)"
if errorlevel 1 (
    echo.
    echo [ACTION] Notepad will open. Fill in these 5 values, save, and close Notepad:
    echo            IMWEB_API_KEY / IMWEB_SECRET_KEY / IMWEB_SITE_CODE
    echo            IMWEB_GROUND_CLIENT_ID / IMWEB_GROUND_CLIENT_SECRET
    echo          Copy them from .env on your main computer (USB / typing). Do NOT send them by chat or email.
    notepad .env
    echo.
    echo Press any key AFTER you saved and closed Notepad...
    pause >nul
)

echo.
echo [5/5] Issuing the Imweb API token for this computer...
python imweb_token_issue.py
if errorlevel 1 (
    echo [FAIL] Token issue failed. Check the 5 values in .env and run this file again.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Setup finished.
echo   Next: double-click "프록시만실행.bat" to start the proxy.
echo   (Admin memo: run "OMS토큰갱신.bat" once and log in to Imweb in the window that opens.)
echo ============================================
pause
