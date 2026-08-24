# encoding: utf-8
"""
QMT 下单客户端（通达信侧）

连接 QMT 内部 Socket 服务（python/QMT/yinhe/yinhe_server.py），
发送下单/查询指令。只负责下单，不碰 QMT 行情（行情由通达信订阅推送提供）。

用法示例：
    from qmt_client import buy, sell, query_pos, tdx_to_qmt_code
    code = tdx_to_qmt_code('SZ159985')          # -> '159985.SZ'
    print(buy(code, 10000, 2.16))               # 买入
    print(sell(code, 10000, 2.16, '深A0184343291'))  # 分仓卖出
"""
import socket

# QMT Socket 服务地址（与 yinhe_server.py 的 LISTEN_PORT 对应）
QMT_HOST = "127.0.0.1"
QMT_PORT = 8888

# ══════════════ 账户配置（与 yinhe_server.py 保持一致）══════════════
FUND_ACCOUNT = "212500003210"

SHAREHOLDER_SZ = [
    "深A0184343291", "深A0273232976", "深A0572649609",
    "深A0273289393", "深A0572652646", "深A0529687621",
]
SHAREHOLDER_SH = [
    "沪AA583900210", "沪AF151081995", "沪AF151183098", "沪AF763358265",
]

FUTURE_ACCOUNT = "0260006339"


def _send_command(cmd: str, timeout: float = 30.0) -> str:
    """发送一条指令，返回回执字符串（去掉末尾换行）"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((QMT_HOST, QMT_PORT))
        s.sendall((cmd + "\n").encode('utf-8'))
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
        return data.decode('utf-8').strip()
    finally:
        s.close()


def ping() -> str:
    # QMT 的 Python 线程调度有 ~6s 固有延迟（策略日志可证），超时设大避免误判
    return _send_command("PING", timeout=15)


def query_account() -> str:
    return _send_command("QUERY_ACCOUNT")


def query_pos() -> str:
    return _send_command("QUERY_POS")


def query_order() -> str:
    return _send_command("QUERY_ORDER")


def query_deal() -> str:
    return _send_command("QUERY_DEAL")


def buy(code: str, volume: int, price: float, account: str = None) -> str:
    """买入。code 形如 '159985.SZ'；account 可选（分仓股东账号）"""
    cmd = f"BUY,{code},{volume},{price}"
    if account:
        cmd += f",{account}"
    return _send_command(cmd, timeout=62)


def sell(code: str, volume: int, price: float, account: str = None) -> str:
    """卖出。code 形如 '159985.SZ'；account 可选（分仓股东账号）"""
    cmd = f"SELL,{code},{volume},{price}"
    if account:
        cmd += f",{account}"
    return _send_command(cmd, timeout=62)


def cancel_order(order_id: str) -> str:
    """撤单。order_id 为合同编号（QUERY_ORDER 返回的 orderId 字段）"""
    return _send_command(f"CANCEL_ORDER,{order_id}", timeout=62)


def shutdown() -> str:
    return _send_command("SHUTDOWN", timeout=5)


def tdx_to_qmt_code(symbol: str) -> str:
    """通达信格式转 QMT 格式：SZ159985 -> 159985.SZ，SH501018 -> 501018.SH"""
    symbol = symbol.strip()
    if len(symbol) == 8 and symbol[:2] in ('SZ', 'SH', 'BJ'):
        return f"{symbol[2:]}.{symbol[:2]}"
    return symbol


def qmt_to_tdx_code(code: str) -> str:
    """QMT 格式转通达信格式：159985.SZ -> SZ159985，501018.SH -> SH501018"""
    code = code.strip()
    if '.' in code:
        num, market = code.split('.', 1)
        return f"{market.upper()}{num}"
    return code
