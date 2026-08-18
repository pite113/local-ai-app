@echo off
chcp 65001 >nul
cd /d %~dp0
powershell -ExecutionPolicy Bypass -File pack.ps1
pause
