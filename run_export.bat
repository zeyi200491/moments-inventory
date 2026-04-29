@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
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

echo [INFO] Starting sync and export...
if not defined WEFLOW_ACCESS_TOKEN (
    echo [WARN] WEFLOW_ACCESS_TOKEN is not set in the current environment.
    echo [WARN] If your WeFlow API requires a token, set it before running again.
)

call ".venv\Scripts\python.exe" -m moments_inventory.cli --config "config/config.yaml" sync --export
if errorlevel 1 (
    echo.
    echo [ERROR] Export failed. Check the error messages above.
    goto :fail
)

echo.
echo [OK] Export completed.
echo [OK] Check task.output_dir in config\config.yaml for the export location.
echo [OK] Excel files and local media are stored in that output directory.
goto :end

:fail
echo.
echo [DONE] Script finished with errors.

:end
echo.
pause
