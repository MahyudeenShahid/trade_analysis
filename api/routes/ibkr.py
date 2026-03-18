"""IBKR REST API routes — connection, status, orders, positions, settings."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_api_key
from db.queries import get_app_settings, set_app_setting, get_live_orders

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ibkr", tags=["ibkr"])


# ---------------------------------------------------------------------------
# Status + connection management
# ---------------------------------------------------------------------------

@router.get("/status")
async def ibkr_status(_auth=Depends(require_api_key)):
    """Return current IBKR connection state and settings."""
    from ibkr.client import is_connected
    from ibkr.account import get_account_summary

    connected = is_connected()
    cfg = get_app_settings()
    account = {}
    if connected:
        try:
            account = await get_account_summary()
        except Exception:
            account = {}

    return {
        "connected": connected,
        "ibkr_enabled": cfg.get("ibkr_enabled", "0") == "1",
        "host": cfg.get("ibkr_host", "127.0.0.1"),
        "port": int(cfg.get("ibkr_port", "4002")),
        "client_id": int(cfg.get("ibkr_client_id", "1")),
        "account": account,
    }


@router.post("/connect")
async def ibkr_connect(payload: dict = None, _auth=Depends(require_api_key)):
    """Manually trigger an IBKR connection.

    Optionally accepts { host, port, client_id } to override app_settings.
    """
    from ibkr.client import connect, is_connected

    cfg = get_app_settings()
    host = (payload or {}).get("host") or cfg.get("ibkr_host", "127.0.0.1")
    port = int((payload or {}).get("port") or cfg.get("ibkr_port", 4002))
    client_id = int((payload or {}).get("client_id") or cfg.get("ibkr_client_id", 1))

    if is_connected():
        return {"ok": True, "message": "Already connected"}

    ok = await connect(host, port, client_id)
    if not ok:
        raise HTTPException(status_code=502, detail="Could not connect to IB Gateway")
    return {"ok": True, "message": f"Connected to {host}:{port}"}


@router.post("/disconnect")
def ibkr_disconnect(_auth=Depends(require_api_key)):
    """Disconnect from IB Gateway."""
    from ibkr.client import disconnect

    disconnect()
    return {"ok": True, "message": "Disconnected"}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@router.get("/settings")
def ibkr_get_settings(_auth=Depends(require_api_key)):
    """Return IBKR-related app_settings keys."""
    cfg = get_app_settings()
    return {
        "ibkr_enabled": cfg.get("ibkr_enabled", "0"),
        "ibkr_host": cfg.get("ibkr_host", "127.0.0.1"),
        "ibkr_port": cfg.get("ibkr_port", "4002"),
        "ibkr_client_id": cfg.get("ibkr_client_id", "1"),
    }


@router.post("/settings")
def ibkr_update_settings(payload: dict, _auth=Depends(require_api_key)):
    """Update IBKR connection settings in app_settings."""
    allowed = {"ibkr_enabled", "ibkr_host", "ibkr_port", "ibkr_client_id"}
    updated = {}
    for key in allowed:
        if key in payload:
            set_app_setting(key, str(payload[key]))
            updated[key] = payload[key]
    return {"ok": True, "updated": updated}


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@router.get("/orders")
def ibkr_orders(hwnd: int = None, limit: int = 100, _auth=Depends(require_api_key)):
    """Return recent live orders, optionally filtered by hwnd."""
    return {"orders": get_live_orders(hwnd=hwnd, limit=limit)}


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

@router.get("/positions")
async def ibkr_positions(_auth=Depends(require_api_key)):
    """Return current account positions from IBKR."""
    from ibkr.account import get_positions

    return {"positions": await get_positions()}


@router.get("/open_orders")
async def ibkr_open_orders(_auth=Depends(require_api_key)):
    """Return currently open orders from IBKR."""
    from ibkr.account import get_open_orders

    return {"open_orders": await get_open_orders()}


# ---------------------------------------------------------------------------
# Order book
# ---------------------------------------------------------------------------

@router.get("/order_book/{ticker}")
def ibkr_order_book(ticker: str, _auth=Depends(require_api_key)):
    """Return the latest cached Level 2 depth snapshot for a ticker."""
    from ibkr.order_book import get_snapshot

    return {"ticker": ticker.upper(), "depth": get_snapshot(ticker.upper())}


@router.post("/order_book/{ticker}/subscribe")
async def ibkr_subscribe_depth(ticker: str, _auth=Depends(require_api_key)):
    """Subscribe to live Level 2 market depth for a ticker."""
    from ibkr.order_book import subscribe_depth

    await subscribe_depth(ticker.upper())
    return {"ok": True, "ticker": ticker.upper()}


# ---------------------------------------------------------------------------
# Historical Data (for charting)
# ---------------------------------------------------------------------------

@router.get("/historical/{ticker}")
async def ibkr_historical_data(
    ticker: str,
    duration: str = "1 D",
    bar_size: str = "1 min",
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
            useRTH=True,  # Regular Trading Hours only
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

