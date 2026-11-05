@echo off
setlocal EnableExtensions
title Codex Auto Resume Installer
echo.
echo Codex Auto Resume - Windows Installer
echo.

set /p SESSION_ID=Enter Codex session ID: 
if "%SESSION_ID%"=="" goto :missing_session

set /p WORKSPACE=Enter original task folder (default: %USERPROFILE%): 
if "%WORKSPACE%"=="" set "WORKSPACE=%USERPROFILE%"

set /p MINUTES=Retry interval in minutes (default: 60): 
if "%MINUTES%"=="" set "MINUTES=60"

where python >nul 2>nul
if errorlevel 1 goto :missing_python
for /f "delims=" %%I in ('where python') do if not defined PYTHON_BIN set "PYTHON_BIN=%%I"

where codex >nul 2>nul
if not errorlevel 1 for /f "delims=" %%I in ('where codex') do if not defined CODEX_BIN set "CODEX_BIN=%%I"
if not defined CODEX_BIN if exist "%LOCALAPPDATA%\Programs\ChatGPT\resources\codex.exe" set "CODEX_BIN=%LOCALAPPDATA%\Programs\ChatGPT\resources\codex.exe"
if not defined CODEX_BIN goto :missing_codex

set "INSTALL_DIR=%LOCALAPPDATA%\CodexResume"
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
copy /Y "%~dp0codex_resume_web.py" "%INSTALL_DIR%\codex_resume_web.py" >nul

set "CONFIG_PATH=%INSTALL_DIR%\config.json"
"%PYTHON_BIN%" "%~dp0write_config.py" "%CONFIG_PATH%" "%SESSION_ID%" "%WORKSPACE%" "%MINUTES%" "%CODEX_BIN%"
if errorlevel 1 goto :failed

(
  echo @echo off
  echo "%PYTHON_BIN%" "%INSTALL_DIR%\codex_resume_web.py"
) > "%INSTALL_DIR%\run.bat"

schtasks /Delete /TN "Codex Auto Resume" /F >nul 2>nul
schtasks /Create /TN "Codex Auto Resume" /SC ONLOGON /TR "\"%INSTALL_DIR%\run.bat\"" /F >nul
if errorlevel 1 goto :failed

start "Codex Auto Resume" /MIN "%INSTALL_DIR%\run.bat"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765"
echo.
echo Installed successfully. Dashboard: http://127.0.0.1:8765
pause
exit /b 0

:missing_session
echo Session ID cannot be empty.
pause
exit /b 1

:missing_python
echo Python 3 was not found. Install it from https://www.python.org/downloads/windows/
echo During installation, enable "Add Python to PATH".
pause
exit /b 1

:missing_codex
echo Codex was not found. Install and sign in to ChatGPT/Codex, then ensure codex is in PATH.
pause
exit /b 1

:failed
echo Installation failed. Please review the messages above.
pause
exit /b 1
