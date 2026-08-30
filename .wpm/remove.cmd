@echo off
REM Overlord Bridge WPM remove script.
REM WPM stages and verifies the retained archive, then runs this script from the
REM extracted .wpm folder. The lifecycle script preserves .env, AGENTS.md,
REM roster.json, and session pins before deleting the installation.
setlocal

set "WPMDIR=%~dp0"
set "PAYLOAD=%WPMDIR%..\payload"

where pwsh >nul 2>&1
if errorlevel 1 (
    echo [overlord] PowerShell 7 ^(pwsh.exe^) is required to remove Overlord. 1>&2
    exit /b 1
)

pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PAYLOAD%\Package-Lifecycle.ps1" -Action Remove
exit /b %ERRORLEVEL%
