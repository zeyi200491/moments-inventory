@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo [1/4] Checking Python...
set "PYTHON_CMD="

where py >nul 2>&1
if not errorlevel 1 (
    py -3.11 --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3.11"
)

if not defined PYTHON_CMD (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python was not found. Install Python 3.11 or newer first.
        goto :fail
    )
    set "PYTHON_CMD=python"
)

call %PYTHON_CMD% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python could not be executed. Check the local Python installation.
    goto :fail
)

echo [2/4] Creating virtual environment...
if not exist ".venv\Scripts\python.exe" (
    call %PYTHON_CMD% -m venv ".venv"
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv.
        goto :fail
    )
) else (
    echo [INFO] .venv already exists. Skip creation.
)

echo [3/4] Installing project dependencies...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip.
    goto :fail
)

call ".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 (
    echo [ERROR] Failed to install the project in editable mode.
    goto :fail
)

echo [4/4] Preparing config files...
if not exist "config\config.yaml" (
    copy /Y "config\config.example.yaml" "config\config.yaml" >nul
    echo [INFO] Created config\config.yaml from config\config.example.yaml
) else (
    echo [INFO] config\config.yaml already exists. Skip copy.
)

if not exist "config\models.txt" (
    copy /Y "config\models.example.txt" "config\models.txt" >nul
    echo [INFO] Created config\models.txt from config\models.example.txt
) else (
    echo [INFO] config\models.txt already exists. Skip copy.
)

echo.
echo [OK] Setup completed.
echo [NEXT] Open README.md and complete these steps:
echo [NEXT] 1. Fill config\config.yaml
echo [NEXT] 2. Fill config\models.txt
echo [NEXT] 3. Set WEFLOW_ACCESS_TOKEN in Windows environment variables
echo [NEXT] 4. Run run_export.bat
goto :end

:fail
echo.
echo [DONE] Setup did not complete successfully.

:end
echo.
pause
