@echo off
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0Doctor-Docker.ps1" %*
if errorlevel 1 pause
