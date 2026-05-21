"""WebSocket broadcaster for real-time updates."""

import asyncio
import base64
import json
import os
from datetime import datetime

from .manager import manager
from config.time_utils import current_timestamp


async def broadcaster_loop():
    """
    Background task that broadcasts status updates to all connected WebSocket clients.
    
    This function runs continuously and:
    - Collects status from all capture services
    - Gathers screenshots and encodes them as base64
    - Updates trader signals automatically
    - Broadcasts combined payload to all WebSocket clients
    - Cleans up old screenshots to save disk space
    """
    # Import here to avoid circular imports
    from services.capture_manager import manager_services
    from services.bot_registry import list_bots_by_hwnd
    from trading.simulator import trader
    from db.queries import get_app_settings
    from ibkr.order_book import (
        ensure_top_of_book,
        get_mid_price,
        get_price_history,
        get_price_volume_history,
        get_snapshot,
        get_top_of_book,
    )

    ibkr_last_prices = {}
    
    while True:
        try:
            signal_source = "screenshot"
            try:
                cfg = get_app_settings()
                signal_source = str(cfg.get("signal_source") or "screenshot").strip().lower()
                if signal_source not in ("screenshot", "ibkr"):
                    signal_source = "screenshot"
            except Exception:
                signal_source = "screenshot"

            # collect per-worker statuses and screenshots
            workers_payload = []
            try:
                for hwnd, svc in manager_services.iter_services():
                    try:
                        st = svc.get_status()
                    except Exception:
                        st = {}
                    last = (st.get('last_result') or {}) if isinstance(st, dict) else {}
                    image_b64 = None
                    image_mime = None
                    img_path = last.get('image_path')
                    if img_path and os.path.exists(img_path):
                        try:
                            with open(img_path, 'rb') as f:
                                image_b64 = base64.b64encode(f.read()).decode('ascii')
                            if str(img_path).lower().endswith(('.jpg', '.jpeg')):
                                image_mime = 'image/jpeg'
                            else:
                                image_mime = 'image/png'
                        except Exception:
                            image_b64 = None

                    # pull session bot settings for this hwnd (fallback to DB when empty)
                    bot_info = None
                    bot_list = []
                    try:
                        bot_list = list_bots_by_hwnd(int(hwnd))
                        bot_info = bot_list[0] if bot_list else None
                    except Exception:
                        bot_info = None
                        bot_list = []
                    if not bot_list:
                        try:
                            from db.queries import get_bot_db_entry
                            bot_db_row = get_bot_db_entry(int(hwnd))
                            if isinstance(bot_db_row, dict) and bot_db_row:
                                bot_info = bot_db_row
                                bot_list = [bot_db_row]
                        except Exception:
                            pass

                    # update trader auto signals if worker produced price/ticker
                    try:
                        raw_trend = last.get('trend') or ''
                        screenshot_trend = str(raw_trend).strip().lower()
                        if screenshot_trend in ('uptrend', 'bullish', 'rise', 'rising'):
                            screenshot_trend = 'up'
                        elif screenshot_trend in ('downtrend', 'bearish', 'fall', 'falling'):
                            screenshot_trend = 'down'

                        screenshot_price = last.get('price') or last.get('price_value') or None
                        screenshot_ticker = last.get('ticker') or None

                        rule_enabled = False
                        rule2_enabled = False
                        rule3_enabled = False
                        rule4_enabled = True
                        rule5_enabled = False
                        rule6_enabled = False
                        rule7_enabled = False
                        rule8_enabled = False
                        rule9_enabled = False
                        tp_amount = None
                        sl_amount = None
                        rule3_drop = None
                        rule4_start = None
                        rule4_end = None
                        rule4_days = None
                        rule5_down = None
                        rule5_reversal = None
                        rule5_scalp = None
                        rule6_down = None
                        rule6_profit = None
                        rule7_up = None
                        rule8_buy = None
                        rule8_sell = None
                        rule9_amount = None
                        rule9_flips = None
                        rule9_window = None
                        rsi_bollinger_enabled = False
                        rsi_bollinger_rsi_length = None
                        rsi_bollinger_rsi_threshold = None
                        rsi_bollinger_bb_length = None
                        rsi_bollinger_bb_stdev = None
                        rsi_bollinger_profit_pct = None
                        rsi_bollinger_stop_pct = None
                        rsi_bollinger_stop_enabled = None
                        rsi_bollinger_strict_enabled = None
                        rsi_bollinger_strict_bars = None
                        rsi_bollinger_bounce_enabled = None
                        rsi_bollinger_bounce_pct = None
                        rsi_bollinger_cooldown_enabled = None
                        rsi_bollinger_cooldown_minutes = None
                        rsi_bollinger_time_exit_enabled = None
                        rsi_bollinger_time_exit_minutes = None
                        rsi_bollinger_only_profit = None
                        rule_12_enabled = False
                        rule_12_buy_threshold = None
                        rule_12_sell_threshold = None
                        rule_12_min_trades = None
                        rule_12_lookback_seconds = None
                        rule_12_weight_tape = None
                        rule_12_weight_book = None
                        rule_12_weight_trend = None
                        rule_12_weight_momentum = None
                        rule_12_weight_volume = None
                        rule_12_weight_spread = None
                        rule_12_weight_pullback = None
                        rule_12_momentum_scale = None
                        rule_12_spread_tight_pct = None

                        for bot in bot_list:
                            try:
                                bot_ticker = bot.get('ticker') or screenshot_ticker
                                if not bot_ticker:
                                    continue
                                trading_paused = bool(bot.get('trading_paused'))
                                rule_enabled = bool(bot.get('rule_1_enabled'))
                                rule2_enabled = bool(bot.get('rule_2_enabled'))
                                rule3_enabled = bool(bot.get('rule_3_enabled'))
                                rule4_enabled = bool(bot.get('rule_4_enabled', 1))
                                rule4_start = bot.get('rule_4_start_time')
                                rule4_end = bot.get('rule_4_end_time')
                                rule4_days = bot.get('rule_4_days')
                                rule5_enabled = bool(bot.get('rule_5_enabled'))
                                rule6_enabled = bool(bot.get('rule_6_enabled'))
                                rule7_enabled = bool(bot.get('rule_7_enabled'))
                                rule8_enabled = bool(bot.get('rule_8_enabled'))
                                rule9_enabled = bool(bot.get('rule_9_enabled'))
                                tp_amount = bot.get('take_profit_amount')
                                sl_amount = bot.get('stop_loss_amount')
                                rule3_drop = bot.get('rule_3_drop_count')
                                rule5_down = bot.get('rule_5_down_minutes')
                                rule5_reversal = bot.get('rule_5_reversal_amount')
                                rule5_scalp = bot.get('rule_5_scalp_amount')
                                rule6_down = bot.get('rule_6_down_minutes')
                                rule6_profit = bot.get('rule_6_profit_amount')
                                rule7_up = bot.get('rule_7_up_minutes')
                                rule8_buy = bot.get('rule_8_buy_offset')
                                rule8_sell = bot.get('rule_8_sell_offset')
                                rule9_amount = bot.get('rule_9_amount')
                                rule9_flips = bot.get('rule_9_flips')
                                rule9_window = bot.get('rule_9_window_minutes')
                                rsi_bollinger_enabled = bool(bot.get('rsi_bollinger_enabled'))
                                rsi_bollinger_rsi_length = bot.get('rsi_bollinger_rsi_length')
                                rsi_bollinger_rsi_threshold = bot.get('rsi_bollinger_rsi_threshold')
                                rsi_bollinger_bb_length = bot.get('rsi_bollinger_bb_length')
                                rsi_bollinger_bb_stdev = bot.get('rsi_bollinger_bb_stdev')
                                rsi_bollinger_profit_pct = bot.get('rsi_bollinger_profit_pct')
                                rsi_bollinger_stop_pct = bot.get('rsi_bollinger_stop_pct')
                                rsi_bollinger_stop_enabled = bot.get('rsi_bollinger_stop_enabled')
                                rsi_bollinger_strict_enabled = bot.get('rsi_bollinger_strict_enabled')
                                rsi_bollinger_strict_bars = bot.get('rsi_bollinger_strict_bars')
                                rsi_bollinger_bounce_enabled = bot.get('rsi_bollinger_bounce_enabled')
                                rsi_bollinger_bounce_pct = bot.get('rsi_bollinger_bounce_pct')
                                rsi_bollinger_cooldown_enabled = bot.get('rsi_bollinger_cooldown_enabled')
                                rsi_bollinger_cooldown_minutes = bot.get('rsi_bollinger_cooldown_minutes')
                                rsi_bollinger_time_exit_enabled = bot.get('rsi_bollinger_time_exit_enabled')
                                rsi_bollinger_time_exit_minutes = bot.get('rsi_bollinger_time_exit_minutes')
                                rsi_bollinger_only_profit = bot.get('rsi_bollinger_only_profit')
                                rsi_bollinger_daily_max_loss = bot.get('rsi_bollinger_daily_max_loss')
                                rsi_bollinger_max_losses_per_day = bot.get('rsi_bollinger_max_losses_per_day')
                                rsi_bollinger_size_multiplier = bot.get('rsi_bollinger_size_multiplier')
                                rsi_bollinger_trend_enabled = bot.get('rsi_bollinger_trend_enabled')
                                rsi_bollinger_trend_ma = bot.get('rsi_bollinger_trend_ma')
                                rsi_bollinger_liquidity_enabled = bot.get('rsi_bollinger_liquidity_enabled')
                                rsi_bollinger_min_avg_volume = bot.get('rsi_bollinger_min_avg_volume')
                                rsi_bollinger_trailing_stop_enabled = bot.get('rsi_bollinger_trailing_stop_enabled')
                                rsi_bollinger_trailing_stop_pct = bot.get('rsi_bollinger_trailing_stop_pct')
                                rsi_bollinger_rsi_slope_enabled = bot.get('rsi_bollinger_rsi_slope_enabled')
                                # Rule 11 settings
                                rule_11_enabled = bool(bot.get('rule_11_enabled'))
                                rule_11_price_jump = bot.get('rule_11_price_jump')
                                rule_11_window_seconds = bot.get('rule_11_window_seconds')
                                rule_11_volume_threshold = bot.get('rule_11_volume_threshold')
                                rule_11_limit_offset = bot.get('rule_11_limit_offset')
                                rule_11_profit_pct = bot.get('rule_11_profit_pct')
                                rule_11_stop_pct = bot.get('rule_11_stop_pct')
                                rule_11_stop_enabled = bot.get('rule_11_stop_enabled')
                                rule_11_only_profit = bot.get('rule_11_only_profit')
                                rule_11_trailing_stop_enabled = bot.get('rule_11_trailing_stop_enabled')
                                rule_11_trailing_stop_pct = bot.get('rule_11_trailing_stop_pct')
                                rule_11_cooldown_enabled = bot.get('rule_11_cooldown_enabled')
                                rule_11_cooldown_minutes = bot.get('rule_11_cooldown_minutes')
                                rule_11_size_multiplier = bot.get('rule_11_size_multiplier')
                                rule_11_daily_max_loss = bot.get('rule_11_daily_max_loss')
                                rule_11_max_losses_per_day = bot.get('rule_11_max_losses_per_day')
                                rule_11_trend_enabled = bot.get('rule_11_trend_enabled')
                                rule_11_trend_ma = bot.get('rule_11_trend_ma')
                                rule_11_liquidity_enabled = bot.get('rule_11_liquidity_enabled')
                                rule_11_min_avg_volume = bot.get('rule_11_min_avg_volume')
                                rule_11_min_tick_density = bot.get('rule_11_min_tick_density')
                                rule_12_enabled = bool(bot.get('rule_12_enabled'))
                                rule_12_buy_threshold = bot.get('rule_12_buy_threshold')
                                rule_12_sell_threshold = bot.get('rule_12_sell_threshold')
                                rule_12_min_trades = bot.get('rule_12_min_trades')
                                rule_12_lookback_seconds = bot.get('rule_12_lookback_seconds')
                                rule_12_weight_tape = bot.get('rule_12_weight_tape')
                                rule_12_weight_book = bot.get('rule_12_weight_book')
                                rule_12_weight_trend = bot.get('rule_12_weight_trend')
                                rule_12_weight_momentum = bot.get('rule_12_weight_momentum')
                                rule_12_weight_volume = bot.get('rule_12_weight_volume')
                                rule_12_weight_spread = bot.get('rule_12_weight_spread')
                                rule_12_weight_pullback = bot.get('rule_12_weight_pullback')
                                rule_12_momentum_scale = bot.get('rule_12_momentum_scale')
                                rule_12_spread_tight_pct = bot.get('rule_12_spread_tight_pct')
                                default_trade = bot.get('default_trade_enabled', True)
                                if default_trade is None:
                                    default_trade = True
                                default_trade = bool(default_trade)
                                bot_id = bot.get('bot_id') or bot.get('id')
                                bot_name = bot.get('name')
                            except Exception:
                                continue

                            if trading_paused:
                                continue

                            signal_price = screenshot_price
                            signal_trend = screenshot_trend
                            rsi_bollinger_history = None
                            rsi_bollinger_avg_volume = None
                            rule_11_history = None
                            rule_12_price_history = None
                            rule_12_price_volume_history = None
                            rule_12_top_book = None
                            rule_12_depth_snapshot = None

                            if signal_source == 'ibkr':
                                ibkr_ticker = str(bot_ticker).strip().upper()
                                ibkr_price = None
                                try:
                                    await ensure_top_of_book(ibkr_ticker)
                                    ibkr_price = get_mid_price(ibkr_ticker)
                                except Exception:
                                    ibkr_price = None

                                if ibkr_price is None:
                                    continue

                                signal_price = ibkr_price
                                prev_price = ibkr_last_prices.get(ibkr_ticker)
                                if prev_price is not None:
                                    if ibkr_price > prev_price:
                                        signal_trend = 'up'
                                    elif ibkr_price < prev_price:
                                        signal_trend = 'down'
                                    else:
                                        signal_trend = ''
                                else:
                                    signal_trend = ''
                                ibkr_last_prices[ibkr_ticker] = ibkr_price
                                rsi_bollinger_history = get_price_history(ibkr_ticker)
                                try:
                                    lookback_s = int(rule_12_lookback_seconds) if rule_12_lookback_seconds is not None else 10
                                except Exception:
                                    lookback_s = 10
                                rule_12_price_history = rsi_bollinger_history
                                rule_12_price_volume_history = get_price_volume_history(ibkr_ticker, lookback_seconds=lookback_s)
                                rule_12_top_book = get_top_of_book(ibkr_ticker)
                                rule_12_depth_snapshot = get_snapshot(ibkr_ticker)
                                # price+volume history for Rule 11 and compute avg volume for liquidity checks
                                try:
                                    rule_11_history = get_price_volume_history(ibkr_ticker, lookback_seconds=int(rule_11_window_seconds) if rule_11_window_seconds else 5)
                                except Exception:
                                    rule_11_history = None
                                try:
                                    rsi_bollinger_avg_volume = None
                                    if isinstance(rule_11_history, list) and rule_11_history:
                                        vols = [float(x.get('volume') or 0.0) for x in rule_11_history]
                                        rsi_bollinger_avg_volume = sum(vols) / len(vols) if vols else None
                                except Exception:
                                    rsi_bollinger_avg_volume = None

                            if signal_price is None:
                                continue

                            # Rules 10/11/12 require live IBKR data — disable in screenshot mode
                            _ibkr_mode = signal_source == 'ibkr'

                            # Always call on_signal - Rule 1 now works alongside default logic
                            try:
                                # Use the monotonic _total_logged counter instead of
                                # len(trade_history) so we detect new trades even when
                                # the history list has just been compacted by the 1000-item
                                # cap (after trimming before==after by length, breaking detection).
                                before_total = trader.core._total_logged
                                trader.on_signal(
                                    signal_trend,
                                    signal_price,
                                    bot_ticker,
                                    auto=True,
                                    rule_1_enabled=rule_enabled,
                                    take_profit_amount=tp_amount,
                                    rule_2_enabled=rule2_enabled,
                                    stop_loss_amount=sl_amount,
                                    rule_3_enabled=rule3_enabled,
                                    rule_3_drop_count=rule3_drop,
                                    rule_4_enabled=rule4_enabled,
                                    rule_4_start_time=rule4_start,
                                    rule_4_end_time=rule4_end,
                                    rule_4_days=rule4_days,
                                    rule_5_enabled=rule5_enabled,
                                    rule_5_down_minutes=rule5_down,
                                    rule_5_reversal_amount=rule5_reversal,
                                    rule_5_scalp_amount=rule5_scalp,
                                    rule_6_enabled=rule6_enabled,
                                    rule_6_down_minutes=rule6_down,
                                    rule_6_profit_amount=rule6_profit,
                                    rule_7_enabled=rule7_enabled,
                                    rule_7_up_minutes=rule7_up,
                                    rule_8_enabled=rule8_enabled,
                                    rule_8_buy_offset=rule8_buy,
                                    rule_8_sell_offset=rule8_sell,
                                    rule_9_enabled=rule9_enabled,
                                    rule_9_amount=rule9_amount,
                                    rule_9_flips=rule9_flips,
                                    rule_9_window_minutes=rule9_window,
                                    rsi_bollinger_enabled=rsi_bollinger_enabled if _ibkr_mode else False,
                                    rsi_bollinger_rsi_length=rsi_bollinger_rsi_length,
                                    rsi_bollinger_rsi_threshold=rsi_bollinger_rsi_threshold,
                                    rsi_bollinger_bb_length=rsi_bollinger_bb_length,
                                    rsi_bollinger_bb_stdev=rsi_bollinger_bb_stdev,
                                    rsi_bollinger_profit_pct=rsi_bollinger_profit_pct,
                                    rsi_bollinger_stop_pct=rsi_bollinger_stop_pct,
                                    rsi_bollinger_stop_enabled=rsi_bollinger_stop_enabled,
                                    rsi_bollinger_strict_enabled=rsi_bollinger_strict_enabled,
                                    rsi_bollinger_strict_bars=rsi_bollinger_strict_bars,
                                    rsi_bollinger_bounce_enabled=rsi_bollinger_bounce_enabled,
                                    rsi_bollinger_bounce_pct=rsi_bollinger_bounce_pct,
                                    rsi_bollinger_cooldown_enabled=rsi_bollinger_cooldown_enabled,
                                    rsi_bollinger_cooldown_minutes=rsi_bollinger_cooldown_minutes,
                                    rsi_bollinger_time_exit_enabled=rsi_bollinger_time_exit_enabled,
                                    rsi_bollinger_time_exit_minutes=rsi_bollinger_time_exit_minutes,
                                    rsi_bollinger_only_profit=rsi_bollinger_only_profit,
                                    rsi_bollinger_price_history=rsi_bollinger_history,
                                    rsi_bollinger_daily_max_loss=rsi_bollinger_daily_max_loss,
                                    rsi_bollinger_max_losses_per_day=rsi_bollinger_max_losses_per_day,
                                    rsi_bollinger_size_multiplier=rsi_bollinger_size_multiplier,
                                    rsi_bollinger_trend_enabled=rsi_bollinger_trend_enabled,
                                    rsi_bollinger_trend_ma=rsi_bollinger_trend_ma,
                                    rsi_bollinger_liquidity_enabled=rsi_bollinger_liquidity_enabled,
                                    rsi_bollinger_min_avg_volume=rsi_bollinger_min_avg_volume,
                                    rsi_bollinger_avg_volume=rsi_bollinger_avg_volume,
                                    rsi_bollinger_trailing_stop_enabled=rsi_bollinger_trailing_stop_enabled,
                                    rsi_bollinger_trailing_stop_pct=rsi_bollinger_trailing_stop_pct,
                                    rsi_bollinger_rsi_slope_enabled=rsi_bollinger_rsi_slope_enabled,
                                    rule_11_enabled=rule_11_enabled if _ibkr_mode else False,
                                    rule_11_price_jump=rule_11_price_jump,
                                    rule_11_window_seconds=rule_11_window_seconds,
                                    rule_11_volume_threshold=rule_11_volume_threshold,
                                    rule_11_limit_offset=rule_11_limit_offset,
                                    rule_11_price_history=rule_11_history,
                                    rule_11_profit_pct=rule_11_profit_pct,
                                    rule_11_stop_pct=rule_11_stop_pct,
                                    rule_11_stop_enabled=rule_11_stop_enabled,
                                    rule_11_only_profit=rule_11_only_profit,
                                    rule_11_trailing_stop_enabled=rule_11_trailing_stop_enabled,
                                    rule_11_trailing_stop_pct=rule_11_trailing_stop_pct,
                                    rule_11_cooldown_enabled=rule_11_cooldown_enabled,
                                    rule_11_cooldown_minutes=rule_11_cooldown_minutes,
                                    rule_11_size_multiplier=rule_11_size_multiplier,
                                    rule_11_daily_max_loss=rule_11_daily_max_loss,
                                    rule_11_max_losses_per_day=rule_11_max_losses_per_day,
                                    rule_11_trend_enabled=rule_11_trend_enabled,
                                    rule_11_trend_ma=rule_11_trend_ma,
                                    rule_11_liquidity_enabled=rule_11_liquidity_enabled,
                                    rule_11_min_avg_volume=rule_11_min_avg_volume,
                                    rule_11_min_tick_density=rule_11_min_tick_density,
                                    rule_12_enabled=rule_12_enabled if _ibkr_mode else False,
                                    rule_12_buy_threshold=rule_12_buy_threshold,
                                    rule_12_sell_threshold=rule_12_sell_threshold,
                                    rule_12_min_trades=rule_12_min_trades,
                                    rule_12_price_history=rule_12_price_history,
                                    rule_12_price_volume_history=rule_12_price_volume_history,
                                    rule_12_top_book=rule_12_top_book,
                                    rule_12_depth_snapshot=rule_12_depth_snapshot,
                                    rule_12_weight_tape=rule_12_weight_tape,
                                    rule_12_weight_book=rule_12_weight_book,
                                    rule_12_weight_trend=rule_12_weight_trend,
                                    rule_12_weight_momentum=rule_12_weight_momentum,
                                    rule_12_weight_volume=rule_12_weight_volume,
                                    rule_12_weight_spread=rule_12_weight_spread,
                                    rule_12_weight_pullback=rule_12_weight_pullback,
                                    rule_12_momentum_scale=rule_12_momentum_scale,
                                    rule_12_spread_tight_pct=rule_12_spread_tight_pct,
                                    default_trade_enabled=default_trade,
                                    bot_id=bot_id,
                                    bot_name=bot_name,
                                )
                                after_total = trader.core._total_logged
                                new_trade_count = after_total - before_total
                                if new_trade_count > 0:
                                    try:
                                        for ev in trader.trade_history[-new_trade_count:]:
                                            if bot_id and ev.get('bot_id') != bot_id:
                                                continue
                                            direction = ev.get('direction')
                                            # Local screenshot/trade-recorder handler should never block
                                            # IBKR dispatch. Keep it isolated and best-effort.
                                            if hasattr(svc, 'handle_trade_event'):
                                                try:
                                                    svc.handle_trade_event(direction, ev.get('ticker'), ev.get('trade_id') or ev.get('ts'), ev.get('price'))
                                                except Exception:
                                                    pass
                                            # After a sell, the trade folder is complete — attach all
                                            # captured screenshots directly onto the trade record so
                                            # the frontend receives them in the same WS message.
                                            if direction == 'sell':
                                                try:
                                                    if hasattr(svc, 'trade_recorder'):
                                                        shots = svc.trade_recorder.get_last_screenshots()
                                                        if shots:
                                                            ev['screenshots'] = shots
                                                except Exception:
                                                    pass
                                            # Fire live IBKR order if bot has live trading enabled
                                            try:
                                                from db.queries import get_bot_db_entry
                                                bot_db_row = get_bot_db_entry(int(hwnd)) or {}
                                                bot_session_row = bot if isinstance(bot, dict) else {}

                                                # UI saves bot settings in session memory (/bots/upsert), while
                                                # DB can be stale. Merge with session taking precedence so IBKR
                                                # uses the latest order size/type selected by the user.
                                                bot_row_for_order = {**bot_db_row, **bot_session_row}
                                                if bot_id and not bot_row_for_order.get('bot_id'):
                                                    bot_row_for_order['bot_id'] = bot_id

                                                live_enabled_raw = bot_row_for_order.get('live_trading_enabled')
                                                if isinstance(live_enabled_raw, str):
                                                    live_enabled = live_enabled_raw.strip().lower() in ('1', 'true', 'yes', 'on')
                                                else:
                                                    live_enabled = bool(live_enabled_raw)

                                                if live_enabled:
                                                    from ibkr.order_router import handle_trade_event as ibkr_handle
                                                    # Create callback to get current signal for trend reversal detection
                                                    # Captures trader and current context
                                                    def make_signal_getter(t, tr):
                                                        def get_signal():
                                                            try:
                                                                # Check if trader has current position and trend
                                                                state = t.core.get_state(tr) if hasattr(t.core, 'get_state') else None
                                                                if state and hasattr(state, 'last_direction'):
                                                                    return state.last_direction
                                                                return None
                                                            except Exception:
                                                                return None
                                                        return get_signal
                                                    signal_getter = make_signal_getter(trader, bot_ticker)
                                                    asyncio.create_task(ibkr_handle(ev, bot_row_for_order, int(hwnd), signal_getter))
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                    except Exception:
                        pass

                    workers_payload.append({
                        'hwnd': int(hwnd),
                        'status': st or {},
                        'screenshot_b64': image_b64,
                        'screenshot_mime': image_mime,
                        'last_result': last,
                        'bot': bot_info,
                        'bots': bot_list,
                    })

                    # Keep only the most recent screenshot per-worker to save disk
                    try:
                        if hasattr(svc, 'capture') and hasattr(svc.capture, 'clear_screenshots'):
                            # Keep enough frames to fill the trade recorder pre-buffer
                            # (pre_count frames before trade + 1 current). If we only
                            # kept 1, pre-trade screenshots would be deleted before
                            # start_trade() could copy them into the trade folder.
                            try:
                                pre_count = svc.trade_recorder.pre_count if hasattr(svc, 'trade_recorder') else 5
                            except Exception:
                                pre_count = 5
                            svc.capture.clear_screenshots(keep_last_n=pre_count + 1)
                    except Exception:
                        pass
            except Exception:
                pass
            # Collect only NEW trades since last broadcast (delta — keeps payload tiny)
            new_trades = []
            try:
                new_trades = trader.core.get_new_trades()
            except Exception:
                new_trades = []

            payload = {
                'timestamp': current_timestamp(),
                'workers': workers_payload,
                'trade_summary': trader.summary(),
                'new_trades': new_trades,
                'signal_source': signal_source,
            }

            # IBKR live trading status (non-blocking — all reads from in-memory or DB)
            try:
                from ibkr.client import is_connected as ibkr_is_connected
                from ibkr.order_book import get_all_snapshots
                from db.queries import get_live_orders
                from ibkr.account import get_account_summary
                payload['ibkr_connected'] = ibkr_is_connected()
                payload['order_books'] = get_all_snapshots()
                payload['live_orders'] = get_live_orders(limit=None)
                payload['ibkr_account'] = await get_account_summary() if payload['ibkr_connected'] else {}
            except Exception:
                payload['ibkr_connected'] = False
                payload['order_books'] = {}
                payload['live_orders'] = []
                payload['ibkr_account'] = {}

            await manager.broadcast(json.dumps(payload))
        except Exception as e:
            print("Broadcaster loop error:", e)
        await asyncio.sleep(1)


__all__ = ["broadcaster_loop"]
