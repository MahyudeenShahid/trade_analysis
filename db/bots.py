"""Bot configuration database operations."""

import json
import sqlite3
from .connection import DB_PATH, DB_LOCK

# Metadata mapping for bot setting fields to dynamic normalization rules and default values
BOT_SETTING_FIELDS = {
    # Rule activation status
    "rule_1_enabled": {"type": "bool", "default": 0},
    "rule_2_enabled": {"type": "bool", "default": 0},
    "rule_3_enabled": {"type": "bool", "default": 0},
    "rule_4_enabled": {"type": "bool", "default": 1},
    "rule_5_enabled": {"type": "bool", "default": 0},
    "rule_6_enabled": {"type": "bool", "default": 0},
    "rule_7_enabled": {"type": "bool", "default": 0},
    "rule_8_enabled": {"type": "bool", "default": 0},
    "rule_9_enabled": {"type": "bool", "default": 0},
    # Rule 3
    "rule_3_drop_count": {"type": "int", "default": 0},
    # Rule 5
    "rule_5_down_minutes": {"type": "int", "default": 3},
    "rule_5_reversal_amount": {"type": "float", "default": 2.0},
    "rule_5_scalp_amount": {"type": "float", "default": 0.25},
    # Rule 6
    "rule_6_down_minutes": {"type": "int", "default": 5},
    "rule_6_profit_amount": {"type": "float", "default": 2.0},
    # Rule 7
    "rule_7_up_minutes": {"type": "int", "default": 3},
    # Rule 8
    "rule_8_buy_offset": {"type": "float", "default": 0.25},
    "rule_8_sell_offset": {"type": "float", "default": 0.25},
    # Rule 9
    "rule_9_amount": {"type": "float", "default": 0.25},
    "rule_9_flips": {"type": "int", "default": 3},
    "rule_9_window_minutes": {"type": "int", "default": 3},
    # General Trade parameters
    "take_profit_amount": {"type": "float", "default": 0.0},
    "stop_loss_amount": {"type": "float", "default": 0.0},
    # RSI Bollinger settings
    "rsi_bollinger_enabled": {"type": "bool", "default": 0},
    "rsi_bollinger_rsi_length": {"type": "int", "default": 14},
    "rsi_bollinger_rsi_threshold": {"type": "float", "default": 30.0},
    "rsi_bollinger_bb_length": {"type": "int", "default": 20},
    "rsi_bollinger_bb_stdev": {"type": "float", "default": 2.0},
    "rsi_bollinger_profit_pct": {"type": "float", "default": 0.2},
    "rsi_bollinger_stop_pct": {"type": "float", "default": 0.4},
    "rsi_bollinger_stop_enabled": {"type": "bool", "default": 1},
    "rsi_bollinger_strict_enabled": {"type": "bool", "default": 0},
    "rsi_bollinger_strict_bars": {"type": "int", "default": 2},
    "rsi_bollinger_bounce_enabled": {"type": "bool", "default": 0},
    "rsi_bollinger_bounce_pct": {"type": "float", "default": 0.05},
    "rsi_bollinger_cooldown_enabled": {"type": "bool", "default": 0},
    "rsi_bollinger_cooldown_minutes": {"type": "float", "default": 5.0},
    "rsi_bollinger_time_exit_enabled": {"type": "bool", "default": 0},
    "rsi_bollinger_time_exit_minutes": {"type": "float", "default": 5.0},
    "rsi_bollinger_only_profit": {"type": "bool", "default": 0},
    "rsi_bollinger_trailing_stop_enabled": {"type": "bool", "default": 0},
    "rsi_bollinger_trailing_stop_pct": {"type": "float", "default": 0.1},
    "rsi_bollinger_rsi_slope_enabled": {"type": "bool", "default": 0},
    # Rule 10 safety settings
    "rsi_bollinger_daily_max_loss": {"type": "float", "default": 0.0},
    "rsi_bollinger_max_losses_per_day": {"type": "int", "default": 0},
    "rsi_bollinger_size_multiplier": {"type": "float", "default": 1.0},
    "rsi_bollinger_trend_enabled": {"type": "bool", "default": 0},
    "rsi_bollinger_trend_ma": {"type": "int", "default": 50},
    "rsi_bollinger_liquidity_enabled": {"type": "bool", "default": 0},
    "rsi_bollinger_min_avg_volume": {"type": "int", "default": 0},
    # Rule 11 settings
    "rule_11_enabled": {"type": "bool", "default": 0},
    "rule_11_price_jump": {"type": "float", "default": 0.03},
    "rule_11_window_seconds": {"type": "int", "default": 5},
    "rule_11_volume_threshold": {"type": "int", "default": 5000},
    "rule_11_limit_offset": {"type": "float", "default": 0.01},
    "rule_11_profit_pct": {"type": "float", "default": 0.2},
    "rule_11_stop_pct": {"type": "float", "default": 0.4},
    "rule_11_stop_enabled": {"type": "bool", "default": 1},
    "rule_11_only_profit": {"type": "bool", "default": 0},
    "rule_11_trailing_stop_enabled": {"type": "bool", "default": 0},
    "rule_11_trailing_stop_pct": {"type": "float", "default": 0.1},
    "rule_11_cooldown_enabled": {"type": "bool", "default": 0},
    "rule_11_cooldown_minutes": {"type": "float", "default": 5.0},
    "rule_11_size_multiplier": {"type": "float", "default": 1.0},
    "rule_11_daily_max_loss": {"type": "float", "default": 0.0},
    "rule_11_max_losses_per_day": {"type": "int", "default": 0},
    "rule_11_trend_enabled": {"type": "bool", "default": 0},
    "rule_11_trend_ma": {"type": "int", "default": 50},
    "rule_11_liquidity_enabled": {"type": "bool", "default": 0},
    "rule_11_min_avg_volume": {"type": "int", "default": 0},
    "rule_11_min_tick_density": {"type": "int", "default": 3},
    # IBKR live execution parameters
    "live_trading_enabled": {"type": "bool", "default": 0},
    "order_size_type": {"type": "str", "default": "fixed", "choices": ("fixed", "percent", "dollars")},
    "order_size_value": {"type": "float", "default": 1.0, "min": 0.000001, "default_on_invalid": 1.0},
    "buy_order_type": {"type": "str", "default": "limit", "choices": ("market", "limit")},
    "sell_order_type": {"type": "str", "default": "limit", "choices": ("market", "limit")},
    "retry_delay_secs": {"type": "float", "default": 5.0, "min": 0.0, "default_on_invalid": 5.0},
    "max_retries": {"type": "int", "default": 3, "min": 0, "default_on_invalid": 3},
    "min_trade_dollars": {"type": "float", "default": 0.0, "min": 0.0, "default_on_invalid": 0.0},
    "validate_conditions_on_retry": {"type": "bool", "default": 1},
    "default_trade_enabled": {"type": "bool", "default": 1},
}


def get_bot_db_entry(hwnd: int) -> dict:
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
                # Insert dynamic with defaults matching the table specs
                insert_data = {
                    "hwnd": hwnd,
                    "name": name,
                    "ticker": ticker,
                    "total_pnl": float(total_pnl) if total_pnl is not None else None,
                    "open_direction": open_direction,
                    "open_price": float(open_price) if open_price is not None else None,
                    "open_time": open_time,
                    "meta": json.dumps(meta) if isinstance(meta, dict) else json.dumps({}),
                }
                for col, spec in BOT_SETTING_FIELDS.items():
                    insert_data[col] = spec["default"]

                cols = list(insert_data.keys())
                placeholders = ["?"] * len(cols)
                sql = f"INSERT INTO bots ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
                cur.execute(sql, tuple(insert_data.values()))

            conn.commit()
            conn.close()
    except Exception as e:
        print(f"Failed to upsert bot for hwnd {hwnd}: {e}")


def upsert_bot_settings(hwnd: int, settings: dict):
    """Upsert per-bot settings without clobbering runtime fields."""
    try:
        hwnd = int(hwnd)
    except Exception:
        raise ValueError("hwnd must be int")

    if not isinstance(settings, dict):
        settings = {}

    name = settings.get('name')
    ticker = settings.get('ticker')

    # Optional meta merge
    meta = settings.get('meta')
    if meta is not None and not isinstance(meta, dict):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}

    # Build updates dict with dynamic normalization
    updates = {}
    if name is not None:
        updates['name'] = str(name)
    if ticker is not None:
        updates['ticker'] = str(ticker)

    for key, spec in BOT_SETTING_FIELDS.items():
        if key in settings:
            val = settings[key]
            if val is None:
                updates[key] = None
                continue

            typ = spec["type"]
            if typ == "bool":
                updates[key] = 1 if bool(val) else 0
            elif typ == "int":
                try:
                    v = int(val)
                    if "min" in spec and v < spec["min"]:
                        v = spec["default_on_invalid"]
                    updates[key] = v
                except Exception:
                    updates[key] = None
            elif typ == "float":
                try:
                    v = float(val)
                    if "min" in spec and v < spec["min"]:
                        v = spec["default_on_invalid"]
                    updates[key] = v
                except Exception:
                    updates[key] = None
            elif typ == "str":
                v = str(val)
                if "choices" in spec and v not in spec["choices"]:
                    v = None
                updates[key] = v

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

        updates['meta'] = json.dumps(merged_meta)

        if row:
            # Dynamic UPDATE (only updates specified fields)
            set_clauses = []
            params = []
            for col, val in updates.items():
                set_clauses.append(f"{col} = ?")
                params.append(val)
            params.append(hwnd)
            sql = f"UPDATE bots SET {', '.join(set_clauses)} WHERE hwnd = ?"
            cur.execute(sql, tuple(params))
        else:
            # Dynamic INSERT with defaults
            insert_data = {"hwnd": hwnd}
            if name is not None:
                insert_data["name"] = str(name)
            if ticker is not None:
                insert_data["ticker"] = str(ticker)

            for col, spec in BOT_SETTING_FIELDS.items():
                val = updates.get(col)
                if val is not None:
                    insert_data[col] = val
                else:
                    insert_data[col] = spec["default"]

            insert_data["meta"] = json.dumps(merged_meta)

            cols = list(insert_data.keys())
            placeholders = ["?"] * len(cols)
            sql = f"INSERT INTO bots ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
            cur.execute(sql, tuple(insert_data.values()))

        conn.commit()
        conn.close()
