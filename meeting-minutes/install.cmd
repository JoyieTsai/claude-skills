@echo off
rem meeting-minutes Windows installer. Double-click it, or run: install.cmd --yes
rem The real work is in install.ps1. This wrapper only lets Windows run it
rem (ExecutionPolicy Bypass), so nobody has to change system settings.
rem Keep this file ASCII-only: cmd.exe reads it in the system code page.
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "code=%ERRORLEVEL%"
rem A double-clicked window closes immediately; pause so the result stays visible.
if "%~1"=="" pause
exit /b %code%
