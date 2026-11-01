@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-pearl-miner.ps1" -ConfigPath "%~dp0miner.block-hunt.local" -ApplyTuning
set "BLOCKHUNTER_EXIT=%ERRORLEVEL%"
echo.
if not "%BLOCKHUNTER_EXIT%"=="0" (
  echo BlockHunter exited with code %BLOCKHUNTER_EXIT%.
  pause
)
exit /b %BLOCKHUNTER_EXIT%
