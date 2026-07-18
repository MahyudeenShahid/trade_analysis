"""Level 2 order book (market depth) subscriptions and in-memory cache."""

import asyncio
import logging
import time
from typing import Optional

from .order_book_cache import (
    _depth_cache,
    _subscriptions,
    _subscription_req_ids,
    _subscription_exchange,
    _subscription_smart_depth,
    _top_subscriptions,
    _top_subscription_req_ids,
    _trade_subscriptions,
    _trade_subscription_req_ids,
    _req_id_to_ticker,
    _depth_last_update,
    _top_book_cache,
    _last_error_by_ticker,
    _last_error_global,
    _STALE_SUB_SECONDS,
    _price_history,
    _last_price_sample_ts,
    get_snapshot,
    get_all_snapshots,
    get_top_of_book,
    get_mid_price,
    _safe_positive_float,
    _safe_non_negative_float,
    _build_bbo_rows,
    _record_price_sample,
    get_price_history,
    get_price_volume_history,
    get_aggregate_volume,
)

logger = logging.getLogger(__name__)


async def ensure_top_of_book(ticker: str, exchange: str = "SMART") -> bool:
    """Ensure top-of-book subscription is active for ticker."""
    from .client import ib, is_connected

    ticker = str(ticker or "").strip().upper()
    if not ticker:
        return False
    if ticker in _top_subscriptions:
        return True
    if not is_connected() or ib is None:
        return False
    try:
        from ib_async import Stock, Crypto
        exchange_u = str(exchange or "SMART").strip().upper()
        ticker_u = str(ticker or "").strip().upper()
        if ticker_u in ("BTC", "ETH", "LTC", "BCH"):
            contract = Crypto(ticker, "PAXOS", "USD")
        else:
            contract = Stock(ticker, exchange_u, "USD")
        await ib.qualifyContractsAsync(contract)
        _ensure_top_of_book_subscription(ticker, contract)
        return ticker in _top_subscriptions
    except Exception as e:
        logger.debug("[IBKR OrderBook] ensure_top_of_book(%s) failed: %s", ticker, e)
        return False


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

    tsub = _trade_subscriptions.pop(ticker, None)
    treq = _trade_subscription_req_ids.pop(ticker, None)
    if treq is not None:
        _req_id_to_ticker.pop(treq, None)
    if tsub is not None and ib is not None:
        try:
            ib.cancelTickByTickData(tsub.contract)
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
        top_ticker = ib.reqMktData(contract, "", False, False)
    except Exception as e:
        logger.debug("[IBKR OrderBook] Could not start top-of-book fallback for %s: %s", ticker, e)
        return

    _top_subscriptions[ticker] = top_ticker

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

        _record_price_sample(
            ticker,
            mid_price,
            volume=(bid_size + ask_size) if (bid_size or ask_size) else 0.0,
            ts=ts,
            force=True,
            source="quote",
        )

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

    try:
        trade_ticker = None
        try:
            trade_ticker = ib.reqTickByTickData(contract, "Last", 0, False)
        except Exception:
            try:
                trade_ticker = ib.reqTickByTick(contract, "Last")
            except Exception:
                trade_ticker = None

        if trade_ticker is not None:
            _trade_subscriptions[ticker] = trade_ticker
            try:
                req_map = getattr(getattr(ib, "wrapper", None), "ticker2ReqId", None)
                tmap = req_map.get("tickByTick", {}) if hasattr(req_map, "get") else {}
                req_id_raw = tmap.get(trade_ticker) if hasattr(tmap, "get") else None
                if req_id_raw is not None:
                    req_id = int(req_id_raw)
                    _trade_subscription_req_ids[ticker] = req_id
                    _req_id_to_ticker[req_id] = ticker
            except Exception:
                pass

            def on_trade_tick(ticker_obj):
                try:
                    price = None
                    size = None
                    price = getattr(ticker_obj, 'price', None) or getattr(ticker_obj, 'last', None) or getattr(ticker_obj, 'price', None)
                    size = getattr(ticker_obj, 'size', None) or getattr(ticker_obj, 'lastSize', None) or getattr(ticker_obj, 'size', None)
                    if price is None:
                        inner = getattr(ticker_obj, 'tick', None) or getattr(ticker_obj, 'data', None)
                        if inner is not None:
                            price = getattr(inner, 'price', None) or inner.get('price') if isinstance(inner, dict) else None
                            size = getattr(inner, 'size', None) or inner.get('size') if isinstance(inner, dict) else None
                    try:
                        price_f = float(price) if price is not None else None
                    except Exception:
                        price_f = None
                    try:
                        size_f = float(size) if size is not None else 0.0
                    except Exception:
                        size_f = 0.0
                    if price_f is not None:
                        _record_price_sample(
                            ticker,
                            price_f,
                            volume=size_f,
                            ts=time.time(),
                            force=True,
                            source="trade",
                        )
                except Exception:
                    pass

            try:
                trade_ticker.updateEvent += on_trade_tick
            except Exception:
                try:
                    trade_ticker.updateEvent = on_trade_tick
                except Exception:
                    pass
    except Exception:
        pass


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
    _last_error_global.update(entry)

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
    """Subscribe to Level 2 market depth for a ticker."""
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
        from ib_async import Stock, Crypto
        ticker_u = str(ticker or "").strip().upper()
        if ticker_u in ("BTC", "ETH", "LTC", "BCH"):
            contract = Crypto(ticker, "PAXOS", "USD")
        else:
            contract = Stock(ticker, exchange, "USD")
        await ib.qualifyContractsAsync(contract)

        depth_ticker = ib.reqMktDepth(contract, numRows=num_rows, isSmartDepth=is_smart_depth)
        _subscriptions[ticker] = depth_ticker
        _subscription_exchange[ticker] = exchange
        _subscription_smart_depth[ticker] = is_smart_depth
        _depth_cache.setdefault(ticker, {"bids": [], "asks": [], "source": None})

        _ensure_top_of_book_subscription(ticker, contract)

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

            try:
                total_vol = 0.0
                for r in (ticker_obj.domBids or []):
                    total_vol += float(getattr(r, 'size', 0) or 0)
                for r in (ticker_obj.domAsks or []):
                    total_vol += float(getattr(r, 'size', 0) or 0)
            except Exception:
                total_vol = 0.0
            _record_price_sample(ticker, mid_price, volume=total_vol, force=True, source="quote")

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
    """Clear all cached DOM rows."""
    for ticker in list(_depth_cache.keys()):
        _depth_cache[ticker] = {"bids": [], "asks": []}


async def resubscribe_all(force: bool = True):
    """Resubscribe all currently tracked depth tickers."""
    tickers = list(_subscriptions.keys())
    for ticker in tickers:
        try:
            exchange = _subscription_exchange.get(ticker, "SMART")
            smart_depth = _subscription_smart_depth.get(ticker, True)
            await subscribe_depth(ticker, exchange=exchange, force=force, is_smart_depth=smart_depth)
        except Exception as e:
            logger.warning(f"[IBKR OrderBook] resubscribe_all failed for {ticker}: {e}")


async def seed_price_history_from_ibkr(ticker: str, duration: str = "900 S", bar_size: str = "10 secs"):
    """Fetch recent historical bars from IBKR to seed the in-memory price history cache."""
    from .client import ib, is_connected
    if not is_connected() or ib is None:
        return
    try:
        from ib_async import Stock
        from .order_book_cache import _record_price_sample
        import datetime
        
        ticker_upper = str(ticker or "").strip().upper()
        if not ticker_upper:
            return
            
        contract = Stock(ticker_upper, "SMART", "USD")
        await ib.qualifyContractsAsync(contract)
        
        # Request recent trades (works in pre/after market with useRTH=False)
        bars = await ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=False,
            formatDate=1,
        )
        if bars:
            for bar in bars:
                ts = None
                if isinstance(bar.date, (datetime.datetime, datetime.date)):
                    if isinstance(bar.date, datetime.datetime):
                        ts = bar.date.timestamp()
                    else:
                        ts = datetime.datetime.combine(bar.date, datetime.time.min).timestamp()
                else:
                    try:
                        ts = datetime.datetime.fromisoformat(str(bar.date)).timestamp()
                    except Exception:
                        pass
                if bar.close:
                    _record_price_sample(
                        ticker_upper,
                        float(bar.close),
                        volume=float(bar.volume or 0.0),
                        ts=ts,
                        force=True,
                        source="historical"
                    )
            logger.info(f"[IBKR OrderBook] Seeded {len(bars)} historical price samples for {ticker_upper}")
    except Exception as e:
        logger.warning(f"[IBKR OrderBook] Failed to seed price history for {ticker_upper}: {e}")


__all__ = [
    "get_snapshot",
    "get_all_snapshots",
    "get_top_of_book",
    "get_mid_price",
    "ensure_top_of_book",
    "resolve_ticker_for_req_id",
    "record_ib_error",
    "get_depth_diagnostics",
    "subscribe_depth",
    "unsubscribe_depth",
    "unsubscribe_all",
    "clear_all_depth_cache",
    "resubscribe_all",
    "get_price_history",
    "get_price_volume_history",
    "get_aggregate_volume",
    "seed_price_history_from_ibkr",
]
