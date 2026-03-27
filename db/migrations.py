"""Database schema migrations and initialization."""

import os
import sqlite3
from .connection import DB_PATH, DB_LOCK
from config.settings import UPLOADS_DIR


def init_db():
    """Initialize database schema and create tables."""
    print(f"[Database] Initializing database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Create observations table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            image_path TEXT,
            name TEXT,
            ticker TEXT,
            price TEXT,
            trend TEXT
        )
        """
    )
    
    # Create records table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            image_path TEXT,
            name TEXT,
            ticker TEXT,
            price TEXT,
            trend TEXT,
            buy_price REAL,
            sell_price REAL,
            buy_time TEXT,
            sell_time TEXT,
            win_reason TEXT,
            bot_id TEXT,
            bot_name TEXT,
            meta TEXT
        )
        """
    )
    
    # Migration: ensure new columns exist
    cur.execute("PRAGMA table_info(records)")
    existing = [r[1] for r in cur.fetchall()]
    additions = [
        ("buy_price", "REAL"),
        ("sell_price", "REAL"),
        ("buy_time", "TEXT"),
        ("sell_time", "TEXT"),
        ("win_reason", "TEXT"),
        ("bot_id", "TEXT"),
        ("bot_name", "TEXT"),
    ]
    for col, typ in additions:
        if col not in existing:
            try:
                cur.execute(f"ALTER TABLE records ADD COLUMN {col} {typ}")
            except Exception:
                pass

    # Create trades table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            ticker TEXT,
            action TEXT,
            qty REAL,
            price REAL,
            profit REAL,
            meta TEXT
        )
        """
    )
    
    # Bots table: store per-worker bot metadata (keyed by hwnd)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bots (
            hwnd INTEGER PRIMARY KEY,
            name TEXT,
            ticker TEXT,
            total_pnl REAL,
            open_direction TEXT,
            open_price REAL,
            open_time TEXT,
            rule_1_enabled INTEGER,
            rule_2_enabled INTEGER,
            rule_3_enabled INTEGER,
            rule_4_enabled INTEGER,
            rule_5_enabled INTEGER,
            rule_6_enabled INTEGER,
            rule_7_enabled INTEGER,
            rule_8_enabled INTEGER,
            rule_9_enabled INTEGER,
            take_profit_amount REAL,
            stop_loss_amount REAL,
            rule_3_drop_count INTEGER,
            rule_5_down_minutes INTEGER,
            rule_5_reversal_amount REAL,
            rule_5_scalp_amount REAL,
            rule_6_down_minutes INTEGER,
            rule_6_profit_amount REAL,
            rule_7_up_minutes INTEGER,
            rule_8_buy_offset REAL,
            rule_8_sell_offset REAL,
            rule_9_amount REAL,
            rule_9_flips INTEGER,
            rule_9_window_minutes INTEGER,
            meta TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    cur.execute(
        "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
        ("time_mode", "local"),
    )
    # IBKR connection defaults
    for _k, _v in [
        ("ibkr_enabled", "0"),
        ("ibkr_host", "127.0.0.1"),
        ("ibkr_port", "4002"),
        ("ibkr_client_id", "1"),
    ]:
        cur.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
            (_k, _v),
        )

    # Live orders table — one row per order placed via IBKR
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS live_orders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts              TEXT NOT NULL,
            hwnd            INTEGER,
            bot_id          TEXT,
            ticker          TEXT,
            direction       TEXT,
            order_type      TEXT,
            qty             REAL,
            price           REAL,
            limit_price     REAL,
            ibkr_order_id   INTEGER,
            status          TEXT,
            fill_price      REAL,
            fill_ts         TEXT,
            error_msg       TEXT,
            retries         INTEGER DEFAULT 0,
            trade_ref_id    TEXT,
            meta            TEXT
        )
        """
    )

    # Order book snapshots — L2 depth at the moment an order fires
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS order_book_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts              TEXT NOT NULL,
            ticker          TEXT,
            trade_ref_id    TEXT,
            snapshot        TEXT
        )
        """
    )

    # Migration: ensure new columns exist in bots
    try:
        cur.execute("PRAGMA table_info(bots)")
        existing_bots = [r[1] for r in cur.fetchall()]
        bot_additions = [
            ("rule_1_enabled", "INTEGER"),
            ("rule_2_enabled", "INTEGER"),
            ("rule_3_enabled", "INTEGER"),
            ("rule_4_enabled", "INTEGER"),
            ("rule_5_enabled", "INTEGER"),
            ("rule_6_enabled", "INTEGER"),
            ("rule_7_enabled", "INTEGER"),
            ("rule_8_enabled", "INTEGER"),
            ("rule_9_enabled", "INTEGER"),
            ("take_profit_amount", "REAL"),
            ("stop_loss_amount", "REAL"),
            ("rule_3_drop_count", "INTEGER"),
            ("rule_5_down_minutes", "INTEGER"),
            ("rule_5_reversal_amount", "REAL"),
            ("rule_5_scalp_amount", "REAL"),
            ("rule_6_down_minutes", "INTEGER"),
            ("rule_6_profit_amount", "REAL"),
            ("rule_7_up_minutes", "INTEGER"),
            ("rule_8_buy_offset", "REAL"),
            ("rule_8_sell_offset", "REAL"),
            ("rule_9_amount", "REAL"),
            ("rule_9_flips", "INTEGER"),
            ("rule_9_window_minutes", "INTEGER"),
            # IBKR live trading settings
            ("live_trading_enabled", "INTEGER DEFAULT 0"),
            ("order_size_type", "TEXT DEFAULT 'fixed'"),
            ("order_size_value", "REAL DEFAULT 1.0"),
            ("buy_order_type", "TEXT DEFAULT 'market'"),
            ("sell_order_type", "TEXT DEFAULT 'market'"),
            ("retry_delay_secs", "REAL DEFAULT 5.0"),
            ("max_retries", "INTEGER DEFAULT 3"),
            ("min_trade_dollars", "REAL DEFAULT 0"),
            ("validate_conditions_on_retry", "INTEGER DEFAULT 1"),
            # Smart order management
            ("cancel_on_trend_reversal", "INTEGER DEFAULT 0"),
        ]
        for col, typ in bot_additions:
            if col not in existing_bots:
                try:
                    cur.execute(f"ALTER TABLE bots ADD COLUMN {col} {typ}")
                except Exception:
                    pass
    except Exception:
        pass
    
    # Migration: ensure screenshot_path column exists in live_orders
    try:
        cur.execute("PRAGMA table_info(live_orders)")
        existing_live_orders_cols = [r[1] for r in cur.fetchall()]
        if "screenshot_path" not in existing_live_orders_cols:
            try:
                cur.execute("ALTER TABLE live_orders ADD COLUMN screenshot_path TEXT")
            except Exception:
                pass
        # Add profit column for P&L tracking
        if "profit" not in existing_live_orders_cols:
            try:
                cur.execute("ALTER TABLE live_orders ADD COLUMN profit REAL")
            except Exception:
                pass
        # Add buy_order_id to link sells to their corresponding buys
        if "buy_order_id" not in existing_live_orders_cols:
            try:
                cur.execute("ALTER TABLE live_orders ADD COLUMN buy_order_id INTEGER")
            except Exception:
                pass
    except Exception:
        pass

    conn.commit()
    conn.close()
    os.makedirs(UPLOADS_DIR, exist_ok=True)

    # Enable WAL mode and create indexes in a separate connection
    # (PRAGMA journal_mode must be done outside a transaction)
    conn2 = sqlite3.connect(DB_PATH)
    conn2.execute("PRAGMA journal_mode=WAL")
    conn2.execute("CREATE INDEX IF NOT EXISTS idx_records_ts ON records(ts DESC)")
    conn2.execute("CREATE INDEX IF NOT EXISTS idx_records_ts_bot ON records(ts DESC, bot_id)")
    conn2.execute("CREATE INDEX IF NOT EXISTS idx_records_ticker ON records(ticker)")
    conn2.execute("CREATE INDEX IF NOT EXISTS idx_live_orders_ts ON live_orders(ts DESC)")
    conn2.execute("CREATE INDEX IF NOT EXISTS idx_live_orders_hwnd ON live_orders(hwnd, ts DESC)")
    conn2.commit()
    conn2.close()


__all__ = ["init_db"]
