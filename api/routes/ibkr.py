"""IBKR REST API routes — connection, status, orders, positions, settings."""

import asyncio
import json
import logging
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from api.dependencies import require_api_key
from config.time_utils import parse_timestamp
from db.connection import DB_PATH, DB_LOCK
from db.queries import get_app_settings, set_app_setting, get_live_orders, count_live_orders

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
async def ibkr_disconnect(_auth=Depends(require_api_key)):
    """Disconnect from IB Gateway."""
    from ibkr.order_book import unsubscribe_all
    from ibkr.client import disconnect

    # Clear depth subscriptions so reconnect can cleanly resubscribe.
    try:
        await unsubscribe_all()
    except Exception as e:
        logger.warning(f"[IBKR] Failed to clear order-book subscriptions on disconnect: {e}")

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
        "require_live_confirm": cfg.get("require_live_confirm", "1"),
    }


@router.post("/settings")
def ibkr_update_settings(payload: dict, _auth=Depends(require_api_key)):
    """Update IBKR connection settings in app_settings."""
    allowed = {"ibkr_enabled", "ibkr_host", "ibkr_port", "ibkr_client_id"}
    # allow updating the optional safety toggle
    allowed.add("require_live_confirm")
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
def ibkr_orders(
    hwnd: int = None,
    bot_id: str = None,
    limit: Optional[int] = None,
    offset: int = 0,
    _auth=Depends(require_api_key),
):
    """Return live orders with optional filters and optional pagination."""
    total = count_live_orders(hwnd=hwnd, bot_id=bot_id)
    orders = get_live_orders(hwnd=hwnd, bot_id=bot_id, limit=limit, offset=offset)
    return JSONResponse(content={"orders": orders}, headers={"X-Total-Count": str(total)})


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

@router.get("/positions")
async def ibkr_positions(_auth=Depends(require_api_key)):
    """Return current account positions from IBKR."""
    from ibkr.account import get_positions

    return {"positions": await get_positions()}


@router.post("/refresh")
async def ibkr_refresh(_auth=Depends(require_api_key)):
    """Force refresh of IBKR account data (positions, account summary, orders)."""
    from ibkr.client import is_connected
    from ibkr.account import get_positions, get_account_summary, get_open_orders

    if not is_connected():
        raise HTTPException(status_code=503, detail="Not connected to IB Gateway")

    try:
        # Fetch fresh data from IBKR
        account = await get_account_summary()
        positions = await get_positions()
        open_orders = await get_open_orders()

        return {
            "ok": True,
            "account": account,
            "positions": positions,
            "open_orders": open_orders,
        }
    except Exception as e:
        logger.error(f"[IBKR] Refresh failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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


# ---------------------------------------------------------------------------
# Historical Data (for charting)
# ---------------------------------------------------------------------------

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


def _to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _format_ibkr_end(dt: datetime) -> str:
    return dt.strftime("%Y%m%d %H:%M:%S") + " UTC"


def _format_utc_z(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None).isoformat() + "Z"


def _duration_from_range(start_dt: datetime, end_dt: datetime) -> str:
    total_seconds = max(1, int((end_dt - start_dt).total_seconds()))
    if total_seconds <= 86400:
        return f"{total_seconds} S"
    total_days = max(1, int(math.ceil(total_seconds / 86400)))
    if total_days <= 7:
        return f"{total_days} D"
    total_weeks = max(1, int(math.ceil(total_days / 7)))
    if total_weeks <= 4:
        return f"{total_weeks} W"
    total_months = max(1, int(math.ceil(total_days / 30)))
    return f"{total_months} M"


@router.get("/replay/{ticker}")
async def ibkr_replay_window(
    ticker: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    buy_time: Optional[str] = None,
    sell_time: Optional[str] = None,
    buffer_min: int = 10,
    bar_size: str = "1 min",
    use_rth: bool = True,
    _auth=Depends(require_api_key),
):
    """Fetch historical bars for a focused replay window.

    Args:
        ticker: Stock symbol (e.g. AAPL)
        start/end: Optional ISO timestamps for the desired window
        buy_time/sell_time: Optional trade timestamps used when start/end are missing
        buffer_min: Minutes to pad before/after the trade window
        bar_size: Bar size setting (e.g. "1 min")

    Returns:
        {ok: true, ticker, start, end, bars}
    """
    from ibkr.client import ib, is_connected

    if not is_connected() or ib is None:
        raise HTTPException(status_code=503, detail="Not connected to IB Gateway")

    start_dt = parse_timestamp(start) or parse_timestamp(buy_time)
    end_dt = parse_timestamp(end) or parse_timestamp(sell_time)

    if start_dt is None and end_dt is None:
        # Fall back to default historical range if no window is provided.
        return await ibkr_historical_data(ticker, duration="1 D", bar_size=bar_size, use_rth=use_rth)

    if start_dt is None and end_dt is not None:
        start_dt = end_dt - timedelta(minutes=max(1, int(buffer_min)))
    if end_dt is None and start_dt is not None:
        end_dt = start_dt + timedelta(minutes=max(1, int(buffer_min)))

    if start_dt is None or end_dt is None:
        raise HTTPException(status_code=400, detail="Missing valid replay timestamps")

    buffer_delta = timedelta(minutes=max(0, int(buffer_min)))
    start_dt = start_dt - buffer_delta
    end_dt = end_dt + buffer_delta
    if end_dt < start_dt:
        start_dt, end_dt = end_dt, start_dt

    start_dt = _to_utc_naive(start_dt)
    end_dt = _to_utc_naive(end_dt)
    duration = _duration_from_range(start_dt, end_dt)
    end_str = _format_ibkr_end(end_dt)

    try:
        from ib_async import Stock
        contract = Stock(ticker.upper(), "SMART", "USD")
        await ib.qualifyContractsAsync(contract)

        bars = await ib.reqHistoricalDataAsync(
            contract,
            endDateTime=end_str,
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=bool(use_rth),
            formatDate=1,
        )

        result = []
        for bar in bars:
            bar_time_str = bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date)
            # Parse the bar time to filter to the exact window
            try:
                bar_ts = parse_timestamp(bar_time_str)
                if bar_ts is not None:
                    bar_ts_naive = _to_utc_naive(bar_ts)
                    if bar_ts_naive < start_dt or bar_ts_naive > end_dt:
                        continue  # skip bars outside the requested window
            except Exception:
                pass  # if parse fails, include the bar
            result.append({
                "time": bar_time_str,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            })

        # Fallback: if strict filtering emptied all bars but IBKR did return bars,
        # return all of them (e.g. weekend/after-hours trade fallback).
        if not result and bars:
            for bar in bars:
                bar_time_str = bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date)
                result.append({
                    "time": bar_time_str,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                })

        return {
            "ok": True,
            "ticker": ticker.upper(),
            "start": start_dt.isoformat() + "Z",
            "end": end_dt.isoformat() + "Z",
            "bars": result,
        }
    except Exception as e:
        logger.error(f"[IBKR] Replay window failed for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _load_trade_replay(trade_ref_id: str) -> Optional[dict]:
    if not trade_ref_id:
        return None
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM trade_replays WHERE trade_ref_id = ? LIMIT 1", (trade_ref_id,))
        row = cur.fetchone()
        conn.close()
    if not row:
        return None
    try:
        bars = json.loads(row["bars"]) if row["bars"] else []
    except Exception:
        bars = []
    try:
        order_book = json.loads(row["order_book"]) if row["order_book"] else None
    except Exception:
        order_book = None
    return {
        "ok": True,
        "saved": True,
        "trade_ref_id": row["trade_ref_id"],
        "ticker": row["ticker"],
        "start": row["start_ts"],
        "end": row["end_ts"],
        "bar_size": row["bar_size"],
        "bars": bars,
        "order_book": order_book,
        "created_at": row["created_at"],
    }


def _store_trade_replay(
    trade_ref_id: str,
    ticker: str,
    start_ts: Optional[str],
    end_ts: Optional[str],
    bar_size: str,
    bars: list,
    order_book: Optional[dict],
) -> dict:
    if not bars:
        return {
            "ok": True,
            "saved": False,
            "trade_ref_id": trade_ref_id,
            "ticker": ticker,
            "start": start_ts,
            "end": end_ts,
            "bar_size": bar_size,
            "bars": [],
            "order_book": None,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }

    created_at = datetime.utcnow().isoformat() + "Z"
    bars_json = json.dumps(bars or [])
    order_book_json = json.dumps(order_book) if order_book is not None else None
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM trade_replays WHERE trade_ref_id = ?", (trade_ref_id,))
        row = cur.fetchone()
        if row:
            cur.execute(
                """
                UPDATE trade_replays
                SET ticker = ?, start_ts = ?, end_ts = ?, bar_size = ?, bars = ?, order_book = ?, created_at = ?
                WHERE trade_ref_id = ?
                """,
                (ticker, start_ts, end_ts, bar_size, bars_json, order_book_json, created_at, trade_ref_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO trade_replays (trade_ref_id, ticker, start_ts, end_ts, bar_size, bars, order_book, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (trade_ref_id, ticker, start_ts, end_ts, bar_size, bars_json, order_book_json, created_at),
            )
        conn.commit()
        conn.close()
    return {
        "ok": True,
        "saved": True,
        "trade_ref_id": trade_ref_id,
        "ticker": ticker,
        "start": start_ts,
        "end": end_ts,
        "bar_size": bar_size,
        "bars": bars or [],
        "order_book": order_book,
        "created_at": created_at,
    }


@router.get("/replay/saved/{trade_ref_id}")
def ibkr_get_saved_replay(trade_ref_id: str, _auth=Depends(require_api_key)):
    saved = _load_trade_replay(str(trade_ref_id))
    if not saved:
        raise HTTPException(status_code=404, detail="Replay not found")
    return saved


@router.post("/replay/save")
async def ibkr_save_replay(payload: dict, _auth=Depends(require_api_key)):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")

    trade_ref_id = str(payload.get("trade_ref_id") or payload.get("trade_id") or "").strip()
    ticker = str(payload.get("ticker") or "").strip().upper()
    if not trade_ref_id:
        raise HTTPException(status_code=400, detail="trade_ref_id is required")
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")

    bar_size = str(payload.get("bar_size") or "1 min")
    buffer_min = int(payload.get("buffer_min") or 10)
    include_order_book = bool(payload.get("include_order_book", True))

    replay = await ibkr_replay_window(
        ticker,
        start=payload.get("start"),
        end=payload.get("end"),
        buy_time=payload.get("buy_time"),
        sell_time=payload.get("sell_time"),
        buffer_min=buffer_min,
        bar_size=bar_size,
        _auth=True,
    )

    bars = replay.get("bars") if isinstance(replay, dict) else []
    start_ts = replay.get("start") if isinstance(replay, dict) else None
    end_ts = replay.get("end") if isinstance(replay, dict) else None

    if not start_ts or not end_ts:
        times = []
        for bar in bars or []:
            parsed = parse_timestamp(bar.get("time")) if isinstance(bar, dict) else None
            if parsed:
                times.append(parsed)
        if times:
            start_ts = _format_utc_z(min(times))
            end_ts = _format_utc_z(max(times))

    order_book = None
    if include_order_book and start_ts and end_ts:
        try:
            from ibkr.order_book_history import get_order_book_history
            order_book = get_order_book_history(ticker, start=start_ts, end=end_ts, max_points=2000)
        except Exception:
            order_book = None

    return _store_trade_replay(
        trade_ref_id=trade_ref_id,
        ticker=ticker,
        start_ts=start_ts,
        end_ts=end_ts,
        bar_size=bar_size,
        bars=bars or [],
        order_book=order_book,
    )


async def _auto_save_trade_replay(
    trade_ref_id: str,
    ticker: str,
    buy_time: Optional[str],
    sell_time: Optional[str],
    buffer_min: int = 5,
    bar_size: str = "1 min",
) -> None:
    """Fire-and-forget: fetch bars around a completed trade and save to DB.

    Called automatically by the order router after a SELL fill is confirmed.
    Runs in the background — any failure is logged but never propagates.
    """
    try:
        from ibkr.client import is_connected
        if not is_connected():
            logger.info("[IBKR] _auto_save_trade_replay: not connected, skipping auto-save")
            return

        # Check if we already have a saved replay for this trade
        existing = _load_trade_replay(trade_ref_id)
        if existing and existing.get("bars"):
            logger.debug(f"[IBKR] Replay already saved for {trade_ref_id}, skipping auto-save")
            return

        logger.info(f"[IBKR] Auto-saving replay for trade {trade_ref_id} ({ticker})")

        replay = await ibkr_replay_window(
            ticker=ticker,
            start=None,
            end=None,
            buy_time=buy_time,
            sell_time=sell_time,
            buffer_min=buffer_min,
            bar_size=bar_size,
            _auth=True,
        )

        bars = replay.get("bars") if isinstance(replay, dict) else []
        start_ts = replay.get("start") if isinstance(replay, dict) else None
        end_ts = replay.get("end") if isinstance(replay, dict) else None

        if not bars:
            logger.warning(f"[IBKR] Auto-save: no bars returned for trade {trade_ref_id}")
            return

        # Try to get order book data for the window
        order_book = None
        if start_ts and end_ts:
            try:
                from ibkr.order_book_history import get_order_book_history
                order_book = get_order_book_history(ticker, start=start_ts, end=end_ts, max_points=2000)
            except Exception:
                order_book = None

        _store_trade_replay(
            trade_ref_id=trade_ref_id,
            ticker=ticker,
            start_ts=start_ts,
            end_ts=end_ts,
            bar_size=bar_size,
            bars=bars,
            order_book=order_book,
        )
        logger.info(f"[IBKR] Auto-saved {len(bars)} bars for trade {trade_ref_id}")
    except Exception as e:
        logger.warning(f"[IBKR] _auto_save_trade_replay failed (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Rule 14 — History Graph Trend Auto-Trader
# ---------------------------------------------------------------------------

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
    configure_r14(
        hwnd,
        enabled=bool(payload.get('enabled', False)),
        qty=int(payload.get('qty', 1)),
        stop_loss_pct=float(payload.get('stop_loss_pct', 0.0)),
        cooldown_secs=float(payload.get('cooldown_secs', 0.0)),
        slope_threshold=slope_threshold_pct / 100.0,  # convert % to fraction
    )
    return {'ok': True, 'state': r14_state_for_frontend(hwnd)}


@router.get("/rule14/state/{hwnd}")
async def rule14_state(hwnd: int, _auth=Depends(require_api_key)):
    """Return current R14 runtime state for a bot (position, trend, P&L, etc.)."""
    from trading.rule14 import r14_state_for_frontend
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

    # Build a minimal bot_row using R14 qty
    bot_row = {
        'live_trading_enabled': True,
        'ticker': ticker,
        'qty': s.qty,
        'order_size': s.qty,
        'buy_order_type': 'limit',
        'sell_order_type': 'limit',
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
