param(
    [ValidateSet("install", "uninstall")]
    [string]$Operation,
    [string]$Time = "17:30",
    [switch]$Publish
)

$ErrorActionPreference = "Stop"
$Target = Join-Path $PSScriptRoot ($Operation + "_scheduler.ps1")
$Arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"{0}"' -f $Target))

if ($Operation -eq "install") {
    $Arguments += @("-Time", $Time)
    if ($Publish) {
        $Arguments += "-Publish"
    }
}

$Process = Start-Process -FilePath "powershell.exe" -ArgumentList $Arguments -Verb RunAs -Wait -PassThru
if ($Process.ExitCode -ne 0) {
    throw "Elevated scheduler command failed with exit code $($Process.ExitCode)."
}
