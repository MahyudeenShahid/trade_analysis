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
from typing import Dict

logger = logging.getLogger(__name__)

# ticker → {"bids": [{price, size, mm}...], "asks": [...]}
_depth_cache: Dict[str, dict] = {}
# ticker → ib Ticker object returned by reqMktDepth
_subscriptions: Dict[str, object] = {}
# ticker → unix timestamp of latest depth update
_depth_last_update: Dict[str, float] = {}

_STALE_SUB_SECONDS = 20.0


def get_snapshot(ticker: str) -> dict:
    """Return the latest cached depth for ticker, or empty structure."""
    return _depth_cache.get(ticker, {"bids": [], "asks": []})


def get_all_snapshots() -> dict:
    """Return all cached order book snapshots keyed by ticker."""
    return dict(_depth_cache)


async def subscribe_depth(ticker: str, exchange: str = "SMART", num_rows: int = 20, force: bool = False) -> bool:
    """Subscribe to Level 2 market depth for a ticker.

    Safe to call multiple times for the same ticker.
    If force=True, existing subscription is cancelled and recreated.
    If a subscription exists but no depth is received for a while, it is recreated.
    Requires an active IB connection (ibkr/client.py).
    """
    from .client import ib, is_connected

    ticker = str(ticker or "").strip().upper()
    if not ticker:
        return False

    now = time.time()
    existing = _subscriptions.get(ticker)

    if existing is not None and not force:
        snap = _depth_cache.get(ticker) or {}
        has_depth = bool((snap.get("bids") or []) or (snap.get("asks") or []))
        last_update = _depth_last_update.get(ticker, 0.0)
        age = (now - last_update) if last_update else None
        stale = (not has_depth) and (age is None or age > _STALE_SUB_SECONDS)
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
                ib.cancelMktDepth(existing.contract, isSmartDepth=True)
        except Exception:
            pass
        _subscriptions.pop(ticker, None)
        _depth_cache.pop(ticker, None)
        _depth_last_update.pop(ticker, None)

    if not is_connected() or ib is None:
        logger.warning(f"[IBKR OrderBook] Not connected — cannot subscribe to {ticker}")
        return False

    try:
        from ib_async import Stock
        contract = Stock(ticker, exchange, "USD")
        await ib.qualifyContractsAsync(contract)

        depth_ticker = ib.reqMktDepth(contract, numRows=num_rows, isSmartDepth=True)
        _subscriptions[ticker] = depth_ticker

        def on_depth_update(ticker_obj):
            bids = [
                {"price": r.price, "size": r.size, "mm": getattr(r, "marketMaker", "")}
                for r in (ticker_obj.domBids or [])
            ]
            asks = [
                {"price": r.price, "size": r.size, "mm": getattr(r, "marketMaker", "")}
                for r in (ticker_obj.domAsks or [])
            ]
            _depth_cache[ticker] = {"bids": bids, "asks": asks}
            _depth_last_update[ticker] = time.time()

        depth_ticker.updateEvent += on_depth_update
        logger.info(f"[IBKR OrderBook] Subscribed to depth for {ticker}")
        return True

    except Exception as e:
        logger.error(f"[IBKR OrderBook] subscribe_depth({ticker}) failed: {e}")
        return False


async def unsubscribe_depth(ticker: str):
    """Cancel depth subscription for a ticker."""
    from .client import ib

    sub = _subscriptions.pop(ticker, None)
    _depth_cache.pop(ticker, None)
    _depth_last_update.pop(ticker, None)
    if sub is not None and ib is not None:
        try:
            ib.cancelMktDepth(sub.contract, isSmartDepth=True)
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
            await subscribe_depth(ticker, force=force)
        except Exception as e:
            logger.warning(f"[IBKR OrderBook] resubscribe_all failed for {ticker}: {e}")
