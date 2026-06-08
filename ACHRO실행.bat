@echo off
chcp 65001 > nul
title ACHRO 재고관리 시스템

:: ── 프록시가 이미 실행 중인지 확인 (포트 7777) ──────────────────
netstat -ano | findstr ":7777 " | findstr "LISTENING" > nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] 프록시 서버 이미 실행 중
) else (
    echo [START] 프록시 서버 시작 중...
    start "ACHRO-Proxy" /min cmd /c "cd /d "%~dp0" && python proxy.py"
    :: 프록시가 뜰 때까지 잠깐 대기
    timeout /t 2 /nobreak > nul
    echo [OK] 프록시 서버 시작 완료
)

:: ── 브라우저에서 index.html 열기 ────────────────────────────────
echo [OPEN] 재고관리 시스템 브라우저 열기...
start "" "%~dp0index.html"

echo.
echo ACHRO 재고관리 시스템이 실행되었습니다.
echo 이 창은 3초 후 자동으로 닫힙니다.
timeout /t 3 /nobreak > nul
