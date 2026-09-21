@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)
set "PYTHONPATH=%CD%\src"


echo [INFO] Importing manual showcase Excel into database...
"%PYTHON_EXE%" -m moments_inventory.cli showcase-db-import --yes --showcase-config "%~dp0config\showcase.yaml"
if errorlevel 1 (
  echo [ERROR] Import failed.
  pause
  exit /b 1
)

echo [INFO] Importing CCD sample images...
"%PYTHON_EXE%" -m moments_inventory.cli showcase-sample-images-import --showcase-config "%~dp0config\showcase.yaml"
if errorlevel 1 (
  echo [ERROR] Sample image import failed.
  pause
  exit /b 1
)

echo [OK] Database updated.
pause
