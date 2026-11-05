@echo off
setlocal
schtasks /Delete /TN "Codex Auto Resume" /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq Codex Auto Resume" /F >nul 2>nul
if exist "%LOCALAPPDATA%\CodexResume" rmdir /S /Q "%LOCALAPPDATA%\CodexResume"
echo Codex Auto Resume has been uninstalled.
pause
