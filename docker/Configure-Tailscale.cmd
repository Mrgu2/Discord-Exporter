@echo off
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0Configure-Tailscale.ps1" %*
if errorlevel 1 pause
