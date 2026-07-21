"""Rule 14 evaluation and order triggers for WebSocket broadcaster."""

import logging
import asyncio
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _clean_price(val):
    if val is None:
        return None
    try:
        if isinstance(val, str):
            cleaned = val.replace('$', '').replace(',', '').strip()
            cleaned = ''.join(cleaned.split())
            return float(cleaned) if cleaned else None
        return float(val)
    except Exception:
        return None


def evaluate_r14_for_bot(
    hwnd: int,
    bot: dict,
    bot_id: str,
    signal_price,
    ibkr_live_state: dict,
    is_paused: bool = False,
) -> bool:
    """Evaluate Rule 14 parameters for a single bot capture worker in the main loop.

    Returns:
        bool: True if a Rule 14 signal fired, causing other rules to be bypassed.
    """
    from trading.rule14 import (
        get_r14_state as _get_r14,
        maybe_rule14_signal as _maybe_r14,
        r14_state_for_frontend as _r14_fe,
        record_order_placed as _r14_record_placed,
    )
    from ibkr.order_book_history import get_order_book_history as _get_obh
    import time as _r14_time
    from datetime import datetime as _r14_dt, timezone as _r14_tz

    bot_ticker = bot.get('ticker')
    _r14_ticker = str(bot_ticker or '').strip().upper()
    _r14_s = _get_r14(int(hwnd))

    parsed_signal_price = _clean_price(signal_price)

    if not _r14_ticker or not _r14_s.enabled:
        return False

    if is_paused:
        # Update price fallback and broadcast state without triggering orders
        if _r14_s.last_mid_price is None and parsed_signal_price is not None:
            _r14_s.last_mid_price = parsed_signal_price
        if _r14_ticker in ibkr_live_state:
            ibkr_live_state[_r14_ticker]['r14'] = _r14_fe(int(hwnd))
        return False

    # Fetch last 60 seconds of order-book history points
    _r14_now = _r14_time.time()
    _r14_end_str = _r14_dt.fromtimestamp(_r14_now, tz=_r14_tz.utc).isoformat().replace('+00:00', 'Z')
    _r14_start_str = _r14_dt.fromtimestamp(_r14_now - 60, tz=_r14_tz.utc).isoformat().replace('+00:00', 'Z')

    _r14_res = _get_obh(
        _r14_ticker,
        start=_r14_start_str,
        end=_r14_end_str,
        max_points=30,
    ) or {}
    _r14_history = _r14_res.get('points') or []

    # Fallback 1: if last 60s of order-book history is empty, try querying the last 1 hour (wider database window)
    if not _r14_history:
        try:
            _r14_res = _get_obh(_r14_ticker, max_points=30) or {}
            _r14_history = _r14_res.get('points') or []
        except Exception:
            pass

    # Fallback 2: to rolling live price list if OB history from SQLite is empty
    if not _r14_history and _r14_ticker in ibkr_live_state:
        prices = ibkr_live_state[_r14_ticker].get('prices') or []
        _r14_history = [{'bids': [{'price': p}], 'asks': [{'price': p}]} for p in prices]

    _r14_sig = _maybe_r14(int(hwnd), _r14_history)

    # If order-book history had no points yet, fall back to parsed_signal_price
    if _r14_s.last_mid_price is None and parsed_signal_price is not None:
        _r14_s.last_mid_price = parsed_signal_price

    # Always push R14 state into ibkr_live_state
    if _r14_ticker in ibkr_live_state:
        ibkr_live_state[_r14_ticker]['r14'] = _r14_fe(int(hwnd))
    else:
        ibkr_live_state[_r14_ticker] = {
            'ticker': _r14_ticker,
            'prices': [],
            'trend': _r14_s.last_trend,
            'price': parsed_signal_price,
            'last_signal': None,
            'r14': _r14_fe(int(hwnd)),
        }

    if _r14_sig in ('buy', 'sell'):
        from db.queries import get_bot_db_entry as _get_bot_db
        _r14_bot_db = _get_bot_db(int(hwnd)) or {}
        _r14_bot_session = bot if isinstance(bot, dict) else {}
        _r14_bot_row = {**_r14_bot_db, **_r14_bot_session}
        _r14_sig_price = parsed_signal_price or _r14_s.last_mid_price or 0
        _r14_trade = {
            'direction': _r14_sig,
            'ticker': _r14_ticker,
            'price': _r14_sig_price,
            'ts': str(_r14_time.time()),
            'bot_id': bot_id,
            'rule': 'R14',
        }
        _r14_lp = _clean_price(_r14_sig_price)
        _r14_record_placed(int(hwnd), _r14_sig, _r14_sig_price or 0, _r14_lp)
        ibkr_live_state[_r14_ticker]['r14'] = _r14_fe(int(hwnd))

        async def _r14_fill_wrap(trade_d, bot_r, _hwnd, _sig, _sp, _lp):
            from ibkr.order_router import handle_trade_event as _hte2
            from trading.rule14 import record_order_fill as _rof
            try:
                live_enabled_raw = bot_r.get('live_trading_enabled')
                if isinstance(live_enabled_raw, str):
                    live_enabled = live_enabled_raw.strip().lower() in ('1', 'true', 'yes', 'on')
                else:
                    live_enabled = bool(live_enabled_raw)

                # Simulated / Paper fill
                if not live_enabled:
                    await asyncio.sleep(0.5)
                    _rof(_hwnd, _sig, _sp, _lp, _sp, True, '')
                    try:
                        from db.queries import save_live_order
                        save_live_order({
                            "ts": datetime.now(timezone.utc).isoformat() + "Z",
                            "hwnd": _hwnd,
                            "bot_id": bot_r.get('id') or bot_r.get('bot_id'),
                            "ticker": trade_d.get('ticker'),
                            "direction": _sig,
                            "order_type": bot_r.get('buy_order_type') if _sig == 'buy' else bot_r.get('sell_order_type') or 'limit',
                            "qty": bot_r.get('order_size_value', 1.0),
                            "price": _sp,
                            "limit_price": _lp,
                            "status": "filled",
                            "trade_ref_id": trade_d.get('ts'),
                            "fill_price": _sp,
                            "fill_ts": datetime.now(timezone.utc).isoformat() + "Z",
                            "error_msg": "Paper Trade Simulated",
                        })
                    except Exception:
                        pass
                    return

                # Route via TWS/Gateway if live trading is enabled
                await _hte2(trade_d, bot_r, _hwnd)
                try:
                    from db.queries import get_last_order_for_hwnd_ticker as _glo
                    last_ord = _glo(_hwnd, trade_d.get('ticker', ''))
                    if last_ord:
                        _rof(_hwnd, _sig, _sp, _lp, last_ord.get('fill_price'),
                             last_ord.get('status') == 'filled', last_ord.get('error_msg') or '')
                    else:
                        _rof(_hwnd, _sig, _sp, _lp, None, False, 'no order record')
                except Exception as _fe:
                    _rof(_hwnd, _sig, _sp, _lp, None, False, str(_fe))
            except Exception as _oe:
                _rof(_hwnd, _sig, _sp, _lp, None, False, str(_oe))

        asyncio.create_task(
            _r14_fill_wrap(_r14_trade, _r14_bot_row, int(hwnd),
                           _r14_sig, _r14_sig_price or 0, _r14_lp)
        )
        ibkr_live_state[_r14_ticker]['last_signal'] = {
            'direction': _r14_sig,
            'price': signal_price,
            'ts': str(_r14_time.time()),
        }
        return True
    return False


async def evaluate_standalone_r14(ibkr_live_state: dict):
    """Evaluate Rule 14 parameters for all registered bots independently of active screenshot captures."""
    try:
        from trading.rule14 import (
            _r14_states as _all_r14,
            maybe_rule14_signal as _r14_eval2,
            r14_state_for_frontend as _r14_fe2,
            record_order_placed as _r14_op2,
        )
        from ibkr.order_book_history import get_order_book_history as _r14_obh2
        from ibkr.order_book import get_mid_price as _r14_mid2, ensure_top_of_book as _r14_ensure
        import time as _r14t2
        from datetime import datetime as _r14dt2, timezone as _r14tz2

        for _r14_hwnd2, _r14_st2 in list(_all_r14.items()):
            try:
                from db.queries import get_bot_db_entry as _gbe4
                _r14_row4 = _gbe4(int(_r14_hwnd2)) or {}
                _r14_tick4 = str(_r14_row4.get('ticker') or '').strip().upper()
                if not _r14_tick4:
                    continue

                if _r14_st2.enabled:
                    # Keep Level 1 fallback subscription active for active Rule 14 bots
                    await _r14_ensure(_r14_tick4)

                    # Query last 60s of order-book history
                    _r14_now4 = _r14t2.time()
                    _r14_end4 = _r14dt2.fromtimestamp(_r14_now4, tz=_r14tz2.utc).isoformat().replace('+00:00', 'Z')
                    _r14_start4 = _r14dt2.fromtimestamp(_r14_now4 - 60, tz=_r14tz2.utc).isoformat().replace('+00:00', 'Z')
                    _r14_res4 = _r14_obh2(_r14_tick4, start=_r14_start4, end=_r14_end4, max_points=30) or {}
                    _r14_pts4 = _r14_res4.get('points') or []

                    # Fallback 1: if last 60s of order-book history is empty, try querying the last 1 hour
                    if not _r14_pts4:
                        try:
                            _r14_res4 = _r14_obh2(_r14_tick4, max_points=30) or {}
                            _r14_pts4 = _r14_res4.get('points') or []
                        except Exception:
                            pass

                    # Fallback 2: to rolling live price list if OB history from SQLite is empty
                    if not _r14_pts4 and _r14_tick4 in ibkr_live_state:
                        prices = ibkr_live_state[_r14_tick4].get('prices') or []
                        _r14_pts4 = [{'bids': [{'price': p}], 'asks': [{'price': p}]} for p in prices]

                    _r14_sig4 = _r14_eval2(int(_r14_hwnd2), _r14_pts4)

                    # Fallback live price when no OB history yet
                    if _r14_st2.last_mid_price is None:
                        try:
                            _lp4 = _r14_mid2(_r14_tick4)
                            if _lp4:
                                _r14_st2.last_mid_price = _clean_price(_lp4)
                        except Exception:
                            pass

                    # Dispatch order if R14 fired
                    if _r14_sig4 in ('buy', 'sell'):
                        from db.queries import get_bot_db_entry as _gbe5
                        _r14_bot5 = _gbe5(int(_r14_hwnd2)) or {}
                        _r14_sp4 = _r14_st2.last_mid_price or 0
                        _r14_td4 = {
                            'direction': _r14_sig4, 'ticker': _r14_tick4,
                            'price': _r14_sp4, 'ts': str(_r14t2.time()),
                            'bot_id': str(_r14_hwnd2), 'rule': 'R14',
                        }
                        _r14_lp4 = _clean_price(_r14_sp4)
                        _r14_op2(int(_r14_hwnd2), _r14_sig4, _r14_sp4, _r14_lp4)

                        async def _r14_fw4(td, br, hw, sg, sp, lp):
                            from ibkr.order_router import handle_trade_event as _h4
                            from trading.rule14 import record_order_fill as _rf4
                            try:
                                live_enabled_raw = br.get('live_trading_enabled')
                                if isinstance(live_enabled_raw, str):
                                    live_enabled = live_enabled_raw.strip().lower() in ('1', 'true', 'yes', 'on')
                                else:
                                    live_enabled = bool(live_enabled_raw)

                                # Simulated / Paper fill
                                if not live_enabled:
                                    await asyncio.sleep(0.5)
                                    _rf4(hw, sg, sp, lp, sp, True, '')
                                    try:
                                        from db.queries import save_live_order
                                        save_live_order({
                                            "ts": datetime.now(timezone.utc).isoformat() + "Z",
                                            "hwnd": hw,
                                            "bot_id": br.get('id') or br.get('bot_id'),
                                            "ticker": td.get('ticker'),
                                            "direction": sg,
                                            "order_type": br.get('buy_order_type') if sg == 'buy' else br.get('sell_order_type') or 'limit',
                                            "qty": br.get('order_size_value', 1.0),
                                            "price": sp,
                                            "limit_price": lp,
                                            "status": "filled",
                                            "trade_ref_id": td.get('ts'),
                                            "fill_price": sp,
                                            "fill_ts": datetime.now(timezone.utc).isoformat() + "Z",
                                            "error_msg": "Paper Trade Simulated",
                                        })
                                    except Exception:
                                        pass
                                    return

                                # Route via TWS/Gateway if live trading is enabled
                                await _h4(td, br, hw)
                                try:
                                    from db.queries import get_last_order_for_hwnd_ticker as _glo4
                                    lo4 = _glo4(hw, td.get('ticker', ''))
                                    if lo4:
                                        _rf4(hw, sg, sp, lp, lo4.get('fill_price'),
                                             lo4.get('status') == 'filled', lo4.get('error_msg') or '')
                                    else:
                                        _rf4(hw, sg, sp, lp, None, False, 'no record')
                                except Exception as _fe4:
                                    _rf4(hw, sg, sp, lp, None, False, str(_fe4))
                            except Exception as _oe4:
                                _rf4(hw, sg, sp, lp, None, False, str(_oe4))

                        asyncio.create_task(_r14_fw4(
                            _r14_td4, _r14_bot5, int(_r14_hwnd2), _r14_sig4, _r14_sp4, _r14_lp4
                        ))

                # Always push R14 state (enabled or disabled) into the WS payload
                if _r14_tick4 in ibkr_live_state:
                    ibkr_live_state[_r14_tick4]['r14'] = _r14_fe2(int(_r14_hwnd2))
                else:
                    ibkr_live_state[_r14_tick4] = {
                        'ticker': _r14_tick4, 'prices': [], 'trend': _r14_st2.last_trend,
                        'price': _r14_st2.last_mid_price, 'last_signal': None,
                        'r14': _r14_fe2(int(_r14_hwnd2)),
                    }
            except Exception as _r14_inner2:
                logger.warning(f'[R14 standalone] hwnd={_r14_hwnd2}: {_r14_inner2}')
    except Exception as _r14_outer4:
        logger.warning(f'[R14 standalone outer]: {_r14_outer4}')


# ─── Rule 12 evaluation ───────────────────────────────────────────────────────

def evaluate_r12_for_bot(
    hwnd: int,
    bot: dict,
    bot_id: str,
    screenshot_trend: str,
    ibkr_live_state: dict,
    is_paused: bool = False,
    signal_price=None,
) -> bool:
    """Evaluate Rule 12 parameters for a single bot capture worker in the main loop."""
    from trading.rules_tape_meter import (
        get_r12_state as _get_r12,
        maybe_rule12_signal as _maybe_r12,
        r12_state_for_frontend as _r12_fe,
        record_order_placed as _r12_record_placed,
    )
    import time as _r12_time
    import asyncio
    from datetime import datetime, timezone

    bot_ticker = bot.get('ticker')
    _r12_ticker = str(bot_ticker or '').strip().upper()
    if not _r12_ticker:
        return False

    _r12_s = _get_r12(int(hwnd))
    
    # Sync config properties directly from the active bot session/database settings
    _r12_s.enabled = bool(bot.get('rule_12_enabled', False))
    _r12_s.stop_loss_pct = float(bot.get('rule_12_buy_threshold') or 0.5)
    _r12_s.always_sell_on_profit = bool(bot.get('rule_12_sell_threshold', False))

    # Get live price from live IBKR
    from ibkr.order_book import get_mid_price as _get_mid
    _live_price = None
    try:
        _live_price = _get_mid(_r12_ticker)
    except Exception:
        pass

    if _live_price is None:
        # Fallback 1: bot dict fields (price saved alongside settings)
        _live_price = bot.get('price') or bot.get('price_value') or bot.get('open_price') or None

    if _live_price is None:
        # Fallback 2: signal_price from the screenshot analysis passed from the broadcaster loop
        _live_price = signal_price

    if _live_price is not None:
        try:
            if isinstance(_live_price, str):
                cleaned = _live_price.replace('$', '').replace(',', '').strip()
                # Remove newlines or extra whitespace in between words/numbers
                cleaned = ''.join(cleaned.split())
                _live_price = float(cleaned)
            else:
                _live_price = float(_live_price)
            _r12_s.last_mid_price = _live_price
        except Exception as parse_err:
            logger.warning(f"[R12 price clean error] Could not convert raw price {repr(_live_price)}: {parse_err}")
            _live_price = None

    _r12_s.last_trend = screenshot_trend

    # Always push R12 state into ibkr_live_state for WS broadcast so UI gets live price and trend
    if _r12_ticker in ibkr_live_state:
        ibkr_live_state[_r12_ticker]['r12'] = _r12_fe(int(hwnd))
    else:
        ibkr_live_state[_r12_ticker] = {
            'ticker': _r12_ticker,
            'prices': [],
            'trend': screenshot_trend,
            'price': _live_price,
            'last_signal': None,
            'r12': _r12_fe(int(hwnd)),
        }

    if not _r12_s.enabled or is_paused:
        return False

    # Can't evaluate without a price — guard before float() cast to avoid TypeError
    if _live_price is None:
        return False

    # Evaluate signal based on screenshot_trend and live price
    _r12_sig = _maybe_r12(int(hwnd), screenshot_trend, float(_live_price))

    if _r12_sig in ('buy', 'sell'):
        from db.queries import get_bot_db_entry as _get_bot_db_r12
        _r12_bot_db = _get_bot_db_r12(int(hwnd)) or {}
        _r12_bot_session = bot if isinstance(bot, dict) else {}
        _r12_bot_row = {**_r12_bot_db, **_r12_bot_session}
        _r12_sig_price = _live_price

        # Label trade as 'rule12'
        _r12_trade = {
            'direction': _r12_sig,
            'ticker': _r12_ticker,
            'price': _r12_sig_price,
            'ts': str(_r12_time.time()),
            'bot_id': bot_id,
            'rule': 'rule12',
        }

        # Record Order Placed log statement
        _r12_record_placed(int(hwnd), _r12_sig, _r12_sig_price)
        if _r12_ticker in ibkr_live_state:
            ibkr_live_state[_r12_ticker]['r12'] = _r12_fe(int(hwnd))

        async def _r12_fw_trade(td, br, hw, sg, sp, lp):
            from ibkr.order_router import handle_trade_event as _h
            from trading.rules_tape_meter import record_order_fill as _rf
            try:
                live_enabled_raw = br.get('live_trading_enabled')
                if isinstance(live_enabled_raw, str):
                    live_enabled = live_enabled_raw.strip().lower() in ('1', 'true', 'yes', 'on')
                else:
                    live_enabled = bool(live_enabled_raw)

                if not live_enabled:
                    await asyncio.sleep(0.5)
                    _rf(hw, sg, sp, True, '')
                    try:
                        from db.queries import save_live_order
                        save_live_order({
                            "ts": datetime.now(timezone.utc).isoformat() + "Z",
                            "hwnd": hw,
                            "bot_id": br.get('id') or br.get('bot_id'),
                            "ticker": td.get('ticker'),
                            "direction": sg,
                            "order_type": br.get('buy_order_type') if sg == 'buy' else br.get('sell_order_type') or 'limit',
                            "qty": br.get('order_size_value', 1.0),
                            "price": sp,
                            "limit_price": lp,
                            "status": "filled",
                            "trade_ref_id": td.get('ts'),
                            "fill_price": sp,
                            "fill_ts": datetime.now(timezone.utc).isoformat() + "Z",
                            "error_msg": "Paper Trade Simulated (R12)",
                        })
                    except Exception:
                        pass
                    return

                await _h(td, br, hw)
                try:
                    from db.queries import get_last_order_for_hwnd_ticker as _glo
                    lo = _glo(hw, td.get('ticker', ''))
                    if lo:
                        _rf(hw, sg, lo.get('fill_price') or sp, lo.get('status') == 'filled', lo.get('error_msg') or '')
                    else:
                        _rf(hw, sg, sp, False, 'no record')
                except Exception as _fe:
                    _rf(hw, sg, sp, False, str(_fe))
            except Exception as _oe:
                _rf(hw, sg, sp, False, str(_oe))

        asyncio.create_task(_r12_fw_trade(
            _r12_trade, _r12_bot_row, int(hwnd),
            _r12_sig, _r12_sig_price, _r12_sig_price
        ))
        return True
    return False


async def evaluate_standalone_r12(ibkr_live_state: dict):
    """Evaluate Rule 12 for all registered bots independently of screenshot captures."""
    try:
        from trading.rules_tape_meter import (
            _r12_states as _all_r12,
            maybe_rule12_signal as _r12_eval_sa,
            r12_state_for_frontend as _r12_fe_sa,
            record_order_placed as _r12_op_sa,
            configure_r12 as _r12_cfg_sa,
        )
        from ibkr.order_book import get_mid_price as _mid_sa
        import time as _r12t_sa
        import asyncio
        from datetime import datetime, timezone

        # Bootstrap: load saved R12 config from DB for any bots not yet in memory
        try:
            from db.connection import DB_PATH, DB_LOCK
            import sqlite3 as _sq_sa
            with DB_LOCK:
                _conn_sa = _sq_sa.connect(DB_PATH)
                _conn_sa.row_factory = _sq_sa.Row
                _rows_sa = _conn_sa.execute("SELECT hwnd, rule_12_enabled, rule_12_buy_threshold, rule_12_sell_threshold FROM bots WHERE hwnd IS NOT NULL").fetchall()
                _conn_sa.close()
            for _boot_row in _rows_sa:
                try:
                    _boot_hwnd = int(_boot_row['hwnd'])
                    if _boot_hwnd in _all_r12:
                        continue
                    _r12_cfg_sa(
                        _boot_hwnd,
                        enabled=bool(_boot_row['rule_12_enabled']),
                        stop_loss_pct=float(_boot_row['rule_12_buy_threshold'] or 0.5),
                        always_sell_on_profit=bool(_boot_row['rule_12_sell_threshold']),
                    )
                except Exception:
                    pass
        except Exception:
            pass

        for _r12_hwnd_sa, _r12_st_sa in list(_all_r12.items()):
            try:
                from db.queries import get_bot_db_entry as _gbe_sa
                _r12_row_sa = _gbe_sa(int(_r12_hwnd_sa)) or {}
                _r12_tick_sa = str(_r12_row_sa.get('ticker') or '').strip().upper()
                if not _r12_tick_sa:
                    continue

                # Keep settings synced with database updates
                _r12_st_sa.enabled = bool(_r12_row_sa.get('rule_12_enabled', False))
                _r12_st_sa.stop_loss_pct = float(_r12_row_sa.get('rule_12_buy_threshold') or 0.5)
                _r12_st_sa.always_sell_on_profit = bool(_r12_row_sa.get('rule_12_sell_threshold', False))

                _live_price = None
                try:
                    _live_price = _mid_sa(_r12_tick_sa)
                except Exception:
                    pass

                if _live_price is not None:
                    _r12_st_sa.last_mid_price = _live_price

                # Push updated R12 state to frontend so it is active
                if _r12_tick_sa in ibkr_live_state:
                    ibkr_live_state[_r12_tick_sa]['r12'] = _r12_fe_sa(int(_r12_hwnd_sa))

                if _r12_st_sa.enabled and _live_price is not None:
                    _r12_sig_sa = None
                    if _r12_st_sa.position_price is not None:
                        _r12_sig_sa = _r12_eval_sa(int(_r12_hwnd_sa), _r12_st_sa.last_trend, _live_price)

                    if _r12_sig_sa == 'sell':
                        _r12_op_sa(int(_r12_hwnd_sa), _r12_sig_sa, _live_price)

                        from db.queries import get_bot_db_entry as _gbe_sa2
                        _r12_bot_sa = _gbe_sa2(int(_r12_hwnd_sa)) or {}
                        _r12_td_sa = {
                            'direction': 'sell', 'ticker': _r12_tick_sa,
                            'price': _live_price, 'ts': str(_r12t_sa.time()),
                            'bot_id': str(_r12_hwnd_sa), 'rule': 'rule12',
                        }

                        async def _r12_fw_sa(td, br, hw, sg, sp, lp):
                            from ibkr.order_router import handle_trade_event as _h_sa
                            from trading.rules_tape_meter import record_order_fill as _rf_sa
                            try:
                                live_enabled_raw = br.get('live_trading_enabled')
                                if isinstance(live_enabled_raw, str):
                                    live_enabled = live_enabled_raw.strip().lower() in ('1', 'true', 'yes', 'on')
                                else:
                                    live_enabled = bool(live_enabled_raw)

                                if not live_enabled:
                                    await asyncio.sleep(0.5)
                                    _rf_sa(hw, sg, sp, True, '')
                                    try:
                                        from db.queries import save_live_order
                                        save_live_order({
                                            "ts": datetime.now(timezone.utc).isoformat() + "Z",
                                            "hwnd": hw, "bot_id": br.get('id') or br.get('bot_id'),
                                            "ticker": td.get('ticker'), "direction": sg,
                                            "order_type": br.get('sell_order_type') or 'limit',
                                            "qty": br.get('order_size_value', 1.0), "price": sp,
                                            "limit_price": lp, "status": "filled",
                                            "trade_ref_id": td.get('ts'), "fill_price": sp,
                                            "fill_ts": datetime.now(timezone.utc).isoformat() + "Z",
                                            "error_msg": "Paper Trade Simulated (R12)",
                                        })
                                    except Exception:
                                        pass
                                    return

                                await _h_sa(td, br, hw)
                                try:
                                    from db.queries import get_last_order_for_hwnd_ticker as _glo_sa
                                    lo_sa = _glo_sa(hw, td.get('ticker', ''))
                                    if lo_sa:
                                        _rf_sa(hw, sg, lo_sa.get('fill_price') or sp, lo_sa.get('status') == 'filled', lo_sa.get('error_msg') or '')
                                    else:
                                        _rf_sa(hw, sg, sp, False, 'no record')
                                except Exception as _fe_sa:
                                    _rf_sa(hw, sg, sp, False, str(_fe_sa))
                            except Exception as _oe_sa:
                                _rf_sa(hw, sg, sp, False, str(_oe_sa))

                        asyncio.create_task(_r12_fw_sa(
                            _r12_td_sa, _r12_bot_sa, int(_r12_hwnd_sa),
                            'sell', _live_price, _live_price
                        ))

                # Always push R12 state into ibkr_live_state regardless of enabled/price —
                # this ensures the ticker entry is created early in the session so the UI
                # can show price and trend even before Rule 12 fires a trade.
                if _r12_tick_sa in ibkr_live_state:
                    ibkr_live_state[_r12_tick_sa]['r12'] = _r12_fe_sa(int(_r12_hwnd_sa))
                else:
                    ibkr_live_state[_r12_tick_sa] = {
                        'ticker': _r12_tick_sa, 'prices': [],
                        'trend': _r12_st_sa.last_trend,
                        'price': _r12_st_sa.last_mid_price, 'last_signal': None,
                        'r12': _r12_fe_sa(int(_r12_hwnd_sa)),
                    }
            except Exception:
                pass
    except Exception:
        pass
