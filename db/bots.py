"""Bot database operations."""

import json
import sqlite3
from .connection import DB_PATH, DB_LOCK


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
                    "INSERT INTO bots (hwnd, name, ticker, total_pnl, open_direction, open_price, open_time, rule_1_enabled, rule_2_enabled, rule_3_enabled, rule_4_enabled, rule_5_enabled, rule_6_enabled, rule_7_enabled, rule_8_enabled, rule_9_enabled, take_profit_amount, stop_loss_amount, rule_3_drop_count, rule_5_down_minutes, rule_5_reversal_amount, rule_5_scalp_amount, rule_6_down_minutes, rule_6_profit_amount, rule_7_up_minutes, rule_8_buy_offset, rule_8_sell_offset, rule_9_amount, rule_9_flips, rule_9_window_minutes, rsi_bollinger_enabled, rsi_bollinger_rsi_length, rsi_bollinger_rsi_threshold, rsi_bollinger_bb_length, rsi_bollinger_bb_stdev, rsi_bollinger_profit_pct, rsi_bollinger_stop_pct, rsi_bollinger_stop_enabled, rsi_bollinger_strict_enabled, rsi_bollinger_strict_bars, rsi_bollinger_bounce_enabled, rsi_bollinger_bounce_pct, rsi_bollinger_cooldown_enabled, rsi_bollinger_cooldown_minutes, rsi_bollinger_time_exit_enabled, rsi_bollinger_time_exit_minutes, rsi_bollinger_only_profit, rsi_bollinger_daily_max_loss, rsi_bollinger_max_losses_per_day, rsi_bollinger_size_multiplier, rsi_bollinger_trend_enabled, rsi_bollinger_trend_ma, rsi_bollinger_liquidity_enabled, rsi_bollinger_min_avg_volume, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                        0,
                        14,
                        30.0,
                        20,
                        2.0,
                        0.2,
                        0.4,
                        1,
                        0,
                        2,
                        0,
                        0.05,
                        0,
                        5.0,
                        0,
                        5.0,
                        0,
                        0,
                        None,
                        0,
                        None,
                        0,
                        50,
                        0,
                        0,
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
    # Rule 11 settings (momentum tick breakout)
    rule_11_enabled = settings.get('rule_11_enabled')
    rule_11_price_jump = settings.get('rule_11_price_jump')
    rule_11_window_seconds = settings.get('rule_11_window_seconds')
    rule_11_volume_threshold = settings.get('rule_11_volume_threshold')
    rule_11_limit_offset = settings.get('rule_11_limit_offset')
    rule_11_profit_pct = settings.get('rule_11_profit_pct')
    rule_11_stop_pct = settings.get('rule_11_stop_pct')
    rule_11_stop_enabled = settings.get('rule_11_stop_enabled')
    rule_11_only_profit = settings.get('rule_11_only_profit')
    rule_11_trailing_stop_enabled = settings.get('rule_11_trailing_stop_enabled')
    rule_11_trailing_stop_pct = settings.get('rule_11_trailing_stop_pct')
    rule_11_cooldown_enabled = settings.get('rule_11_cooldown_enabled')
    rule_11_cooldown_minutes = settings.get('rule_11_cooldown_minutes')
    rule_11_size_multiplier = settings.get('rule_11_size_multiplier')
    rule_11_daily_max_loss = settings.get('rule_11_daily_max_loss')
    rule_11_max_losses_per_day = settings.get('rule_11_max_losses_per_day')
    rule_11_trend_enabled = settings.get('rule_11_trend_enabled')
    rule_11_trend_ma = settings.get('rule_11_trend_ma')
    rule_11_liquidity_enabled = settings.get('rule_11_liquidity_enabled')
    rule_11_min_avg_volume = settings.get('rule_11_min_avg_volume')
    rule_11_min_tick_density = settings.get('rule_11_min_tick_density')
    rsi_bollinger_enabled = settings.get('rsi_bollinger_enabled')
    rsi_bollinger_rsi_length = settings.get('rsi_bollinger_rsi_length')
    rsi_bollinger_rsi_threshold = settings.get('rsi_bollinger_rsi_threshold')
    rsi_bollinger_bb_length = settings.get('rsi_bollinger_bb_length')
    rsi_bollinger_bb_stdev = settings.get('rsi_bollinger_bb_stdev')
    rsi_bollinger_profit_pct = settings.get('rsi_bollinger_profit_pct')
    rsi_bollinger_stop_pct = settings.get('rsi_bollinger_stop_pct')
    rsi_bollinger_stop_enabled = settings.get('rsi_bollinger_stop_enabled')
    rsi_bollinger_strict_enabled = settings.get('rsi_bollinger_strict_enabled')
    rsi_bollinger_strict_bars = settings.get('rsi_bollinger_strict_bars')
    rsi_bollinger_bounce_enabled = settings.get('rsi_bollinger_bounce_enabled')
    rsi_bollinger_bounce_pct = settings.get('rsi_bollinger_bounce_pct')
    rsi_bollinger_cooldown_enabled = settings.get('rsi_bollinger_cooldown_enabled')
    rsi_bollinger_cooldown_minutes = settings.get('rsi_bollinger_cooldown_minutes')
    rsi_bollinger_time_exit_enabled = settings.get('rsi_bollinger_time_exit_enabled')
    rsi_bollinger_time_exit_minutes = settings.get('rsi_bollinger_time_exit_minutes')
    rsi_bollinger_only_profit = settings.get('rsi_bollinger_only_profit')
    rsi_bollinger_trailing_stop_enabled = settings.get('rsi_bollinger_trailing_stop_enabled')
    rsi_bollinger_trailing_stop_pct = settings.get('rsi_bollinger_trailing_stop_pct')
    rsi_bollinger_rsi_slope_enabled = settings.get('rsi_bollinger_rsi_slope_enabled')

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
    if rsi_bollinger_enabled is not None:
        rsi_bollinger_enabled = 1 if bool(rsi_bollinger_enabled) else 0
    if rsi_bollinger_rsi_length is not None:
        try:
            rsi_bollinger_rsi_length = int(rsi_bollinger_rsi_length)
        except Exception:
            rsi_bollinger_rsi_length = None
    if rsi_bollinger_rsi_threshold is not None:
        try:
            rsi_bollinger_rsi_threshold = float(rsi_bollinger_rsi_threshold)
        except Exception:
            rsi_bollinger_rsi_threshold = None
    if rsi_bollinger_bb_length is not None:
        try:
            rsi_bollinger_bb_length = int(rsi_bollinger_bb_length)
        except Exception:
            rsi_bollinger_bb_length = None
    if rsi_bollinger_bb_stdev is not None:
        try:
            rsi_bollinger_bb_stdev = float(rsi_bollinger_bb_stdev)
        except Exception:
            rsi_bollinger_bb_stdev = None
    if rsi_bollinger_profit_pct is not None:
        try:
            rsi_bollinger_profit_pct = float(rsi_bollinger_profit_pct)
        except Exception:
            rsi_bollinger_profit_pct = None
    if rsi_bollinger_stop_pct is not None:
        try:
            rsi_bollinger_stop_pct = float(rsi_bollinger_stop_pct)
        except Exception:
            rsi_bollinger_stop_pct = None
    if rsi_bollinger_stop_enabled is not None:
        rsi_bollinger_stop_enabled = 1 if bool(rsi_bollinger_stop_enabled) else 0
    if rsi_bollinger_strict_enabled is not None:
        rsi_bollinger_strict_enabled = 1 if bool(rsi_bollinger_strict_enabled) else 0
    if rsi_bollinger_strict_bars is not None:
        try:
            rsi_bollinger_strict_bars = int(rsi_bollinger_strict_bars)
        except Exception:
            rsi_bollinger_strict_bars = None
    if rsi_bollinger_bounce_enabled is not None:
        rsi_bollinger_bounce_enabled = 1 if bool(rsi_bollinger_bounce_enabled) else 0
    if rsi_bollinger_bounce_pct is not None:
        try:
            rsi_bollinger_bounce_pct = float(rsi_bollinger_bounce_pct)
        except Exception:
            rsi_bollinger_bounce_pct = None
    if rsi_bollinger_cooldown_enabled is not None:
        rsi_bollinger_cooldown_enabled = 1 if bool(rsi_bollinger_cooldown_enabled) else 0
    if rsi_bollinger_cooldown_minutes is not None:
        try:
            rsi_bollinger_cooldown_minutes = float(rsi_bollinger_cooldown_minutes)
        except Exception:
            rsi_bollinger_cooldown_minutes = None
    if rsi_bollinger_time_exit_enabled is not None:
        rsi_bollinger_time_exit_enabled = 1 if bool(rsi_bollinger_time_exit_enabled) else 0
    if rsi_bollinger_time_exit_minutes is not None:
        try:
            rsi_bollinger_time_exit_minutes = float(rsi_bollinger_time_exit_minutes)
        except Exception:
            rsi_bollinger_time_exit_minutes = None
    if rsi_bollinger_only_profit is not None:
        rsi_bollinger_only_profit = 1 if bool(rsi_bollinger_only_profit) else 0
    if rsi_bollinger_trailing_stop_enabled is not None:
        rsi_bollinger_trailing_stop_enabled = 1 if bool(rsi_bollinger_trailing_stop_enabled) else 0
    if rsi_bollinger_trailing_stop_pct is not None:
        try:
            rsi_bollinger_trailing_stop_pct = float(rsi_bollinger_trailing_stop_pct)
        except Exception:
            rsi_bollinger_trailing_stop_pct = None
    if rsi_bollinger_rsi_slope_enabled is not None:
        rsi_bollinger_rsi_slope_enabled = 1 if bool(rsi_bollinger_rsi_slope_enabled) else 0

    # New Rule10 safety settings
    rsi_bollinger_daily_max_loss = settings.get('rsi_bollinger_daily_max_loss')
    rsi_bollinger_max_losses_per_day = settings.get('rsi_bollinger_max_losses_per_day')
    rsi_bollinger_size_multiplier = settings.get('rsi_bollinger_size_multiplier')
    rsi_bollinger_trend_enabled = settings.get('rsi_bollinger_trend_enabled')
    rsi_bollinger_trend_ma = settings.get('rsi_bollinger_trend_ma')
    rsi_bollinger_liquidity_enabled = settings.get('rsi_bollinger_liquidity_enabled')
    rsi_bollinger_min_avg_volume = settings.get('rsi_bollinger_min_avg_volume')

    # Normalize new Rule10 safety fields
    if rsi_bollinger_daily_max_loss is not None:
        try:
            rsi_bollinger_daily_max_loss = float(rsi_bollinger_daily_max_loss)
        except Exception:
            rsi_bollinger_daily_max_loss = None
    if rsi_bollinger_max_losses_per_day is not None:
        try:
            rsi_bollinger_max_losses_per_day = int(rsi_bollinger_max_losses_per_day)
        except Exception:
            rsi_bollinger_max_losses_per_day = None
    if rsi_bollinger_size_multiplier is not None:
        try:
            rsi_bollinger_size_multiplier = float(rsi_bollinger_size_multiplier)
        except Exception:
            rsi_bollinger_size_multiplier = None
    if rsi_bollinger_trend_enabled is not None:
        rsi_bollinger_trend_enabled = 1 if bool(rsi_bollinger_trend_enabled) else 0
    if rsi_bollinger_trend_ma is not None:
        try:
            rsi_bollinger_trend_ma = int(rsi_bollinger_trend_ma)
        except Exception:
            rsi_bollinger_trend_ma = None
    if rsi_bollinger_liquidity_enabled is not None:
        rsi_bollinger_liquidity_enabled = 1 if bool(rsi_bollinger_liquidity_enabled) else 0
    if rsi_bollinger_min_avg_volume is not None:
        try:
            rsi_bollinger_min_avg_volume = int(rsi_bollinger_min_avg_volume)
        except Exception:
            rsi_bollinger_min_avg_volume = None

    # Normalize Rule 11
    if rule_11_enabled is not None:
        rule_11_enabled = 1 if bool(rule_11_enabled) else 0
    if rule_11_price_jump is not None:
        try:
            rule_11_price_jump = float(rule_11_price_jump)
        except Exception:
            rule_11_price_jump = None
    if rule_11_window_seconds is not None:
        try:
            rule_11_window_seconds = int(rule_11_window_seconds)
        except Exception:
            rule_11_window_seconds = None
    if rule_11_volume_threshold is not None:
        try:
            rule_11_volume_threshold = int(rule_11_volume_threshold)
        except Exception:
            rule_11_volume_threshold = None
    if rule_11_limit_offset is not None:
        try:
            rule_11_limit_offset = float(rule_11_limit_offset)
        except Exception:
            rule_11_limit_offset = None
    if rule_11_profit_pct is not None:
        try:
            rule_11_profit_pct = float(rule_11_profit_pct)
        except Exception:
            rule_11_profit_pct = None
    if rule_11_stop_pct is not None:
        try:
            rule_11_stop_pct = float(rule_11_stop_pct)
        except Exception:
            rule_11_stop_pct = None
    if rule_11_stop_enabled is not None:
        rule_11_stop_enabled = 1 if bool(rule_11_stop_enabled) else 0
    if rule_11_only_profit is not None:
        rule_11_only_profit = 1 if bool(rule_11_only_profit) else 0
    if rule_11_trailing_stop_enabled is not None:
        rule_11_trailing_stop_enabled = 1 if bool(rule_11_trailing_stop_enabled) else 0
    if rule_11_trailing_stop_pct is not None:
        try:
            rule_11_trailing_stop_pct = float(rule_11_trailing_stop_pct)
        except Exception:
            rule_11_trailing_stop_pct = None
    if rule_11_cooldown_enabled is not None:
        rule_11_cooldown_enabled = 1 if bool(rule_11_cooldown_enabled) else 0
    if rule_11_cooldown_minutes is not None:
        try:
            rule_11_cooldown_minutes = float(rule_11_cooldown_minutes)
        except Exception:
            rule_11_cooldown_minutes = None
    if rule_11_size_multiplier is not None:
        try:
            rule_11_size_multiplier = float(rule_11_size_multiplier)
        except Exception:
            rule_11_size_multiplier = None
    if rule_11_daily_max_loss is not None:
        try:
            rule_11_daily_max_loss = float(rule_11_daily_max_loss)
        except Exception:
            rule_11_daily_max_loss = None
    if rule_11_max_losses_per_day is not None:
        try:
            rule_11_max_losses_per_day = int(rule_11_max_losses_per_day)
        except Exception:
            rule_11_max_losses_per_day = None
    if rule_11_trend_enabled is not None:
        rule_11_trend_enabled = 1 if bool(rule_11_trend_enabled) else 0
    if rule_11_trend_ma is not None:
        try:
            rule_11_trend_ma = int(rule_11_trend_ma)
        except Exception:
            rule_11_trend_ma = None
    if rule_11_liquidity_enabled is not None:
        rule_11_liquidity_enabled = 1 if bool(rule_11_liquidity_enabled) else 0
    if rule_11_min_avg_volume is not None:
        try:
            rule_11_min_avg_volume = int(rule_11_min_avg_volume)
        except Exception:
            rule_11_min_avg_volume = None
    if rule_11_min_tick_density is not None:
        try:
            rule_11_min_tick_density = int(rule_11_min_tick_density)
        except Exception:
            rule_11_min_tick_density = None

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
                    rsi_bollinger_enabled = COALESCE(?, rsi_bollinger_enabled),
                    rsi_bollinger_rsi_length = COALESCE(?, rsi_bollinger_rsi_length),
                    rsi_bollinger_rsi_threshold = COALESCE(?, rsi_bollinger_rsi_threshold),
                    rsi_bollinger_bb_length = COALESCE(?, rsi_bollinger_bb_length),
                    rsi_bollinger_bb_stdev = COALESCE(?, rsi_bollinger_bb_stdev),
                    rsi_bollinger_profit_pct = COALESCE(?, rsi_bollinger_profit_pct),
                    rsi_bollinger_stop_pct = COALESCE(?, rsi_bollinger_stop_pct),
                    rsi_bollinger_stop_enabled = COALESCE(?, rsi_bollinger_stop_enabled),
                    rsi_bollinger_strict_enabled = COALESCE(?, rsi_bollinger_strict_enabled),
                    rsi_bollinger_strict_bars = COALESCE(?, rsi_bollinger_strict_bars),
                    rsi_bollinger_bounce_enabled = COALESCE(?, rsi_bollinger_bounce_enabled),
                    rsi_bollinger_bounce_pct = COALESCE(?, rsi_bollinger_bounce_pct),
                    rsi_bollinger_cooldown_enabled = COALESCE(?, rsi_bollinger_cooldown_enabled),
                    rsi_bollinger_cooldown_minutes = COALESCE(?, rsi_bollinger_cooldown_minutes),
                    rsi_bollinger_time_exit_enabled = COALESCE(?, rsi_bollinger_time_exit_enabled),
                    rsi_bollinger_time_exit_minutes = COALESCE(?, rsi_bollinger_time_exit_minutes),
                    rsi_bollinger_only_profit = COALESCE(?, rsi_bollinger_only_profit),
                    rsi_bollinger_daily_max_loss = COALESCE(?, rsi_bollinger_daily_max_loss),
                    rsi_bollinger_max_losses_per_day = COALESCE(?, rsi_bollinger_max_losses_per_day),
                    rsi_bollinger_size_multiplier = COALESCE(?, rsi_bollinger_size_multiplier),
                    rsi_bollinger_trend_enabled = COALESCE(?, rsi_bollinger_trend_enabled),
                    rsi_bollinger_trend_ma = COALESCE(?, rsi_bollinger_trend_ma),
                    rsi_bollinger_liquidity_enabled = COALESCE(?, rsi_bollinger_liquidity_enabled),
                    rsi_bollinger_min_avg_volume = COALESCE(?, rsi_bollinger_min_avg_volume),
                    rsi_bollinger_trailing_stop_enabled = COALESCE(?, rsi_bollinger_trailing_stop_enabled),
                    rsi_bollinger_trailing_stop_pct = COALESCE(?, rsi_bollinger_trailing_stop_pct),
                    rsi_bollinger_rsi_slope_enabled = COALESCE(?, rsi_bollinger_rsi_slope_enabled),
                    rule_11_enabled = COALESCE(?, rule_11_enabled),
                    rule_11_price_jump = COALESCE(?, rule_11_price_jump),
                    rule_11_window_seconds = COALESCE(?, rule_11_window_seconds),
                    rule_11_volume_threshold = COALESCE(?, rule_11_volume_threshold),
                    rule_11_limit_offset = COALESCE(?, rule_11_limit_offset),
                    rule_11_profit_pct = COALESCE(?, rule_11_profit_pct),
                    rule_11_stop_pct = COALESCE(?, rule_11_stop_pct),
                    rule_11_stop_enabled = COALESCE(?, rule_11_stop_enabled),
                    rule_11_only_profit = COALESCE(?, rule_11_only_profit),
                    rule_11_trailing_stop_enabled = COALESCE(?, rule_11_trailing_stop_enabled),
                    rule_11_trailing_stop_pct = COALESCE(?, rule_11_trailing_stop_pct),
                    rule_11_cooldown_enabled = COALESCE(?, rule_11_cooldown_enabled),
                    rule_11_cooldown_minutes = COALESCE(?, rule_11_cooldown_minutes),
                    rule_11_size_multiplier = COALESCE(?, rule_11_size_multiplier),
                    rule_11_daily_max_loss = COALESCE(?, rule_11_daily_max_loss),
                    rule_11_max_losses_per_day = COALESCE(?, rule_11_max_losses_per_day),
                    rule_11_trend_enabled = COALESCE(?, rule_11_trend_enabled),
                    rule_11_trend_ma = COALESCE(?, rule_11_trend_ma),
                    rule_11_liquidity_enabled = COALESCE(?, rule_11_liquidity_enabled),
                    rule_11_min_avg_volume = COALESCE(?, rule_11_min_avg_volume),
                    rule_11_min_tick_density = COALESCE(?, rule_11_min_tick_density),
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
                    rsi_bollinger_enabled,
                    rsi_bollinger_rsi_length,
                    rsi_bollinger_rsi_threshold,
                    rsi_bollinger_bb_length,
                    rsi_bollinger_bb_stdev,
                    rsi_bollinger_profit_pct,
                    rsi_bollinger_stop_pct,
                    rsi_bollinger_stop_enabled,
                    rsi_bollinger_strict_enabled,
                    rsi_bollinger_strict_bars,
                    rsi_bollinger_bounce_enabled,
                    rsi_bollinger_bounce_pct,
                    rsi_bollinger_cooldown_enabled,
                    rsi_bollinger_cooldown_minutes,
                    rsi_bollinger_time_exit_enabled,
                    rsi_bollinger_time_exit_minutes,
                    rsi_bollinger_only_profit,
                    rsi_bollinger_daily_max_loss,
                    rsi_bollinger_max_losses_per_day,
                    rsi_bollinger_size_multiplier,
                    rsi_bollinger_trend_enabled,
                    rsi_bollinger_trend_ma,
                    rsi_bollinger_liquidity_enabled,
                    rsi_bollinger_min_avg_volume,
                    rsi_bollinger_trailing_stop_enabled,
                    rsi_bollinger_trailing_stop_pct,
                    rsi_bollinger_rsi_slope_enabled,
                    rule_11_enabled,
                    rule_11_price_jump,
                    rule_11_window_seconds,
                    rule_11_volume_threshold,
                    rule_11_limit_offset,
                    rule_11_profit_pct,
                    rule_11_stop_pct,
                    rule_11_stop_enabled,
                    rule_11_only_profit,
                    rule_11_trailing_stop_enabled,
                    rule_11_trailing_stop_pct,
                    rule_11_cooldown_enabled,
                    rule_11_cooldown_minutes,
                    rule_11_size_multiplier,
                    rule_11_daily_max_loss,
                    rule_11_max_losses_per_day,
                    rule_11_trend_enabled,
                    rule_11_trend_ma,
                    rule_11_liquidity_enabled,
                    rule_11_min_avg_volume,
                    rule_11_min_tick_density,
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
                INSERT INTO bots (hwnd, name, ticker, total_pnl, open_direction, open_price, open_time, rule_1_enabled, rule_2_enabled, rule_3_enabled, rule_4_enabled, rule_5_enabled, rule_6_enabled, rule_7_enabled, rule_8_enabled, rule_9_enabled, take_profit_amount, stop_loss_amount, rule_3_drop_count, rule_5_down_minutes, rule_5_reversal_amount, rule_5_scalp_amount, rule_6_down_minutes, rule_6_profit_amount, rule_7_up_minutes, rule_8_buy_offset, rule_8_sell_offset, rule_9_amount, rule_9_flips, rule_9_window_minutes, rsi_bollinger_enabled, rsi_bollinger_rsi_length, rsi_bollinger_rsi_threshold, rsi_bollinger_bb_length, rsi_bollinger_bb_stdev, rsi_bollinger_profit_pct, rsi_bollinger_stop_pct, rsi_bollinger_stop_enabled, rsi_bollinger_strict_enabled, rsi_bollinger_strict_bars, rsi_bollinger_bounce_enabled, rsi_bollinger_bounce_pct, rsi_bollinger_cooldown_enabled, rsi_bollinger_cooldown_minutes, rsi_bollinger_time_exit_enabled, rsi_bollinger_time_exit_minutes, rsi_bollinger_only_profit, rsi_bollinger_daily_max_loss, rsi_bollinger_max_losses_per_day, rsi_bollinger_size_multiplier, rsi_bollinger_trend_enabled, rsi_bollinger_trend_ma, rsi_bollinger_liquidity_enabled, rsi_bollinger_min_avg_volume, rsi_bollinger_trailing_stop_enabled, rsi_bollinger_trailing_stop_pct, rsi_bollinger_rsi_slope_enabled, rule_11_enabled, rule_11_price_jump, rule_11_window_seconds, rule_11_volume_threshold, rule_11_limit_offset, rule_11_profit_pct, rule_11_stop_pct, rule_11_stop_enabled, rule_11_only_profit, rule_11_trailing_stop_enabled, rule_11_trailing_stop_pct, rule_11_cooldown_enabled, rule_11_cooldown_minutes, rule_11_size_multiplier, rule_11_daily_max_loss, rule_11_max_losses_per_day, rule_11_trend_enabled, rule_11_trend_ma, rule_11_liquidity_enabled, rule_11_min_avg_volume, rule_11_min_tick_density, live_trading_enabled, order_size_type, order_size_value, buy_order_type, sell_order_type, retry_delay_secs, max_retries, min_trade_dollars, validate_conditions_on_retry, default_trade_enabled, meta)
                VALUES (?, ?, ?, NULL, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    rsi_bollinger_enabled if rsi_bollinger_enabled is not None else 0,
                    rsi_bollinger_rsi_length if rsi_bollinger_rsi_length is not None else 14,
                    rsi_bollinger_rsi_threshold if rsi_bollinger_rsi_threshold is not None else 30.0,
                    rsi_bollinger_bb_length if rsi_bollinger_bb_length is not None else 20,
                    rsi_bollinger_bb_stdev if rsi_bollinger_bb_stdev is not None else 2.0,
                    rsi_bollinger_profit_pct if rsi_bollinger_profit_pct is not None else 0.2,
                    rsi_bollinger_stop_pct if rsi_bollinger_stop_pct is not None else 0.4,
                    rsi_bollinger_stop_enabled if rsi_bollinger_stop_enabled is not None else 1,
                    rsi_bollinger_strict_enabled if rsi_bollinger_strict_enabled is not None else 0,
                    rsi_bollinger_strict_bars if rsi_bollinger_strict_bars is not None else 2,
                    rsi_bollinger_bounce_enabled if rsi_bollinger_bounce_enabled is not None else 0,
                    rsi_bollinger_bounce_pct if rsi_bollinger_bounce_pct is not None else 0.05,
                    rsi_bollinger_cooldown_enabled if rsi_bollinger_cooldown_enabled is not None else 0,
                    rsi_bollinger_cooldown_minutes if rsi_bollinger_cooldown_minutes is not None else 5.0,
                    rsi_bollinger_time_exit_enabled if rsi_bollinger_time_exit_enabled is not None else 0,
                    rsi_bollinger_time_exit_minutes if rsi_bollinger_time_exit_minutes is not None else 5.0,
                    rsi_bollinger_only_profit if rsi_bollinger_only_profit is not None else 0,
                    rsi_bollinger_daily_max_loss if rsi_bollinger_daily_max_loss is not None else 0.0,
                    rsi_bollinger_max_losses_per_day if rsi_bollinger_max_losses_per_day is not None else 0,
                    rsi_bollinger_size_multiplier if rsi_bollinger_size_multiplier is not None else 1.0,
                    rsi_bollinger_trend_enabled if rsi_bollinger_trend_enabled is not None else 0,
                    rsi_bollinger_trend_ma if rsi_bollinger_trend_ma is not None else 50,
                    rsi_bollinger_liquidity_enabled if rsi_bollinger_liquidity_enabled is not None else 0,
                    rsi_bollinger_min_avg_volume if rsi_bollinger_min_avg_volume is not None else 0,
                    rsi_bollinger_trailing_stop_enabled if rsi_bollinger_trailing_stop_enabled is not None else 0,
                    rsi_bollinger_trailing_stop_pct if rsi_bollinger_trailing_stop_pct is not None else 0.1,
                    rsi_bollinger_rsi_slope_enabled if rsi_bollinger_rsi_slope_enabled is not None else 0,
                    rule_11_enabled if rule_11_enabled is not None else 0,
                    rule_11_price_jump if rule_11_price_jump is not None else 0.03,
                    rule_11_window_seconds if rule_11_window_seconds is not None else 5,
                    rule_11_volume_threshold if rule_11_volume_threshold is not None else 5000,
                    rule_11_limit_offset if rule_11_limit_offset is not None else 0.01,
                    rule_11_profit_pct if rule_11_profit_pct is not None else 0.2,
                    rule_11_stop_pct if rule_11_stop_pct is not None else 0.4,
                    rule_11_stop_enabled if rule_11_stop_enabled is not None else 1,
                    rule_11_only_profit if rule_11_only_profit is not None else 0,
                    rule_11_trailing_stop_enabled if rule_11_trailing_stop_enabled is not None else 0,
                    rule_11_trailing_stop_pct if rule_11_trailing_stop_pct is not None else 0.1,
                    rule_11_cooldown_enabled if rule_11_cooldown_enabled is not None else 0,
                    rule_11_cooldown_minutes if rule_11_cooldown_minutes is not None else 5.0,
                    rule_11_size_multiplier if rule_11_size_multiplier is not None else 1.0,
                    rule_11_daily_max_loss if rule_11_daily_max_loss is not None else 0.0,
                    rule_11_max_losses_per_day if rule_11_max_losses_per_day is not None else 0,
                    rule_11_trend_enabled if rule_11_trend_enabled is not None else 0,
                    rule_11_trend_ma if rule_11_trend_ma is not None else 50,
                    rule_11_liquidity_enabled if rule_11_liquidity_enabled is not None else 0,
                    rule_11_min_avg_volume if rule_11_min_avg_volume is not None else 0,
                    rule_11_min_tick_density if rule_11_min_tick_density is not None else 3,
                    live_trading_enabled if live_trading_enabled is not None else 0,
                    order_size_type if order_size_type is not None else 'fixed',
                    order_size_value if order_size_value is not None else 1.0,
                    buy_order_type if buy_order_type is not None else 'limit',
                    sell_order_type if sell_order_type is not None else 'limit',
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
    "count_live_orders",
    "get_last_buy_order",
    "get_last_order_for_hwnd_ticker",
]
