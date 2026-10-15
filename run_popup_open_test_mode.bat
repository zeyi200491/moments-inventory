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
if not exist "output" mkdir "output"
set "RUNTIME_CONFIG=.test-tmp\run-modes\popup-open-test.config.yaml"
set "CAPTURE_DIR=%ROOT%output\popup-open-test-snapshots"

echo [INFO] Preparing popup-open observation config; timeline scrolling is disabled.
call ".venv\Scripts\python.exe" -m moments_inventory.run_modes --base-config "config/config.yaml" --output-config "%RUNTIME_CONFIG%" --run-output-dir "%ROOT%output" --skip-timeline-scroll --timeline-open-observe-ms 1000 --timeline-open-capture-dir "%CAPTURE_DIR%"
if errorlevel 1 (
    echo [ERROR] Failed to prepare popup-open test config.
    goto :fail
)

echo [INFO] Starting warmup-only popup-open test. No inventory sync or export will run.
call ".venv\Scripts\python.exe" -m moments_inventory.cli --config "%RUNTIME_CONFIG%" warmup
if errorlevel 1 (
    echo [ERROR] Popup-open test failed.
    goto :fail
)

echo [OK] Popup-open test completed.
goto :success

:fail
echo [DONE] Script finished with errors.
call :cleanup_screenshots
goto :end_fail

:success
call :cleanup_screenshots
if /I not "%NONINTERACTIVE%"=="1" pause
exit /b 0

:end_fail
if /I not "%NONINTERACTIVE%"=="1" pause
exit /b 1

:cleanup_screenshots
if exist "%ROOT%output" (
    for /d %%D in ("%ROOT%output\*snapshots*") do (
        if exist "%%~fD\" (
            echo [INFO] Removing screenshot residue: %%~fD
            rmdir /s /q "%%~fD" 2>nul
        )
    )
)
exit /b 0
