# encoding: utf-8
"""
QMT 下单记录 sqlite 存储

下单操作都会记录到 sqlite，便于审计与回溯。
后期实时行情/对冲快照也会写入，便于回测查看。

数据库文件默认在 python/auto/data/qmt_trading.db。
"""
import os
import sqlite3
import time

# 数据库路径（可在外部覆盖）
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'qmt_trading.db')


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建表（幂等）"""
    conn = _get_conn()
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
    conn.commit()
    conn.close()


def log_order(action: str, code: str, volume: int, price: float,
              account: str, result: str, qmt_order_id: str = None):
    """记录一条下单/撤单操作"""
    conn = _get_conn()
    conn.execute(
        'INSERT INTO orders (ts, action, code, volume, price, account, status, qmt_order_id, raw) '
        'VALUES (?,?,?,?,?,?,?,?,?)',
        (time.strftime('%Y-%m-%d %H:%M:%S'), action, code, volume, price,
         account, result, qmt_order_id, result)
    )
    conn.commit()
    conn.close()


def log_trades(deals):
    """批量写入成交记录。deals: list[dict]（QUERY_DEAL 返回的 deals 字段）"""
    conn = _get_conn()
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    for d in (deals or []):
        conn.execute(
            'INSERT INTO trades (ts, code, name, action, volume, price, amount, commission, order_id, trade_time) '
            'VALUES (?,?,?,?,?,?,?,?,?,?)',
            (ts, d.get('code'), d.get('name'), d.get('action'), d.get('volume'),
             d.get('price'), d.get('amount'), d.get('commission'), d.get('orderId'), d.get('time'))
        )
    conn.commit()
    conn.close()


def log_positions(positions):
    """批量写入持仓快照。positions: list[dict]（QUERY_POS 返回的 positions 字段）"""
    conn = _get_conn()
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    for p in (positions or []):
        conn.execute(
            'INSERT INTO positions (ts, code, name, account, can_use, total, cost_price, mkt_value, profit) '
            'VALUES (?,?,?,?,?,?,?,?,?)',
            (ts, p.get('code'), p.get('name'), p.get('account'), p.get('canUse'),
             p.get('total'), p.get('costPrice'), p.get('mktValue'), p.get('profit'))
        )
    conn.commit()
    conn.close()


def list_orders(limit: int = 20):
    """查询最近 N 条下单记录"""
    conn = _get_conn()
    rows = conn.execute(
        'SELECT * FROM orders ORDER BY id DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return rows


if __name__ == '__main__':
    init_db()
    print(f"数据库初始化完成: {DB_PATH}")
