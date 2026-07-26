@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   Palmmicro 本地数据服务 - 启动脚本
echo ========================================
echo.

REM === 停止旧进程 ===
echo [1/3] 正在停止旧进程...

REM 根据端口 40005 (dtale) 查找并杀死进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":40005.*LISTENING" 2^>nul') do (
    echo   终止 dtale 进程 PID:%%a
    taskkill /F /PID %%a >nul 2>&1
)

REM 杀死带 Palmmicro 窗口的 python 进程
for /f "tokens=2" %%a in ('tasklist /FI "WINDOWTITLE eq Palmmicro" /FO TABLE ^| findstr "python" 2^>nul') do (
    echo   终止 Palmmicro 进程 PID:%%a
    taskkill /F /PID %%a >nul 2>&1
)

REM 等进程退出
timeout /t 2 /nobreak >nul
echo   旧进程已清理
echo.

REM === 检查依赖 ===
echo [2/3] 检查运行环境...

REM 检查通达信目录
if not exist "D:\new_tdx64\PYPlugins\user\tqcenter.py" (
    echo   [警告] 通达信 Python 插件未找到: D:\new_tdx64\PYPlugins\user\tqcenter.py
    echo   请确认通达信64位已安装到 D:\new_tdx64
) else (
    echo   通达信插件: OK
)

REM 检查 IBKR
netstat -ano | findstr ":7497.*ESTABLISHED" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [警告] IBKR TWS/Gateway 可能未连接 (端口 7497)
) else (
    echo   IBKR 连接: OK
)

echo.

REM === 启动服务 ===
echo [3/3] 启动 PalmmicroApp...
echo   - TKinter GUI 窗口
echo   - dtale Web 面板: http://127.0.0.1:40005
echo.

set PYTHONIOENCODING=utf-8
python main.py

echo.
echo 服务已退出.
pause
