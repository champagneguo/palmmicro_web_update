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
Write-Host "[2/5] 正在停止旧进程..." -ForegroundColor Yellow

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

# 关闭旧 ngrok 进程
$ngrok = Get-Process ngrok -ErrorAction SilentlyContinue
if ($ngrok) {
    foreach ($p in $ngrok) {
        Write-Host "  终止 ngrok 进程 PID:$($p.Id)"
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
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
Write-Host "[3/5] 检查运行环境..." -ForegroundColor Yellow

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

# === 启动 ngrok 隧道 ===
Write-Host "[4/5] 启动 ngrok 隧道..." -ForegroundColor Yellow

# 生成访问令牌 (随机32位)
$chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
$token = -join ((1..32) | ForEach-Object { $chars[(Get-Random -Maximum $chars.Length)] })
# 通过环境变量传给 Dashboard
$env:DASHBOARD_TOKEN = $token

# 在后台启动 ngrok (仅暴露 Dashboard :40006)
Start-Process ngrok -ArgumentList "http", "40006" -WindowStyle Hidden

# 等待 ngrok 进程就绪后轮询 web 面板, 拿到公网 URL
# ngrok 首次连服务器需几秒, 故先等 3 秒再开始轮询
Start-Sleep -Seconds 3
$ngrokUrl = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    $foundPort = $null
    foreach ($port in 4040, 4041, 4042) {
        try {
            $tunnels = Invoke-RestMethod "http://127.0.0.1:$port/api/tunnels" -ErrorAction SilentlyContinue
            if ($null -eq $tunnels -or $null -eq $tunnels.tunnels) { continue }
            $candidate = $tunnels.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1
            if ($candidate) {
                $ngrokUrl = $candidate.public_url
                $foundPort = $port
                break
            }
        } catch {}
    }
    if ($ngrokUrl) { break }
}

if ($ngrokUrl) {
    Write-Host "  公网访问: ${ngrokUrl}?token=$token" -ForegroundColor Green
    Write-Host "  访问令牌: $token" -ForegroundColor Green
} else {
    Write-Host "  [警告] ngrok 隧道启动失败, 仅本地访问可用" -ForegroundColor Red
}

Write-Host ""

# === 启动服务 ===
Write-Host "[5/5] 启动 PalmmicroApp..." -ForegroundColor Yellow
Write-Host "  - TKinter GUI 窗口"
Write-Host "  - dtale Web 面板(仅本地): http://127.0.0.1:40005"
Write-Host "  - Dashboard: http://127.0.0.1:40006"
Write-Host ""

$env:PYTHONIOENCODING = "utf-8"
python main.py

Write-Host ""
Write-Host "服务已退出." -ForegroundColor Cyan
Read-Host "按 Enter 关闭"
