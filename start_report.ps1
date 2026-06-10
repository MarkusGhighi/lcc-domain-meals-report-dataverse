# Start LCC Domain Meals Report Server
# Double-click or run: powershell -File start_report.ps1

$pythonExe = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$genScript = Join-Path $scriptDir "gen_meals_report.py"

if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

if (-not (Test-Path $genScript)) {
    Write-Host "Report-Skript nicht gefunden: $genScript" -ForegroundColor Red
    pause
    exit 1
}

Write-Host ""
Write-Host "  LCC Domain Meals Report - Dataverse" -ForegroundColor Cyan
Write-Host "  ================================================" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Starte Server... Browser oeffnet sich automatisch." -ForegroundColor Green
Write-Host "  Zum Beenden: Ctrl+C oder Fenster schliessen." -ForegroundColor DarkGray
Write-Host ""

& $pythonExe $genScript
