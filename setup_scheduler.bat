@echo off
chcp 65001 > nul
echo ============================================
echo   아크로 쇼핑몰 Daily 브리핑 - 스케줄러 등록
echo ============================================
echo.

:: Python 경로 자동 탐색
for /f "tokens=*" %%i in ('where python') do set PYTHON_PATH=%%i
if "%PYTHON_PATH%"=="" (
    echo [오류] Python을 찾을 수 없습니다. Python을 먼저 설치해주세요.
    pause
    exit /b 1
)
echo [확인] Python: %PYTHON_PATH%

:: briefing.py 절대 경로
set SCRIPT_PATH=%~dp0briefing.py
echo [확인] 스크립트: %SCRIPT_PATH%
echo.

:: 기존 작업 삭제 후 새로 등록
schtasks /delete /tn "아크로_Daily_브리핑" /f > nul 2>&1

schtasks /create ^
  /tn "아크로_Daily_브리핑" ^
  /tr "\"%PYTHON_PATH%\" \"%SCRIPT_PATH%\"" ^
  /sc daily ^
  /st 08:00 ^
  /ru "%USERNAME%" ^
  /rl highest ^
  /f

if %errorlevel% equ 0 (
    echo.
    echo [완료] 매일 오전 8:00 자동 실행으로 등록되었습니다.
    echo        작업 스케줄러에서 "아크로_Daily_브리핑" 항목을 확인하세요.
) else (
    echo.
    echo [오류] 스케줄러 등록에 실패했습니다.
    echo        관리자 권한으로 이 배치파일을 실행해주세요.
)
echo.
pause
