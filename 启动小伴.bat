@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 小伴 · 一键启动

set ROOT=E:\WH\pc-core
set PY=%ROOT%\.venv\Scripts\python.exe
set ADB=C:\Users\Wh987\.phonemcp\platform-tools\adb.exe
set PKG=com.xiaoban.app
set SVC=%PKG%/%PKG%.XiaobanAccessibilityService

echo ==================================================
echo    小伴 · 一键启动
echo ==================================================
echo.

cd /d "%ROOT%" || (echo [X] 找不到项目目录 & pause & exit /b 1)

:: ---------- 1. 清理旧进程 ----------
echo [1/6] 清理旧进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8770 " ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8771 " ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
timeout /t 1 /nobreak >nul
echo      OK

:: ---------- 2. 启动后端 + 控制台 ----------
echo [2/6] 启动后端和控制台...
start "" /min "%PY%" "%ROOT%\run_daemon.py"
timeout /t 8 /nobreak >nul
echo      OK

:: ---------- 3. 检查后端 ----------
echo [3/6] 检查服务...
set OK0=
set OK1=
for /l %%i in (1,1,20) do (
  if not defined OK0 (
    curl -s -m 2 http://127.0.0.1:8770/api/health >nul 2>&1 && set OK0=1
    if not defined OK0 timeout /t 1 /nobreak >nul
  )
)
curl -s -m 2 http://127.0.0.1:8771/ >nul 2>&1 && set OK1=1
if defined OK0 (echo      后端 8770 OK) else (echo      [X] 后端 8770 没起来)
if defined OK1 (echo      控制台 8771 OK) else (echo      [!] 控制台 8771 没起来)

:: ---------- 4. 手机：无障碍 + Shizuku ----------
echo [4/6] 恢复手机能力...
if not exist "%ADB%" (
  echo      [!] 没找到 adb，跳过手机部分
  goto skip_phone
)
"%ADB%" devices 2>nul | findstr /R /C:"device$" >nul
if errorlevel 1 (
  echo      [!] 手机没连 USB，跳过（远程走 Tailscale 也能用）
  goto skip_phone
)

:: 先确保 App 在跑
"%ADB%" shell monkey -p %PKG% -c android.intent.category.LAUNCHER 1 >nul 2>&1
timeout /t 4 /nobreak >nul

:: 关一次再开一次（vivo 必须这个顺序）
"%ADB%" shell settings put secure accessibility_enabled 0 >nul 2>&1
"%ADB%" shell settings put secure enabled_accessibility_services null >nul 2>&1
timeout /t 1 /nobreak >nul
"%ADB%" shell settings put secure enabled_accessibility_services %SVC% >nul 2>&1
"%ADB%" shell settings put secure accessibility_enabled 1 >nul 2>&1
timeout /t 3 /nobreak >nul

:: 读手机 IP 验证
set PHONEIP=
for /f "tokens=1" %%a in ('"%ADB%" shell ip -brief addr show wlan0 ^| findstr wlan0') do set PHONEIP=%%a
if "%PHONEIP%"=="DOWN" set PHONEIP=
if not defined PHONEIP (
  for /f "tokens=1" %%a in ('"%ADB%" shell ip -brief addr show tun0 ^| findstr tun0') do set PHONEIP=%%a
)
if defined PHONEIP (
  set TOKEN=DVO5BZyPDRRLY_lJ-y-etSZn1UZSkF21guugqD-hz7U
  powershell -NoProfile -Command "try{$r=Invoke-RestMethod -Uri ('http://!PHONEIP!:9123/ping') -Headers @{'X-PC-Token'='!TOKEN!'} -TimeoutSec 8; Write-Host ('      手机 ' + '!PHONEIP!' + ' 界面操作=' + $r.accessibility + ' 版本=' + $r.version)}catch{Write-Host '      [!] 手机服务没响应'}" 2>nul
)
echo      OK

:skip_phone

:: ---------- 5. 打开界面 ----------
echo [5/6] 打开界面...
start "" http://127.0.0.1:8770
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8771
echo      OK

:: ---------- 6. 汇总 ----------
echo [6/6] 完成
echo.
echo ==================================================
echo   聊天界面   http://127.0.0.1:8770
echo   控制台     http://127.0.0.1:8771   PIN 556378
echo.
echo   手机上打开：
echo     同 WiFi   http://172.30.0.217:8771
echo     异地      http://100.118.110.25:8771
echo ==================================================
echo.
pause
