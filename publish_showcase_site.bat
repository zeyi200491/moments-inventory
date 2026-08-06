@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv. Please run setup_windows.bat first.
  pause
  exit /b 1
)

echo [INFO] Building CCD showcase site...
".venv\Scripts\python.exe" -m moments_inventory.cli showcase-build --sample-assets-dir "showcase_assets" --output-dir "site_dist"
if errorlevel 1 (
  echo [ERROR] Showcase site build failed.
  pause
  exit /b 1
)

echo [OK] Showcase site built at site_dist
pause
