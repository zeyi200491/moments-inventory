@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "NONINTERACTIVE=%MOMENTS_INVENTORY_NONINTERACTIVE%"
cd /d "%ROOT%"
set "PYTHONPATH=%ROOT%src;%PYTHONPATH%"

if not defined WEFLOW_ACCESS_TOKEN (
    for /f "tokens=2,*" %%A in ('reg query HKCU\Environment /v WEFLOW_ACCESS_TOKEN 2^>nul ^| findstr /R /C:"WEFLOW_ACCESS_TOKEN"') do set "WEFLOW_ACCESS_TOKEN=%%B"
)

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Missing virtual environment: .venv\Scripts\python.exe
    echo [HINT] Run setup_windows.bat first.
    goto :fail
)

if not exist "config" mkdir "config"

if not exist "config\config.yaml" (
    if exist "config\config.example.yaml" (
        copy /Y "config\config.example.yaml" "config\config.yaml" >nul
        echo [INFO] Created config\config.yaml from config\config.example.yaml
    ) else (
        echo [ERROR] Missing config file: config\config.yaml
        echo [HINT] Run setup_windows.bat and fill the config file first.
        goto :fail
    )
)

if not exist "config\models.txt" (
    if exist "config\models.example.txt" (
        copy /Y "config\models.example.txt" "config\models.txt" >nul
        echo [INFO] Created config\models.txt from config\models.example.txt
    ) else (
        echo [ERROR] Missing model dictionary: config\models.txt
        echo [HINT] Copy from config\models.example.txt and fill it first.
        goto :fail
    )
)

echo [INFO] Checking Python dependencies...
call ".venv\Scripts\python.exe" -c "import PIL, pywinauto, win32clipboard" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing or refreshing project dependencies...
    call ".venv\Scripts\python.exe" -m pip install -e .
    if errorlevel 1 (
        echo [ERROR] Failed to install project dependencies.
        goto :fail
    )
)

if not exist ".test-tmp\run-modes" mkdir ".test-tmp\run-modes"
set "RUNTIME_CONFIG=.test-tmp\run-modes\full-mode.config.yaml"

echo [INFO] Preparing full mode runtime config...
call ".venv\Scripts\python.exe" -m moments_inventory.run_modes --base-config "config/config.yaml" --output-config "%RUNTIME_CONFIG%" --run-output-dir "%ROOT%output" --download-media
if errorlevel 1 (
    echo [ERROR] Failed to prepare runtime config.
    goto :fail
)

echo [INFO] Checking WeFlow API access...
call ".venv\Scripts\python.exe" -c "from moments_inventory.config import load_settings; from moments_inventory.weflow_client import WeFlowClient; settings = load_settings(r'%RUNTIME_CONFIG%'); token = settings.weflow.access_token; assert token, 'Missing WEFLOW_ACCESS_TOKEN'; WeFlowClient(settings)._get_json('/api/v1/contacts', {'count': '1'}); print('[OK] WeFlow preflight passed')"
if errorlevel 1 (
    echo [ERROR] WeFlow preflight failed.
    echo [HINT] Check config\config.yaml weflow.base_url and WEFLOW_ACCESS_TOKEN.
    echo [HINT] If you just ran setx, close this command window and run run_full_mode.bat again.
    goto :fail
)

echo [INFO] Full mode = run P1 first, then P2.
echo [INFO] Media download is enabled.
echo [INFO] Starting full mode now...

call ".venv\Scripts\python.exe" -m moments_inventory.cli --config "%RUNTIME_CONFIG%" orchestrated-run --mode full
if errorlevel 1 (
    echo.
    echo [ERROR] Full mode run failed. Check logs and output files.
    goto :fail
)

echo.
echo [OK] Full mode completed.
goto :success

:fail
echo.
echo [DONE] Script finished with errors.
call :cleanup_screenshots
goto :end_fail

:success
echo.
call :cleanup_screenshots
if /I not "%NONINTERACTIVE%"=="1" pause
exit /b 0

:end_fail
echo.
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
