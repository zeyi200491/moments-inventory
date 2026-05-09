@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "NONINTERACTIVE=%MOMENTS_INVENTORY_NONINTERACTIVE%"
cd /d "%ROOT%"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Missing virtual environment: .venv\Scripts\python.exe
    echo [HINT] Run setup_windows.bat first.
    goto :fail
)

if not exist "config\config.yaml" (
    echo [ERROR] Missing config file: config\config.yaml
    echo [HINT] Run setup_windows.bat and fill the config file first.
    goto :fail
)

if not exist "config\models.txt" (
    echo [ERROR] Missing model dictionary: config\models.txt
    echo [HINT] Copy from config\models.example.txt and fill it first.
    goto :fail
)

echo [INFO] Before running, keep WeChat on Contacts or Chat List.
echo [INFO] Press any key to start warmup, sync, and export.
if /I not "%NONINTERACTIVE%"=="1" pause >nul

if not defined WEFLOW_ACCESS_TOKEN (
    echo [WARN] WEFLOW_ACCESS_TOKEN is not set in the current environment.
    echo [WARN] If your WeFlow API requires a token, set it before running again.
)

call ".venv\Scripts\python.exe" -m moments_inventory.cli --config "config/config.yaml" warmup --export
if errorlevel 1 (
    echo.
    echo [ERROR] Warmup export failed. Check the error messages above.
    goto :fail
)

echo.
echo [OK] Warmup, sync, and export completed.
goto :success

:fail
echo.
echo [DONE] Script finished with errors.
goto :end_fail

:success
echo.
if /I not "%NONINTERACTIVE%"=="1" pause
exit /b 0

:end_fail
echo.
if /I not "%NONINTERACTIVE%"=="1" pause
exit /b 1
