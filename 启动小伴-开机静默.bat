@echo off
rem 开机自启专用：不弹窗、不开浏览器、不等按键
setlocal

set ROOT=E:\WH\pc-core
set PY=%ROOT%\.venv\Scripts\python.exe
set ADB=C:\Users\Wh987\.phonemcp\platform-tools\adb.exe
set PKG=com.xiaoban.app
set SVC=%PKG%/%PKG%.XiaobanAccessibilityService

cd /d "%ROOT%" 2>nul || exit /b 1

rem 已经在跑就不重复启动
netstat -ano | findstr ":8770 " | findstr LISTENING >nul 2>&1 && goto phone
start "" /min "%PY%" "%ROOT%\run_daemon.py"
timeout /t 10 /nobreak >nul

:phone
if not exist "%ADB%" exit /b 0
"%ADB%" devices 2>nul | findstr /R /C:"device$" >nul || exit /b 0

"%ADB%" shell monkey -p %PKG% -c android.intent.category.LAUNCHER 1 >nul 2>&1
timeout /t 4 /nobreak >nul
"%ADB%" shell settings put secure accessibility_enabled 0 >nul 2>&1
"%ADB%" shell settings put secure enabled_accessibility_services null >nul 2>&1
timeout /t 1 /nobreak >nul
"%ADB%" shell settings put secure enabled_accessibility_services %SVC% >nul 2>&1
"%ADB%" shell settings put secure accessibility_enabled 1 >nul 2>&1
exit /b 0
