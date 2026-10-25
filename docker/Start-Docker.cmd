@echo off
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0Start-Docker.ps1" %*
if errorlevel 1 pause
