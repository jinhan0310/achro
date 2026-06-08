@echo off
chcp 65001 > nul
title ACHRO 재고관리 시스템

:: ── 오늘 날짜 (yyyy-MM-dd) ───────────────────────────────────────
for /f %%i in ('powershell -nologo -command "Get-Date -Format 'yyyy-MM-dd'"') do set TODAY=%%i

:: ── 프록시 서버 확인 (포트 7777) ─────────────────────────────────
netstat -ano | findstr ":7777 " | findstr "LISTENING" > nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] 프록시 서버 이미 실행 중
) else (
    echo [START] 프록시 서버 시작 중...
    start "ACHRO-Proxy" /min cmd /c "cd /d "%~dp0" && python proxy.py"
    timeout /t 2 /nobreak > nul
    echo [OK] 프록시 서버 시작 완료
)

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

:: ── 브라우저에서 index.html 열기 ─────────────────────────────────
echo [OPEN] 재고관리 시스템 브라우저 열기...
start "" "%~dp0index.html"

echo.
echo ACHRO 재고관리 시스템이 실행되었습니다.
echo 이 창은 3초 후 자동으로 닫힙니다.
timeout /t 3 /nobreak > nul
