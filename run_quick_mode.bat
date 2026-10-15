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

echo [INFO] Quick mode runs only the configured priority batch.
echo [INFO] WeChat must be open and ready before collection starts.
if not exist ".test-tmp\run-modes" mkdir ".test-tmp\run-modes"
set "RUNTIME_CONFIG=.test-tmp\run-modes\quick-mode.config.yaml"

call ".venv\Scripts\python.exe" -m moments_inventory.run_modes --base-config "config/config.yaml" --output-config "%RUNTIME_CONFIG%" --run-output-dir "%ROOT%output"
if errorlevel 1 (
    echo [ERROR] Failed to prepare quick mode runtime config.
    goto :fail
)

call ".venv\Scripts\python.exe" -m moments_inventory.cli --config "%RUNTIME_CONFIG%" orchestrated-run --mode priority_only
if errorlevel 1 (
    echo [ERROR] Quick mode failed. Check logs and output files.
    goto :fail
)

echo [OK] Quick mode completed.
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
