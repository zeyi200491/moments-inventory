@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo [INFO] Before running, keep WeChat on Contacts or Chat List.
echo [INFO] Press any key to start batched warmup, sync, and export.
pause >nul

python -m moments_inventory.cli --config "config/config.yaml" batch-run --export
if errorlevel 1 (
    echo [ERROR] Batched export failed.
    exit /b 1
)

echo [OK] Batched warmup, sync, and export completed.
exit /b 0
