@echo off
title OMS Token Refresh
cd /d "%~dp0"
echo [1/2] Removing expired token cache...
if exist .oms_token.json del .oms_token.json
echo [2/2] Logging in to Imweb admin to get a new OMS token (about 30 sec)...
python -c "from fetch_orders_oms import get_oms_token; get_oms_token(); print('[OK] New OMS token saved. You can close this window.')"
if errorlevel 1 echo [FAIL] Token refresh failed. Check .env (IMWEB_EMAIL / IMWEB_PASSWORD).
echo.
pause
