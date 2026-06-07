@echo off
chcp 65001 > nul
echo ============================================
echo   자비스 + ngrok 시작
echo ============================================

:: Jarvis 서버가 이미 실행 중이면 종료
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :5000 ^| findstr LISTENING 2^>nul') do (
    taskkill /f /pid %%a > nul 2>&1
)

:: Jarvis 서버 백그라운드 실행
echo [1/2] Jarvis 서버 시작 중...
start "Jarvis Server" /min cmd /c "cd /d %~dp0.. && python jarvis/jarvis.py"
timeout /t 2 > nul
echo       http://localhost:5000 (로컬)

:: ngrok으로 외부 공개 (고정 도메인)
echo [2/2] ngrok 터널 연결 중...
echo.
echo ============================================
echo   카카오 오픈빌더 스킬 서버 URL:
echo   https://oxidation-trespass-penny.ngrok-free.dev/webhook
echo ============================================
echo.
"C:\Users\user\AppData\Local\Microsoft\WinGet\Links\ngrok.exe" http --domain=oxidation-trespass-penny.ngrok-free.dev 5000
