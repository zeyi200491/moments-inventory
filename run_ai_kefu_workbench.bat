@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
set "HELPER_SCRIPT=%ROOT%scripts\start_ai_kefu_workbench.ps1"

if not exist "%POWERSHELL_EXE%" (
    echo [ERROR] Missing PowerShell executable: %POWERSHELL_EXE%
    goto :fail
)

if not exist "%HELPER_SCRIPT%" (
    echo [ERROR] Missing helper script: scripts\start_ai_kefu_workbench.ps1
    goto :fail
)

"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%HELPER_SCRIPT%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%MOMENTS_INVENTORY_NONINTERACTIVE%"=="1" (
    echo.
    pause
)

exit /b %EXIT_CODE%

:fail
if not "%MOMENTS_INVENTORY_NONINTERACTIVE%"=="1" (
    echo.
    pause
)
exit /b 1
