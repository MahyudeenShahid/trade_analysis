"""Level 2 order book (market depth) subscriptions and in-memory cache.

IBKR reqMktDepth gives up to 20 price levels per side.
isSmartDepth=True routes across all exchanges (SmartRouting).

Usage:
    await subscribe_depth("AAPL")
    snap = get_snapshot("AAPL")   # {"bids": [...], "asks": [...]}
"""

import asyncio
import logging
from typing import Dict

logger = logging.getLogger(__name__)

# ticker → {"bids": [{price, size, mm}...], "asks": [...]}
_depth_cache: Dict[str, dict] = {}
# ticker → ib Ticker object returned by reqMktDepth
_subscriptions: Dict[str, object] = {}


def get_snapshot(ticker: str) -> dict:
    """Return the latest cached depth for ticker, or empty structure."""
    return _depth_cache.get(ticker, {"bids": [], "asks": []})


def get_all_snapshots() -> dict:
    """Return all cached order book snapshots keyed by ticker."""
    return dict(_depth_cache)


async def subscribe_depth(ticker: str, exchange: str = "SMART", num_rows: int = 20):
    """Subscribe to Level 2 market depth for a ticker.

    Safe to call multiple times for the same ticker — skips if already subscribed.
    Requires an active IB connection (ibkr/client.py).
    """
    from .client import ib, is_connected

    if ticker in _subscriptions:
        return

    if not is_connected() or ib is None:
        logger.warning(f"[IBKR OrderBook] Not connected — cannot subscribe to {ticker}")
        return

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

        depth_ticker.updateEvent += on_depth_update
        logger.info(f"[IBKR OrderBook] Subscribed to depth for {ticker}")

    except Exception as e:
        logger.error(f"[IBKR OrderBook] subscribe_depth({ticker}) failed: {e}")


async def unsubscribe_depth(ticker: str):
    """Cancel depth subscription for a ticker."""
    from .client import ib

    sub = _subscriptions.pop(ticker, None)
    _depth_cache.pop(ticker, None)
    if sub is not None and ib is not None:
        try:
            ib.cancelMktDepth(sub.contract, isSmartDepth=True)
        except Exception:
            pass


async def unsubscribe_all():
    """Cancel all depth subscriptions — call on shutdown."""
    for ticker in list(_subscriptions.keys()):
        await unsubscribe_depth(ticker)
