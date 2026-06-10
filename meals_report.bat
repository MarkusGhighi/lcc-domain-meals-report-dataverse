@echo off
title Meals Report Server
cd /d "%~dp0"

set LOGFILE=%~dp0error.log

echo Starting LCC Domain Meals Report...
echo.

:: Log start
echo %date% %time% ^| START  ^| meals_report.bat gestartet >> "%LOGFILE%"

"C:\Users\marku\AppData\Local\Programs\Python\Python314\python.exe" gen_meals_report.py 2>"%TEMP%\meals_report_stderr.txt"

if errorlevel 1 (
    echo.
    echo === FEHLER beim Starten des Reports ===
    echo.
    :: Log error with stderr output
    echo %date% %time% ^| ERROR  ^| Report Server fehlgeschlagen (exit code %errorlevel%) >> "%LOGFILE%"
    for /f "usebackq delims=" %%L in ("%TEMP%\meals_report_stderr.txt") do (
        echo %date% %time% ^| DETAIL ^| %%L >> "%LOGFILE%"
    )
    type "%TEMP%\meals_report_stderr.txt"
    echo.
    pause
) else (
    echo %date% %time% ^| STOP   ^| Report Server beendet >> "%LOGFILE%"
)
