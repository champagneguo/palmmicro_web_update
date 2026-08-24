# encoding: utf-8
"""
QMT 下单编排：下单 → 回调推送回执 → 落库

place_order 下单后，服务端（yinhe_server_update.py）会通过
order_callback / deal_callback 主动推送委托/成交状态（PUSH 消息），
客户端读推送落库，无需轮询 get_trade_detail_data。
"""
import json
import time

import qmt_client
import qmt_db

# 委托终止状态（银河QMT状态码）：已成 56 / 已撤 54 / 废单 57
TERMINAL_ORDER_STATUS = {54, 56, 57}


def _parse_json(resp: str):
    try:
        return json.loads(resp)
    except (json.JSONDecodeError, TypeError):
        return None


def place_order(action, code, volume, price, account=None, wait_push=True):
    """下单，等待回调推送委托/成交回执，落库。

    :param action:  'BUY' / 'SELL'
    :param code:    QMT 格式代码，如 '159985.SZ'
    :param volume:  数量（股）
    :param price:   价格
    :param account: 资金账号或股东账号；None 则默认资金账号
    :param wait_push: 是否等待回调推送（默认 True）
    :return: {"ok", "result", "remark", "orders", "deals"}
    """
    if action not in ('BUY', 'SELL'):
        return {"ok": False, "error": f"未知方向: {action}"}

    cmd = f"{action},{code},{volume},{price}"
    if account:
        cmd += f",{account}"

    # 1. 下单（服务端返回 OK:remark，remark 用于关联后续推送）
    result = qmt_client.send_command(cmd)
    account_used = account or qmt_client.FUND_ACCOUNT
    qmt_db.log_order(action, code, volume, price, account_used, result)

    remark = None
    if result.startswith("OK:"):
        remark = result[3:].split(":", 1)[0]

    # 2. 读回调推送（ORDER/DEAL），直到终止状态或超时
    orders = []
    deals = []
    if wait_push:
        deadline = time.time() + 15
        while time.time() < deadline:
            msg = qmt_client.receive_push(timeout=max(0.5, deadline - time.time()))
            if not msg or not msg.startswith("PUSH:"):
                break
            data = _parse_json(msg[5:]) or {}
            if data.get("type") == "ORDER":
                orders.append(data)
                if data.get("status") in TERMINAL_ORDER_STATUS:
                    break
            elif data.get("type") == "DEAL":
                deals.append(data)

    # 3. 成交落库（PUSH 的 DEAL 字段转成 log_trades 格式；dealId 用于幂等去重）
    if deals:
        qmt_db.log_trades([{
            "code": d.get("code"), "name": "", "action": action,
            "volume": d.get("volume"), "price": d.get("price"),
            "amount": d.get("amount"), "commission": 0,
            "orderId": d.get("orderId"), "dealId": d.get("dealId"),
            "time": d.get("time"),
        } for d in deals])

    return {
        "ok": True,
        "result": result,
        "remark": remark,
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
