@echo off
chcp 65001 >nul
setlocal

if "%~1"=="" (
    set /p "EXCEL_PATH=请输入 CCD 型号 Excel 文件路径: "
) else (
    set "EXCEL_PATH=%~1"
)

if "%EXCEL_PATH%"=="" (
    echo 未提供 Excel 文件路径。
    pause
    exit /b 1
)

pushd "%~dp0"
python scripts\download_xhs_ccd_images.py "%EXCEL_PATH%"
set "EXIT_CODE=%ERRORLEVEL%"
popd

pause
exit /b %EXIT_CODE%
