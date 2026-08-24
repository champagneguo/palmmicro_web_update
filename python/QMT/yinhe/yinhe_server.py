# encoding: utf-8
"""
银河QMT Socket 下单服务 v1.0（纯下单版）

职责：QMT 只负责下单/查询，行情交给通达信（订阅推送）。
    外部进程（通达信程序）通过 Socket 发指令，本策略在 QMT 主线程执行 passorder。

支持指令：
  PING                            - 心跳，返回 PONG
  QUERY_ACCOUNT                   - 查询账户资金（JSON）
  QUERY_POS                       - 查询持仓（含股东账号分仓信息，JSON）
  QUERY_ORDER                     - 查询最近 10 条委托（JSON）
  QUERY_DEAL                      - 查询最近 10 条成交（JSON）
  BUY,<code>,<volume>,<price>[,<account>]   - 买入（account 可选，分仓时填股东账号）
  SELL,<code>,<volume>,<price>[,<account>]  - 卖出（同上）
  CANCEL_ORDER,<orderId>          - 撤单（orderId 为合同编号）
  SHUTDOWN                        - 关闭服务释放端口

架构说明（双回调分工）：
  Socket 子线程：只收指令、入队、Event.wait() 等结果，绝不直接调用 QMT C++ API。
  check_orders 主线程：QMT 每秒定时触发，唯一安全调用 passorder/get_trade_detail_data 的地方。
"""
import socket
import threading
import time
import json
import queue


# ══════════════════════════════════════════════════════════════════════
# 账户配置（与通达信侧 python/auto/qmt_client.py 保持一致）
# ══════════════════════════════════════════════════════════════════════

# 资金账号（股票主账户）
FUND_ACCOUNT = "212500003210"

# 下挂股东账号（分仓）。深A = 深圳A股股东账号，沪A = 上海A股股东账号。
# 下单时可选指定某个股东账号；不指定则默认用资金账号 FUND_ACCOUNT。
# 注意：passorder 的 accountid 通常传资金账号；分仓传股东账号的格式需实盘实测，
#       若需去掉"深A"/"沪A"前缀，改这里的列表即可。
SHAREHOLDER_SZ = [
    "深A0184343291", "深A0273232976", "深A0572649609",
    "深A0273289393", "深A0572652646", "深A0529687621",
]
SHAREHOLDER_SH = [
    "沪AA583900210", "沪AF151081995", "沪AF151183098", "沪AF763358265",
]

# 期货账号（后续扩展，本期不使用）
FUTURE_ACCOUNT = "0260006339"

# Socket 监听端口
LISTEN_PORT = 8888


# ══════════════════════════════════════════════════════════════════════
# 全局变量
# ══════════════════════════════════════════════════════════════════════

g_context = None

# Socket 服务器对象。SHUTDOWN 时直接 close 此对象，socket_server_thread 检测到变化后退出。
g_server_socket = None

# 请求队列（线程安全）：Socket 子线程写入，check_orders 主线程读取
g_request_queue = queue.Queue()


def log(msg: str):
    """统一日志输出，QMT 策略窗口可见"""
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"[YinheQMT {ts}] {msg}")


# ══════════════════════════════════════════════════════════════════════
# 请求封装（Event 无 CPU 等待）
# ══════════════════════════════════════════════════════════════════════

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
# Socket 子线程：客户端连接处理
# ══════════════════════════════════════════════════════════════════════

def handle_client(conn: socket.socket, addr):
    try:
        while True:
            # ── 读取一条指令（以 \n 结尾），长连接复用 ──────────
            raw = b""
            conn.settimeout(30)  # 等待下一条指令最长 30s，超时视为客户端不再下发
            try:
                while len(raw) < 2048:
                    chunk = conn.recv(512)
                    if not chunk:
                        raw = b""
                        break  # EOF → 客户端断开
                    raw += chunk
                    if b"\n" in raw:
                        break
            except socket.timeout:
                break  # 30s 无新指令，关闭连接

            if not raw:
                break  # 客户端断开

            data = raw.decode('utf-8').strip()
            if not data:
                continue

            log(f"收到指令 [{addr}]: {data!r}")
            parts = data.split(',')
            action = parts[0].strip().upper()

            # ── PING ────────────────────────────────────────────
            if action == 'PING':
                conn.sendall(b"PONG\n")
                continue

            # ── SHUTDOWN ────────────────────────────────────────
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

            # ── 需要 QMT C++ 接口的指令：入队 + Event 等待 ──────
            if action in ("QUERY_ACCOUNT", "QUERY_POS", "QUERY_ORDER", "QUERY_DEAL",
                          "BUY", "SELL", "CANCEL_ORDER"):
                # 交易指令需等待交易所回执，超时 62s；查询指令 30s
                wait_timeout = 62.0 if action in ('BUY', 'SELL', 'CANCEL_ORDER') else 30.0

                req = QueryRequest(data)
                g_request_queue.put(req)
                log(f"{action} 请求已入队，等待主线程处理... 队列大小={g_request_queue.qsize()}")

                if req.wait(timeout=wait_timeout):
                    result_str = req.result or "ERROR:empty_result"
                else:
                    result_str = "TIMEOUT"
                    log(f"{action} 等待超时（{wait_timeout}s）")

                log(f"{action} 回执: {result_str[:200]}")
                conn.settimeout(None)  # 发送回执前取消超时，防止大回执发不完
                conn.sendall((result_str + "\n").encode('utf-8'))
                continue

            log(f"未知指令: {data!r}")
            conn.sendall(b"UNKNOWN\n")

    except Exception as e:
        log(f"handle_client 异常 [{addr}]: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════
# Socket 服务器线程
# ══════════════════════════════════════════════════════════════════════

def socket_server_thread():
    global g_server_socket

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind(('0.0.0.0', LISTEN_PORT))
        server.listen(10)
        server.settimeout(1.0)  # 每秒超时一次，用于检测 g_server_socket 变化
        g_server_socket = server
        log(f"Socket 服务器已启动，监听 0.0.0.0:{LISTEN_PORT}")
    except Exception as e:
        log(f"Socket 服务器启动失败: {e}")
        return

    while True:
        if g_server_socket is not server:
            log("检测到 g_server_socket 已变化（QMT 重置或 SHUTDOWN），Socket 服务器线程退出")
            try:
                server.close()
            except Exception:
                pass
            break

        try:
            conn, addr = server.accept()
            log(f"新连接: {addr}")
            # 关键优化：同步处理，不为每个连接新开线程。
            # QMT 内嵌 Python 对新线程的调度有 1~5s 延迟（日志里"新连接→收到指令"间隔即此），
            # 在 accept() 的同一线程里直接 recv 即可消除这段延迟。
            # 代价：同一时刻只处理一个连接（本场景客户端串行发指令，无影响）。
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
# 主线程处理函数（只在 check_orders 中调用）
# ══════════════════════════════════════════════════════════════════════

def _process_request(req: QueryRequest, ContextInfo):
    cmd = req.cmd
    parts = cmd.split(',')
    action = parts[0].strip().upper()
    log(f"主线程处理指令: {cmd!r}")

    try:
        # ── QUERY_ACCOUNT：查询账户资金 ────────────────────────
        if action == 'QUERY_ACCOUNT':
            accounts = get_trade_detail_data(FUND_ACCOUNT, 'STOCK', 'account')
            if accounts:
                a = accounts[0]
                data = {
                    "accountID":      getattr(a, 'm_strAccountID',    FUND_ACCOUNT),
                    "balance":        getattr(a, 'm_dBalance',        0),   # 总资产
                    "available":      getattr(a, 'm_dAvailable',      0),   # 可用金额
                    "fetchBalance":   getattr(a, 'm_dFetchBalance',   0),   # 可取金额
                    "frozenCash":     getattr(a, 'm_dFrozenCash',     0),   # 冻结金额
                    "stockValue":     getattr(a, 'm_dStockValue',     0),   # 股票市值
                    "fundValue":      getattr(a, 'm_dFundValue',      0),   # 基金市值
                    "positionProfit": getattr(a, 'm_dPositionProfit', 0),   # 持仓盈亏
                    "closeProfit":    getattr(a, 'm_dCloseProfit',    0),   # 平仓盈亏
                    "commission":     getattr(a, 'm_dCommission',     0),   # 手续费
                    "tradingDate":    getattr(a, 'm_strTradingDate',  ''),  # 交易日
                }
                req.complete(json.dumps(data, ensure_ascii=False))
            else:
                req.complete(json.dumps({"error": "no_account_data"}))
            log(f"QUERY_ACCOUNT -> {req.result}")

        # ── QUERY_POS：查询持仓 ────────────────────────────────
        elif action == 'QUERY_POS':
            holdings = get_trade_detail_data(FUND_ACCOUNT, 'STOCK', 'position')
            positions = []
            for p in (holdings or []):
                positions.append({
                    "code":      getattr(p, 'm_strInstrumentID',   ''),
                    "name":      getattr(p, 'm_strInstrumentName', ''),
                    "account":   getattr(p, 'm_strAccountID',      ''),  # 股东账号（分仓信息）
                    "canUse":    getattr(p, 'm_nCanUseVolume',     0),   # 可用数量
                    "total":     getattr(p, 'm_nVolume',           0),   # 总持仓
                    "costPrice": getattr(p, 'm_dOpenPrice',        0),   # 成本价
                    "mktValue":  getattr(p, 'm_dMarketValue',      0),   # 市值
                    "profit":    getattr(p, 'm_dProfit',           0),   # 浮动盈亏
                })
            req.complete(json.dumps({"account": FUND_ACCOUNT, "positions": positions}, ensure_ascii=False))
            log(f"QUERY_POS -> {len(positions)} 条持仓")

        # ── QUERY_ORDER：查询最近 10 条委托 ────────────────────
        elif action == 'QUERY_ORDER':
            orders = get_trade_detail_data(FUND_ACCOUNT, 'STOCK', 'order')
            # 银河QMT m_nOrderStatus 状态码映射
            status_map = {
                48:  '未报', 49: '待报', 50: '已报', 51: '已报待撤',
                52:  '部成待撤', 53: '部撤', 54: '已撤', 55: '部成',
                56:  '已成', 57: '废单', 255: '未知',
            }
            order_list = []
            for o in (orders or [])[-10:]:
                raw_status = getattr(o, 'm_nOrderStatus', None)
                status_str = status_map.get(
                    raw_status if raw_status is not None else -1,
                    f'未知({raw_status})'
                )
                order_sys_id = getattr(o, 'm_strOrderSysID', '') or ''
                order_id_local = getattr(o, 'm_strOrderID', '') or ''
                order_list.append({
                    "code":    getattr(o, 'm_strInstrumentID',      ''),
                    "name":    getattr(o, 'm_strInstrumentName',    ''),
                    "action":  getattr(o, 'm_strOptName',           ''),  # 买入/卖出
                    "volume":  getattr(o, 'm_nVolumeTotalOriginal', 0),   # 委托数量
                    "traded":  getattr(o, 'm_nVolumeTraded',        0),   # 成交数量
                    "price":   getattr(o, 'm_dLimitPrice',          0),   # 委托价格
                    "status":  status_str,
                    "orderId": order_sys_id or order_id_local,            # 合同编号
                    "time":    getattr(o, 'm_strInsertTime',        ''),  # 委托时间
                })
            req.complete(json.dumps({"orders": order_list}, ensure_ascii=False))
            log(f"QUERY_ORDER -> {len(order_list)} 条委托")

        # ── QUERY_DEAL：查询最近 10 条成交 ─────────────────────
        elif action == 'QUERY_DEAL':
            deals = get_trade_detail_data(FUND_ACCOUNT, 'STOCK', 'deal')
            deal_list = []
            for d in (deals or [])[-10:]:
                deal_list.append({
                    "code":       getattr(d, 'm_strInstrumentID',   ''),
                    "name":       getattr(d, 'm_strInstrumentName', ''),
                    "action":     getattr(d, 'm_strOptName',        ''),  # 买入/卖出
                    "volume":     getattr(d, 'm_nVolume',           0),   # 成交数量
                    "price":      getattr(d, 'm_dPrice',            0),   # 成交价格
                    "amount":     getattr(d, 'm_dTradeAmount',      0),   # 成交金额
                    "commission": getattr(d, 'm_dCommission',       0),   # 手续费
                    "orderId":    getattr(d, 'm_strOrderSysID',     ''),  # 合同编号
                    "time":       getattr(d, 'm_strTradeTime',      ''),  # 成交时间
                })
            req.complete(json.dumps({"deals": deal_list}, ensure_ascii=False))
            log(f"QUERY_DEAL -> {len(deal_list)} 条成交")

        # ── BUY / SELL：下单 ───────────────────────────────────
        elif action in ('BUY', 'SELL') and len(parts) >= 4:
            op_type = 23 if action == 'BUY' else 24  # 23=买入, 24=卖出
            code    = parts[1].strip()
            volume  = int(parts[2].strip())
            price   = float(parts[3].strip())
            # 分仓：可选第 5 个参数指定股东账号，默认资金账号
            account = parts[4].strip() if len(parts) >= 5 and parts[4].strip() else FUND_ACCOUNT
            log(f"下单: {'买入' if op_type == 23 else '卖出'} {code} 数量={volume} 价格={price} 账号={account}")
            ret = passorder(op_type, 1101, account, code, 11, price, volume,
                            'SocketTrade', 1, "API", ContextInfo)
            result_str = f"OK:{ret}" if ret else "OK"
            req.complete(result_str)
            log(f"passorder 完成: {action} {code} {volume}@{price} 账号={account} 订单ID={ret}")

        # ── CANCEL_ORDER：撤单 ─────────────────────────────────
        elif action == 'CANCEL_ORDER' and len(parts) >= 2:
            order_id = parts[1].strip()
            log(f"撤单: orderId={order_id}")
            try:
                ret = passorder(48, 1101, FUND_ACCOUNT, '', 11, 0, 0,
                                'SocketCancel', 1, order_id, ContextInfo)
                result_str = f"OK:{ret}" if ret else "OK"
                req.complete(result_str)
                log(f"CANCEL_ORDER 完成: orderId={order_id} ret={ret}")
            except Exception as cancel_e:
                req.complete(f"ERROR:{cancel_e}")
                log(f"CANCEL_ORDER 异常: orderId={order_id} err={cancel_e}")

        else:
            req.complete(f"UNKNOWN:{cmd}")
            log(f"未知指令: {cmd!r}")

    except Exception as e:
        req.complete(f"ERROR:{e}")
        log(f"处理指令异常 [{action}]: {e}")


# ══════════════════════════════════════════════════════════════════════
# QMT 策略入口函数（QMT 引擎识别的固定函数名）
# ══════════════════════════════════════════════════════════════════════

def init(ContextInfo):
    """QMT 策略初始化回调，在 QMT 主线程中调用"""
    global g_context
    g_context = ContextInfo
    log(f"策略初始化，账户: {FUND_ACCOUNT}")
    ContextInfo.set_account(FUND_ACCOUNT)

    # ── 清理旧端口（QMT 重载策略时旧线程可能仍占用 8888）──────
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

    # ── 启动 Socket 服务器线程 ────────────────────────────────
    threading.Thread(target=socket_server_thread, daemon=True, name="SocketServer").start()
    log("Socket 服务器线程已启动")

    # ── 注册定时器（每秒处理请求队列）────────────────────────
    ContextInfo.run_time("check_orders", "1nSecond", "2020-01-01 09:30:00")
    log("定时器 check_orders 已注册（每秒处理请求队列）")


def check_orders(ContextInfo):
    """QMT 定时回调，每秒执行，处理请求队列（唯一安全调用 QMT C++ API 的地方）"""
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
