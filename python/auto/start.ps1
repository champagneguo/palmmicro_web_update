# Palmmicro 本地数据服务 - 一键启动脚本
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

Write-Host "========================================"  -ForegroundColor Cyan
Write-Host "  Palmmicro 本地数据服务 - 启动脚本"     -ForegroundColor Cyan
Write-Host "========================================"  -ForegroundColor Cyan
Write-Host ""

# === 安装依赖 ===
Write-Host "[1/4] 安装 Python 依赖..." -ForegroundColor Yellow
pip install -r "$PSScriptRoot\requirements.txt" -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [错误] 依赖安装失败!" -ForegroundColor Red
}
Write-Host "  依赖安装完成"
Write-Host ""

# === 停止旧进程 ===
Write-Host "[2/4] 正在停止旧进程..." -ForegroundColor Yellow

# 关闭占用端口 40005 的进程 (dtale)
$port40005 = Get-NetTCPConnection -LocalPort 40005 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($port40005) {
    foreach ($p in $port40005) {
        Write-Host "  终止 dtale 进程 PID:$p"
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    }
}

# 关闭占用端口 40006 的进程 (dashboard)
$port40006 = Get-NetTCPConnection -LocalPort 40006 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($port40006) {
    foreach ($p in $port40006) {
        Write-Host "  终止 dashboard 进程 PID:$p"
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    }
}

# 关闭 Palmmicro 窗口进程
$palmmicro = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq "Palmmicro" }
if ($palmmicro) {
    Write-Host "  终止 Palmmicro 进程 PID:$($palmmicro.Id)"
    Stop-Process -Id $palmmicro.Id -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 2
Write-Host "  旧进程已清理"
Write-Host ""

# === 检查环境 ===
Write-Host "[3/4] 检查运行环境..." -ForegroundColor Yellow

if (Test-Path "D:\new_tdx64\PYPlugins\user\tqcenter.py") {
    Write-Host "  通达信插件: OK" -ForegroundColor Green
} else {
    Write-Host "  [警告] 通达信 Python 插件未找到: D:\new_tdx64\PYPlugins\user\tqcenter.py" -ForegroundColor Red
    Write-Host "  请确认通达信64位已安装到 D:\new_tdx64"
}

$ibkr = netstat -ano | Select-String ":7497.*ESTABLISHED"
if ($ibkr) {
    Write-Host "  IBKR 连接: OK" -ForegroundColor Green
} else {
    Write-Host "  [警告] IBKR TWS/Gateway 可能未连接 (端口 7497)" -ForegroundColor Red
}

Write-Host ""

# === 启动服务 ===
Write-Host "[4/4] 启动 PalmmicroApp..." -ForegroundColor Yellow
Write-Host "  - TKinter GUI 窗口"
Write-Host "  - dtale Web 面板: http://127.0.0.1:40005"
Write-Host "  - Dashboard: http://127.0.0.1:40006"
Write-Host ""

$env:PYTHONIOENCODING = "utf-8"
python main.py

Write-Host ""
Write-Host "服务已退出." -ForegroundColor Cyan
Read-Host "按 Enter 关闭"
