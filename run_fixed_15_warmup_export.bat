@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "NONINTERACTIVE=%MOMENTS_INVENTORY_NONINTERACTIVE%"
cd /d "%ROOT%"
set "PYTHONPATH=%ROOT%src;%PYTHONPATH%"

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
    echo [HINT] Copy config\models.example.txt to config\models.txt first.
    goto :fail
)

if not exist ".test-tmp\run-modes" mkdir ".test-tmp\run-modes"
set "RUNTIME_CONFIG=.test-tmp\run-modes\fixed-15-warmup.config.yaml"

echo [INFO] Preparing the fixed 15-contact, no-media warmup config...
call ".venv\Scripts\python.exe" -m moments_inventory.run_modes --base-config "config/config.yaml" --output-config "%RUNTIME_CONFIG%" --preset fixed-15-warmup --run-output-dir "%ROOT%output"
if errorlevel 1 (
    echo [ERROR] Failed to prepare the fixed 15-contact runtime config.
    goto :fail
)

echo [INFO] Starting fixed 15-contact warmup and priority export...
call ".venv\Scripts\python.exe" -m moments_inventory.cli --config "%RUNTIME_CONFIG%" orchestrated-run --mode priority_only
if errorlevel 1 (
    echo [ERROR] Fixed 15-contact warmup/export failed.
    goto :fail
)

echo [OK] Fixed 15-contact warmup/export completed.
goto :success

:fail
echo [DONE] Script finished with errors.
goto :end_fail

:success
if /I not "%NONINTERACTIVE%"=="1" pause
exit /b 0

:end_fail
if /I not "%NONINTERACTIVE%"=="1" pause
exit /b 1
