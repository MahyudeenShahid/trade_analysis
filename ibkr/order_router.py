"""IBKR order placement, retry logic, and trade event dispatcher."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, Callable

from .models import IBKROrderRequest, IBKROrderResult
from .order_router_helpers import (
    DEFAULT_MAX_RETRIES,
    ORDER_FILL_TIMEOUT,
    _is_non_retryable,
    _ib_async_available,
    _parse_ibkr_error,
    _calc_qty,
    update_cached_nav,
)

logger = logging.getLogger(__name__)


async def place_order(
    req: IBKROrderRequest,
    retry_delay: float = 5.0,
    max_retries: int = DEFAULT_MAX_RETRIES,
    condition_validator: Optional[Callable[[], bool]] = None,
    trend_checker: Optional[Callable[[], Optional[str]]] = None,
    cancel_on_trend_reversal: bool = False,
) -> IBKROrderResult:
    """Place a single order via IBKR with up to max_retries attempts."""
    from .client import ib, ensure_connected
    from db.queries import get_app_settings

    if not _ib_async_available():
        return IBKROrderResult(ok=False, error_msg="ib-async not installed", retries=0)

    cfg = get_app_settings()
    host = cfg.get("ibkr_host", "127.0.0.1")
    port = int(cfg.get("ibkr_port", "4002"))
    cid = int(cfg.get("ibkr_client_id", "1"))

    from ib_async import Stock, MarketOrder, LimitOrder, Crypto

    ticker_u = str(req.ticker or '').strip().upper()
    if ticker_u in ("BTC", "ETH", "LTC", "BCH"):
        contract = Crypto(req.ticker, "PAXOS", "USD")
    else:
        contract = Stock(req.ticker, "SMART", "USD")

    last_error = "Unknown error"
    for attempt in range(max_retries):
        if attempt > 0 and condition_validator is not None:
            try:
                if not condition_validator():
                    logger.info(
                        f"[IBKR] Conditions no longer valid for {req.direction.upper()} {req.ticker} — cancelling retry"
                    )
                    return IBKROrderResult(
                        ok=False,
                        error_msg="Conditions changed — order cancelled",
                        retries=attempt,
                    )
            except Exception as cv_err:
                logger.warning(f"[IBKR] Condition validator error: {cv_err}")

        try:
            await ensure_connected(host, port, cid)
            await ib.qualifyContractsAsync(contract)

            effective_order_type = req.order_type

            # IBKR does NOT allow market orders outside regular trading hours (pre/after-market).
            # Even with outsideRth=True, market orders get silently cancelled.
            # Auto-downgrade to a limit order at mid-price when market is closed.
            from datetime import timezone, time as dt_time
            _now_et = datetime.now(timezone.utc).astimezone(
                __import__('zoneinfo', fromlist=['ZoneInfo']).ZoneInfo('America/New_York')
            )
            _market_open = dt_time(9, 30)
            _market_close = dt_time(16, 0)
            _is_weekday = _now_et.weekday() < 5
            _in_rth = _is_weekday and _market_open <= _now_et.time() < _market_close

            if effective_order_type == "market" and not _in_rth:
                try:
                    from ibkr.order_book import get_mid_price
                    _mid = get_mid_price(req.ticker)
                    if _mid:
                        effective_order_type = "limit"
                        req = IBKROrderRequest(
                            ticker=req.ticker,
                            direction=req.direction,
                            order_type="limit",
                            qty=req.qty,
                            limit_price=float(_mid),
                            bot_id=req.bot_id,
                            hwnd=req.hwnd,
                            trade_ref_id=req.trade_ref_id,
                        )
                        logger.warning(
                            f"[IBKR] Market order outside RTH — downgraded to LIMIT @ {_mid:.2f} for {req.ticker}"
                        )
                    else:
                        logger.warning(
                            f"[IBKR] Market order outside RTH but no mid-price available for {req.ticker} — order may fail"
                        )
                except Exception as _rth_err:
                    logger.warning(f"[IBKR] RTH check failed (non-fatal): {_rth_err}")

            if effective_order_type == "limit":
                if not req.limit_price:
                    return IBKROrderResult(
                        ok=False, error_msg="Limit order requires limit_price", retries=attempt
                    )
                order = LimitOrder(req.direction.upper(), req.qty, req.limit_price)
            else:
                order = MarketOrder(req.direction.upper(), req.qty)

            order.outsideRth = True

            trade = ib.placeOrder(contract, order)
            logger.info(
                f"[IBKR] Placed {req.order_type} {req.direction.upper()} "
                f"{req.qty} {req.ticker} (attempt {attempt + 1}/{max_retries})"
            )

            deadline = asyncio.get_event_loop().time() + ORDER_FILL_TIMEOUT
            trend_cancelled = False
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.5)
                status = trade.orderStatus.status
                if status in ("Filled", "ApiCancelled", "Cancelled", "Inactive"):
                    break

                if cancel_on_trend_reversal and trend_checker is not None and status not in ("Filled",):
                    try:
                        current_trend = trend_checker()
                        if current_trend:
                            should_cancel = (
                                (req.direction.lower() == "buy" and current_trend.lower() == "down") or
                                (req.direction.lower() == "sell" and current_trend.lower() == "up")
                            )
                            if should_cancel:
                                logger.info(
                                    f"[IBKR] Trend reversed to '{current_trend}' — cancelling {req.direction.upper()} order"
                                )
                                try:
                                    ib.cancelOrder(trade.order)
                                    trend_cancelled = True
                                    await asyncio.sleep(0.5)
                                except Exception as cancel_err:
                                    logger.warning(f"[IBKR] Failed to cancel on trend reversal: {cancel_err}")
                                break
                    except Exception as tc_err:
                        logger.debug(f"[IBKR] Trend checker error (non-fatal): {tc_err}")

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
            elif trend_cancelled:
                return IBKROrderResult(
                    ok=False,
                    error_msg="Order cancelled — trend reversed",
                    retries=attempt,
                )
            else:
                if status not in ("ApiCancelled", "Cancelled", "Inactive"):
                    try:
                        ib.cancelOrder(trade.order)
                        logger.info(f"[IBKR] Cancelled unfilled order {trade.order.orderId} (status was {status})")
                        await asyncio.sleep(0.5)
                    except Exception as cancel_err:
                        logger.warning(f"[IBKR] Failed to cancel order: {cancel_err}")

                cancel_reason = None
                try:
                    for log_entry in reversed(trade.log):
                        msg = str(getattr(log_entry, 'message', '') or '')
                        if 'Order Canceled' in msg or 'reason:' in msg:
                            cancel_reason = msg
                            break
                        if getattr(log_entry, 'errorCode', None) == 202:
                            cancel_reason = msg or "Order cancelled by IBKR (error 202)"
                            break
                except Exception:
                    pass

                if cancel_reason:
                    last_error = cancel_reason
                else:
                    last_error = f"Order ended with status: {status}"
                logger.warning(f"[IBKR] {last_error} (attempt {attempt + 1}/{max_retries})")

                if _is_non_retryable(last_error):
                    logger.warning(
                        f"[IBKR] Non-retryable error detected — aborting order: {last_error}"
                    )
                    return IBKROrderResult(
                        ok=False,
                        error_msg=f"Order cancelled (non-retryable): {last_error}",
                        retries=attempt,
                    )

        except Exception as e:
            last_error = _parse_ibkr_error(str(e))
            logger.error(f"[IBKR] place_order attempt {attempt + 1}/{max_retries} failed: {last_error}")
            if _is_non_retryable(last_error):
                logger.warning(f"[IBKR] Non-retryable exception — aborting: {last_error}")
                return IBKROrderResult(ok=False, error_msg=last_error, retries=attempt)

        if attempt < max_retries - 1:
            logger.info(f"[IBKR] Retrying in {retry_delay}s …")
            await asyncio.sleep(retry_delay)

    return IBKROrderResult(ok=False, error_msg=last_error, retries=max_retries - 1)


async def handle_trade_event(
    trade_dict: dict,
    bot_row: dict,
    hwnd: int,
    get_current_signal: Optional[Callable[[], Optional[str]]] = None,
):
    """Top-level dispatcher called from the broadcaster loop when a trade fires."""
    from db.queries import get_app_settings, save_live_order, update_live_order_status
    from ibkr.order_book import get_snapshot
    from screenshot_capture import ScreenshotCapture
    import os
    from datetime import datetime as dt_import

    try:
        cfg = get_app_settings()
        ibkr_enabled_raw = cfg.get("ibkr_enabled", "0")
        if isinstance(ibkr_enabled_raw, str):
            ibkr_enabled = ibkr_enabled_raw.strip().lower() in ("1", "true", "yes", "on")
        else:
            ibkr_enabled = bool(ibkr_enabled_raw)
        if not ibkr_enabled:
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

        if direction == "buy":
            order_type = bot_row.get("buy_order_type") or "limit"
        else:
            order_type = bot_row.get("sell_order_type") or "limit"

        qty = _calc_qty(bot_row, cfg, price)
        if qty <= 0:
            logger.warning(f"[IBKR] Calculated qty={qty} — skipping order")
            return

        min_trade_dollars = float(bot_row.get("min_trade_dollars") or 0)
        if min_trade_dollars > 0 and price is not None:
            trade_value = qty * float(price)
            if trade_value < min_trade_dollars:
                logger.info(
                    f"[IBKR] Trade value ${trade_value:.2f} < min ${min_trade_dollars:.2f} — skipping"
                )
                return

        max_trade_dollars = float(cfg.get("max_trade_dollars") or 0)
        if max_trade_dollars > 0 and price is not None:
            trade_value = qty * float(price)
            if trade_value > max_trade_dollars:
                logger.warning(
                    f"[IBKR] Trade value ${trade_value:.2f} > max ${max_trade_dollars:.2f} — skipping for safety"
                )
                return

        limit_price: Optional[float] = None
        if order_type == "limit" and price is not None:
            limit_price = float(price)
            try:
                from ibkr.order_book import get_mid_price
                mid = get_mid_price(ticker)
                try:
                    offset = float(bot_row.get('rule_11_limit_offset') or bot_row.get('limit_offset') or 0.01)
                except Exception:
                    offset = 0.01
                offset = max(offset, 0.0)  # Allow 0.0 offset for zero slippage
                if direction.lower() == 'buy':
                    # Buy slightly above mid/signal to ensure fill
                    limit_price = float(limit_price) + offset
                elif direction.lower() == 'sell':
                    # Sell slightly below mid/signal to ensure fill
                    limit_price = float(limit_price) - offset
            except Exception:
                pass

        retry_delay = float(bot_row.get("retry_delay_secs") or cfg.get("retry_delay_secs") or 5.0)
        max_retries = int(bot_row.get("max_retries") or DEFAULT_MAX_RETRIES)
        validate_on_retry = bool(bot_row.get("validate_conditions_on_retry", 1))
        cancel_on_reversal = bool(bot_row.get("cancel_on_trend_reversal", 0))

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

        screenshot_path = None
        try:
            base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trade_screenshots")
            date_str = dt_import.now().strftime("%Y%m%d")
            trade_ts_str = dt_import.now().strftime("%Y%m%d_%H%M%S")
            screenshot_dir = os.path.join(base_dir, date_str, f"hwnd_{hwnd}", ticker, f"trade_{trade_ts_str}")
            os.makedirs(screenshot_dir, exist_ok=True)

            capturer = ScreenshotCapture()
            screenshot_file = f"live_{direction}_{trade_ts_str}.jpg"
            screenshot_full_path = os.path.join(screenshot_dir, screenshot_file)

            img = capturer.capture_window(hwnd, screenshot_full_path)
            if img:
                screenshot_path = os.path.relpath(screenshot_full_path, base_dir).replace(os.sep, '/')
                logger.info(f"[IBKR] Screenshot saved: {screenshot_path}")
        except Exception as sc_err:
            logger.warning(f"[IBKR] Screenshot capture failed (non-fatal): {sc_err}")

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
                "screenshot_path": screenshot_path,
            }
        )

        try:
            snap = get_snapshot(ticker)
            if snap.get("bids") or snap.get("asks"):
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

        condition_validator = None
        if validate_on_retry and get_current_signal is not None:
            def validator():
                try:
                    current = get_current_signal()
                    if current is None:
                        return True
                    return current.lower() == direction.lower()
                except Exception:
                    return True
            condition_validator = validator

        trend_checker = None
        if cancel_on_reversal and get_current_signal is not None:
            def check_trend():
                try:
                    current = get_current_signal()
                    if current is None:
                        return None
                    return "up" if current.lower() == "buy" else "down"
                except Exception:
                    return None
            trend_checker = check_trend

        result = await place_order(
            req,
            retry_delay=retry_delay,
            max_retries=max_retries,
            condition_validator=condition_validator,
            trend_checker=trend_checker,
            cancel_on_trend_reversal=cancel_on_reversal,
        )

        profit = None
        buy_order_id = None
        buy_fill_ts = None
        last_buy = None
        if result.ok and direction.lower() == "sell" and result.fill_price:
            try:
                from db.queries import get_last_buy_order
                last_buy = get_last_buy_order(hwnd, ticker)
                if last_buy and last_buy.get("fill_price"):
                    buy_price = float(last_buy["fill_price"])
                    sell_price = float(result.fill_price)
                    buy_qty = float(last_buy.get("qty") or qty)
                    matched_qty = max(0.0, min(float(qty), buy_qty))
                    profit = (sell_price - buy_price) * matched_qty
                    buy_order_id = last_buy.get("id")
                    buy_fill_ts = last_buy.get("fill_ts") or last_buy.get("ts")
                    logger.info(
                        f"[IBKR] P&L calculated: ${profit:.2f} "
                        f"(qty={matched_qty:.4f}, buy @ {buy_price:.2f}, sell @ {sell_price:.2f})"
                    )
            except Exception as pnl_err:
                logger.warning(f"[IBKR] P&L calculation failed (non-fatal): {pnl_err}")

        if result.ok and direction.lower() == "sell" and trade_ref_id and ticker:
            try:
                from api.routes.ibkr import _auto_save_trade_replay
                asyncio.create_task(_auto_save_trade_replay(
                    trade_ref_id=str(trade_ref_id),
                    ticker=ticker,
                    buy_time=buy_fill_ts,
                    sell_time=result.fill_ts,
                    buffer_min=5,
                    bar_size="1 min",
                ))
                logger.info(f"[IBKR] Queued auto-save for trade replay: {trade_ref_id}")
            except Exception as as_err:
                logger.debug(f"[IBKR] Auto-save task creation failed (non-fatal): {as_err}")

        update_live_order_status(
            order_row_id,
            status="filled" if result.ok else "failed",
            fill_price=result.fill_price,
            fill_ts=result.fill_ts,
            error_msg=result.error_msg,
            ibkr_order_id=result.ibkr_order_id,
            retries=result.retries,
            profit=profit,
            buy_order_id=buy_order_id,
        )

        # Write to records table so it shows in the Trade History UI
        if result.ok and direction.lower() == "sell" and result.fill_price:
            try:
                from db.queries import save_observation
                # Extract meta/name if possible
                bot_name = bot_row.get("name") or bot_row.get("bot_name") or f"Bot {hwnd}"
                bot_id = bot_row.get("id") or bot_row.get("bot_id") or str(hwnd)
                
                trade_record = {
                    "ts": result.fill_ts or (dt_import.utcnow().isoformat() + "Z"),
                    "image_path": None,
                    "name": bot_name,
                    "ticker": ticker,
                    "price": str(result.fill_price),
                    "trend": "sell",
                    "buy_price": float(last_buy.get("fill_price")) if last_buy and last_buy.get("fill_price") else None,
                    "sell_price": float(result.fill_price),
                    "buy_time": buy_fill_ts,
                    "sell_time": result.fill_ts or (dt_import.utcnow().isoformat() + "Z"),
                    "win_reason": "profit" if profit and profit > 0 else "loss",
                    "bot_id": bot_id,
                    "bot_name": bot_name,
                    "meta": {
                        "hwnd": hwnd,
                        "ibkr_order_id": result.ibkr_order_id,
                        "live_trade": True,
                        "profit": profit,
                    }
                }
                save_observation(trade_record)
                logger.info(f"[IBKR] Paired live trade persisted to records: {trade_record}")
            except Exception as rec_err:
                logger.warning(f"[IBKR] Failed to persist live trade record: {rec_err}")

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
