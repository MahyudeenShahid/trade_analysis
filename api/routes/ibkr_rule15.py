"""Rule 15 REST API routes."""

import asyncio
from fastapi import APIRouter, Depends, HTTPException
from api.dependencies import require_api_key

router = APIRouter(prefix="", tags=["ibkr"])


def _persist_r15_config(hwnd: int, config: dict):
    """Save R15 config into the bot's meta field so it survives server restarts."""
    try:
        from db.queries import get_bot_db_entry, upsert_bot_settings
        row = get_bot_db_entry(hwnd) or {}
        existing_meta = row.get('meta') or {}
        if isinstance(existing_meta, str):
            import json
            try:
                existing_meta = json.loads(existing_meta)
            except Exception:
                existing_meta = {}
        if not isinstance(existing_meta, dict):
            existing_meta = {}
        existing_meta['r15_config'] = config
        upsert_bot_settings(hwnd, {'meta': existing_meta})
        
        # Sync to in-memory bot registry to update UI badges immediately
        try:
            from services.bot_registry import list_bots_by_hwnd, update_bot
            for b in list_bots_by_hwnd(hwnd):
                bid = b.get('bot_id') or b.get('id')
                if bid:
                    update_bot(bid, {'meta': existing_meta})
        except Exception:
            pass
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[R15] Failed to persist config for hwnd={hwnd}: {e}")


def load_r15_config_from_db(hwnd: int) -> dict | None:
    """Load R15 config from DB meta for this bot. Returns None if not set."""
    try:
        from db.queries import get_bot_db_entry
        row = get_bot_db_entry(hwnd) or {}
        meta = row.get('meta') or {}
        if isinstance(meta, str):
            import json
            try:
                meta = json.loads(meta)
            except Exception:
                return None
        return meta.get('r15_config') if isinstance(meta, dict) else None
    except Exception:
        return None


@router.post("/rule15/configure")
async def rule15_configure(payload: dict, _auth=Depends(require_api_key)):
    """
    Enable or disable Rule 15 for a bot, and set its parameters.

    Body:
      hwnd             int   — bot window handle
      enabled          bool  — turn on/off
      qty              int   — shares per order (default 1)
      stop_loss_pct    float — stop-loss %, 0 = disabled (default 0)
      cooldown_secs    float — seconds between trades, 0 = none (default 0)
      slope_threshold  float — min slope % to trigger (default 0.03)
      strategy_mode    str   — 'scan' | 'slope' (default 'scan')
      lookback_seconds float — price window in seconds (default 300)
    """
    from trading.rule15 import configure_r15, r15_state_for_frontend, DEFAULT_SLOPE_THRESHOLD
    hwnd = int(payload.get('hwnd') or 0)
    if hwnd <= 0:
        raise HTTPException(status_code=400, detail='hwnd required')
    try:
        slope_val = payload.get('slope_threshold')
        slope_threshold_pct = float(slope_val) if slope_val is not None else (DEFAULT_SLOPE_THRESHOLD * 100)
    except (TypeError, ValueError):
        slope_threshold_pct = DEFAULT_SLOPE_THRESHOLD * 100

    strategy_mode = str(payload.get('strategy_mode') or 'scan').strip().lower()

    try:
        lookback_val = payload.get('lookback_seconds')
        lookback_seconds = float(lookback_val) if lookback_val is not None else 300.0
    except (TypeError, ValueError):
        lookback_seconds = 300.0

    enabled = bool(payload.get('enabled', False))

    try:
        qty_val = payload.get('qty')
        qty = int(qty_val) if qty_val is not None else 1
    except (TypeError, ValueError):
        qty = 1

    try:
        stop_val = payload.get('stop_loss_pct')
        stop_loss_pct = float(stop_val) if stop_val is not None else 0.0
    except (TypeError, ValueError):
        stop_loss_pct = 0.0

    try:
        cooldown_val = payload.get('cooldown_secs')
        cooldown_secs = float(cooldown_val) if cooldown_val is not None else 0.0
    except (TypeError, ValueError):
        cooldown_secs = 0.0

    use_bot_trend = bool(payload.get('use_bot_trend', False))
    always_sell_on_profit = bool(payload.get('always_sell_on_profit', False))

    configure_r15(
        hwnd,
        enabled=enabled,
        qty=qty,
        stop_loss_pct=stop_loss_pct,
        cooldown_secs=cooldown_secs,
        slope_threshold=slope_threshold_pct / 100.0,
        strategy_mode=strategy_mode,
        lookback_seconds=lookback_seconds,
        use_bot_trend=use_bot_trend,
        always_sell_on_profit=always_sell_on_profit,
    )

    # Persist to DB so settings survive server restart
    _persist_r15_config(hwnd, {
        'enabled': enabled,
        'qty': qty,
        'stop_loss_pct': stop_loss_pct,
        'cooldown_secs': cooldown_secs,
        'slope_threshold': slope_threshold_pct,   # stored as pct (e.g. 0.03)
        'strategy_mode': strategy_mode,
        'lookback_seconds': lookback_seconds,
        'use_bot_trend': use_bot_trend,
        'always_sell_on_profit': always_sell_on_profit,
    })

    return {'ok': True, 'state': r15_state_for_frontend(hwnd)}


@router.get("/rule15/state/{hwnd}")
async def rule15_state(hwnd: int, _auth=Depends(require_api_key)):
    """Return current R15 runtime state for a bot (position, trend, P&L, etc.)."""
    from trading.rule15 import r15_state_for_frontend, get_r15_state, configure_r15, maybe_rule15_signal, DEFAULT_SLOPE_THRESHOLD
    s = get_r15_state(hwnd)

    # ── Bootstrap from DB if this is a fresh server session ─────────────────
    # (i.e. _r15_states was empty — state has no config loaded yet)
    saved = load_r15_config_from_db(hwnd)
    if saved:
        configure_r15(
            hwnd,
            enabled=bool(saved.get('enabled', False)),
            qty=int(saved.get('qty', 1)),
            stop_loss_pct=float(saved.get('stop_loss_pct', 0.0)),
            cooldown_secs=float(saved.get('cooldown_secs', 0.0)),
            slope_threshold=float(saved.get('slope_threshold', DEFAULT_SLOPE_THRESHOLD * 100)) / 100.0,
            strategy_mode=str(saved.get('strategy_mode', 'scan')),
            lookback_seconds=float(saved.get('lookback_seconds', 300.0)),
            use_bot_trend=bool(saved.get('use_bot_trend', False)),
            always_sell_on_profit=bool(saved.get('always_sell_on_profit', False)),
        )
        s = get_r15_state(hwnd)

    # Try to fetch live price and run slope eval
    if s.last_mid_price is None or s.enabled:
        try:
            from db.queries import get_bot_db_entry
            bot_row = get_bot_db_entry(hwnd) or {}
            ticker = str(bot_row.get('ticker') or '').strip().upper()
            if ticker:
                try:
                    from ibkr.order_book import get_mid_price, get_price_history, seed_price_history_from_ibkr
                    history = get_price_history(ticker, raw=True) or []
                    if len(history) < 2:
                        await seed_price_history_from_ibkr(ticker)
                        history = get_price_history(ticker, raw=True) or []

                    live_p = get_mid_price(ticker)
                    if live_p and s.last_mid_price is None:
                        s.last_mid_price = float(live_p)
                    if s.enabled and history:
                        maybe_rule15_signal(hwnd, history)
                except Exception:
                    pass
        except Exception:
            pass

    return r15_state_for_frontend(hwnd)
