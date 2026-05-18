"""Trade simulation and manual trade routes."""

from fastapi import APIRouter, Depends, HTTPException
from api.dependencies import require_api_key
from trading.simulator import trader, persist_trade_as_record
from services.bot_registry import list_bots_by_hwnd, get_bot
import json

router = APIRouter(prefix="", tags=["trades"])


@router.get("/trades")
def api_trades(_auth: bool = Depends(require_api_key)):
    """
    Get trade summary from the simulator.
    
    Returns:
        dict: Current trading summary with positions and P&L
    """
    return trader.summary()


def _get_bot_settings_from_trade(trade: dict):
    """Extract bot settings from trade metadata."""
    bot_settings = {}
    try:
        # Try to get bot_id from trade
        bot_id = trade.get('bot_id')
        if bot_id:
            bot_settings = get_bot(bot_id) or {}
        
        # Try to get by hwnd
        if not bot_settings and trade.get('hwnd'):
            hwnd = int(trade.get('hwnd'))
            bots = list_bots_by_hwnd(hwnd)
            if bots:
                bot_settings = bots[0]
        
        # Try to get from meta
        if not bot_settings:
            meta = trade.get('meta') or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    pass
            if isinstance(meta, dict):
                bot_id = meta.get('bot_id')
                if bot_id:
                    bot_settings = get_bot(bot_id) or {}
    except Exception:
        pass
    
    return bot_settings


@router.post("/manual_trade")
def api_manual_trade(trade: dict, _auth: bool = Depends(require_api_key)):
    """
    Accept a manual trade JSON payload and persist it to the records table.

    Expected payload: a JSON object representing a trade, e.g.
    { "ticker": "TSLA", "price": 123.45, "direction": "buy", "ts": "...", "meta": {...} }
    
    Args:
        trade: Trade dictionary
        
    Returns:
        dict: Success status
    """
    try:
        if not isinstance(trade, dict):
            raise HTTPException(status_code=400, detail="trade must be a JSON object")
        
        # Persist the trade using existing helper
        persist_trade_as_record(trade)
        
        # Get bot settings
        bot_settings = _get_bot_settings_from_trade(trade)
        
        # Optionally trigger trader signals if applicable
        try:
            trend = (trade.get('direction') or '').lower()
            price = trade.get('price')
            ticker = trade.get('ticker')
            
            # If explicit buy/sell direction provided, directly record in simulator
            if trend in ('buy', 'sell') and price is not None and ticker:
                try:
                    if trend == 'buy':
                        trader._buy(ticker, float(price))
                    else:
                        trader._sell(ticker, float(price))
                except Exception:
                    # fallback: try signaling with mapped trend and bot settings
                    mapped = 'up' if trend == 'buy' else 'down'
                    try:
                        trader.on_signal(
                            mapped, price, ticker, auto=True,
                            rsi_bollinger_enabled=bot_settings.get('rsi_bollinger_enabled', False),
                            rsi_bollinger_rsi_length=bot_settings.get('rsi_bollinger_rsi_length'),
                            rsi_bollinger_rsi_threshold=bot_settings.get('rsi_bollinger_rsi_threshold'),
                            rsi_bollinger_bb_length=bot_settings.get('rsi_bollinger_bb_length'),
                            rsi_bollinger_bb_stdev=bot_settings.get('rsi_bollinger_bb_stdev'),
                            rsi_bollinger_profit_pct=bot_settings.get('rsi_bollinger_profit_pct'),
                            rsi_bollinger_stop_pct=bot_settings.get('rsi_bollinger_stop_pct'),
                            rsi_bollinger_stop_enabled=bot_settings.get('rsi_bollinger_stop_enabled'),
                            rsi_bollinger_trailing_stop_enabled=bot_settings.get('rsi_bollinger_trailing_stop_enabled'),
                            rsi_bollinger_trailing_stop_pct=bot_settings.get('rsi_bollinger_trailing_stop_pct'),
                            rule_11_enabled=bot_settings.get('rule_11_enabled', False),
                            rule_11_price_jump=bot_settings.get('rule_11_price_jump'),
                            rule_11_window_seconds=bot_settings.get('rule_11_window_seconds'),
                            rule_11_volume_threshold=bot_settings.get('rule_11_volume_threshold'),
                        )
                    except Exception:
                        pass
            else:
                # allow other trend naming (e.g., 'up'/'down') to be handled by simulator
                if trend and price and ticker:
                    try:
                        trader.on_signal(
                            trend, price, ticker, auto=True,
                            rsi_bollinger_enabled=bot_settings.get('rsi_bollinger_enabled', False),
                            rsi_bollinger_rsi_length=bot_settings.get('rsi_bollinger_rsi_length'),
                            rsi_bollinger_rsi_threshold=bot_settings.get('rsi_bollinger_rsi_threshold'),
                            rsi_bollinger_bb_length=bot_settings.get('rsi_bollinger_bb_length'),
                            rsi_bollinger_bb_stdev=bot_settings.get('rsi_bollinger_bb_stdev'),
                            rsi_bollinger_profit_pct=bot_settings.get('rsi_bollinger_profit_pct'),
                            rsi_bollinger_stop_pct=bot_settings.get('rsi_bollinger_stop_pct'),
                            rsi_bollinger_stop_enabled=bot_settings.get('rsi_bollinger_stop_enabled'),
                            rsi_bollinger_trailing_stop_enabled=bot_settings.get('rsi_bollinger_trailing_stop_enabled'),
                            rsi_bollinger_trailing_stop_pct=bot_settings.get('rsi_bollinger_trailing_stop_pct'),
                            rule_11_enabled=bot_settings.get('rule_11_enabled', False),
                            rule_11_price_jump=bot_settings.get('rule_11_price_jump'),
                            rule_11_window_seconds=bot_settings.get('rule_11_window_seconds'),
                            rule_11_volume_threshold=bot_settings.get('rule_11_volume_threshold'),
                        )
                    except Exception:
                        pass
        except Exception:
            pass
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/close_all_positions")
def api_close_all_positions(_auth: bool = Depends(require_api_key)):
    """
    Force-close every open position in the simulator and mark each as INCOMPLETE.

    Called before disconnection so that open trades are not left dangling in the
    database without a corresponding sell record.

    Returns:
        dict: Number of positions that were closed.
    """
    try:
        closed = 0
        all_states = trader.state_manager.all_states()
        for key, state in list(all_states.items()):
            if state.position is not None:
                try:
                    entry_price = state.position.get("entry")
                    # Use entry_price as sell price so profit = 0; this keeps the
                    # DB record consistent (buy_price == sell_price = entry).
                    sell_price = entry_price if entry_price is not None else 0.0
                    trader.core.sell(key, sell_price, state, win_reason="INCOMPLETE")
                    closed += 1
                except Exception:
                    pass
        return {"closed": closed}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router"]
