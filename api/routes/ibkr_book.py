"""IBKR Level 2 depth order book and historical data REST API routes."""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from api.dependencies import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["ibkr"])


@router.get("/order_book/{ticker}")
def ibkr_order_book(ticker: str, _auth=Depends(require_api_key)):
    """Return the latest cached Level 2 depth snapshot for a ticker."""
    from ibkr.order_book import get_snapshot

    return {"ticker": ticker.upper(), "depth": get_snapshot(ticker.upper())}


@router.get("/order_book/history/settings")
def ibkr_order_book_history_settings(_auth=Depends(require_api_key)):
    from ibkr.order_book_history import get_history_settings

    return get_history_settings()


@router.post("/order_book/history/settings")
def ibkr_update_order_book_history_settings(payload: dict, _auth=Depends(require_api_key)):
    from ibkr.order_book_history import update_history_settings

    return update_history_settings(payload or {})


@router.get("/order_book/{ticker}/history")
def ibkr_order_book_history(
    ticker: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    max_points: int = 1000,
    _auth=Depends(require_api_key),
):
    from ibkr.order_book_history import get_order_book_history

    return get_order_book_history(ticker, start=start, end=end, max_points=max_points)


@router.get("/order_book/{ticker}/diagnostics")
def ibkr_order_book_diagnostics(ticker: str, _auth=Depends(require_api_key)):
    """Return depth subscription health and latest IB error context for ticker."""
    from ibkr.order_book import get_depth_diagnostics

    return get_depth_diagnostics(ticker.upper())


@router.post("/order_book/{ticker}/subscribe")
async def ibkr_subscribe_depth(
    ticker: str,
    force: bool = False,
    exchange: str = "SMART",
    smart_depth: Optional[bool] = None,
    rows: int = 5,
    _auth=Depends(require_api_key),
):
    """Subscribe to live Level 2 market depth for a ticker."""
    from ibkr.client import is_connected
    from ibkr.order_book import subscribe_depth

    if not is_connected():
        raise HTTPException(status_code=503, detail="Not connected to IB Gateway")

    ticker_u = ticker.upper()
    exchange_u = str(exchange or "SMART").strip().upper()
    rows = max(1, min(20, int(rows or 5)))
    if smart_depth is None:
        smart_depth = exchange_u == "SMART"

    ok = await subscribe_depth(
        ticker_u,
        exchange=exchange_u,
        num_rows=rows,
        force=force,
        is_smart_depth=bool(smart_depth),
    )
    if not ok:
        raise HTTPException(status_code=502, detail=f"Failed to subscribe depth for {ticker_u}")

    return {
        "ok": True,
        "ticker": ticker_u,
        "force": force,
        "exchange": exchange_u,
        "smart_depth": bool(smart_depth),
        "rows": rows,
    }


@router.get("/order_book/exchanges")
async def ibkr_order_book_exchanges(_auth=Depends(require_api_key)):
    """Return exchanges that provide market depth for this account/session."""
    from ibkr.client import ib, is_connected

    if not is_connected() or ib is None:
        raise HTTPException(status_code=503, detail="Not connected to IB Gateway")

    try:
        if hasattr(ib, "reqMktDepthExchangesAsync"):
            rows = await ib.reqMktDepthExchangesAsync()
        else:
            rows = ib.reqMktDepthExchanges()

        exchanges = []
        for r in rows or []:
            exchanges.append(
                {
                    "exchange": getattr(r, "exchange", ""),
                    "sec_type": getattr(r, "secType", ""),
                    "listing_exch": getattr(r, "listingExch", ""),
                    "service_data_type": getattr(r, "serviceDataType", ""),
                    "agg_group": getattr(r, "aggGroup", None),
                }
            )

        return {"ok": True, "exchanges": exchanges}
    except Exception as e:
        logger.error(f"[IBKR] reqMktDepthExchanges failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/historical/{ticker}")
async def ibkr_historical_data(
    ticker: str,
    duration: str = "1 D",
    bar_size: str = "1 min",
    use_rth: bool = True,
    _auth=Depends(require_api_key)
):
    """Fetch historical price data from IBKR for charting.

    Args:
        ticker: Stock symbol (e.g. AAPL)
        duration: How far back to fetch (e.g. "1 D", "2 D", "1 W", "1 M")
        bar_size: Bar/candle size (e.g. "1 min", "5 mins", "15 mins", "1 hour", "1 day")

    Returns:
        {ok: true, ticker: str, bars: [{time, open, high, low, close, volume}, ...]}
    """
    from ibkr.client import ib, is_connected

    if not is_connected() or ib is None:
        raise HTTPException(status_code=503, detail="Not connected to IB Gateway")

    try:
        from ib_async import Stock
        contract = Stock(ticker.upper(), "SMART", "USD")
        await ib.qualifyContractsAsync(contract)

        bars = await ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",  # now
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=bool(use_rth),
            formatDate=1,
        )

        result = []
        for bar in bars:
            result.append({
                "time": bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            })

        return {"ok": True, "ticker": ticker.upper(), "bars": result}

    except Exception as e:
        logger.error(f"[IBKR] Historical data failed for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
