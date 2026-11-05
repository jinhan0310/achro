@echo off
title ACHRO Proxy
cd /d "%~dp0"

if exist .git (
    echo [1/3] Updating code...
    git pull origin main >nul 2>&1
    echo Done.
) else (
    echo [1/3] Skipping update ^(not a git folder - download the latest ZIP to update^).
)

echo [2/3] Restarting proxy...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7777 " ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul
start "ACHRO-Proxy" /min cmd /c "cd /d "%~dp0" && python proxy.py"
powershell -nologo -command "for($i=0;$i -lt 15;$i++){try{$r=(New-Object Net.WebClient).DownloadString('http://localhost:7777/ping');if($r -like '*ok*'){Write-Host '[OK] Proxy ready';exit 0}}catch{};Start-Sleep 1};Write-Host '[FAIL] Proxy did not start. Run 다른PC설치.bat first.';exit 1"
if errorlevel 1 (
    pause
    exit /b 1
)

echo [3/3] Opening ACHRO...
start "" "https://jinhan0310.github.io/achro/"
timeout /t 3 /nobreak >nul
