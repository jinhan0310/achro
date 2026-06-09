@echo off
title ACHRO System

for /f %%i in ('powershell -nologo -command "Get-Date -Format 'yyyy-MM-dd'"') do set TODAY=%%i

cd /d "%~dp0"

echo [1/4] Updating code...
git pull origin main > nul 2>&1
echo Done.

echo [2/4] Restarting proxy...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7777 " ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a > nul 2>&1
)
timeout /t 1 /nobreak > nul
start "ACHRO-Proxy" /min cmd /c "cd /d "%~dp0" && python proxy.py"
powershell -nologo -command "for($i=0;$i -lt 15;$i++){try{$r=(New-Object Net.WebClient).DownloadString('http://localhost:7777/ping');if($r -like '*ok*'){Write-Host '[OK] Proxy ready';exit 0}}catch{};Start-Sleep 1};Write-Host '[WARN] Proxy slow'"

echo [3/4] Starting Jarvis...
netstat -ano | findstr ":5000 " | findstr "LISTENING" > nul 2>&1
if %errorlevel% neq 0 (
    start "ACHRO-Jarvis" /min cmd /c "cd /d "%~dp0" && python jarvis/jarvis.py"
    timeout /t 2 /nobreak > nul
)

echo [4/4] Briefing check...
set MARKER=%~dp0jarvis\.last_briefing
set LAST_RUN=
if exist "%MARKER%" set /p LAST_RUN=<"%MARKER%"
if not "%LAST_RUN%"=="%TODAY%" (
    echo %TODAY%>"%MARKER%"
    start "ACHRO-Briefing" /min cmd /c "cd /d "%~dp0" && python briefing.py"
)

echo Opening browser...
start "" "https://jinhan0310.github.io/achro/"

timeout /t 3 /nobreak > nul
