@echo off
cd /d "%~dp0"
echo. >> briefing_log.txt
echo =========================================== >> briefing_log.txt
echo [Start] %date% %time% >> briefing_log.txt
echo =========================================== >> briefing_log.txt
python briefing.py >> briefing_log.txt 2>&1
echo [Done] %date% %time% / ExitCode: %errorlevel% >> briefing_log.txt
