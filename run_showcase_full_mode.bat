@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv. Please run setup_windows.bat first.
  pause
  exit /b 1
)

echo [INFO] Running full inventory mode...
".venv\Scripts\python.exe" -m moments_inventory.cli orchestrated-run --mode full
if errorlevel 1 (
  echo [ERROR] Full inventory run failed.
  pause
  exit /b 1
)

echo [INFO] Updating manual showcase workbook...
".venv\Scripts\python.exe" -m moments_inventory.cli showcase-merge
if errorlevel 1 (
  echo [ERROR] Showcase workbook merge failed.
  pause
  exit /b 1
)

echo [OK] Manual showcase workbook updated.
pause
