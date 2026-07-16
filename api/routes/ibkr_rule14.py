"""Rule 14 REST API routes."""

import asyncio
from fastapi import APIRouter, Depends, HTTPException
from api.dependencies import require_api_key

router = APIRouter(prefix="", tags=["ibkr"])


@router.post("/rule14/configure")
async def rule14_configure(payload: dict, _auth=Depends(require_api_key)):
    """
    Enable or disable Rule 14 for a bot, and set its parameters.

    Body:
      hwnd             int   — bot window handle
      enabled          bool  — turn on/off
      qty              int   — shares per order (default 1)
      stop_loss_pct    float — stop-loss %, 0 = disabled (default 0)
      cooldown_secs    float — seconds between trades, 0 = none (default 0)
      slope_threshold  float — min slope % to trigger (default 0.03)
    """
    from trading.rule14 import configure_r14, r14_state_for_frontend, DEFAULT_SLOPE_THRESHOLD
    hwnd = int(payload.get('hwnd') or 0)
    if hwnd <= 0:
        raise HTTPException(status_code=400, detail='hwnd required')
    slope_threshold_pct = float(payload.get('slope_threshold', DEFAULT_SLOPE_THRESHOLD * 100))
    strategy_mode = str(payload.get('strategy_mode', 'scan')).strip().lower()
    configure_r14(
        hwnd,
        enabled=bool(payload.get('enabled', False)),
        qty=int(payload.get('qty', 1)),
        stop_loss_pct=float(payload.get('stop_loss_pct', 0.0)),
        cooldown_secs=float(payload.get('cooldown_secs', 0.0)),
        slope_threshold=slope_threshold_pct / 100.0,  # convert % to fraction
        strategy_mode=strategy_mode,
    )
    return {'ok': True, 'state': r14_state_for_frontend(hwnd)}


@router.get("/rule14/state/{hwnd}")
async def rule14_state(hwnd: int, _auth=Depends(require_api_key)):
    """Return current R14 runtime state for a bot (position, trend, P&L, etc.)."""
    from trading.rule14 import r14_state_for_frontend, get_r14_state, maybe_rule14_signal
    s = get_r14_state(hwnd)

    # If we have no price yet, try to fetch it from IBKR + run slope eval
    if s.last_mid_price is None or s.enabled:
        try:
            from db.queries import get_bot_db_entry
            bot_row = get_bot_db_entry(hwnd) or {}
            ticker = str(bot_row.get('ticker') or '').strip().upper()
            if ticker:
                # Try live mid price from IBKR OB
                try:
                    from ibkr.order_book import get_mid_price
                    live_p = get_mid_price(ticker)
                    if live_p and s.last_mid_price is None:
                        s.last_mid_price = float(live_p)
                except Exception:
                    pass

                # Run slope evaluation from recent OB history
                if s.enabled:
                    import time as _t
                    from datetime import datetime as _dt, timezone as _tz
                    from ibkr.order_book_history import get_order_book_history
                    _now = _t.time()
                    _end = _dt.fromtimestamp(_now, tz=_tz.utc).isoformat().replace('+00:00', 'Z')
                    _start = _dt.fromtimestamp(_now - 60, tz=_tz.utc).isoformat().replace('+00:00', 'Z')
                    try:
                        _res = get_order_book_history(ticker, start=_start, end=_end, max_points=30) or {}
                        _pts = _res.get('points') or []
                        maybe_rule14_signal(hwnd, _pts)
                    except Exception:
                        pass
        except Exception:
            pass

    return r14_state_for_frontend(hwnd)


@router.post("/rule14/manual_order")
async def rule14_manual_order(payload: dict, _auth=Depends(require_api_key)):
    """
    Place an immediate manual buy or sell for a bot via R14 (bypasses trend check).
    Used for the [SELL NOW] / [BUY NOW] override buttons.

    Body:
      hwnd       int
      direction  'buy' | 'sell'
      ticker     str
    """
    from trading.rule14 import get_r14_state
    from ibkr.order_router import handle_trade_event
    import time

    hwnd = int(payload.get('hwnd') or 0)
    direction = str(payload.get('direction') or '').lower()
    ticker = str(payload.get('ticker') or '').strip().upper()

    if hwnd <= 0 or direction not in ('buy', 'sell') or not ticker:
        raise HTTPException(status_code=400, detail='hwnd, direction, and ticker required')

    s = get_r14_state(hwnd)

    # Build a synthetic trade event and dispatch through the normal IBKR order path
    from ibkr.order_book import get_mid_price
    price = get_mid_price(ticker) or payload.get('price')

    trade_dict = {
        'direction': direction,
        'ticker': ticker,
        'price': price,
        'ts': str(time.time()),
        'bot_id': f'rule14_manual_{hwnd}',
        'rule': 'R14_MANUAL',
    }

    # Fetch bot row from database to use its configured order types, offsets, etc.
    from db.queries import get_bot_db_entry
    db_bot = get_bot_db_entry(hwnd) or {}

    payload_order_type = payload.get('order_type')
    buy_order_type = payload_order_type or db_bot.get('buy_order_type') or 'limit'
    sell_order_type = payload_order_type or db_bot.get('sell_order_type') or 'limit'

    # Build a complete bot_row preserving settings like offsets, delays, and order types
    bot_row = {
        **db_bot,
        'live_trading_enabled': True,
        'ticker': ticker,
        'qty': s.qty,
        'order_size': s.qty,
        'order_size_type': 'fixed',
        'order_size_value': float(s.qty),
        'buy_order_type': buy_order_type,
        'sell_order_type': sell_order_type,
    }

    asyncio.create_task(handle_trade_event(trade_dict, bot_row, hwnd))

    # Update state immediately
    if direction == 'buy':
        s.position_price = float(price) if price else None
        s.position_ts = time.time()
        s.last_signal = 'buy'
    else:
        s.position_price = None
        s.last_sell_ts = time.time()
        s.last_signal = 'sell'

    return {'ok': True, 'direction': direction, 'ticker': ticker, 'price': price}
