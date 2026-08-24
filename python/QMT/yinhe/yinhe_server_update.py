# encoding: utf-8
"""
银河QMT Socket 下单服务 v2（事件驱动版）

相比 v1（yinhe_server.py）的改进：
  - 下单后不再轮询 get_trade_detail_data 回查委托/成交，
    改用 order_callback / deal_callback 回调：委托状态一变、每笔成交，都由 QMT 主动推送，
    服务端再通过 Socket 把「PUSH:<json>」实时推给客户端。
  - 消除两次回查往返 + daemon 线程调度延迟，下单→回执更快。

支持指令（同 v1）：
  PING / QUERY_ACCOUNT / QUERY_POS / QUERY_ORDER / QUERY_DEAL
  BUY,<code>,<volume>,<price>[,<account>]
  SELL,<code>,<volume>,<price>[,<account>]
  CANCEL_ORDER,<orderId>
  SHUTDOWN

推送消息（服务端主动下发给客户端，每行一条）：
  PUSH:{"type":"ORDER", ...}   —— order_callback 触发
  PUSH:{"type":"DEAL",  ...}   —— deal_callback 触发

关键前提：
  - init 里必须 ContextInfo.set_account(资金账号)，回调才会生效。
  - 回调机制在实盘运行模式下生效（仿真模式可能不触发，需实盘验证）。
"""
import socket
import threading
import time
import json
import queue


# ══════════════════════════════════════════════════════════════════════
# 账户配置（与通达信侧 python/auto/qmt_client.py 保持一致）
# ══════════════════════════════════════════════════════════════════════
FUND_ACCOUNT = "212500003210"

SHAREHOLDER_SZ = [
    "深A0184343291", "深A0273232976", "深A0572649609",
    "深A0273289393", "深A0572652646", "深A0529687621",
]
SHAREHOLDER_SH = [
    "沪AA583900210", "沪AF151081995", "沪AF151183098", "沪AF763358265",
]

FUTURE_ACCOUNT = "0260006339"
LISTEN_PORT = 8888


# ══════════════════════════════════════════════════════════════════════
# 全局变量
# ══════════════════════════════════════════════════════════════════════
g_context = None
g_server_socket = None
g_request_queue = queue.Queue()

# 当前客户端持久连接（供 order_callback/deal_callback 主动推送）
g_client_sock = None
g_send_lock = threading.Lock()

# 下单序号（生成唯一 userOrderId/remark，用于回执与回调关联）
g_order_seq = 0
g_seq_lock = threading.Lock()


def log(msg: str):
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"[YinheQMT {ts}] {msg}")


def _next_remark() -> str:
    """生成唯一下单备注，随委托一路传递，回调里可读到"""
    global g_order_seq
    with g_seq_lock:
        g_order_seq += 1
        return f"ord-{int(time.time() * 1000)}-{g_order_seq}"


def _push(msg: str):
    """向客户端推送一条消息（主线程回调里调用，线程安全）"""
    with g_send_lock:
        sock = g_client_sock
        if sock is None:
            return
        try:
            sock.sendall((msg + "\n").encode('utf-8'))
        except Exception as e:
            log(f"推送失败: {e}")


class QueryRequest:
    __slots__ = ('cmd', 'result', '_event')

    def __init__(self, cmd: str):
        self.cmd = cmd
        self.result = None
        self._event = threading.Event()

    def complete(self, result: str):
        self.result = result
        self._event.set()

    def wait(self, timeout: float = 30.0) -> bool:
        return self._event.wait(timeout)


# ══════════════════════════════════════════════════════════════════════
# Socket 子线程：客户端连接处理（长连接，循环读指令）
# ══════════════════════════════════════════════════════════════════════

def handle_client(conn: socket.socket, addr):
    global g_client_sock
    g_client_sock = conn  # 注册当前连接，供回调推送
    try:
        while True:
            raw = b""
            conn.settimeout(3600)  # 长连接空闲超时 1 小时
            try:
                while len(raw) < 2048:
                    chunk = conn.recv(512)
                    if not chunk:
                        raw = b""
                        break
                    raw += chunk
                    if b"\n" in raw:
                        break
            except socket.timeout:
                break

            if not raw:
                break

            data = raw.decode('utf-8').strip()
            if not data:
                continue

            log(f"收到指令 [{addr}]: {data!r}")
            parts = data.split(',')
            action = parts[0].strip().upper()

            if action == 'PING':
                conn.sendall(b"PONG\n")
                continue

            if action == 'SHUTDOWN':
                log("收到 SHUTDOWN 指令，准备关闭 Socket 服务...")
                conn.sendall(b"OK\n")
                _sock = g_server_socket
                if _sock is not None:
                    try:
                        _sock.close()
                    except Exception:
                        pass
                break

            if action in ("QUERY_ACCOUNT", "QUERY_POS", "QUERY_ORDER", "QUERY_DEAL",
                          "BUY", "SELL", "CANCEL_ORDER"):
                wait_timeout = 62.0 if action in ('BUY', 'SELL', 'CANCEL_ORDER') else 30.0

                req = QueryRequest(data)
                g_request_queue.put(req)
                log(f"{action} 请求已入队，队列大小={g_request_queue.qsize()}")

                if req.wait(timeout=wait_timeout):
                    result_str = req.result or "ERROR:empty_result"
                else:
                    result_str = "TIMEOUT"
                    log(f"{action} 等待超时（{wait_timeout}s）")

                log(f"{action} 回执: {result_str[:200]}")
                conn.settimeout(None)
                with g_send_lock:
                    conn.sendall((result_str + "\n").encode('utf-8'))
                continue

            log(f"未知指令: {data!r}")
            conn.sendall(b"UNKNOWN\n")

    except Exception as e:
        log(f"handle_client 异常 [{addr}]: {e}")
    finally:
        if g_client_sock is conn:
            g_client_sock = None
        try:
            conn.close()
        except Exception:
            pass


def socket_server_thread():
    global g_server_socket

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind(('0.0.0.0', LISTEN_PORT))
        server.listen(10)
        server.settimeout(1.0)
        g_server_socket = server
        log(f"Socket 服务器已启动，监听 0.0.0.0:{LISTEN_PORT}")
    except Exception as e:
        log(f"Socket 服务器启动失败: {e}")
        return

    while True:
        if g_server_socket is not server:
            log("检测到 g_server_socket 已变化，Socket 服务器线程退出")
            try:
                server.close()
            except Exception:
                pass
            break

        try:
            conn, addr = server.accept()
            log(f"新连接: {addr}")
            handle_client(conn, addr)
        except socket.timeout:
            continue
        except OSError:
            log("Socket 服务器已关闭，线程退出")
            break
        except Exception as e:
            log(f"Socket accept 异常: {e}")
            time.sleep(1)

    log("Socket 服务器线程已退出")


# ══════════════════════════════════════════════════════════════════════
# 主线程处理（check_orders 调用）
# ══════════════════════════════════════════════════════════════════════

def _process_request(req: QueryRequest, ContextInfo):
    cmd = req.cmd
    parts = cmd.split(',')
    action = parts[0].strip().upper()
    log(f"主线程处理指令: {cmd!r}")

    try:
        if action == 'QUERY_ACCOUNT':
            accounts = get_trade_detail_data(FUND_ACCOUNT, 'STOCK', 'account')
            if accounts:
                a = accounts[0]
                data = {
                    "accountID":      getattr(a, 'm_strAccountID',    FUND_ACCOUNT),
                    "balance":        getattr(a, 'm_dBalance',        0),
                    "available":      getattr(a, 'm_dAvailable',      0),
                    "fetchBalance":   getattr(a, 'm_dFetchBalance',   0),
                    "frozenCash":     getattr(a, 'm_dFrozenCash',     0),
                    "stockValue":     getattr(a, 'm_dStockValue',     0),
                    "fundValue":      getattr(a, 'm_dFundValue',      0),
                    "positionProfit": getattr(a, 'm_dPositionProfit', 0),
                    "closeProfit":    getattr(a, 'm_dCloseProfit',    0),
                    "commission":     getattr(a, 'm_dCommission',     0),
                    "tradingDate":    getattr(a, 'm_strTradingDate',  ''),
                }
                req.complete(json.dumps(data, ensure_ascii=False))
            else:
                req.complete(json.dumps({"error": "no_account_data"}))
            log(f"QUERY_ACCOUNT -> {req.result}")

        elif action == 'QUERY_POS':
            holdings = get_trade_detail_data(FUND_ACCOUNT, 'STOCK', 'position')
            positions = []
            for p in (holdings or []):
                positions.append({
                    "code":      getattr(p, 'm_strInstrumentID',   ''),
                    "name":      getattr(p, 'm_strInstrumentName', ''),
                    "account":   getattr(p, 'm_strAccountID',      ''),
                    "canUse":    getattr(p, 'm_nCanUseVolume',     0),
                    "total":     getattr(p, 'm_nVolume',           0),
                    "costPrice": getattr(p, 'm_dOpenPrice',        0),
                    "mktValue":  getattr(p, 'm_dMarketValue',      0),
                    "profit":    getattr(p, 'm_dProfit',           0),
                })
            req.complete(json.dumps({"account": FUND_ACCOUNT, "positions": positions}, ensure_ascii=False))
            log(f"QUERY_POS -> {len(positions)} 条持仓")

        elif action == 'QUERY_ORDER':
            orders = get_trade_detail_data(FUND_ACCOUNT, 'STOCK', 'order')
            status_map = {
                48: '未报', 49: '待报', 50: '已报', 51: '已报待撤',
                52: '部成待撤', 53: '部撤', 54: '已撤', 55: '部成',
                56: '已成', 57: '废单', 255: '未知',
            }
            order_list = []
            for o in (orders or [])[-10:]:
                raw_status = getattr(o, 'm_nOrderStatus', None)
                order_list.append({
                    "code":    getattr(o, 'm_strInstrumentID',      ''),
                    "name":    getattr(o, 'm_strInstrumentName',    ''),
                    "action":  getattr(o, 'm_strOptName',           ''),
                    "volume":  getattr(o, 'm_nVolumeTotalOriginal', 0),
                    "traded":  getattr(o, 'm_nVolumeTraded',        0),
                    "price":   getattr(o, 'm_dLimitPrice',          0),
                    "status":  status_map.get(raw_status, f'未知({raw_status})'),
                    "orderId": getattr(o, 'm_strOrderSysID', '') or getattr(o, 'm_strOrderID', ''),
                    "time":    getattr(o, 'm_strInsertTime',        ''),
                })
            req.complete(json.dumps({"orders": order_list}, ensure_ascii=False))
            log(f"QUERY_ORDER -> {len(order_list)} 条委托")

        elif action == 'QUERY_DEAL':
            deals = get_trade_detail_data(FUND_ACCOUNT, 'STOCK', 'deal')
            deal_list = []
            for d in (deals or [])[-10:]:
                deal_list.append({
                    "code":       getattr(d, 'm_strInstrumentID',   ''),
                    "name":       getattr(d, 'm_strInstrumentName', ''),
                    "action":     getattr(d, 'm_strOptName',        ''),
                    "volume":     getattr(d, 'm_nVolume',           0),
                    "price":      getattr(d, 'm_dPrice',            0),
                    "amount":     getattr(d, 'm_dTradeAmount',      0),
                    "commission": getattr(d, 'm_dCommission',       0),
                    "orderId":    getattr(d, 'm_strOrderSysID',     ''),
                    "time":       getattr(d, 'm_strTradeTime',      ''),
                })
            req.complete(json.dumps({"deals": deal_list}, ensure_ascii=False))
            log(f"QUERY_DEAL -> {len(deal_list)} 条成交")

        elif action in ('BUY', 'SELL') and len(parts) >= 4:
            op_type = 23 if action == 'BUY' else 24
            code    = parts[1].strip()
            volume  = int(parts[2].strip())
            price   = float(parts[3].strip())
            account = parts[4].strip() if len(parts) >= 5 and parts[4].strip() else FUND_ACCOUNT
            remark  = _next_remark()
            log(f"下单: {'买入' if op_type == 23 else '卖出'} {code} 数量={volume} 价格={price} 账号={account} 备注={remark}")
            ret = passorder(op_type, 1101, account, code, 11, price, volume,
                            'SocketTrade', 1, remark, ContextInfo)
            # 返回 remark，客户端据此关联后续 PUSH 回调
            result_str = f"OK:{remark}" if ret is None else f"OK:{remark}:{ret}"
            req.complete(result_str)
            log(f"passorder 完成: {action} {code} {volume}@{price} 备注={remark} 订单ID={ret}")

        elif action == 'CANCEL_ORDER' and len(parts) >= 2:
            order_id = parts[1].strip()
            log(f"撤单: orderId={order_id}")
            try:
                ret = passorder(48, 1101, FUND_ACCOUNT, '', 11, 0, 0,
                                'SocketCancel', 1, order_id, ContextInfo)
                req.complete(f"OK:{ret}" if ret else "OK")
                log(f"CANCEL_ORDER 完成: orderId={order_id} ret={ret}")
            except Exception as cancel_e:
                req.complete(f"ERROR:{cancel_e}")
                log(f"CANCEL_ORDER 异常: {cancel_e}")

        else:
            req.complete(f"UNKNOWN:{cmd}")
            log(f"未知指令: {cmd!r}")

    except Exception as e:
        req.complete(f"ERROR:{e}")
        log(f"处理指令异常 [{action}]: {e}")


# ══════════════════════════════════════════════════════════════════════
# QMT 委托/成交回调（事件驱动推送，主线程执行）
# ══════════════════════════════════════════════════════════════════════

def order_callback(ContextInfo, orderInfo):
    """委托回调：委托状态变化时触发，主动推送给客户端"""
    try:
        data = {
            "type":     "ORDER",
            "code":     getattr(orderInfo, 'm_strInstrumentID', ''),
            "status":   getattr(orderInfo, 'm_nOrderStatus', -1),
            "volume":   getattr(orderInfo, 'm_nVolumeTotalOriginal', 0),
            "traded":   getattr(orderInfo, 'm_nVolumeTraded', 0),
            "price":    getattr(orderInfo, 'm_dLimitPrice', 0),
            "orderId":  getattr(orderInfo, 'm_strOrderSysID', ''),
            "remark":   getattr(orderInfo, 'm_strRemark', ''),
        }
        _push("PUSH:" + json.dumps(data, ensure_ascii=False))
        log(f"order_callback: {json.dumps(data, ensure_ascii=False)}")
    except Exception as e:
        log(f"order_callback 异常: {e}")


def deal_callback(ContextInfo, dealInfo):
    """成交回调：每笔成交触发一次，主动推送给客户端"""
    try:
        data = {
            "type":     "DEAL",
            "code":     getattr(dealInfo, 'm_strInstrumentID', ''),
            "volume":   getattr(dealInfo, 'm_nVolume', 0),
            "price":    getattr(dealInfo, 'm_dTradePrice', 0),
            "amount":   getattr(dealInfo, 'm_dTradeAmount', 0),
            "time":     getattr(dealInfo, 'm_strTradeTime', ''),
            "dealId":   getattr(dealInfo, 'm_strDealID', ''),
            "orderId":  getattr(dealInfo, 'm_strOrderSysID', ''),
            "remark":   getattr(dealInfo, 'm_strRemark', ''),
        }
        _push("PUSH:" + json.dumps(data, ensure_ascii=False))
        log(f"deal_callback: {json.dumps(data, ensure_ascii=False)}")
    except Exception as e:
        log(f"deal_callback 异常: {e}")


# ══════════════════════════════════════════════════════════════════════
# QMT 策略入口
# ══════════════════════════════════════════════════════════════════════

def init(ContextInfo):
    global g_context
    g_context = ContextInfo
    log(f"策略初始化，账户: {FUND_ACCOUNT}")
    # 关键：set_account 订阅资金账号，order_callback/deal_callback 才会生效
    ContextInfo.set_account(FUND_ACCOUNT)

    try:
        killer = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        killer.settimeout(1.0)
        if killer.connect_ex(('127.0.0.1', LISTEN_PORT)) == 0:
            log(f"检测到旧服务占用 {LISTEN_PORT} 端口，发送 SHUTDOWN...")
            killer.sendall(b"SHUTDOWN\n")
            try:
                killer.recv(16)
            except Exception:
                pass
        killer.close()
        time.sleep(1)
    except Exception as e:
        log(f"端口清理异常（可忽略）: {e}")

    threading.Thread(target=socket_server_thread, daemon=True, name="SocketServer").start()
    log("Socket 服务器线程已启动")

    ContextInfo.run_time("check_orders", "1nSecond", "2020-01-01 09:30:00")
    log("定时器 check_orders 已注册（每秒处理请求队列）")


def check_orders(ContextInfo):
    global g_context
    g_context = ContextInfo

    all_reqs = []
    while len(all_reqs) < 50:
        try:
            all_reqs.append(g_request_queue.get_nowait())
        except queue.Empty:
            break

    if all_reqs:
        for req in all_reqs:
            _process_request(req, ContextInfo)
        log(f"check_orders 本轮处理完成：{len(all_reqs)} 个请求")
