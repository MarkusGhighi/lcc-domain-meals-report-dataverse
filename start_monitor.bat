@echo off
title LCC Domain Report Monitor
cd /d "%~dp0"
"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" monitor_server.py
