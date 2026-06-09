@echo off
chcp 65001 > nul
title ACHRO 재고관리 시스템

:: ── 오늘 날짜 (yyyy-MM-dd) ───────────────────────────────────────
for /f %%i in ('powershell -nologo -command "Get-Date -Format 'yyyy-MM-dd'"') do set TODAY=%%i

:: ── 최신 코드 업데이트 (git pull) ────────────────────────────────
echo [UPDATE] 최신 코드 업데이트 중...
cd /d "%~dp0"
git pull origin main > nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] 코드 최신 상태
) else (
    echo [WARN] git pull 실패 (오프라인이거나 git 미설치) — 기존 코드로 실행
)

:: ── 프록시 서버 재시작 (항상 최신 코드로) ───────────────────────
echo [RESTART] 프록시 서버 재시작 중...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7777 " ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a > nul 2>&1
)
timeout /t 1 /nobreak > nul
start "ACHRO-Proxy" /min cmd /c "cd /d "%~dp0" && python proxy.py"

:: 프록시 응답 대기 (최대 15초)
echo [WAIT] 프록시 준비 대기 중...
powershell -nologo -command "for($i=0;$i -lt 15;$i++){try{$r=(New-Object Net.WebClient).DownloadString('http://localhost:7777/ping');if($r -like '*ok*'){Write-Host '[OK] 프록시 준비 완료';exit 0}}catch{};Start-Sleep 1};Write-Host '[WARN] 프록시 응답 지연'"

:: ── 자비스 서버 확인 (포트 5000) ─────────────────────────────────
netstat -ano | findstr ":5000 " | findstr "LISTENING" > nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] 자비스 서버 이미 실행 중
) else (
    echo [START] 자비스 서버 시작 중...
    start "ACHRO-Jarvis" /min cmd /c "cd /d "%~dp0" && python jarvis/jarvis.py"
    timeout /t 2 /nobreak > nul
    echo [OK] 자비스 서버 시작 완료
)

:: ── 브리핑 자동 실행 (오늘 아직 안 돌린 경우) ───────────────────
set MARKER=%~dp0jarvis\.last_briefing
set LAST_RUN=
if exist "%MARKER%" (
    set /p LAST_RUN=<"%MARKER%"
)

if "%LAST_RUN%"=="%TODAY%" (
    echo [OK] 브리핑 오늘 이미 수집됨 (%TODAY%)
) else (
    echo [START] 브리핑 데이터 수집 시작 (백그라운드)...
    echo %TODAY%>"%MARKER%"
    start "ACHRO-Briefing" /min cmd /c "cd /d "%~dp0" && python briefing.py"
    echo [OK] 브리핑 백그라운드 실행 중 (수 분 소요)
)

:: ── 브라우저에서 GitHub Pages 열기 ──────────────────────────────
echo [OPEN] 재고관리 시스템 브라우저 열기...
start "" "https://jinhan0310.github.io/achro/"

echo.
echo ACHRO 재고관리 시스템이 실행되었습니다.
echo 이 창은 3초 후 자동으로 닫힙니다.
timeout /t 3 /nobreak > nul
