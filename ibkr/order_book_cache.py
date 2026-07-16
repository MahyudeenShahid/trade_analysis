"""In-memory cache and price/volume rolling history metrics for Level 2 depth subscriptions."""

import time
from typing import Dict, Optional

# Ticker → {"bids": [{price, size, mm}...], "asks": [...]}
_depth_cache: Dict[str, dict] = {}
# Ticker → ib Ticker object returned by reqMktDepth
_subscriptions: Dict[str, object] = {}
# Ticker -> reqId used for reqMktDepth
_subscription_req_ids: Dict[str, int] = {}
# Ticker -> exchange used for reqMktDepth subscription
_subscription_exchange: Dict[str, str] = {}
# Ticker -> isSmartDepth flag used for reqMktDepth
_subscription_smart_depth: Dict[str, bool] = {}
# Ticker -> ib Ticker object returned by reqMktData (best bid/ask fallback)
_top_subscriptions: Dict[str, object] = {}
# Ticker -> reqId used for reqMktData fallback subscription
_top_subscription_req_ids: Dict[str, int] = {}
# Ticker -> trade (tick-by-tick) subscription ticker object
_trade_subscriptions: Dict[str, object] = {}
# Ticker -> reqId used for tick-by-tick trades
_trade_subscription_req_ids: Dict[str, int] = {}
# reqId -> ticker mapping for error correlation
_req_id_to_ticker: Dict[int, str] = {}
# Ticker → unix timestamp of latest depth update
_depth_last_update: Dict[str, float] = {}
# Ticker -> latest top-of-book (bid/ask) update
_top_book_cache: Dict[str, dict] = {}
# Ticker -> last IB API error seen for this depth stream
_last_error_by_ticker: Dict[str, dict] = {}
# Most recent IB API error across all requests
_last_error_global: dict = {}

_STALE_SUB_SECONDS = 20.0
# Price history retention and sampling cadence
_PRICE_HISTORY_WINDOW_SECONDS = 20 * 60
# Default min interval between sampled entries (seconds)
_PRICE_SAMPLE_INTERVAL_SECONDS = 0.25

# Ticker -> list of {ts, price, volume} samples (rolling window)
_price_history: Dict[str, list] = {}
# Ticker -> last sample timestamp
_last_price_sample_ts: Dict[str, float] = {}


def get_snapshot(ticker: str) -> dict:
    """Return the latest cached depth for ticker, or empty structure."""
    return _depth_cache.get(ticker, {"bids": [], "asks": []})


def get_all_snapshots() -> dict:
    """Return all cached order book snapshots keyed by ticker."""
    return dict(_depth_cache)


def get_top_of_book(ticker: str) -> Optional[dict]:
    """Return the latest top-of-book cache for ticker, or None."""
    ticker = str(ticker or "").strip().upper()
    if not ticker:
        return None
    return _top_book_cache.get(ticker)


def get_mid_price(ticker: str) -> Optional[float]:
    """Return mid price from top-of-book (bid/ask), or None when unavailable."""
    top_book = get_top_of_book(ticker)
    if not isinstance(top_book, dict):
        return None
    bid = _safe_positive_float(top_book.get("bid"))
    ask = _safe_positive_float(top_book.get("ask"))
    if bid is not None and ask is not None:
        return round((bid + ask) / 2.0, 6)
    return bid if bid is not None else ask


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


def _record_price_sample(
    ticker: str,
    price: Optional[float],
    volume: Optional[float] = 0.0,
    ts: Optional[float] = None,
    force: bool = False,
    source: Optional[str] = None,
):
    """Record a timestamped price sample with optional associated volume."""
    if price is None:
        return

    ts = float(ts if ts is not None else time.time())
    last_ts = _last_price_sample_ts.get(ticker)
    if not force and last_ts is not None and (ts - last_ts) < _PRICE_SAMPLE_INTERVAL_SECONDS:
        return

    _last_price_sample_ts[ticker] = ts
    history = _price_history.setdefault(ticker, [])
    history.append(
        {
            "ts": ts,
            "price": float(price),
            "volume": float(volume or 0.0),
            "source": (str(source).strip().lower() if source else "quote"),
        }
    )

    cutoff = ts - _PRICE_HISTORY_WINDOW_SECONDS
    while history and history[0].get("ts", 0) < cutoff:
        history.pop(0)


def get_price_history(ticker: str, lookback_seconds: int = _PRICE_HISTORY_WINDOW_SECONDS, raw: bool = False) -> list:
    """Return recent price samples."""
    ticker = str(ticker or "").strip().upper()
    history = _price_history.get(ticker) or []
    if not history:
        return []

    cutoff = time.time() - float(lookback_seconds or _PRICE_HISTORY_WINDOW_SECONDS)
    rows = [row for row in history if row.get("ts", 0) >= cutoff]
    return rows if raw else [row.get("price") for row in rows]


def get_price_volume_history(ticker: str, lookback_seconds: int = _PRICE_SAMPLE_INTERVAL_SECONDS * 20) -> list:
    """Return recent timestamped `{ts, price, volume}` samples for a ticker."""
    return get_price_history(ticker, lookback_seconds=lookback_seconds, raw=True)


def get_aggregate_volume(ticker: str, lookback_seconds: int = 60) -> float:
    """Return aggregated sample volume over the past `lookback_seconds` seconds."""
    rows = get_price_volume_history(ticker, lookback_seconds=lookback_seconds)
    if not rows:
        return 0.0
    try:
        return sum(float(r.get('volume', 0.0) or 0.0) for r in rows)
    except Exception:
        return 0.0
