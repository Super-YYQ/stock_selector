param(
    [string]$Time = "17:30",
    [switch]$Midday,
    [string]$MiddayTime = "12:30",
    [switch]$Publish
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$TaskName = -join @([char]0x0041, [char]0x80A1, [char]0x76D8, [char]0x540E, [char]0x9009, [char]0x80A1, [char]0x52A9, [char]0x624B)
$Bootstrap = Join-Path $Root "scripts\bootstrap.py"
$PythonLauncher = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonLauncher)) {
    $PythonLauncher = (Get-Command python.exe -ErrorAction Stop).Source
}
$Arguments = '"{0}" --command daily' -f $Bootstrap
if ($Publish) {
    $Arguments += " --publish"
}

function New-WeekdayTrigger([string]$Value) {
    $Hours = [int]$Value.Substring(0, 2)
    $Minutes = [int]$Value.Substring(3, 2)
    $AtTime = [datetime]::Today.AddHours($Hours).AddMinutes($Minutes)
    return New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $AtTime
}

# Wrap the task in cmd.exe with output redirection so an interactive console
# (QuickEdit selection mode) can never block the pipeline on stdout/stderr writes.
$LogDir = Join-Path $Root "logs"
$LogFile = Join-Path $LogDir "bootstrap.log"
$InnerCommand = 'if not exist "{0}" mkdir "{0}" & "{1}" {2} >> "{3}" 2>&1' -f $LogDir, $PythonLauncher, $Arguments, $LogFile
$Action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument ('/c "{0}"' -f $InnerCommand) -WorkingDirectory $Root
$Triggers = @()
if ($Midday) {
    $Triggers += New-WeekdayTrigger $MiddayTime
}
$Triggers += New-WeekdayTrigger $Time
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 6) -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Triggers -Settings $Settings -Principal $Principal -Description "A-share intraday snapshot and post-market selector on weekdays" -Force | Out-Null
Write-Host "Scheduled task installed: $TaskName (weekdays at $Time)" -ForegroundColor Green
Write-Host "Task output is redirected to $LogFile" -ForegroundColor Yellow
if ($Midday) {
    Write-Host "Intraday snapshot enabled: weekdays at $MiddayTime" -ForegroundColor Cyan
}
if ($Publish) {
    Write-Host "The generated site will be committed and pushed after a successful run." -ForegroundColor Yellow
}
