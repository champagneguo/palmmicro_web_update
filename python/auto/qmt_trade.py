# encoding: utf-8
"""
QMT 下单编排：下单 → 回查委托/成交 → 落库

把「下单 + 回执落库」串成一个动作，供 dashboard / 命令行调用。
只负责下单，行情归通达信。
"""
import json

import qmt_client
import qmt_db


def _parse_json(resp: str):
    try:
        return json.loads(resp)
    except (json.JSONDecodeError, TypeError):
        return None


def place_order(action, code, volume, price, account=None):
    """下单并回查委托/成交，落库。返回结果 dict。

    复用单条长连接依次下发「下单 → 回查委托 → 回查成交」三条指令，
    避免每次指令都新建/关闭 TCP 连接。

    :param action:  'BUY' / 'SELL'
    :param code:    QMT 格式代码，如 '159985.SZ'
    :param volume:  数量（股）
    :param price:   价格
    :param account: 资金账号或股东账号；None 则默认资金账号
    :return: {"ok": bool, "result": str, "orders": [...], "deals": [...]}
    """
    if action not in ('BUY', 'SELL'):
        return {"ok": False, "error": f"未知方向: {action}"}

    cmd = f"{action},{code},{volume},{price}"
    if account:
        cmd += f",{account}"

    with qmt_client.QmtConnection() as conn:
        # 1. 下单
        result = conn.command(cmd)
        account_used = account or qmt_client.FUND_ACCOUNT
        qmt_db.log_order(action, code, volume, price, account_used, result)

        # 2. 回查委托 + 成交（复用同一连接）
        order_data = _parse_json(conn.command("QUERY_ORDER"))
        deal_data = _parse_json(conn.command("QUERY_DEAL"))

    orders = (order_data or {}).get('orders', [])
    deals = (deal_data or {}).get('deals', [])

    # 3. 成交落库
    if deals:
        qmt_db.log_trades(deals)

    return {
        "ok": True,
        "result": result,
        "orders": orders,
        "deals": deals,
    }


def refresh_positions():
    """查询持仓并落库（供定时刷新或手动调用）"""
    pos_data = _parse_json(qmt_client.query_pos())
    positions = (pos_data or {}).get('positions', [])
    if positions:
        qmt_db.log_positions(positions)
    return positions
