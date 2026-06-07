# 아크로 쇼핑몰 Daily 브리핑 - 작업 스케줄러 등록
# 관리자 권한 자동 요청

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

$workDir    = "C:\Users\user\Downloads\클로드코드폴더"
$wrapperBat = "$workDir\run_briefing.bat"
$taskName   = "아크로_Daily_브리핑"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  아크로 쇼핑몰 Daily 브리핑 스케줄러 등록" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "래퍼: $wrapperBat"
Write-Host "실행: 매일 오전 9:00 / PC 꺼져 있으면 켜진 후 즉시 실행"
Write-Host "로그: $workDir\briefing_log.txt"
Write-Host ""

# 기존 작업 삭제
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# 액션: cmd로 배치 실행 (콘솔 없이)
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$wrapperBat`"" `
    -WorkingDirectory $workDir

# 트리거: 매일 9시
$trigger = New-ScheduledTaskTrigger -Daily -At "09:00AM"

# 설정: PC 꺼져있다 켜지면 즉시 실행, 최대 1시간, 윈도우 숨김
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Description "아크로 쇼핑몰 일일 브리핑 자동 실행 (매일 9:00)" `
    -Force | Out-Null

if ($?) {
    Write-Host "[완료] 등록 성공!" -ForegroundColor Green
    Write-Host ""
    Write-Host "확인 방법:" -ForegroundColor Yellow
    Write-Host "  1. 작업 스케줄러 열기: Win+R → taskschd.msc"
    Write-Host "  2. 작업 스케줄러 라이브러리에서 '$taskName' 찾기"
    Write-Host "  3. 우클릭 → '실행' 으로 즉시 테스트 가능"
    Write-Host ""
    Write-Host "로그 확인: $workDir\briefing_log.txt"
} else {
    Write-Host "[오류] 등록 실패 - 관리자 권한으로 재시도해주세요." -ForegroundColor Red
}

Write-Host ""
Read-Host "엔터를 눌러 종료"
