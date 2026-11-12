@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_app.ps1"
exit /b %errorlevel%
