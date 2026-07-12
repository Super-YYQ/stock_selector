param(
    [string]$Time = "17:30",
    [switch]$Publish
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$TaskName = -join @([char]0x0041, [char]0x80A1, [char]0x76D8, [char]0x540E, [char]0x9009, [char]0x80A1, [char]0x52A9, [char]0x624B)
$Bootstrap = Join-Path $Root "scripts\bootstrap.py"
$PythonLauncher = $null
$Py = Get-Command py.exe -ErrorAction SilentlyContinue

if ($Py) {
    $Candidate = & $Py.Source -3.12 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $Candidate) {
        $PythonLauncher = $Candidate.Trim()
    }
}
if (-not $PythonLauncher) {
    $PythonLauncher = (Get-Command python.exe -ErrorAction Stop).Source
}
$Arguments = '"{0}" --command daily' -f $Bootstrap
if ($Publish) {
    $Arguments += " --publish"
}

$Action = New-ScheduledTaskAction -Execute $PythonLauncher -Argument $Arguments -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 6) -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "工作日盘后更新 A 股数据并生成观察报告" -Force | Out-Null
Write-Host "已安装计划任务：$TaskName（工作日 $Time）" -ForegroundColor Green
if ($Publish) {
    Write-Host "任务成功后将自动提交并推送 site 目录。" -ForegroundColor Yellow
}
