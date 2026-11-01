@echo off
chcp 936 >nul
setlocal
set PORT=8770
echo.
echo   停止小伴 PC 控制台（端口 %PORT%）
echo.
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr LISTENING') do (
    echo   结束进程 PID %%a
    taskkill /F /PID %%a >nul 2>&1
)
echo   完成。
timeout /t 2 >nul
