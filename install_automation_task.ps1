$ErrorActionPreference = 'Stop'

$taskName = 'LCC Domain Meals Report Automation'
$root = $PSScriptRoot
$script = Join-Path $root 'run_report_automation.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'Generates the LCC Domain Dataverse report and pushes it to GitHub Pages.' -Force | Out-Null

Write-Host "Installed scheduled task: $taskName"
Write-Host "Interval: every 30 minutes"
Write-Host "Script: $script"
