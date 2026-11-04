@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
echo.
echo   小伴 PC 控制台 - 正在启动
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 (
    echo.
    echo   启动失败，请看上面的报错。
    pause
)
