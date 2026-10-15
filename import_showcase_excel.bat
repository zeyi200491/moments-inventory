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


echo [INFO] Importing manual showcase Excel into database...
"%PYTHON_EXE%" scripts\verify_showcase_environment.py --config "%SHOWCASE_CONFIG%"
if errorlevel 1 (
  echo [错误] 为保护正式数据，拒绝导入到非权威 CCD 数据库。
  pause
  exit /b 1
)

"%PYTHON_EXE%" -m moments_inventory.cli showcase-db-import --yes --showcase-config "%SHOWCASE_CONFIG%"
if errorlevel 1 (
  echo [ERROR] Import failed.
  pause
  exit /b 1
)

echo [INFO] Importing CCD sample images...
"%PYTHON_EXE%" -m moments_inventory.cli showcase-sample-images-import --showcase-config "%SHOWCASE_CONFIG%"
if errorlevel 1 (
  echo [ERROR] Sample image import failed.
  pause
  exit /b 1
)

echo [OK] Database updated.
pause
