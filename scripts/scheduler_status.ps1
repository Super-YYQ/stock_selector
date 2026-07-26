$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$TaskName = -join @([char]0x0041, [char]0x80A1, [char]0x76D8, [char]0x540E, [char]0x9009, [char]0x80A1, [char]0x52A9, [char]0x624B)
try {
    $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
}
catch {
    if ($_.FullyQualifiedErrorId -like "CmdletizationQuery_NotFound_TaskName,*") {
        $Task = $null
    }
    else {
        Write-Error ("Unable to read scheduled task: " + $_.Exception.Message)
        exit 1
    }
}

if (-not $Task) {
    @{
        supported = $true
        enabled = $false
        task_name = $TaskName
        state = "NotInstalled"
        time = "17:30"
        midday_enabled = $false
        midday_time = "12:30"
        trigger_times = @()
        publish = $false
        next_run_time = $null
        last_run_time = $null
        last_result = $null
    } | ConvertTo-Json -Compress
    exit 0
}

$Info = Get-ScheduledTaskInfo -TaskName $TaskName
$Action = $Task.Actions | Select-Object -First 1
$TriggerTimes = @(
    $Task.Triggers |
        Where-Object { $_.StartBoundary } |
        ForEach-Object { ([datetime]$_.StartBoundary).ToString("HH:mm") } |
        Sort-Object
)
$TaskTime = if ($TriggerTimes.Count -gt 0) { $TriggerTimes[-1] } else { "17:30" }
$MiddayEnabled = $TriggerTimes.Count -gt 1
$MiddayTime = "12:30"
if ($MiddayEnabled) {
    $MiddayTime = $TriggerTimes[0]
}

@{
    supported = $true
    enabled = ($Task.State -ne "Disabled")
    task_name = $TaskName
    state = [string]$Task.State
    time = $TaskTime
    midday_enabled = $MiddayEnabled
    midday_time = $MiddayTime
    trigger_times = $TriggerTimes
    publish = [bool]($Action.Arguments -match "--publish")
    next_run_time = if ($Info.NextRunTime -and $Info.NextRunTime.Year -gt 1900) { $Info.NextRunTime.ToString("s") } else { $null }
    last_run_time = if ($Info.LastRunTime -and $Info.LastRunTime.Year -gt 2000) { $Info.LastRunTime.ToString("s") } else { $null }
    last_result = $Info.LastTaskResult
} | ConvertTo-Json -Compress
