# Palmmicro 本地数据服务

## 概述

Palmmicro 企业微信数据本地部署软件，集成了通达信、新浪财经、IBKR 等数据源，提供对冲交易实时数据面板。

## 架构

```
┌─────────────────────────────────────────────────┐
│                  PalmmicroApp (v0.6)              │
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ 通达信 TDX │  │ 新浪 Sina │  │  IBKR TWS     │  │
│  │ D:\new_tdx64│ │ 实时汇率  │  │  Gateway 7497 │  │
│  └────┬─────┘  └────┬─────┘  └──────┬────────┘  │
│       │             │               │            │
│       └──────┬──────┘───────────────┘            │
│              ▼                                    │
│     ┌────────────────┐                           │
│     │  PalmmicroAPI  │  ← 后端配置与对冲计算       │
│     └───────┬────────┘                           │
│             ▼                                     │
│  ┌──────────────────────┐                        │
│  │  dtale Web 面板       │  http://127.0.0.1:40005│
│  ├──────────────────────┤                        │
│  │  Tkinter GUI 窗口     │  本地桌面               │
│  └──────────────────────┘                        │
└─────────────────────────────────────────────────┘
```

## 环境要求

| 组件 | 说明 |
|------|------|
| Python | 3.12+ |
| 通达信 | 64位，安装于 `D:\new_tdx64`，已导入 `Palmmicro.EBK` 板块文件 |
| IBKR | TWS 或 IB Gateway 已启动，API 端口 7497 |
| pip 依赖 | `dtale`, `pandas`, `requests`, `ibapi` |

## 文件说明

```
python/auto/
├── main.py              # 入口
├── palmmicroapp.py      # GUI 主应用 (Tkinter + dtale)
├── palmmicrostock.py    # 行情数据 (通达信/新浪/IBKR)
├── palmmicroapi.py      # 后端 API 与 DataFrame
├── Palmmicro.EBK        # 通达信自定义板块文件
├── redfox.png           # 应用图标
├── _mytoken.py          # API Token (不入库，需自行创建)
└── start.bat            # 一键启动脚本
```

## 首次部署

### 1. 安装依赖

```powershell
pip install dtale pandas requests ibapi
```

### 2. 配置 Token

创建 `python/auto/_mytoken.py`：

```python
BOT_TOKEN = "your-token-here"
```

### 3. 确认通达信路径

通达信 64 位必须安装到 `D:\new_tdx64`，且 Python 插件 `tqcenter.py` 位于 `D:\new_tdx64\PYPlugins\user\`。

如果路径不同，修改 `palmmicrostock.py` 第 440 行：

```python
sys.path.append('D:/new_tdx64/PYPlugins/user')
```

### 4. 导入板块文件

在通达信中导入 `Palmmicro.EBK` 到自定义板块 PLMM。

### 5. 启动 IBKR

启动 TWS 或 IB Gateway，确保 API 端口为 7497。

## 启动方式

### 方式一：双击启动（推荐）

直接双击 `python/auto/start.bat`，脚本会自动：
1. 关闭旧进程（dtale 端口 40005 + Palmmicro 窗口）
2. 检查通达信和 IBKR 环境
3. 启动服务

### 方式二：命令行

```powershell
cd python/auto
$env:PYTHONIOENCODING='utf-8'
python main.py
```

## 启动后

- **Tkinter 窗口**：显示对冲交易数据表格
- **dtale Web 面板**：浏览器自动打开 `http://127.0.0.1:40005`，提供完整 DataFrame 浏览

## 关闭

关闭 Tkinter 窗口即可，程序会自动释放通达信、新浪、IBKR 连接资源。
