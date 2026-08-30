@echo off
REM Overlord Bridge WPM install script.
REM WPM extracts the package to a staging directory and runs this script from
REM the extracted .wpm folder. The deployable tree lives in ..\payload.
setlocal enabledelayedexpansion

set "WPMDIR=%~dp0"
set "PAYLOAD=%WPMDIR%..\payload"

set "PKGVER=unknown"
for /f "usebackq tokens=1,* delims==" %%A in ("%WPMDIR%package.txt") do (
    if /I "%%A"=="version" set "PKGVER=%%B"
)

where pwsh >nul 2>&1
if errorlevel 1 (
    echo [overlord] PowerShell 7 ^(pwsh.exe^) is required. Install it, then reinstall. 1>&2
    exit /b 1
)

pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PAYLOAD%\Package-Lifecycle.ps1" -Action Install -SourceDirectory "%PAYLOAD%" -Version "%PKGVER%"
exit /b %ERRORLEVEL%
