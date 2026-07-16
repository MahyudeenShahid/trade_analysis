"""Database schema SQL definitions for SQLite tables."""

OBSERVATIONS_SCHEMA = """
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

RECORDS_SCHEMA = """
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

TRADES_SCHEMA = """
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

BOTS_SCHEMA = """
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
    rsi_bollinger_enabled INTEGER,
    rsi_bollinger_rsi_length INTEGER,
    rsi_bollinger_rsi_threshold REAL,
    rsi_bollinger_bb_length INTEGER,
    rsi_bollinger_bb_stdev REAL,
    rsi_bollinger_profit_pct REAL,
    rsi_bollinger_stop_pct REAL,
    rsi_bollinger_stop_enabled INTEGER,
    rsi_bollinger_strict_enabled INTEGER,
    rsi_bollinger_strict_bars INTEGER,
    rsi_bollinger_bounce_enabled INTEGER,
    rsi_bollinger_bounce_pct REAL,
    rsi_bollinger_cooldown_enabled INTEGER,
    rsi_bollinger_cooldown_minutes REAL,
    rsi_bollinger_time_exit_enabled INTEGER,
    rsi_bollinger_time_exit_minutes REAL,
    rsi_bollinger_only_profit INTEGER,
    rule_11_enabled INTEGER,
    rule_11_price_jump REAL,
    rule_11_window_seconds INTEGER,
    rule_11_volume_threshold INTEGER,
    rule_11_limit_offset REAL,
    rule_11_profit_pct REAL DEFAULT 0.2,
    rule_11_stop_pct REAL DEFAULT 0.4,
    rule_11_stop_enabled INTEGER DEFAULT 1,
    rule_11_only_profit INTEGER DEFAULT 0,
    rule_11_trailing_stop_enabled INTEGER DEFAULT 0,
    rule_11_trailing_stop_pct REAL DEFAULT 0.1,
    rule_11_cooldown_enabled INTEGER DEFAULT 0,
    rule_11_cooldown_minutes REAL DEFAULT 5.0,
    rule_11_size_multiplier REAL DEFAULT 1.0,
    rule_11_daily_max_loss REAL DEFAULT 0.0,
    rule_11_max_losses_per_day INTEGER DEFAULT 0,
    rule_11_trend_enabled INTEGER DEFAULT 0,
    rule_11_trend_ma INTEGER DEFAULT 50,
    rule_11_liquidity_enabled INTEGER DEFAULT 0,
    rule_11_min_avg_volume INTEGER DEFAULT 0,
    rule_11_min_tick_density INTEGER DEFAULT 3,
    rule_12_enabled INTEGER DEFAULT 0,
    rule_12_buy_threshold REAL DEFAULT 70.0,
    rule_12_sell_threshold REAL DEFAULT 60.0,
    rule_12_lookback_seconds INTEGER DEFAULT 10,
    rule_12_min_trades INTEGER DEFAULT 5,
    rule_12_weight_tape REAL DEFAULT 0.4,
    rule_12_weight_book REAL DEFAULT 0.2,
    rule_12_weight_trend REAL DEFAULT 0.2,
    rule_12_weight_momentum REAL DEFAULT 0.1,
    rule_12_weight_volume REAL DEFAULT 0.1,
    rule_12_weight_spread REAL DEFAULT 0.0,
    rule_12_weight_pullback REAL DEFAULT 0.0,
    rule_12_momentum_scale REAL DEFAULT 0.0005,
    rule_12_spread_tight_pct REAL DEFAULT 0.001,
    rsi_bollinger_trailing_stop_enabled INTEGER DEFAULT 0,
    rsi_bollinger_trailing_stop_pct REAL DEFAULT 0.1,
    rsi_bollinger_rsi_slope_enabled INTEGER DEFAULT 0,
    rsi_bollinger_graph_trend_enabled INTEGER DEFAULT 0,
    rsi_bollinger_graph_trend_lookback INTEGER DEFAULT 5,
    rsi_bollinger_graph_trend_threshold_pct REAL DEFAULT 0.0005,
    rule_13_enabled INTEGER DEFAULT 0,
    rule_13_lookback INTEGER DEFAULT 5,
    rule_13_slope_threshold_pct REAL DEFAULT 0.0005,
    rule_13_profit_pct REAL DEFAULT 0.2,
    rule_13_stop_pct REAL DEFAULT 0.4,
    rule_13_stop_enabled INTEGER DEFAULT 1,
    rule_13_only_profit INTEGER DEFAULT 0,
    rule_13_cooldown_minutes REAL DEFAULT 0.0,
    meta TEXT
)
"""

APP_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
"""

LIVE_ORDERS_SCHEMA = """
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

ORDER_BOOK_SNAPSHOTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS order_book_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    ticker          TEXT,
    trade_ref_id    TEXT,
    snapshot        TEXT
)
"""

ORDER_BOOK_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS order_book_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    ticker          TEXT,
    source          TEXT,
    levels          INTEGER,
    bids            TEXT,
    asks            TEXT
)
"""

TRADE_REPLAYS_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_replays (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_ref_id    TEXT UNIQUE,
    ticker          TEXT,
    start_ts        TEXT,
    end_ts          TEXT,
    bar_size        TEXT,
    bars            TEXT,
    order_book      TEXT,
    created_at      TEXT
)
"""
