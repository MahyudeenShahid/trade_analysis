"""IBKR order placement, retry logic, and trade event dispatcher.

Flow:
  broadcaster_loop detects a new buy/sell trade
    → asyncio.create_task(handle_trade_event(trade_dict, bot_row, hwnd))
        → place_order(req, settings)
            → retries up to 3 times with configurable delay
            → writes result to live_orders table
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from .models import IBKROrderRequest, IBKROrderResult

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
ORDER_FILL_TIMEOUT = 30  # seconds to wait for a fill


async def place_order(req: IBKROrderRequest, retry_delay: float = 5.0) -> IBKROrderResult:
    """Place a single order via IBKR with up to MAX_RETRIES attempts.

    Returns IBKROrderResult(ok=True) on fill, IBKROrderResult(ok=False) on failure.
    """
    from .client import ib, ensure_connected
    from db.queries import get_app_settings

    if not _ib_async_available():
        return IBKROrderResult(ok=False, error_msg="ib-async not installed", retries=0)

    cfg = get_app_settings()
    host = cfg.get("ibkr_host", "127.0.0.1")
    port = int(cfg.get("ibkr_port", "4002"))
    cid = int(cfg.get("ibkr_client_id", "1"))

    from ib_async import Stock, MarketOrder, LimitOrder

    contract = Stock(req.ticker, "SMART", "USD")

    last_error = "Unknown error"
    for attempt in range(MAX_RETRIES):
        try:
            await ensure_connected(host, port, cid)

            # Qualify contract to get conId etc.
            await ib.qualifyContractsAsync(contract)

            if req.order_type == "limit":
                if not req.limit_price:
                    return IBKROrderResult(
                        ok=False, error_msg="Limit order requires limit_price", retries=attempt
                    )
                order = LimitOrder(req.direction.upper(), req.qty, req.limit_price)
            else:
                order = MarketOrder(req.direction.upper(), req.qty)

            trade = ib.placeOrder(contract, order)
            logger.info(
                f"[IBKR] Placed {req.order_type} {req.direction.upper()} "
                f"{req.qty} {req.ticker} (attempt {attempt + 1})"
            )

            # Wait for terminal status
            deadline = asyncio.get_event_loop().time() + ORDER_FILL_TIMEOUT
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.5)
                status = trade.orderStatus.status
                if status in ("Filled", "ApiCancelled", "Cancelled", "Inactive"):
                    break

            status = trade.orderStatus.status
            if status == "Filled":
                fill = trade.fills[-1] if trade.fills else None
                fill_price = fill.execution.price if fill else trade.orderStatus.avgFillPrice
                return IBKROrderResult(
                    ok=True,
                    ibkr_order_id=trade.order.orderId,
                    fill_price=fill_price,
                    fill_ts=datetime.utcnow().isoformat() + "Z",
                    retries=attempt,
                )
            else:
                last_error = f"Order ended with status: {status}"
                logger.warning(f"[IBKR] {last_error} (attempt {attempt + 1})")

        except Exception as e:
            last_error = str(e)
            logger.error(f"[IBKR] place_order attempt {attempt + 1} failed: {e}")

        if attempt < MAX_RETRIES - 1:
            logger.info(f"[IBKR] Retrying in {retry_delay}s …")
            await asyncio.sleep(retry_delay)

    return IBKROrderResult(ok=False, error_msg=last_error, retries=MAX_RETRIES - 1)


async def handle_trade_event(trade_dict: dict, bot_row: dict, hwnd: int):
    """Top-level dispatcher called from the broadcaster loop when a trade fires.

    Guards:
      - bot must have live_trading_enabled == 1
      - app_settings must have ibkr_enabled == '1'
    """
    from db.queries import get_app_settings, save_live_order, update_live_order_status
    from ibkr.order_book import get_snapshot

    try:
        cfg = get_app_settings()
        if cfg.get("ibkr_enabled", "0") != "1":
            return
        if not bot_row.get("live_trading_enabled"):
            return

        direction = trade_dict.get("direction")
        if direction not in ("buy", "sell"):
            return

        ticker = trade_dict.get("ticker") or bot_row.get("ticker") or ""
        if not ticker:
            logger.warning("[IBKR] handle_trade_event: no ticker — skipping")
            return

        price = trade_dict.get("price")
        trade_ref_id = trade_dict.get("trade_id") or trade_dict.get("ts")

        # Determine order type
        if direction == "buy":
            order_type = bot_row.get("buy_order_type") or "market"
        else:
            order_type = bot_row.get("sell_order_type") or "market"

        # Determine quantity
        qty = _calc_qty(bot_row, cfg)
        if qty <= 0:
            logger.warning(f"[IBKR] Calculated qty={qty} — skipping order")
            return

        limit_price: Optional[float] = None
        if order_type == "limit" and price is not None:
            limit_price = float(price)

        retry_delay = float(bot_row.get("retry_delay_secs") or cfg.get("retry_delay_secs") or 5.0)

        req = IBKROrderRequest(
            ticker=ticker,
            direction=direction,
            order_type=order_type,
            qty=qty,
            limit_price=limit_price,
            bot_id=trade_dict.get("bot_id"),
            hwnd=hwnd,
            trade_ref_id=trade_ref_id,
        )

        ts = datetime.utcnow().isoformat() + "Z"

        # Save pending row first so we have an id for updates
        order_row_id = save_live_order(
            {
                "ts": ts,
                "hwnd": hwnd,
                "bot_id": req.bot_id,
                "ticker": ticker,
                "direction": direction,
                "order_type": order_type,
                "qty": qty,
                "price": price,
                "limit_price": limit_price,
                "status": "pending",
                "trade_ref_id": trade_ref_id,
            }
        )

        # Save order book snapshot at the moment the order fires
        try:
            snap = get_snapshot(ticker)
            if snap.get("bids") or snap.get("asks"):
                from db.queries import query_records
                from db.connection import DB_PATH, DB_LOCK
                import sqlite3
                with DB_LOCK:
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute(
                        "INSERT INTO order_book_snapshots (ts, ticker, trade_ref_id, snapshot) VALUES (?, ?, ?, ?)",
                        (ts, ticker, trade_ref_id, json.dumps(snap)),
                    )
                    conn.commit()
                    conn.close()
        except Exception as snap_err:
            logger.debug(f"[IBKR] Snapshot save failed (non-fatal): {snap_err}")

        # Place the order
        result = await place_order(req, retry_delay=retry_delay)

        # Update DB row with result
        update_live_order_status(
            order_row_id,
            status="filled" if result.ok else "failed",
            fill_price=result.fill_price,
            fill_ts=result.fill_ts,
            error_msg=result.error_msg,
            ibkr_order_id=result.ibkr_order_id,
            retries=result.retries,
        )

        if result.ok:
            logger.info(
                f"[IBKR] Order FILLED: {direction.upper()} {qty} {ticker} "
                f"@ {result.fill_price} (orderId={result.ibkr_order_id})"
            )
        else:
            logger.error(
                f"[IBKR] Order FAILED: {direction.upper()} {qty} {ticker} "
                f"— {result.error_msg}"
            )

    except Exception as e:
        logger.error(f"[IBKR] handle_trade_event error: {e}")


def _calc_qty(bot_row: dict, cfg: dict) -> float:
    """Calculate order quantity from bot settings."""
    size_type = bot_row.get("order_size_type") or "fixed"
    size_value = float(bot_row.get("order_size_value") or 1.0)

    if size_type == "fixed":
        return max(1.0, round(size_value))

    # percent of account net liquidation value
    if size_type == "percent":
        # Non-blocking: use cached account value if available, else default to 1 share
        try:
            from ibkr.account import get_account_value
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule and return default for now; a future tick will have correct value
                # For simplicity we use a module-level cache updated by a background task
                nav = _cached_nav if _cached_nav > 0 else 10000.0
            else:
                nav = loop.run_until_complete(get_account_value())
            price_approx = 100.0  # rough share price for qty calculation
            qty = (nav * (size_value / 100.0)) / price_approx
            return max(1.0, round(qty))
        except Exception:
            return 1.0

    return 1.0


def _ib_async_available() -> bool:
    try:
        import ib_async  # noqa: F401
        return True
    except ImportError:
        return False


# Module-level NAV cache (updated by account background task if needed)
_cached_nav: float = 0.0
