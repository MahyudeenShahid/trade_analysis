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
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


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
            "INSERT INTO records (ts, image_path, name, ticker, price, trend, buy_price, sell_price, buy_time, sell_time, win_reason, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    "INSERT INTO bots (hwnd, name, ticker, total_pnl, open_direction, open_price, open_time, rule_1_enabled, rule_2_enabled, rule_3_enabled, rule_4_enabled, rule_5_enabled, take_profit_amount, stop_loss_amount, rule_3_drop_count, rule_5_down_minutes, rule_5_reversal_amount, rule_5_scalp_amount, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                        0.0,
                        0.0,
                        0,
                        3,
                        2.0,
                        0.25,
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
    take_profit_amount = settings.get('take_profit_amount')
    stop_loss_amount = settings.get('stop_loss_amount')
    rule_3_drop_count = settings.get('rule_3_drop_count')
    rule_5_down_minutes = settings.get('rule_5_down_minutes')
    rule_5_reversal_amount = settings.get('rule_5_reversal_amount')
    rule_5_scalp_amount = settings.get('rule_5_scalp_amount')

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
                    take_profit_amount = COALESCE(?, take_profit_amount),
                    stop_loss_amount = COALESCE(?, stop_loss_amount),
                    rule_3_drop_count = COALESCE(?, rule_3_drop_count),
                    rule_5_down_minutes = COALESCE(?, rule_5_down_minutes),
                    rule_5_reversal_amount = COALESCE(?, rule_5_reversal_amount),
                    rule_5_scalp_amount = COALESCE(?, rule_5_scalp_amount),
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
                    take_profit_amount,
                    stop_loss_amount,
                    rule_3_drop_count,
                    rule_5_down_minutes,
                    rule_5_reversal_amount,
                    rule_5_scalp_amount,
                    json.dumps(merged_meta) if isinstance(merged_meta, dict) else json.dumps({}),
                    hwnd,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO bots (hwnd, name, ticker, total_pnl, open_direction, open_price, open_time, rule_1_enabled, rule_2_enabled, rule_3_enabled, rule_4_enabled, rule_5_enabled, take_profit_amount, stop_loss_amount, rule_3_drop_count, rule_5_down_minutes, rule_5_reversal_amount, rule_5_scalp_amount, meta)
                VALUES (?, ?, ?, NULL, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    take_profit_amount if take_profit_amount is not None else 0.0,
                    stop_loss_amount if stop_loss_amount is not None else 0.0,
                    rule_3_drop_count if rule_3_drop_count is not None else 0,
                    rule_5_down_minutes if rule_5_down_minutes is not None else 3,
                    rule_5_reversal_amount if rule_5_reversal_amount is not None else 2.0,
                    rule_5_scalp_amount if rule_5_scalp_amount is not None else 0.25,
                    json.dumps(merged_meta) if isinstance(merged_meta, dict) else json.dumps({}),
                ),
            )
        conn.commit()
        conn.close()


__all__ = [
    "query_records",
    "get_latest_record",
    "save_observation",
    "get_bot_db_entry",
    "upsert_bot_from_last_result",
    "upsert_bot_settings",
]
