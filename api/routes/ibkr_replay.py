"""IBKR trade replay extraction and persistence REST API routes."""

import json
import logging
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from api.dependencies import require_api_key
from config.time_utils import parse_timestamp
from db.connection import DB_PATH, DB_LOCK

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["ibkr"])


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
    from .ibkr_book import ibkr_historical_data

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
