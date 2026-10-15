@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)
set "PYTHONPATH=%CD%\src"
set "SHOWCASE_CONFIG=%~dp0config\showcase.yaml"
if exist "%~dp0config\showcase.local.yaml" set "SHOWCASE_CONFIG=%~dp0config\showcase.local.yaml"

echo [INFO] Backing up showcase database and uploaded images...
"%PYTHON_EXE%" scripts\verify_showcase_environment.py --config "%SHOWCASE_CONFIG%"
if errorlevel 1 (
  echo [错误] 为保护备份数据，拒绝备份非权威 CCD 数据库。
  pause
  exit /b 1
)

"%PYTHON_EXE%" -m moments_inventory.cli showcase-db-backup --showcase-config "%SHOWCASE_CONFIG%"
if errorlevel 1 (
  echo [ERROR] Backup failed.
  pause
  exit /b 1
)

echo [OK] Backup created under backup\showcase
pause
