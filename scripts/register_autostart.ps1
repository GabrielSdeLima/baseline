# Registers a Task Scheduler entry so the Baseline API starts on user log-on.
# Per-user task — no admin rights required.
#
# Run once:
#     powershell -ExecutionPolicy Bypass -File scripts\register_autostart.ps1
#
# To remove:
#     Unregister-ScheduledTask -TaskName BaselineAPI -Confirm:$false

$ErrorActionPreference = "Stop"

$TaskName    = "BaselineAPI"
$RepoRoot    = Split-Path -Parent $PSScriptRoot
$StartScript = Join-Path $PSScriptRoot "start_api.ps1"

if (-not (Test-Path $StartScript)) {
    throw "start_api.ps1 not found at $StartScript"
}

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Removing existing '$TaskName' task…" -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$StartScript`"" `
    -WorkingDirectory $RepoRoot

$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -RestartCount 3 `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName   $TaskName `
    -Action     $Action `
    -Trigger    $Trigger `
    -Settings   $Settings `
    -Description "Baseline health platform API with Garmin auto-sync" | Out-Null

Write-Host ""
Write-Host "Registered task '$TaskName' (runs at log-on)." -ForegroundColor Green
Write-Host "Test it manually now with:" -ForegroundColor Cyan
Write-Host "    Start-ScheduledTask -TaskName $TaskName"
Write-Host "Remove with:" -ForegroundColor Cyan
Write-Host "    Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
