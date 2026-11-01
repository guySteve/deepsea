@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-pearl-miner.ps1" -Benchmark
set "BLOCKHUNTER_EXIT=%ERRORLEVEL%"
echo.
if not "%BLOCKHUNTER_EXIT%"=="0" pause
exit /b %BLOCKHUNTER_EXIT%
