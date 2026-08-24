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

    :param action:  'BUY' / 'SELL'
    :param code:    QMT 格式代码，如 '159985.SZ'
    :param volume:  数量（股）
    :param price:   价格
    :param account: 资金账号或股东账号；None 则默认资金账号
    :return: {"ok": bool, "result": str, "orders": [...], "deals": [...]}
    """
    # 1. 下单
    if action == 'BUY':
        result = qmt_client.buy(code, volume, price, account)
    elif action == 'SELL':
        result = qmt_client.sell(code, volume, price, account)
    else:
        return {"ok": False, "error": f"未知方向: {action}"}

    account_used = account or qmt_client.FUND_ACCOUNT
    qmt_db.log_order(action, code, volume, price, account_used, result)

    # 2. 回查委托 + 成交（每条指令约 6~8s QMT 延迟）
    order_data = _parse_json(qmt_client.query_order())
    deal_data = _parse_json(qmt_client.query_deal())

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
