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


__all__ = ["router"]
