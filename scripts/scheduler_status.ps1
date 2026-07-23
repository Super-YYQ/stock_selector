$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$TaskName = -join @([char]0x0041, [char]0x80A1, [char]0x76D8, [char]0x540E, [char]0x9009, [char]0x80A1, [char]0x52A9, [char]0x624B)
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if (-not $Task) {
    @{
        supported = $true
        enabled = $false
        task_name = $TaskName
        state = "NotInstalled"
        time = "17:30"
        publish = $false
        next_run_time = $null
        last_run_time = $null
        last_result = $null
    } | ConvertTo-Json -Compress
    exit 0
}

$Info = Get-ScheduledTaskInfo -TaskName $TaskName
$Trigger = $Task.Triggers | Select-Object -First 1
$Action = $Task.Actions | Select-Object -First 1
$TaskTime = "17:30"
if ($Trigger -and $Trigger.StartBoundary) {
    $TaskTime = ([datetime]$Trigger.StartBoundary).ToString("HH:mm")
}

@{
    supported = $true
    enabled = ($Task.State -ne "Disabled")
    task_name = $TaskName
    state = [string]$Task.State
    time = $TaskTime
    publish = [bool]($Action.Arguments -match "--publish")
    next_run_time = if ($Info.NextRunTime -and $Info.NextRunTime.Year -gt 1900) { $Info.NextRunTime.ToString("s") } else { $null }
    last_run_time = if ($Info.LastRunTime -and $Info.LastRunTime.Year -gt 2000) { $Info.LastRunTime.ToString("s") } else { $null }
    last_result = $Info.LastTaskResult
} | ConvertTo-Json -Compress
