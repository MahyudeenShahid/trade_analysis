"""Rule 14 evaluation and order triggers for WebSocket broadcaster."""

import logging
import asyncio
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def evaluate_r14_for_bot(
    hwnd: int,
    bot: dict,
    bot_id: str,
    signal_price,
    ibkr_live_state: dict,
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

    if not _r14_ticker or not _r14_s.enabled:
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

    # If order-book history had no points yet, fall back to signal_price
    if _r14_s.last_mid_price is None and signal_price:
        try:
            _r14_s.last_mid_price = float(signal_price)
        except Exception:
            pass

    # Always push R14 state into ibkr_live_state
    if _r14_ticker in ibkr_live_state:
        ibkr_live_state[_r14_ticker]['r14'] = _r14_fe(int(hwnd))
    else:
        ibkr_live_state[_r14_ticker] = {
            'ticker': _r14_ticker,
            'prices': [],
            'trend': _r14_s.last_trend,
            'price': signal_price,
            'last_signal': None,
            'r14': _r14_fe(int(hwnd)),
        }

    if _r14_sig in ('buy', 'sell'):
        from db.queries import get_bot_db_entry as _get_bot_db
        _r14_bot_db = _get_bot_db(int(hwnd)) or {}
        _r14_bot_session = bot if isinstance(bot, dict) else {}
        _r14_bot_row = {**_r14_bot_db, **_r14_bot_session}
        _r14_sig_price = signal_price or _r14_s.last_mid_price or 0
        _r14_trade = {
            'direction': _r14_sig,
            'ticker': _r14_ticker,
            'price': _r14_sig_price,
            'ts': str(_r14_time.time()),
            'bot_id': bot_id,
            'rule': 'R14',
        }
        _r14_lp = None
        try:
            _r14_lp = float(_r14_sig_price) if _r14_sig_price else None
        except Exception:
            pass
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
                                _r14_st2.last_mid_price = float(_lp4)
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
                        _r14_lp4 = float(_r14_sp4) if _r14_sp4 else None
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
