#requires -Version 5.1
<#
  小伴 PC-CORE 启动器
  ------------------------------------------------------------
  为什么是 PowerShell 而不是纯 bat：
  这个工程在 E: 盘（exFAT）+ 中文路径下，cmd 的 GBK 代码页会把
  中文路径拆碎。PowerShell 原生 Unicode，绕开这个坑。

  注意：本文件必须存成 UTF-8 with BOM，否则 PS 5.1 按 GBK 读会乱码报错。
#>

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host ''
Write-Host '  小伴 · PC 控制台' -ForegroundColor Cyan
Write-Host "  工作目录：$Root" -ForegroundColor DarkGray
Write-Host ''

# ---------- 1. 找 Python ----------
$Candidates = @(
    (Join-Path $Root '.venv\Scripts\python.exe'),
    'C:\dog\01-工程源码\.venv\Scripts\python.exe',
    'python'
)

$Python = $null
foreach ($c in $Candidates) {
    if ($c -eq 'python') {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($cmd) { $Python = $cmd.Source; break }
    } elseif (Test-Path $c) {
        $Python = $c; break
    }
}

if (-not $Python) {
    Write-Host '  [X] 找不到 Python。' -ForegroundColor Red
    Write-Host '      请装 Python 3.11+，或在项目根建 .venv' -ForegroundColor DarkGray
    exit 1
}
Write-Host "  [1/4] Python: $Python" -ForegroundColor Green

# ---------- 2. 依赖检查 ----------
$Missing = & $Python -c "import importlib,sys
mods=['fastapi','uvicorn','httpx']
miss=[m for m in mods if importlib.util.find_spec(m) is None]
print(','.join(miss))" 2>&1

if ($Missing -and $Missing.Trim() -ne '') {
    Write-Host "  [X] 缺少依赖：$Missing" -ForegroundColor Red
    Write-Host "      装一下：& '$Python' -m pip install fastapi uvicorn httpx" -ForegroundColor DarkGray
    exit 1
}
Write-Host '  [2/4] 依赖齐全' -ForegroundColor Green

# ---------- 3. 端口占用检查 ----------
$Port = 8770
$Busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($Busy) {
    $OwnerPid = ($Busy | Select-Object -First 1).OwningProcess
    $Proc = Get-Process -Id $OwnerPid -ErrorAction SilentlyContinue
    Write-Host "  [!] 端口 $Port 已被占用（PID $OwnerPid / $($Proc.ProcessName)）" -ForegroundColor Yellow
    $Ans = Read-Host '      要结束它并重启吗？(y/N)'
    if ($Ans -match '^[Yy]') {
        Stop-Process -Id $OwnerPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 600
    } else {
        Write-Host '      已取消。' -ForegroundColor DarkGray
        exit 0
    }
}
Write-Host "  [3/4] 端口 $Port 可用" -ForegroundColor Green

# ---------- 4. 起服务 ----------
Write-Host '  [4/4] 启动中…' -ForegroundColor Green
Write-Host ''
Write-Host "  → http://127.0.0.1:$Port" -ForegroundColor Cyan
Write-Host '  （Ctrl+C 停止）' -ForegroundColor DarkGray
Write-Host ''

# 关键：必须 cd 到工程根，否则 config.json / data/ 相对路径全错
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

& $Python -m uvicorn server.main:app --host 127.0.0.1 --port $Port
