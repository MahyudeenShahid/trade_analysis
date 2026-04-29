"""Level 2 order book (market depth) subscriptions and in-memory cache.

IBKR reqMktDepth gives up to 20 price levels per side.
isSmartDepth=True routes across all exchanges (SmartRouting).

Usage:
    await subscribe_depth("AAPL")
    snap = get_snapshot("AAPL")   # {"bids": [...], "asks": [...]}
"""

import asyncio
import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ticker → {"bids": [{price, size, mm}...], "asks": [...]}
_depth_cache: Dict[str, dict] = {}
# ticker → ib Ticker object returned by reqMktDepth
_subscriptions: Dict[str, object] = {}
# ticker -> reqId used for reqMktDepth
_subscription_req_ids: Dict[str, int] = {}
# ticker -> exchange used for reqMktDepth subscription
_subscription_exchange: Dict[str, str] = {}
# ticker -> isSmartDepth flag used for reqMktDepth
_subscription_smart_depth: Dict[str, bool] = {}
# ticker -> ib Ticker object returned by reqMktData (best bid/ask fallback)
_top_subscriptions: Dict[str, object] = {}
# ticker -> reqId used for reqMktData fallback subscription
_top_subscription_req_ids: Dict[str, int] = {}
# reqId -> ticker mapping for error correlation
_req_id_to_ticker: Dict[int, str] = {}
# ticker → unix timestamp of latest depth update
_depth_last_update: Dict[str, float] = {}
# ticker -> latest top-of-book (bid/ask) update
_top_book_cache: Dict[str, dict] = {}
# ticker -> last IB API error seen for this depth stream
_last_error_by_ticker: Dict[str, dict] = {}
# most recent IB API error across all requests
_last_error_global: dict = {}

_STALE_SUB_SECONDS = 20.0
_PRICE_HISTORY_WINDOW_SECONDS = 20 * 60
_PRICE_SAMPLE_INTERVAL_SECONDS = 60

# ticker -> list of {ts, price} samples (rolling window)
_price_history: Dict[str, list] = {}
# ticker -> last sample timestamp (to control sampling cadence)
_last_price_sample_ts: Dict[str, float] = {}


def get_snapshot(ticker: str) -> dict:
    """Return the latest cached depth for ticker, or empty structure."""
    return _depth_cache.get(ticker, {"bids": [], "asks": []})


def get_all_snapshots() -> dict:
    """Return all cached order book snapshots keyed by ticker."""
    return dict(_depth_cache)


def _safe_positive_float(value):
    """Parse value into a positive float or None."""
    try:
        num = float(value)
    except Exception:
        return None
    return num if num > 0 else None


def _safe_non_negative_float(value, default: float = 0.0) -> float:
    """Parse value into a non-negative float with default fallback."""
    try:
        num = float(value)
    except Exception:
        return default
    return num if num >= 0 else default


def _build_bbo_rows(top_book: Optional[dict]):
    """Convert best-bid/ask into depth-like rows for UI compatibility."""
    if not isinstance(top_book, dict):
        return [], []

    bid = _safe_positive_float(top_book.get("bid"))
    ask = _safe_positive_float(top_book.get("ask"))
    bid_size = _safe_non_negative_float(top_book.get("bid_size"), default=0.0)
    ask_size = _safe_non_negative_float(top_book.get("ask_size"), default=0.0)

    bids = [{"price": bid, "size": bid_size, "mm": "BBO"}] if bid is not None else []
    asks = [{"price": ask, "size": ask_size, "mm": "BBO"}] if ask is not None else []
    return bids, asks


def _record_price_sample(ticker: str, price: Optional[float], ts: Optional[float] = None):
    if price is None:
        return

    ts = float(ts if ts is not None else time.time())
    last_ts = _last_price_sample_ts.get(ticker)
    if last_ts is not None and (ts - last_ts) < _PRICE_SAMPLE_INTERVAL_SECONDS:
        return

    _last_price_sample_ts[ticker] = ts
    history = _price_history.setdefault(ticker, [])
    history.append({"ts": ts, "price": float(price)})

    cutoff = ts - _PRICE_HISTORY_WINDOW_SECONDS
    while history and history[0].get("ts", 0) < cutoff:
        history.pop(0)


def get_price_history(ticker: str, lookback_seconds: int = _PRICE_HISTORY_WINDOW_SECONDS) -> list:
    """Return recent price samples for RSI/Bollinger calculations."""
    ticker = str(ticker or "").strip().upper()
    history = _price_history.get(ticker) or []
    if not history:
        return []

    cutoff = time.time() - float(lookback_seconds or _PRICE_HISTORY_WINDOW_SECONDS)
    return [row.get("price") for row in history if row.get("ts", 0) >= cutoff]


def _cancel_top_of_book_subscription(ticker: str):
    """Cancel reqMktData fallback stream for ticker and clear its cache."""
    from .client import ib

    sub = _top_subscriptions.pop(ticker, None)
    req_id = _top_subscription_req_ids.pop(ticker, None)
    if req_id is not None:
        _req_id_to_ticker.pop(req_id, None)
    _top_book_cache.pop(ticker, None)

    if sub is not None and ib is not None:
        try:
            ib.cancelMktData(sub.contract)
        except Exception:
            pass


def _ensure_top_of_book_subscription(ticker: str, contract):
    """Ensure reqMktData best-bid/ask fallback is active for this ticker."""
    from .client import ib, is_connected

    if ticker in _top_subscriptions:
        return
    if ib is None or not is_connected():
        return

    try:
        # Keep this lightweight: no generic ticks, no snapshot mode.
        top_ticker = ib.reqMktData(contract, "", False, False)
    except Exception as e:
        logger.debug("[IBKR OrderBook] Could not start top-of-book fallback for %s: %s", ticker, e)
        return

    _top_subscriptions[ticker] = top_ticker

    # Correlate reqId -> ticker for fallback stream errors as well.
    try:
        req_map = getattr(getattr(ib, "wrapper", None), "ticker2ReqId", None)
        mkt_data_map = req_map.get("mktData", {}) if hasattr(req_map, "get") else {}
        req_id_raw = mkt_data_map.get(top_ticker) if hasattr(mkt_data_map, "get") else None
        if req_id_raw is not None:
            req_id = int(req_id_raw)
            _top_subscription_req_ids[ticker] = req_id
            _req_id_to_ticker[req_id] = ticker
    except Exception:
        pass

    def on_top_update(ticker_obj):
        bid = _safe_positive_float(getattr(ticker_obj, "bid", None))
        ask = _safe_positive_float(getattr(ticker_obj, "ask", None))
        bid_size = _safe_non_negative_float(getattr(ticker_obj, "bidSize", None), default=0.0)
        ask_size = _safe_non_negative_float(getattr(ticker_obj, "askSize", None), default=0.0)

        if bid is None and ask is None:
            return

        ts = time.time()
        top_book = {
            "bid": bid,
            "ask": ask,
            "bid_size": bid_size,
            "ask_size": ask_size,
            "ts": ts,
        }
        _top_book_cache[ticker] = top_book

        mid_price = None
        if bid is not None and ask is not None:
            mid_price = (bid + ask) / 2.0
        elif bid is not None:
            mid_price = bid
        elif ask is not None:
            mid_price = ask
        _record_price_sample(ticker, mid_price, ts)

        # Only overwrite cached rows while L2 is absent; once true DOM appears,
        # keep L2 as authoritative.
        snap = _depth_cache.get(ticker) or {}
        has_l2 = (
            str(snap.get("source") or "").upper() == "L2"
            and bool((snap.get("bids") or []) or (snap.get("asks") or []))
        )
        if has_l2:
            return

        bids, asks = _build_bbo_rows(top_book)
        if bids or asks:
            _depth_cache[ticker] = {"bids": bids, "asks": asks, "source": "BBO"}
            _depth_last_update[ticker] = ts
            _last_error_by_ticker.pop(ticker, None)

    top_ticker.updateEvent += on_top_update


def resolve_ticker_for_req_id(req_id) -> Optional[str]:
    """Best-effort resolve of IB reqId back to ticker for depth requests."""
    try:
        req_id_int = int(req_id)
    except Exception:
        return None
    return _req_id_to_ticker.get(req_id_int)


def record_ib_error(req_id, code, message: str) -> Optional[str]:
    """Record latest IB API error and associate it to ticker when possible."""
    global _last_error_global

    try:
        req_id_int = int(req_id)
    except Exception:
        req_id_int = None

    entry = {
        "req_id": req_id_int,
        "code": code,
        "message": str(message or ""),
        "ts": time.time(),
    }
    _last_error_global = entry

    ticker = resolve_ticker_for_req_id(req_id_int) if req_id_int is not None else None
    if ticker:
        _last_error_by_ticker[ticker] = entry
    return ticker


def get_depth_diagnostics(ticker: str) -> dict:
    """Return detailed diagnostics for a ticker depth subscription."""
    ticker = str(ticker or "").strip().upper()
    snapshot = get_snapshot(ticker)
    bids = snapshot.get("bids") or []
    asks = snapshot.get("asks") or []
    source = str(snapshot.get("source") or "").upper() or None
    last_update = _depth_last_update.get(ticker)
    age = None
    if last_update:
        age = round(max(0.0, time.time() - float(last_update)), 3)

    top_book = _top_book_cache.get(ticker)
    top_book_ts = top_book.get("ts") if isinstance(top_book, dict) else None
    top_book_age = None
    if top_book_ts:
        top_book_age = round(max(0.0, time.time() - float(top_book_ts)), 3)

    return {
        "ticker": ticker,
        "subscribed": ticker in _subscriptions,
        "top_of_book_subscribed": ticker in _top_subscriptions,
        "req_id": _subscription_req_ids.get(ticker),
        "top_req_id": _top_subscription_req_ids.get(ticker),
        "exchange": _subscription_exchange.get(ticker),
        "is_smart_depth": _subscription_smart_depth.get(ticker),
        "source": source,
        "has_depth": bool(bids or asks),
        "bid_levels": len(bids),
        "ask_levels": len(asks),
        "last_update_unix": last_update,
        "last_update_age_sec": age,
        "top_of_book": top_book or None,
        "top_of_book_age_sec": top_book_age,
        "last_error": _last_error_by_ticker.get(ticker),
        "last_error_global": _last_error_global or None,
    }


async def subscribe_depth(
    ticker: str,
    exchange: str = "SMART",
    num_rows: int = 5,
    force: bool = False,
    is_smart_depth: bool = True,
) -> bool:
    """Subscribe to Level 2 market depth for a ticker.

    Safe to call multiple times for the same ticker.
    If force=True, existing subscription is cancelled and recreated.
    If a subscription exists but no depth is received for a while, it is recreated.
    Requires an active IB connection (ibkr/client.py).
    """
    from .client import ib, is_connected

    ticker = str(ticker or "").strip().upper()
    exchange = str(exchange or "SMART").strip().upper()
    is_smart_depth = bool(is_smart_depth)
    if not ticker:
        return False

    now = time.time()
    existing = _subscriptions.get(ticker)

    if existing is not None and not force:
        snap = _depth_cache.get(ticker) or {}
        has_depth = bool((snap.get("bids") or []) or (snap.get("asks") or []))
        last_update = _depth_last_update.get(ticker, 0.0)
        age = (now - last_update) if last_update else None
        stale = ((age is None) and (not has_depth)) or ((age is not None) and (age > _STALE_SUB_SECONDS))
        if not stale:
            return True
        logger.warning(
            "[IBKR OrderBook] %s subscription stale (has_depth=%s age=%s) — resubscribing",
            ticker,
            has_depth,
            f"{age:.1f}s" if age is not None else "never",
        )

    if existing is not None:
        try:
            if ib is not None and is_connected():
                prev_smart_depth = _subscription_smart_depth.get(ticker, True)
                ib.cancelMktDepth(existing.contract, isSmartDepth=bool(prev_smart_depth))
        except Exception:
            pass
        req_id = _subscription_req_ids.pop(ticker, None)
        if req_id is not None:
            _req_id_to_ticker.pop(req_id, None)
        _subscription_exchange.pop(ticker, None)
        _subscription_smart_depth.pop(ticker, None)
        _subscriptions.pop(ticker, None)
        _cancel_top_of_book_subscription(ticker)
        _depth_cache.pop(ticker, None)
        _depth_last_update.pop(ticker, None)
        _last_error_by_ticker.pop(ticker, None)

    if not is_connected() or ib is None:
        logger.warning(f"[IBKR OrderBook] Not connected — cannot subscribe to {ticker}")
        return False

    try:
        from ib_async import Stock
        contract = Stock(ticker, exchange, "USD")
        await ib.qualifyContractsAsync(contract)

        depth_ticker = ib.reqMktDepth(contract, numRows=num_rows, isSmartDepth=is_smart_depth)
        _subscriptions[ticker] = depth_ticker
        _subscription_exchange[ticker] = exchange
        _subscription_smart_depth[ticker] = is_smart_depth
        _depth_cache.setdefault(ticker, {"bids": [], "asks": [], "source": None})

        # Parallel top-of-book stream provides best-bid/ask fallback when
        # Level 2 rows are unavailable for this symbol/account/venue.
        _ensure_top_of_book_subscription(ticker, contract)

        # Correlate IB reqId -> ticker so errorEvent can tell which symbol failed.
        try:
            req_map = getattr(getattr(ib, "wrapper", None), "ticker2ReqId", None)
            mkt_depth_map = req_map.get("mktDepth", {}) if hasattr(req_map, "get") else {}
            req_id_raw = mkt_depth_map.get(depth_ticker) if hasattr(mkt_depth_map, "get") else None
            if req_id_raw is not None:
                req_id = int(req_id_raw)
                _subscription_req_ids[ticker] = req_id
                _req_id_to_ticker[req_id] = ticker
        except Exception:
            pass

        def on_depth_update(ticker_obj):
            dom_bids = [
                {"price": r.price, "size": r.size, "mm": getattr(r, "marketMaker", "")}
                for r in (ticker_obj.domBids or [])
            ]
            dom_asks = [
                {"price": r.price, "size": r.size, "mm": getattr(r, "marketMaker", "")}
                for r in (ticker_obj.domAsks or [])
            ]

            if dom_bids or dom_asks:
                bids, asks = dom_bids, dom_asks
                source = "L2"
            else:
                bids, asks = _build_bbo_rows(_top_book_cache.get(ticker))
                source = "BBO" if (bids or asks) else None

            _depth_cache[ticker] = {"bids": bids, "asks": asks, "source": source}
            if bids or asks:
                _depth_last_update[ticker] = time.time()
            if bids or asks:
                _last_error_by_ticker.pop(ticker, None)

            best_bid = bids[0].get("price") if bids else None
            best_ask = asks[0].get("price") if asks else None
            mid_price = None
            if best_bid is not None and best_ask is not None:
                mid_price = (float(best_bid) + float(best_ask)) / 2.0
            elif best_bid is not None:
                mid_price = float(best_bid)
            elif best_ask is not None:
                mid_price = float(best_ask)
            _record_price_sample(ticker, mid_price)

        depth_ticker.updateEvent += on_depth_update
        logger.info(
            "[IBKR OrderBook] Subscribed to depth for %s (exchange=%s isSmartDepth=%s rows=%s)",
            ticker,
            exchange,
            is_smart_depth,
            num_rows,
        )
        return True

    except Exception as e:
        logger.error(f"[IBKR OrderBook] subscribe_depth({ticker}) failed: {e}")
        return False


async def unsubscribe_depth(ticker: str):
    """Cancel depth subscription for a ticker."""
    from .client import ib

    sub = _subscriptions.pop(ticker, None)
    smart_depth = _subscription_smart_depth.get(ticker, True)
    req_id = _subscription_req_ids.pop(ticker, None)
    if req_id is not None:
        _req_id_to_ticker.pop(req_id, None)
    _subscription_exchange.pop(ticker, None)
    _subscription_smart_depth.pop(ticker, None)
    _cancel_top_of_book_subscription(ticker)
    _depth_cache.pop(ticker, None)
    _depth_last_update.pop(ticker, None)
    _last_error_by_ticker.pop(ticker, None)
    _price_history.pop(ticker, None)
    _last_price_sample_ts.pop(ticker, None)
    if sub is not None and ib is not None:
        try:
            ib.cancelMktDepth(sub.contract, isSmartDepth=bool(smart_depth))
        except Exception:
            pass


async def unsubscribe_all():
    """Cancel all depth subscriptions — call on shutdown."""
    for ticker in list(_subscriptions.keys()):
        await unsubscribe_depth(ticker)


def clear_all_depth_cache():
    """Clear all cached DOM rows.

    IBKR error 317 explicitly requires clearing deep-book contents before
    applying subsequent incremental updates.
    """
    for ticker in list(_depth_cache.keys()):
        _depth_cache[ticker] = {"bids": [], "asks": []}


async def resubscribe_all(force: bool = True):
    """Resubscribe all currently tracked depth tickers.

    Useful after IBKR notifies that market data requests were lost.
    """
    tickers = list(_subscriptions.keys())
    for ticker in tickers:
        try:
            exchange = _subscription_exchange.get(ticker, "SMART")
            smart_depth = _subscription_smart_depth.get(ticker, True)
            await subscribe_depth(ticker, exchange=exchange, force=force, is_smart_depth=smart_depth)
        except Exception as e:
            logger.warning(f"[IBKR OrderBook] resubscribe_all failed for {ticker}: {e}")
