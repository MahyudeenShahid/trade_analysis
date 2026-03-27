"""Database query operations."""

import json
import sqlite3
from datetime import datetime, timedelta
from .connection import DB_PATH, DB_LOCK


def _row_to_dict(row: sqlite3.Row):
    """Convert SQLite row to dictionary."""
    return {k: row[k] for k in row.keys()}


def query_records(sql: str, params: tuple = ()):
    """Execute a query and return results as list of dictionaries."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def query_history_page(where: str, params: tuple, limit: int, offset: int):
    """Run COUNT and paginated SELECT in a single connection — avoids opening DB twice."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) as count FROM records WHERE {where}", params)
    total = cur.fetchone()["count"]
    cur.execute(
        f"SELECT * FROM records WHERE {where} ORDER BY ts DESC LIMIT ? OFFSET ?",
        params + (limit, offset),
    )
    rows = [_row_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return total, rows


def get_latest_record():
    """Get the most recent record from the database."""
    rows = query_records("SELECT * FROM records ORDER BY ts DESC LIMIT 1")
    return rows[0] if rows else None


def save_observation(obs: dict):
    """Persist a record to DB thread-safely and prune older than 7 days."""
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO records (ts, image_path, name, ticker, price, trend, buy_price, sell_price, buy_time, sell_time, win_reason, bot_id, bot_name, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                obs.get("ts"),
                obs.get("image_path"),
                obs.get("name"),
                obs.get("ticker"),
                obs.get("price"),
                obs.get("trend"),
                obs.get("buy_price"),
                obs.get("sell_price"),
                obs.get("buy_time"),
                obs.get("sell_time"),
                obs.get("win_reason"),
                obs.get("bot_id"),
                obs.get("bot_name"),
                json.dumps(obs.get("meta", {})) if obs.get("meta") is not None else None,
            ),
        )
        conn.commit()
        # prune older than 7 days (use UTC 'Z' suffixed ISO strings)
        cutoff = datetime.utcnow() - timedelta(days=7)
        cur.execute("DELETE FROM records WHERE ts < ?", (cutoff.isoformat() + 'Z',))
        conn.commit()
        conn.close()


def get_bot_db_entry(hwnd: int):
    """Get bot entry from database by hwnd."""
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM bots WHERE hwnd = ?", (int(hwnd),))
            r = cur.fetchone()
            conn.close()
            if not r:
                return None
            out = {k: r[k] for k in r.keys()}
            # parse meta JSON
            try:
                out['meta'] = json.loads(out.get('meta') or '{}')
            except Exception:
                out['meta'] = {}
            return out
    except Exception:
        return None


def upsert_bot_from_last_result(hwnd: int, last: dict):
    """Insert or update a bots table row based on the worker's last_result payload."""
    try:
        hwnd = int(hwnd)
    except Exception:
        return

    if not isinstance(last, dict):
        last = {}

    name = last.get('name') or last.get('window_title') or last.get('title')
    ticker = last.get('ticker')

    meta = last.get('meta') if isinstance(last, dict) else {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    if not isinstance(meta, dict):
        meta = {}

    # total_pnl: prefer meta.profit if present
    total_pnl = None
    try:
        total_pnl = meta.get('profit')
    except Exception:
        total_pnl = None

    open_direction = None
    open_price = None
    open_time = None
    try:
        open_direction = meta.get('direction') or meta.get('trend')
        open_price = meta.get('buy_price') or meta.get('entry_price') or meta.get('price')
        open_time = meta.get('buy_time') or meta.get('entry_time') or meta.get('ts')
    except Exception:
        pass

    try:
        with DB_LOCK:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            # Check existing
            cur.execute("SELECT hwnd FROM bots WHERE hwnd = ?", (hwnd,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE bots SET name = COALESCE(?, name), ticker = COALESCE(?, ticker), total_pnl = ?, open_direction = ?, open_price = ?, open_time = ?, meta = ? WHERE hwnd = ?",
                    (
                        name,
                        ticker,
                        float(total_pnl) if total_pnl is not None else None,
                        open_direction,
                        float(open_price) if open_price is not None else None,
                        open_time,
                        json.dumps(meta) if isinstance(meta, dict) else json.dumps({}),
                        hwnd,
                    ),
                )
            else:
                cur.execute(
                    "INSERT INTO bots (hwnd, name, ticker, total_pnl, open_direction, open_price, open_time, rule_1_enabled, rule_2_enabled, rule_3_enabled, rule_4_enabled, rule_5_enabled, rule_6_enabled, rule_7_enabled, rule_8_enabled, rule_9_enabled, take_profit_amount, stop_loss_amount, rule_3_drop_count, rule_5_down_minutes, rule_5_reversal_amount, rule_5_scalp_amount, rule_6_down_minutes, rule_6_profit_amount, rule_7_up_minutes, rule_8_buy_offset, rule_8_sell_offset, rule_9_amount, rule_9_flips, rule_9_window_minutes, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        hwnd,
                        name,
                        ticker,
                        float(total_pnl) if total_pnl is not None else None,
                        open_direction,
                        float(open_price) if open_price is not None else None,
                        open_time,
                        0,
                        0,
                        0,
                        1,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0.0,
                        0.0,
                        0,
                        3,
                        2.0,
                        0.25,
                        5,
                        2.0,
                        3,
                        0.25,
                        0.25,
                        0.25,
                        3,
                        3,
                        json.dumps(meta) if isinstance(meta, dict) else json.dumps({}),
                    ),
                )
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"Failed to upsert bot for hwnd {hwnd}: {e}")


def upsert_bot_settings(hwnd: int, settings: dict):
    """Upsert per-bot settings (including Rule #1/#2 fields) without clobbering runtime fields."""
    try:
        hwnd = int(hwnd)
    except Exception:
        raise ValueError("hwnd must be int")

    if not isinstance(settings, dict):
        settings = {}

    name = settings.get('name')
    ticker = settings.get('ticker')

    rule_1_enabled = settings.get('rule_1_enabled')
    rule_2_enabled = settings.get('rule_2_enabled')
    rule_3_enabled = settings.get('rule_3_enabled')
    rule_4_enabled = settings.get('rule_4_enabled')
    rule_5_enabled = settings.get('rule_5_enabled')
    rule_6_enabled = settings.get('rule_6_enabled')
    rule_7_enabled = settings.get('rule_7_enabled')
    rule_8_enabled = settings.get('rule_8_enabled')
    rule_9_enabled = settings.get('rule_9_enabled')
    take_profit_amount = settings.get('take_profit_amount')
    stop_loss_amount = settings.get('stop_loss_amount')
    rule_3_drop_count = settings.get('rule_3_drop_count')
    rule_5_down_minutes = settings.get('rule_5_down_minutes')
    rule_5_reversal_amount = settings.get('rule_5_reversal_amount')
    rule_5_scalp_amount = settings.get('rule_5_scalp_amount')
    rule_6_down_minutes = settings.get('rule_6_down_minutes')
    rule_6_profit_amount = settings.get('rule_6_profit_amount')
    rule_7_up_minutes = settings.get('rule_7_up_minutes')
    rule_8_buy_offset = settings.get('rule_8_buy_offset')
    rule_8_sell_offset = settings.get('rule_8_sell_offset')
    rule_9_amount = settings.get('rule_9_amount')
    rule_9_flips = settings.get('rule_9_flips')
    rule_9_window_minutes = settings.get('rule_9_window_minutes')

    # IBKR order settings
    live_trading_enabled = settings.get('live_trading_enabled')
    order_size_type = settings.get('order_size_type')
    order_size_value = settings.get('order_size_value')
    buy_order_type = settings.get('buy_order_type')
    sell_order_type = settings.get('sell_order_type')
    retry_delay_secs = settings.get('retry_delay_secs')
    max_retries = settings.get('max_retries')
    min_trade_dollars = settings.get('min_trade_dollars')
    validate_conditions_on_retry = settings.get('validate_conditions_on_retry')
    default_trade_enabled = settings.get('default_trade_enabled')

    # Normalize
    if rule_1_enabled is not None:
        rule_1_enabled = 1 if bool(rule_1_enabled) else 0
    if rule_2_enabled is not None:
        rule_2_enabled = 1 if bool(rule_2_enabled) else 0
    if rule_3_enabled is not None:
        rule_3_enabled = 1 if bool(rule_3_enabled) else 0
    if rule_4_enabled is not None:
        rule_4_enabled = 1 if bool(rule_4_enabled) else 0
    if rule_5_enabled is not None:
        rule_5_enabled = 1 if bool(rule_5_enabled) else 0
    if rule_6_enabled is not None:
        rule_6_enabled = 1 if bool(rule_6_enabled) else 0
    if rule_7_enabled is not None:
        rule_7_enabled = 1 if bool(rule_7_enabled) else 0
    if rule_8_enabled is not None:
        rule_8_enabled = 1 if bool(rule_8_enabled) else 0
    if rule_9_enabled is not None:
        rule_9_enabled = 1 if bool(rule_9_enabled) else 0
    if take_profit_amount is not None:
        try:
            take_profit_amount = float(take_profit_amount)
        except Exception:
            take_profit_amount = None
    if stop_loss_amount is not None:
        try:
            stop_loss_amount = float(stop_loss_amount)
        except Exception:
            stop_loss_amount = None
    if rule_3_drop_count is not None:
        try:
            rule_3_drop_count = int(rule_3_drop_count)
        except Exception:
            rule_3_drop_count = None
    if rule_5_down_minutes is not None:
        try:
            rule_5_down_minutes = int(rule_5_down_minutes)
        except Exception:
            rule_5_down_minutes = None
    if rule_5_reversal_amount is not None:
        try:
            rule_5_reversal_amount = float(rule_5_reversal_amount)
        except Exception:
            rule_5_reversal_amount = None
    if rule_5_scalp_amount is not None:
        try:
            rule_5_scalp_amount = float(rule_5_scalp_amount)
        except Exception:
            rule_5_scalp_amount = None
    if rule_6_down_minutes is not None:
        try:
            rule_6_down_minutes = int(rule_6_down_minutes)
        except Exception:
            rule_6_down_minutes = None
    if rule_6_profit_amount is not None:
        try:
            rule_6_profit_amount = float(rule_6_profit_amount)
        except Exception:
            rule_6_profit_amount = None
    if rule_7_up_minutes is not None:
        try:
            rule_7_up_minutes = int(rule_7_up_minutes)
        except Exception:
            rule_7_up_minutes = None
    if rule_8_buy_offset is not None:
        try:
            rule_8_buy_offset = float(rule_8_buy_offset)
        except Exception:
            rule_8_buy_offset = None
    if rule_8_sell_offset is not None:
        try:
            rule_8_sell_offset = float(rule_8_sell_offset)
        except Exception:
            rule_8_sell_offset = None
    if rule_9_amount is not None:
        try:
            rule_9_amount = float(rule_9_amount)
        except Exception:
            rule_9_amount = None
    if rule_9_flips is not None:
        try:
            rule_9_flips = int(rule_9_flips)
        except Exception:
            rule_9_flips = None
    if rule_9_window_minutes is not None:
        try:
            rule_9_window_minutes = int(rule_9_window_minutes)
        except Exception:
            rule_9_window_minutes = None

    # Normalize IBKR order settings
    if live_trading_enabled is not None:
        live_trading_enabled = 1 if bool(live_trading_enabled) else 0
    if order_size_type is not None:
        order_size_type = str(order_size_type) if order_size_type in ('fixed', 'percent', 'dollars') else None
    if order_size_value is not None:
        try:
            order_size_value = float(order_size_value)
            if order_size_value <= 0:
                order_size_value = 1.0
        except Exception:
            order_size_value = None
    if buy_order_type is not None:
        buy_order_type = str(buy_order_type) if buy_order_type in ('market', 'limit') else None
    if sell_order_type is not None:
        sell_order_type = str(sell_order_type) if sell_order_type in ('market', 'limit') else None
    if retry_delay_secs is not None:
        try:
            retry_delay_secs = float(retry_delay_secs)
            if retry_delay_secs < 0:
                retry_delay_secs = 5.0
        except Exception:
            retry_delay_secs = None
    if max_retries is not None:
        try:
            max_retries = int(max_retries)
            if max_retries < 0:
                max_retries = 3
        except Exception:
            max_retries = None
    if min_trade_dollars is not None:
        try:
            min_trade_dollars = float(min_trade_dollars)
            if min_trade_dollars < 0:
                min_trade_dollars = 0.0
        except Exception:
            min_trade_dollars = None
    if validate_conditions_on_retry is not None:
        validate_conditions_on_retry = 1 if bool(validate_conditions_on_retry) else 0
    if default_trade_enabled is not None:
        default_trade_enabled = 1 if bool(default_trade_enabled) else 0

    # Optional meta merge
    meta = settings.get('meta')
    if meta is not None and not isinstance(meta, dict):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}

    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM bots WHERE hwnd = ?", (hwnd,))
        row = cur.fetchone()

        existing_meta = {}
        if row:
            try:
                existing_meta = json.loads(row['meta']) if row['meta'] else {}
            except Exception:
                existing_meta = {}

        merged_meta = existing_meta
        if isinstance(meta, dict):
            try:
                merged_meta = {**(existing_meta or {}), **meta}
            except Exception:
                merged_meta = existing_meta or {}

        if row:
            cur.execute(
                """
                UPDATE bots
                SET
                    name = COALESCE(?, name),
                    ticker = COALESCE(?, ticker),
                    rule_1_enabled = COALESCE(?, rule_1_enabled),
                    rule_2_enabled = COALESCE(?, rule_2_enabled),
                    rule_3_enabled = COALESCE(?, rule_3_enabled),
                    rule_4_enabled = COALESCE(?, rule_4_enabled),
                    rule_5_enabled = COALESCE(?, rule_5_enabled),
                    rule_6_enabled = COALESCE(?, rule_6_enabled),
                    rule_7_enabled = COALESCE(?, rule_7_enabled),
                    rule_8_enabled = COALESCE(?, rule_8_enabled),
                    rule_9_enabled = COALESCE(?, rule_9_enabled),
                    take_profit_amount = COALESCE(?, take_profit_amount),
                    stop_loss_amount = COALESCE(?, stop_loss_amount),
                    rule_3_drop_count = COALESCE(?, rule_3_drop_count),
                    rule_5_down_minutes = COALESCE(?, rule_5_down_minutes),
                    rule_5_reversal_amount = COALESCE(?, rule_5_reversal_amount),
                    rule_5_scalp_amount = COALESCE(?, rule_5_scalp_amount),
                    rule_6_down_minutes = COALESCE(?, rule_6_down_minutes),
                    rule_6_profit_amount = COALESCE(?, rule_6_profit_amount),
                    rule_7_up_minutes = COALESCE(?, rule_7_up_minutes),
                    rule_8_buy_offset = COALESCE(?, rule_8_buy_offset),
                    rule_8_sell_offset = COALESCE(?, rule_8_sell_offset),
                    rule_9_amount = COALESCE(?, rule_9_amount),
                    rule_9_flips = COALESCE(?, rule_9_flips),
                    rule_9_window_minutes = COALESCE(?, rule_9_window_minutes),
                    live_trading_enabled = COALESCE(?, live_trading_enabled),
                    order_size_type = COALESCE(?, order_size_type),
                    order_size_value = COALESCE(?, order_size_value),
                    buy_order_type = COALESCE(?, buy_order_type),
                    sell_order_type = COALESCE(?, sell_order_type),
                    retry_delay_secs = COALESCE(?, retry_delay_secs),
                    max_retries = COALESCE(?, max_retries),
                    min_trade_dollars = COALESCE(?, min_trade_dollars),
                    validate_conditions_on_retry = COALESCE(?, validate_conditions_on_retry),
                    default_trade_enabled = COALESCE(?, default_trade_enabled),
                    meta = ?
                WHERE hwnd = ?
                """,
                (
                    name,
                    ticker,
                    rule_1_enabled,
                    rule_2_enabled,
                    rule_3_enabled,
                    rule_4_enabled,
                    rule_5_enabled,
                    rule_6_enabled,
                    rule_7_enabled,
                    rule_8_enabled,
                    rule_9_enabled,
                    take_profit_amount,
                    stop_loss_amount,
                    rule_3_drop_count,
                    rule_5_down_minutes,
                    rule_5_reversal_amount,
                    rule_5_scalp_amount,
                    rule_6_down_minutes,
                    rule_6_profit_amount,
                    rule_7_up_minutes,
                    rule_8_buy_offset,
                    rule_8_sell_offset,
                    rule_9_amount,
                    rule_9_flips,
                    rule_9_window_minutes,
                    live_trading_enabled,
                    order_size_type,
                    order_size_value,
                    buy_order_type,
                    sell_order_type,
                    retry_delay_secs,
                    max_retries,
                    min_trade_dollars,
                    validate_conditions_on_retry,
                    default_trade_enabled,
                    json.dumps(merged_meta) if isinstance(merged_meta, dict) else json.dumps({}),
                    hwnd,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO bots (hwnd, name, ticker, total_pnl, open_direction, open_price, open_time, rule_1_enabled, rule_2_enabled, rule_3_enabled, rule_4_enabled, rule_5_enabled, rule_6_enabled, rule_7_enabled, rule_8_enabled, rule_9_enabled, take_profit_amount, stop_loss_amount, rule_3_drop_count, rule_5_down_minutes, rule_5_reversal_amount, rule_5_scalp_amount, rule_6_down_minutes, rule_6_profit_amount, rule_7_up_minutes, rule_8_buy_offset, rule_8_sell_offset, rule_9_amount, rule_9_flips, rule_9_window_minutes, live_trading_enabled, order_size_type, order_size_value, buy_order_type, sell_order_type, retry_delay_secs, max_retries, min_trade_dollars, validate_conditions_on_retry, default_trade_enabled, meta)
                VALUES (?, ?, ?, NULL, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hwnd,
                    name,
                    ticker,
                    rule_1_enabled if rule_1_enabled is not None else 0,
                    rule_2_enabled if rule_2_enabled is not None else 0,
                    rule_3_enabled if rule_3_enabled is not None else 0,
                    rule_4_enabled if rule_4_enabled is not None else 1,
                    rule_5_enabled if rule_5_enabled is not None else 0,
                    rule_6_enabled if rule_6_enabled is not None else 0,
                    rule_7_enabled if rule_7_enabled is not None else 0,
                    rule_8_enabled if rule_8_enabled is not None else 0,
                    rule_9_enabled if rule_9_enabled is not None else 0,
                    take_profit_amount if take_profit_amount is not None else 0.0,
                    stop_loss_amount if stop_loss_amount is not None else 0.0,
                    rule_3_drop_count if rule_3_drop_count is not None else 0,
                    rule_5_down_minutes if rule_5_down_minutes is not None else 3,
                    rule_5_reversal_amount if rule_5_reversal_amount is not None else 2.0,
                    rule_5_scalp_amount if rule_5_scalp_amount is not None else 0.25,
                    rule_6_down_minutes if rule_6_down_minutes is not None else 5,
                    rule_6_profit_amount if rule_6_profit_amount is not None else 2.0,
                    rule_7_up_minutes if rule_7_up_minutes is not None else 3,
                    rule_8_buy_offset if rule_8_buy_offset is not None else 0.25,
                    rule_8_sell_offset if rule_8_sell_offset is not None else 0.25,
                    rule_9_amount if rule_9_amount is not None else 0.25,
                    rule_9_flips if rule_9_flips is not None else 3,
                    rule_9_window_minutes if rule_9_window_minutes is not None else 3,
                    live_trading_enabled if live_trading_enabled is not None else 0,
                    order_size_type if order_size_type is not None else 'fixed',
                    order_size_value if order_size_value is not None else 1.0,
                    buy_order_type if buy_order_type is not None else 'market',
                    sell_order_type if sell_order_type is not None else 'market',
                    retry_delay_secs if retry_delay_secs is not None else 5.0,
                    max_retries if max_retries is not None else 3,
                    min_trade_dollars if min_trade_dollars is not None else 0.0,
                    validate_conditions_on_retry if validate_conditions_on_retry is not None else 1,
                    default_trade_enabled if default_trade_enabled is not None else 1,
                    json.dumps(merged_meta) if isinstance(merged_meta, dict) else json.dumps({}),
                ),
            )
        conn.commit()
        conn.close()


def get_app_settings() -> dict:
    """Return all app_settings rows as a key→value dict."""
    rows = query_records("SELECT key, value FROM app_settings")
    return {r["key"]: r["value"] for r in rows}


def set_app_setting(key: str, value: str):
    """Upsert a single app_settings row."""
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        conn.commit()
        conn.close()


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


def get_live_orders(hwnd: int = None, bot_id: str = None, limit: int = 50) -> list:
    """Return recent live_orders rows, optionally filtered by hwnd or bot_id."""
    if hwnd is not None and bot_id is not None:
        return query_records(
            "SELECT * FROM live_orders WHERE hwnd = ? AND bot_id = ? ORDER BY ts DESC LIMIT ?",
            (int(hwnd), bot_id, limit),
        )
    if hwnd is not None:
        return query_records(
            "SELECT * FROM live_orders WHERE hwnd = ? ORDER BY ts DESC LIMIT ?",
            (int(hwnd), limit),
        )
    if bot_id is not None:
        return query_records(
            "SELECT * FROM live_orders WHERE bot_id = ? ORDER BY ts DESC LIMIT ?",
            (bot_id, limit),
        )
    return query_records(
        "SELECT * FROM live_orders ORDER BY ts DESC LIMIT ?",
        (limit,),
    )


def get_last_buy_order(hwnd: int, ticker: str) -> dict:
    """Get the most recent filled BUY order for a ticker/hwnd to calculate P&L on sell."""
    rows = query_records(
        """SELECT * FROM live_orders
           WHERE hwnd = ? AND ticker = ? AND direction = 'buy' AND status = 'filled'
           ORDER BY ts DESC LIMIT 1""",
        (int(hwnd), ticker),
    )
    return rows[0] if rows else None


__all__ = [
    "query_records",
    "get_latest_record",
    "save_observation",
    "get_bot_db_entry",
    "upsert_bot_from_last_result",
    "upsert_bot_settings",
    "get_app_settings",
    "set_app_setting",
    "save_live_order",
    "update_live_order_status",
    "get_live_orders",
    "get_last_buy_order",
]
