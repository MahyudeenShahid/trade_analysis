"""WebSocket broadcaster loop coordinator."""

import asyncio
import json
import logging
from .manager import manager
from config.time_utils import current_timestamp
from .broadcaster_worker import build_workers_payload
from .broadcaster_r14 import evaluate_r14_for_bot, evaluate_standalone_r14, evaluate_r15_for_bot, evaluate_standalone_r15

logger = logging.getLogger(__name__)


async def broadcaster_loop():
    """
    Background task that broadcasts status updates to all connected WebSocket clients.

    - Collects workers status and screenshot payloads
    - Evaluates Rule 14 triggers
    - Evaluates rules on the TradeSimulator engine
    - Manages live IBKR order dispatches
    - Broadcasts the combined state to Web UIs
    """
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
    ibkr_live_state: dict = {}

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
                cfg = {}

            # Step 1: Collect workers status and screenshots payload
            raw_workers = build_workers_payload()
            workers_payload = []

            # Step 2: Process signals and evaluate rules per active worker
            for item in raw_workers:
                hwnd = item['hwnd']
                st = item['status']
                image_b64 = item['screenshot_b64']
                image_mime = item['screenshot_mime']
                last = item['last_result']
                bot_info = item['bot']
                bot_list = item['bots']
                svc = item['svc']

                # Add serializable entries to output payload
                workers_payload.append({
                    'hwnd': hwnd,
                    'status': st,
                    'screenshot_b64': image_b64,
                    'screenshot_mime': image_mime,
                    'last_result': last,
                    'bot': bot_info,
                    'bots': bot_list,
                })

                # Extract screenshot-based trends and prices
                raw_trend = last.get('trend') or ''
                screenshot_trend = str(raw_trend).strip().lower()
                if screenshot_trend in ('uptrend', 'bullish', 'rise', 'rising'):
                    screenshot_trend = 'up'
                elif screenshot_trend in ('downtrend', 'bearish', 'fall', 'falling'):
                    screenshot_trend = 'down'

                screenshot_price = last.get('price') or last.get('price_value') or None
                screenshot_ticker = last.get('ticker') or None

                for bot in bot_list:
                    bot_ticker = bot.get('ticker') or screenshot_ticker
                    if not bot_ticker:
                        continue
                    if bool(bot.get('trading_paused')):
                        continue

                    bot_id = bot.get('bot_id') or bot.get('id')
                    bot_name = bot.get('name')

                    signal_price = screenshot_price
                    signal_trend = screenshot_trend
                    rsi_bollinger_history = None
                    rsi_bollinger_avg_volume = None
                    rule_11_history = None
                    rule_12_price_history = None
                    rule_12_price_volume_history = None
                    rule_12_top_book = None
                    rule_12_depth_snapshot = None

                    # If ibkr is the signal source, pull live data from TWS/Gateway
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
                        ibkr_last_prices[ibkr_ticker] = ibkr_price
                        rsi_bollinger_history = get_price_history(ibkr_ticker)

                        # Slope-based trend detection
                        try:
                            from trading.rule13 import _compute_slope_pct
                            _trend_lookback = int(cfg.get('ibkr_trend_lookback') or 5)
                            _trend_threshold = float(cfg.get('ibkr_trend_threshold_pct') or 0.0003)
                            _prices = rsi_bollinger_history or []
                            _slope = _compute_slope_pct(_prices, _trend_lookback)
                            if _slope is None:
                                signal_trend = ''
                            elif _slope > _trend_threshold:
                                signal_trend = 'up'
                            elif _slope < -_trend_threshold:
                                signal_trend = 'down'
                            else:
                                signal_trend = ''
                        except Exception:
                            # Fallback: single-tick price delta
                            _prev = ibkr_last_prices.get(ibkr_ticker)
                            if _prev is not None:
                                if ibkr_price > _prev:
                                    signal_trend = 'up'
                                elif ibkr_price < _prev:
                                    signal_trend = 'down'
                                else:
                                    signal_trend = ''
                            else:
                                signal_trend = ''

                        try:
                            lookback_s = int(bot.get('rule_12_lookback_seconds') or 10)
                        except Exception:
                            lookback_s = 10
                        rule_12_price_history = rsi_bollinger_history
                        rule_12_price_volume_history = get_price_volume_history(ibkr_ticker, lookback_seconds=lookback_s)
                        rule_12_top_book = get_top_of_book(ibkr_ticker)
                        rule_12_depth_snapshot = get_snapshot(ibkr_ticker)

                        try:
                            rule_11_history = get_price_volume_history(ibkr_ticker, lookback_seconds=int(bot.get('rule_11_window_seconds') or 5))
                        except Exception:
                            rule_11_history = None
                        try:
                            rsi_bollinger_avg_volume = None
                            if isinstance(rule_11_history, list) and rule_11_history:
                                vols = [float(x.get('volume') or 0.0) for x in rule_11_history]
                                rsi_bollinger_avg_volume = sum(vols) / len(vols) if vols else None
                        except Exception:
                            rsi_bollinger_avg_volume = None

                        try:
                            _tick_prices = list(rsi_bollinger_history or [])[-60:]
                            ibkr_live_state[ibkr_ticker] = {
                                'ticker': ibkr_ticker,
                                'prices': _tick_prices,
                                'trend': signal_trend,
                                'price': signal_price,
                                'last_signal': ibkr_live_state.get(ibkr_ticker, {}).get('last_signal'),
                            }
                        except Exception:
                            pass

                    # Rule 14 Evaluation
                    r14_fired = False
                    try:
                        r14_fired = evaluate_r14_for_bot(hwnd, bot, bot_id, signal_price, ibkr_live_state)
                    except Exception as re:
                        logger.warning(f"[R14 evaluation error] {re}")

                    if r14_fired:
                        # Skip other rules if R14 trade was placed
                        continue

                    # Rule 15 Evaluation (main chart slope scalper)
                    r15_fired = False
                    try:
                        r15_fired = evaluate_r15_for_bot(hwnd, bot, bot_id, signal_price, ibkr_live_state, signal_trend)
                    except Exception as r15e:
                        logger.warning(f"[R15 evaluation error] {r15e}")

                    if r15_fired:
                        # Skip other rules if R15 trade was placed
                        continue

                    if signal_price is None:
                        continue

                    _ibkr_mode = signal_source == 'ibkr'

                    # Process simulator rules (Rules 1-12)
                    try:
                        before_total = trader.core._total_logged
                        trader.on_signal(
                            signal_trend,
                            signal_price,
                            bot_ticker,
                            auto=True,
                            rule_1_enabled=bool(bot.get('rule_1_enabled')),
                            take_profit_amount=bot.get('take_profit_amount'),
                            rule_2_enabled=bool(bot.get('rule_2_enabled')),
                            stop_loss_amount=bot.get('stop_loss_amount'),
                            rule_3_enabled=bool(bot.get('rule_3_enabled')),
                            rule_3_drop_count=bot.get('rule_3_drop_count'),
                            rule_4_enabled=bool(bot.get('rule_4_enabled', 1)),
                            rule_4_start_time=bot.get('rule_4_start_time'),
                            rule_4_end_time=bot.get('rule_4_end_time'),
                            rule_4_days=bot.get('rule_4_days'),
                            rule_5_enabled=bool(bot.get('rule_5_enabled')),
                            rule_5_down_minutes=bot.get('rule_5_down_minutes'),
                            rule_5_reversal_amount=bot.get('rule_5_reversal_amount'),
                            rule_5_scalp_amount=bot.get('rule_5_scalp_amount'),
                            rule_6_enabled=bool(bot.get('rule_6_enabled')),
                            rule_6_down_minutes=bot.get('rule_6_down_minutes'),
                            rule_6_profit_amount=bot.get('rule_6_profit_amount'),
                            rule_7_enabled=bool(bot.get('rule_7_enabled')),
                            rule_7_up_minutes=bot.get('rule_7_up_minutes'),
                            rule_8_enabled=bool(bot.get('rule_8_enabled')),
                            rule_8_buy_offset=bot.get('rule_8_buy_offset'),
                            rule_8_sell_offset=bot.get('rule_8_sell_offset'),
                            rule_9_enabled=bool(bot.get('rule_9_enabled')),
                            rule_9_amount=bot.get('rule_9_amount'),
                            rule_9_flips=bot.get('rule_9_flips'),
                            rule_9_window_minutes=bot.get('rule_9_window_minutes'),
                            rsi_bollinger_enabled=bool(bot.get('rsi_bollinger_enabled')) if _ibkr_mode else False,
                            rsi_bollinger_rsi_length=bot.get('rsi_bollinger_rsi_length'),
                            rsi_bollinger_rsi_threshold=bot.get('rsi_bollinger_rsi_threshold'),
                            rsi_bollinger_bb_length=bot.get('rsi_bollinger_bb_length'),
                            rsi_bollinger_bb_stdev=bot.get('rsi_bollinger_bb_stdev'),
                            rsi_bollinger_profit_pct=bot.get('rsi_bollinger_profit_pct'),
                            rsi_bollinger_stop_pct=bot.get('rsi_bollinger_stop_pct'),
                            rsi_bollinger_stop_enabled=bot.get('rsi_bollinger_stop_enabled'),
                            rsi_bollinger_strict_enabled=bot.get('rsi_bollinger_strict_enabled'),
                            rsi_bollinger_strict_bars=bot.get('rsi_bollinger_strict_bars'),
                            rsi_bollinger_bounce_enabled=bot.get('rsi_bollinger_bounce_enabled'),
                            rsi_bollinger_bounce_pct=bot.get('rsi_bollinger_bounce_pct'),
                            rsi_bollinger_cooldown_enabled=bot.get('rsi_bollinger_cooldown_enabled'),
                            rsi_bollinger_cooldown_minutes=bot.get('rsi_bollinger_cooldown_minutes'),
                            rsi_bollinger_time_exit_enabled=bot.get('rsi_bollinger_time_exit_enabled'),
                            rsi_bollinger_time_exit_minutes=bot.get('rsi_bollinger_time_exit_minutes'),
                            rsi_bollinger_only_profit=bot.get('rsi_bollinger_only_profit'),
                            rsi_bollinger_price_history=rsi_bollinger_history,
                            rsi_bollinger_daily_max_loss=bot.get('rsi_bollinger_daily_max_loss'),
                            rsi_bollinger_max_losses_per_day=bot.get('rsi_bollinger_max_losses_per_day'),
                            rsi_bollinger_size_multiplier=bot.get('rsi_bollinger_size_multiplier'),
                            rsi_bollinger_trend_enabled=bot.get('rsi_bollinger_trend_enabled'),
                            rsi_bollinger_trend_ma=bot.get('rsi_bollinger_trend_ma'),
                            rsi_bollinger_liquidity_enabled=bot.get('rsi_bollinger_liquidity_enabled'),
                            rsi_bollinger_min_avg_volume=bot.get('rsi_bollinger_min_avg_volume'),
                            rsi_bollinger_avg_volume=rsi_bollinger_avg_volume,
                            rsi_bollinger_trailing_stop_enabled=bot.get('rsi_bollinger_trailing_stop_enabled'),
                            rsi_bollinger_trailing_stop_pct=bot.get('rsi_bollinger_trailing_stop_pct'),
                            rsi_bollinger_rsi_slope_enabled=bot.get('rsi_bollinger_rsi_slope_enabled'),
                            rsi_bollinger_min_reentry_seconds=bot.get('rsi_bollinger_min_reentry_seconds'),
                            rule_11_enabled=bool(bot.get('rule_11_enabled')) if _ibkr_mode else False,
                            rule_11_price_jump=bot.get('rule_11_price_jump'),
                            rule_11_window_seconds=bot.get('rule_11_window_seconds'),
                            rule_11_volume_threshold=bot.get('rule_11_volume_threshold'),
                            rule_11_limit_offset=bot.get('rule_11_limit_offset'),
                            rule_11_price_history=rule_11_history,
                            rule_11_profit_pct=bot.get('rule_11_profit_pct'),
                            rule_11_stop_pct=bot.get('rule_11_stop_pct'),
                            rule_11_stop_enabled=bot.get('rule_11_stop_enabled'),
                            rule_11_only_profit=bot.get('rule_11_only_profit'),
                            rule_11_trailing_stop_enabled=bot.get('rule_11_trailing_stop_enabled'),
                            rule_11_trailing_stop_pct=bot.get('rule_11_trailing_stop_pct'),
                            rule_11_cooldown_enabled=bot.get('rule_11_cooldown_enabled'),
                            rule_11_cooldown_minutes=bot.get('rule_11_cooldown_minutes'),
                            rule_11_size_multiplier=bot.get('rule_11_size_multiplier'),
                            rule_11_daily_max_loss=bot.get('rule_11_daily_max_loss'),
                            rule_11_max_losses_per_day=bot.get('rule_11_max_losses_per_day'),
                            rule_11_trend_enabled=bot.get('rule_11_trend_enabled'),
                            rule_11_trend_ma=bot.get('rule_11_trend_ma'),
                            rule_11_liquidity_enabled=bot.get('rule_11_liquidity_enabled'),
                            rule_11_min_avg_volume=bot.get('rule_11_min_avg_volume'),
                            rule_11_min_tick_density=bot.get('rule_11_min_tick_density'),
                            rule_12_enabled=bool(bot.get('rule_12_enabled')) if _ibkr_mode else False,
                            rule_12_buy_threshold=bot.get('rule_12_buy_threshold'),
                            rule_12_sell_threshold=bot.get('rule_12_sell_threshold'),
                            rule_12_min_trades=bot.get('rule_12_min_trades'),
                            rule_12_price_history=rule_12_price_history,
                            rule_12_price_volume_history=rule_12_price_volume_history,
                            rule_12_top_book=rule_12_top_book,
                            rule_12_depth_snapshot=rule_12_depth_snapshot,
                            rule_12_weight_tape=bot.get('rule_12_weight_tape'),
                            rule_12_weight_book=bot.get('rule_12_weight_book'),
                            rule_12_weight_trend=bot.get('rule_12_weight_trend'),
                            rule_12_weight_momentum=bot.get('rule_12_weight_momentum'),
                            rule_12_weight_volume=bot.get('rule_12_weight_volume'),
                            rule_12_weight_spread=bot.get('rule_12_weight_spread'),
                            rule_12_weight_pullback=bot.get('rule_12_weight_pullback'),
                            rule_12_momentum_scale=bot.get('rule_12_momentum_scale'),
                            rule_12_spread_tight_pct=bot.get('rule_12_spread_tight_pct'),
                            default_trade_enabled=bool(bot.get('default_trade_enabled', True)),
                            bot_id=bot_id,
                            bot_name=bot_name,
                        )
                        after_total = trader.core._total_logged
                        new_trade_count = after_total - before_total
                        if new_trade_count > 0:
                            for ev in trader.trade_history[-new_trade_count:]:
                                if bot_id and ev.get('bot_id') != bot_id:
                                    continue
                                direction = ev.get('direction')
                                try:
                                    _ev_ticker = str(ev.get('ticker') or bot_ticker or '').upper()
                                    if _ev_ticker and direction in ('buy', 'sell'):
                                        if _ev_ticker in ibkr_live_state:
                                            ibkr_live_state[_ev_ticker]['last_signal'] = {
                                                'direction': direction,
                                                'price': ev.get('price'),
                                                'ts': ev.get('ts'),
                                            }
                                except Exception:
                                    pass

                                if hasattr(svc, 'handle_trade_event'):
                                    try:
                                        svc.handle_trade_event(direction, ev.get('ticker'), ev.get('trade_id') or ev.get('ts'), ev.get('price'))
                                    except Exception:
                                        pass

                                if direction == 'sell':
                                    try:
                                        if hasattr(svc, 'trade_recorder'):
                                            shots = svc.trade_recorder.get_last_screenshots()
                                            if shots:
                                                ev['screenshots'] = shots
                                    except Exception:
                                        pass

                                # Live IBKR order routing
                                try:
                                    from db.queries import get_bot_db_entry
                                    bot_db_row = get_bot_db_entry(int(hwnd)) or {}
                                    bot_session_row = bot if isinstance(bot, dict) else {}
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
                                        def make_signal_getter(t, tr):
                                            def get_signal():
                                                try:
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
                    except Exception as sig_err:
                        logger.error(f"[Simulator signal evaluation error]: {sig_err}")

                # Clean up old screenshots
                try:
                    if hasattr(svc, 'capture') and hasattr(svc.capture, 'clear_screenshots'):
                        try:
                            pre_count = svc.trade_recorder.pre_count if hasattr(svc, 'trade_recorder') else 5
                        except Exception:
                            pre_count = 5
                        svc.capture.clear_screenshots(keep_last_n=pre_count + 1)
                except Exception:
                    pass

            # Step 3: Run standalone R14 and R15 evaluation passes
            try:
                await evaluate_standalone_r14(ibkr_live_state)
            except Exception as se_err:
                logger.error(f"[Standalone R14 error]: {se_err}")

            try:
                await evaluate_standalone_r15(ibkr_live_state)
            except Exception as se_err_r15:
                logger.error(f"[Standalone R15 error]: {se_err_r15}")

            # Step 4: Construct final broadcast payload
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
                'ibkr_live_state': ibkr_live_state,
            }

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
        except Exception as outer_err:
            logger.error(f"Broadcaster loop outer error: {outer_err}")
        await asyncio.sleep(0.1)


__all__ = ["broadcaster_loop"]
