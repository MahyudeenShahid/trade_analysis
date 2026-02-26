"""Trade simulation and manual trade routes."""

from fastapi import APIRouter, Depends, HTTPException
from api.dependencies import require_api_key
from trading.simulator import trader, persist_trade_as_record

router = APIRouter(prefix="", tags=["trades"])


@router.get("/trades")
def api_trades(_auth: bool = Depends(require_api_key)):
    """
    Get trade summary from the simulator.
    
    Returns:
        dict: Current trading summary with positions and P&L
    """
    return trader.summary()


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
                    # fallback: try signaling with mapped trend
                    mapped = 'up' if trend == 'buy' else 'down'
                    try:
                        trader.on_signal(mapped, price, ticker, auto=True)
                    except Exception:
                        pass
            else:
                # allow other trend naming (e.g., 'up'/'down') to be handled by simulator
                if trend and price and ticker:
                    try:
                        trader.on_signal(trend, price, ticker, auto=True)
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
