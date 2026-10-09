@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)
set "PYTHONPATH=%CD%\src"

"%PYTHON_EXE%" -m moments_inventory.cli showcase-admin-password-reset --showcase-config "%~dp0config\showcase.yaml"
if errorlevel 1 (
  echo [ERROR] Admin password reset failed.
  pause
  exit /b 1
)

echo [INFO] Admin password reset completed. Existing admin sessions were revoked.
pause
