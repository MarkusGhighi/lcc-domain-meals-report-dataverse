@echo off
title LCC Domain Report - Publish to GitHub Pages
cd /d "%~dp0"

echo Running monitored Dataverse -> GitHub Pages automation...
echo Dashboard: http://127.0.0.1:8767/
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_report_automation.ps1"
if errorlevel 1 (
    echo.
    echo  ERROR: Automation failed. Open the monitor dashboard for details:
    echo  http://127.0.0.1:8767/
    pause
    exit /b 1
)

echo.
echo  ========================================
echo   Published! Your report is live at:
echo   https://markusghighi.github.io/lcc-domain-meals-report-dataverse/
echo  ========================================
echo.
pause
