# encoding: utf-8
"""
QMT 下单记录 sqlite 存储（常驻连接 + WAL，线程安全）

下单操作都会记录到 sqlite，便于审计与回溯。
后期实时行情/对冲快照也会写入，便于回测查看。

性能优化：
  - 常驻单连接：避免每次读写都 open/close（原来每次写都新开连接，被杀软扫描 .db 时会秒级卡顿）
  - WAL 模式 + synchronous=NORMAL：写入不阻塞读，更快
  - 线程锁串行化访问（dashboard 多线程请求共用）
"""
import os
import sqlite3
import threading
import time

# 数据库路径（可在外部覆盖）
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'qmt_trading.db')

_lock = threading.Lock()
_conn = None


def _ensure_conn():
    """确保常驻连接已初始化（调用方需已持有 _lock）"""
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute('PRAGMA journal_mode=WAL')       # 写不阻塞读
        _conn.execute('PRAGMA synchronous=NORMAL')     # 提升写入速度
        _create_tables(_conn)
    return _conn


def _create_tables(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS orders (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ts           TEXT NOT NULL,          -- 下单时间 YYYY-MM-DD HH:MM:SS
        action       TEXT NOT NULL,          -- BUY / SELL / CANCEL
        code         TEXT NOT NULL,          -- QMT 格式 159985.SZ
        volume       INTEGER,
        price        REAL,
        account      TEXT,                   -- 资金账号或股东账号（分仓）
        status       TEXT,                   -- 回执状态
        qmt_order_id TEXT,                   -- QMT 返回的订单ID
        raw          TEXT                    -- 原始回执
    );

    CREATE TABLE IF NOT EXISTS trades (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ts         TEXT NOT NULL,
        code       TEXT,
        name       TEXT,
        action     TEXT,
        volume     INTEGER,
        price      REAL,
        amount     REAL,
        commission REAL,
        order_id   TEXT,
        trade_time TEXT
    );

    CREATE TABLE IF NOT EXISTS positions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ts         TEXT NOT NULL,
        code       TEXT,
        name       TEXT,
        account    TEXT,
        can_use    INTEGER,
        total      INTEGER,
        cost_price REAL,
        mkt_value  REAL,
        profit     REAL
    );
    ''')


def _execute(sql, params=()):
    with _lock:
        conn = _ensure_conn()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur


def _query(sql, params=()):
    with _lock:
        conn = _ensure_conn()
        return conn.execute(sql, params).fetchall()


def init_db():
    """初始化（幂等，首次写/读时也会自动初始化）"""
    with _lock:
        _ensure_conn()


def log_order(action, code, volume, price, account, result, qmt_order_id=None):
    """记录一条下单/撤单操作"""
    _execute(
        'INSERT INTO orders (ts, action, code, volume, price, account, status, qmt_order_id, raw) '
        'VALUES (?,?,?,?,?,?,?,?,?)',
        (time.strftime('%Y-%m-%d %H:%M:%S'), action, code, volume, price,
         account, result, qmt_order_id, result)
    )


def log_trades(deals):
    """批量写入成交记录。deals: list[dict]（QUERY_DEAL 返回的 deals 字段）"""
    if not deals:
        return
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    with _lock:
        conn = _ensure_conn()
        for d in deals:
            conn.execute(
                'INSERT INTO trades (ts, code, name, action, volume, price, amount, commission, order_id, trade_time) '
                'VALUES (?,?,?,?,?,?,?,?,?,?)',
                (ts, d.get('code'), d.get('name'), d.get('action'), d.get('volume'),
                 d.get('price'), d.get('amount'), d.get('commission'), d.get('orderId'), d.get('time'))
            )
        conn.commit()


def log_positions(positions):
    """批量写入持仓快照。positions: list[dict]（QUERY_POS 返回的 positions 字段）"""
    if not positions:
        return
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    with _lock:
        conn = _ensure_conn()
        for p in positions:
            conn.execute(
                'INSERT INTO positions (ts, code, name, account, can_use, total, cost_price, mkt_value, profit) '
                'VALUES (?,?,?,?,?,?,?,?,?)',
                (ts, p.get('code'), p.get('name'), p.get('account'), p.get('canUse'),
                 p.get('total'), p.get('costPrice'), p.get('mktValue'), p.get('profit'))
            )
        conn.commit()


def list_orders(limit=20):
    """查询最近 N 条下单记录"""
    return _query('SELECT * FROM orders ORDER BY id DESC LIMIT ?', (limit,))


def close():
    """关闭常驻连接（程序退出时调用）"""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


if __name__ == '__main__':
    init_db()
    print(f"数据库初始化完成: {DB_PATH}")
