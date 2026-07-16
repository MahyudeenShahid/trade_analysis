"""Database schema migrations and initialization."""

import os
import sqlite3
from .connection import DB_PATH
from config.settings import UPLOADS_DIR
from .schemas import (
    OBSERVATIONS_SCHEMA,
    RECORDS_SCHEMA,
    TRADES_SCHEMA,
    BOTS_SCHEMA,
    APP_SETTINGS_SCHEMA,
    LIVE_ORDERS_SCHEMA,
    ORDER_BOOK_SNAPSHOTS_SCHEMA,
    ORDER_BOOK_HISTORY_SCHEMA,
    TRADE_REPLAYS_SCHEMA,
)


def init_db():
    """Initialize database schema and create tables."""
    print(f"[Database] Initializing database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(OBSERVATIONS_SCHEMA)
    cur.execute(RECORDS_SCHEMA)

    # Migration: ensure new columns exist in records table
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

    cur.execute(TRADES_SCHEMA)
    cur.execute(BOTS_SCHEMA)
    cur.execute(APP_SETTINGS_SCHEMA)

    # Migration: ensure new Rule 10 columns exist on bots table
    try:
        cur.execute("PRAGMA table_info(bots)")
        existing_bots = [r[1] for r in cur.fetchall()]
        bot_additions = [
            ("rsi_bollinger_stop_enabled", "INTEGER"),
            ("rsi_bollinger_strict_enabled", "INTEGER"),
            ("rsi_bollinger_strict_bars", "INTEGER"),
            ("rsi_bollinger_bounce_enabled", "INTEGER"),
            ("rsi_bollinger_bounce_pct", "REAL"),
            ("rsi_bollinger_cooldown_enabled", "INTEGER"),
            ("rsi_bollinger_cooldown_minutes", "REAL"),
            ("rsi_bollinger_time_exit_enabled", "INTEGER"),
            ("rsi_bollinger_time_exit_minutes", "REAL"),
            ("rsi_bollinger_only_profit", "INTEGER"),
        ]
        for col, typ in bot_additions:
            if col not in existing_bots:
                try:
                    cur.execute(f"ALTER TABLE bots ADD COLUMN {col} {typ}")
                except Exception:
                    pass
    except Exception:
        pass

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

    # Order book history defaults
    for _k, _v in [
        ("order_book_history_enabled", "1"),
        ("order_book_history_interval_ms", "1000"),
        ("order_book_history_levels", "5"),
        ("order_book_history_retention_days", "30"),
    ]:
        cur.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
            (_k, _v),
        )

    cur.execute(
        "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
        ("signal_source", "screenshot"),
    )

    cur.execute(
        "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
        ("require_live_confirm", "1"),
    )

    cur.execute(LIVE_ORDERS_SCHEMA)
    cur.execute(ORDER_BOOK_SNAPSHOTS_SCHEMA)
    cur.execute(ORDER_BOOK_HISTORY_SCHEMA)

    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_order_book_history_ticker_ts ON order_book_history (ticker, ts)")
    except Exception:
        pass

    cur.execute(TRADE_REPLAYS_SCHEMA)

    try:
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_replays_ref ON trade_replays (trade_ref_id)")
    except Exception:
        pass

    # Migration: ensure new columns exist in trade_replays
    try:
        cur.execute("PRAGMA table_info(trade_replays)")
        existing_replays = [r[1] for r in cur.fetchall()]
        replay_additions = [
            ("trade_ref_id", "TEXT"),
            ("ticker", "TEXT"),
            ("start_ts", "TEXT"),
            ("end_ts", "TEXT"),
            ("bar_size", "TEXT"),
            ("bars", "TEXT"),
            ("order_book", "TEXT"),
            ("created_at", "TEXT"),
        ]
        for col, typ in replay_additions:
            if col not in existing_replays:
                try:
                    cur.execute(f"ALTER TABLE trade_replays ADD COLUMN {col} {typ}")
                except Exception:
                    pass
    except Exception:
        pass

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
            ("rsi_bollinger_enabled", "INTEGER DEFAULT 0"),
            ("rsi_bollinger_rsi_length", "INTEGER DEFAULT 14"),
            ("rsi_bollinger_rsi_threshold", "REAL DEFAULT 30"),
            ("rsi_bollinger_bb_length", "INTEGER DEFAULT 20"),
            ("rsi_bollinger_bb_stdev", "REAL DEFAULT 2.0"),
            ("rsi_bollinger_profit_pct", "REAL DEFAULT 0.2"),
            ("rsi_bollinger_stop_pct", "REAL DEFAULT 0.4"),
            ("live_trading_enabled", "INTEGER DEFAULT 0"),
            ("order_size_type", "TEXT DEFAULT 'fixed'"),
            ("order_size_value", "REAL DEFAULT 1.0"),
            ("buy_order_type", "TEXT DEFAULT 'limit'"),
            ("sell_order_type", "TEXT DEFAULT 'limit'"),
            ("retry_delay_secs", "REAL DEFAULT 5.0"),
            ("max_retries", "INTEGER DEFAULT 3"),
            ("min_trade_dollars", "REAL DEFAULT 0"),
            ("validate_conditions_on_retry", "INTEGER DEFAULT 1"),
            ("cancel_on_trend_reversal", "INTEGER DEFAULT 0"),
            ("rsi_bollinger_daily_max_loss", "REAL"),
            ("rsi_bollinger_max_losses_per_day", "INTEGER"),
            ("rsi_bollinger_size_multiplier", "REAL"),
            ("rsi_bollinger_trend_enabled", "INTEGER"),
            ("rsi_bollinger_trend_ma", "INTEGER"),
            ("rsi_bollinger_liquidity_enabled", "INTEGER"),
            ("rsi_bollinger_min_avg_volume", "INTEGER"),
            ("rsi_bollinger_trailing_stop_enabled", "INTEGER DEFAULT 0"),
            ("rsi_bollinger_trailing_stop_pct", "REAL DEFAULT 0.1"),
            ("rsi_bollinger_rsi_slope_enabled", "INTEGER DEFAULT 0"),
            ("rule_11_profit_pct", "REAL DEFAULT 0.2"),
            ("rule_11_stop_pct", "REAL DEFAULT 0.4"),
            ("rule_11_stop_enabled", "INTEGER DEFAULT 1"),
            ("rule_11_only_profit", "INTEGER DEFAULT 0"),
            ("rule_11_trailing_stop_enabled", "INTEGER DEFAULT 0"),
            ("rule_11_trailing_stop_pct", "REAL DEFAULT 0.1"),
            ("rule_11_cooldown_enabled", "INTEGER DEFAULT 0"),
            ("rule_11_cooldown_minutes", "REAL DEFAULT 5.0"),
            ("rule_11_size_multiplier", "REAL DEFAULT 1.0"),
            ("rule_11_daily_max_loss", "REAL DEFAULT 0.0"),
            ("rule_11_max_losses_per_day", "INTEGER DEFAULT 0"),
            ("rule_11_trend_enabled", "INTEGER DEFAULT 0"),
            ("rule_11_trend_ma", "INTEGER DEFAULT 50"),
            ("rule_11_liquidity_enabled", "INTEGER DEFAULT 0"),
            ("rule_11_min_avg_volume", "INTEGER DEFAULT 0"),
            ("rule_11_min_tick_density", "INTEGER DEFAULT 3"),
            ("rule_12_weight_tape", "REAL DEFAULT 0.4"),
            ("rule_12_weight_book", "REAL DEFAULT 0.2"),
            ("rule_12_weight_trend", "REAL DEFAULT 0.2"),
            ("rule_12_weight_momentum", "REAL DEFAULT 0.1"),
            ("rule_12_weight_volume", "REAL DEFAULT 0.1"),
            ("rule_12_weight_spread", "REAL DEFAULT 0.0"),
            ("rule_12_weight_pullback", "REAL DEFAULT 0.0"),
            ("rule_12_momentum_scale", "REAL DEFAULT 0.0005"),
            ("rule_12_spread_tight_pct", "REAL DEFAULT 0.001"),
            ("rsi_bollinger_graph_trend_enabled", "INTEGER DEFAULT 0"),
            ("rsi_bollinger_graph_trend_lookback", "INTEGER DEFAULT 5"),
            ("rsi_bollinger_graph_trend_threshold_pct", "REAL DEFAULT 0.0005"),
            ("rule_13_enabled", "INTEGER DEFAULT 0"),
            ("rule_13_lookback", "INTEGER DEFAULT 5"),
            ("rule_13_slope_threshold_pct", "REAL DEFAULT 0.0005"),
            ("rule_13_profit_pct", "REAL DEFAULT 0.2"),
            ("rule_13_stop_pct", "REAL DEFAULT 0.4"),
            ("rule_13_stop_enabled", "INTEGER DEFAULT 1"),
            ("rule_13_only_profit", "INTEGER DEFAULT 0"),
            ("rule_13_cooldown_minutes", "REAL DEFAULT 0.0"),
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
        if "profit" not in existing_live_orders_cols:
            try:
                cur.execute("ALTER TABLE live_orders ADD COLUMN profit REAL")
            except Exception:
                pass
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
