@echo off
chcp 65001 >nul
setlocal

set ADB=C:\Users\Wh987\.phonemcp\platform-tools\adb.exe
set PKG=com.xiaoban.app
set SVC=%PKG%/%PKG%.XiaobanAccessibilityService

echo ============================================
echo   小伴 · 手机一键恢复
echo ============================================
echo.

if not exist "%ADB%" (
  echo [X] 找不到 adb：%ADB%
  echo     请确认手机助手装好了
  pause
  exit /b 1
)

echo [1/4] 检查手机连接...
"%ADB%" devices | findstr /R /C:"device$" >nul
if errorlevel 1 (
  echo [X] 手机没连上
  echo     1. 用 USB 线连电脑
  echo     2. 手机上点「允许 USB 调试」
  echo     3. 再跑一次这个脚本
  pause
  exit /b 1
)
echo     OK 已连接
echo.

echo [2/4] 关闭再打开无障碍服务（vivo 需要这个顺序才生效）...
"%ADB%" shell settings put secure accessibility_enabled 0
"%ADB%" shell settings put secure enabled_accessibility_services null
timeout /t 1 /nobreak >nul
"%ADB%" shell settings put secure enabled_accessibility_services %SVC%
"%ADB%" shell settings put secure accessibility_enabled 1
timeout /t 3 /nobreak >nul
echo     OK
echo.

echo [3/4] 启动小伴 App...
"%ADB%" shell monkey -p %PKG% -c android.intent.category.LAUNCHER 1 >nul 2>&1
timeout /t 4 /nobreak >nul
echo     OK
echo.

echo [4/4] 验证能力...
set TOKEN=DVO5BZyPDRRLY_lJ-y-etSZn1UZSkF21guugqD-hz7U
for /f "tokens=2 delims=:" %%i in ('"%ADB%" shell ip -brief addr show wlan0 ^| findstr wlan0') do set IPLINE=%%i
for /f "tokens=1" %%a in ("%IPLINE%") do set PHONEIP=%%a
echo     手机 IP: %PHONEIP%
echo.
echo     正在验证无障碍和 Shizuku...
powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Uri ('http://%PHONEIP%:9123/ping') -Headers @{'X-PC-Token'='%TOKEN%'} -TimeoutSec 6; Write-Host ('    无障碍: ' + $(if($r.accessibility){'OK'}else{'没开'})); Write-Host ('    版本: ' + $r.version) } catch { Write-Host '    连不上 App 的本地服务（可能 App 没启动）' }" 2>nul

echo.
echo ============================================
echo   完成
echo   如果无障碍还是没开，去设置里手动开一次：
echo   设置 - 无障碍 - 已下载的服务 - 小伴·界面操作
echo ============================================
pause
