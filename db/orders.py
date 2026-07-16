"""Live orders and trade executions database operations."""

import json
import sqlite3
from .connection import DB_PATH, DB_LOCK
from .base import query_records


def save_live_order(order: dict) -> int:
    """Insert a new live_orders row and return its id."""
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO live_orders
               (ts, hwnd, bot_id, ticker, direction, order_type, qty, price,
                limit_price, ibkr_order_id, status, fill_price, fill_ts,
                error_msg, retries, trade_ref_id, meta, screenshot_path, profit, buy_order_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order.get("ts"),
                order.get("hwnd"),
                order.get("bot_id"),
                order.get("ticker"),
                order.get("direction"),
                order.get("order_type"),
                order.get("qty"),
                order.get("price"),
                order.get("limit_price"),
                order.get("ibkr_order_id"),
                order.get("status", "pending"),
                order.get("fill_price"),
                order.get("fill_ts"),
                order.get("error_msg"),
                order.get("retries", 0),
                order.get("trade_ref_id"),
                json.dumps(order.get("meta", {})) if order.get("meta") is not None else None,
                order.get("screenshot_path"),
                order.get("profit"),
                order.get("buy_order_id"),
            ),
        )
        row_id = cur.lastrowid
        conn.commit()
        conn.close()
        return row_id


def update_live_order_status(
    order_id: int,
    status: str,
    fill_price=None,
    fill_ts=None,
    error_msg=None,
    ibkr_order_id=None,
    retries=None,
    profit=None,
    buy_order_id=None,
):
    """Update status fields on an existing live_orders row."""
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """UPDATE live_orders
               SET status = ?,
                   fill_price = COALESCE(?, fill_price),
                   fill_ts = COALESCE(?, fill_ts),
                   error_msg = COALESCE(?, error_msg),
                   ibkr_order_id = COALESCE(?, ibkr_order_id),
                   retries = COALESCE(?, retries),
                   profit = COALESCE(?, profit),
                   buy_order_id = COALESCE(?, buy_order_id)
               WHERE id = ?""",
            (status, fill_price, fill_ts, error_msg, ibkr_order_id, retries, profit, buy_order_id, order_id),
        )
        conn.commit()
        conn.close()


def get_live_orders(hwnd: int = None, bot_id: str = None, limit: int = None, offset: int = 0) -> list:
    """Return live_orders rows, optionally filtered by hwnd/bot_id and paginated by limit/offset."""
    where = []
    params = []
    if hwnd is not None:
        where.append("hwnd = ?")
        params.append(int(hwnd))
    if bot_id is not None:
        where.append("bot_id = ?")
        params.append(bot_id)

    sql = "SELECT * FROM live_orders"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts DESC"

    if limit is not None:
        lim = max(1, int(limit))
        off = max(0, int(offset or 0))
        sql += " LIMIT ? OFFSET ?"
        params.extend([lim, off])

    return query_records(sql, tuple(params))


def count_live_orders(hwnd: int = None, bot_id: str = None) -> int:
    """Return total count of live_orders for optional hwnd/bot_id filters."""
    where = []
    params = []
    if hwnd is not None:
        where.append("hwnd = ?")
        params.append(int(hwnd))
    if bot_id is not None:
        where.append("bot_id = ?")
        params.append(bot_id)

    sql = "SELECT COUNT(*) as count FROM live_orders"
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = query_records(sql, tuple(params))
    return int(rows[0]["count"]) if rows else 0


def get_last_buy_order(hwnd: int, ticker: str) -> dict:
    """Get the most recent unmatched filled BUY order for a ticker/hwnd.

    A BUY is considered matched if any filled SELL already references it via buy_order_id.
    """
    rows = query_records(
        """SELECT b.*
             FROM live_orders b
             WHERE b.hwnd = ?
                 AND b.ticker = ?
                 AND b.direction = 'buy'
                 AND b.status = 'filled'
                 AND NOT EXISTS (
                     SELECT 1
                     FROM live_orders s
                     WHERE s.direction = 'sell'
                         AND s.status = 'filled'
                         AND s.buy_order_id = b.id
                 )
             ORDER BY b.ts DESC
             LIMIT 1""",
        (int(hwnd), ticker),
    )
    return rows[0] if rows else None


def get_last_order_for_hwnd_ticker(hwnd: int, ticker: str) -> dict:
    """Get the most recent live_order row for a bot/ticker (any direction, any status).
    Used by R14 to read fill price and status after an order completes.
    """
    rows = query_records(
        """SELECT * FROM live_orders
             WHERE hwnd = ? AND ticker = ?
             ORDER BY ts DESC
             LIMIT 1""",
        (int(hwnd), ticker),
    )
    return rows[0] if rows else None
