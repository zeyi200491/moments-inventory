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

"%PYTHON_EXE%" scripts\verify_showcase_environment.py --config "%SHOWCASE_CONFIG%"
if errorlevel 1 (
  echo [错误] 为保护正式数据，拒绝连接非权威 CCD 数据库。
  pause
  exit /b 1
)

echo [INFO] Starting Xingxing CCD database showcase.
echo [INFO] Customer page: http://127.0.0.1:8899/
echo [INFO] Admin page:    http://127.0.0.1:8899/admin-xingxing
echo.

"%PYTHON_EXE%" -m moments_inventory.cli showcase-db-init --showcase-config "%SHOWCASE_CONFIG%"

if errorlevel 1 (
  echo [ERROR] Database initialization failed.
  pause
  exit /b 1
)

"%PYTHON_EXE%" -m moments_inventory.cli showcase-server --showcase-config "%SHOWCASE_CONFIG%"
pause
