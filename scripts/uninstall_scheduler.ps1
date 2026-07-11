$ErrorActionPreference = "Stop"
$TaskName = "A股盘后选股助手"
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Task) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "已删除计划任务：$TaskName" -ForegroundColor Green
} else {
    Write-Host "未找到计划任务：$TaskName"
}
