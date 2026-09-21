@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)
set "PYTHONPATH=%CD%\src"

echo [INFO] Backing up showcase database and uploaded images...
"%PYTHON_EXE%" -m moments_inventory.cli showcase-db-backup --showcase-config "%~dp0config\showcase.yaml"
if errorlevel 1 (
  echo [ERROR] Backup failed.
  pause
  exit /b 1
)

echo [OK] Backup created under backup\showcase
pause
