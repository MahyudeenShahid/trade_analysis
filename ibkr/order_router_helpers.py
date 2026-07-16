"""Helpers for quantity calculation, error parsing, and constants for TWS Order Routing."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3
ORDER_FILL_TIMEOUT = 45  # seconds to wait for a fill (limit orders need more time)

# Non-retryable error patterns — bail immediately if any of these appear
NON_RETRYABLE_PATTERNS = [
    "No market data on major exchange",  # Market closed / no data
    "no market data",
    "market closed",
    "Order Canceled - reason",  # IBKR-initiated cancel with explicit reason
    "Order rejected",
    "201",  # Order rejected
    "200",  # No security definition
    "The contract is not available",
    "Invalid order",
    "Margin required",
    "insufficient funds",
    "account does not have trading permissions",
    "not subscribed",
]

# Module-level NAV cache (updated by account background task if needed)
_cached_nav: float = 0.0


def update_cached_nav(nav: float):
    """Update NAV cache value used by order quantity calculator."""
    global _cached_nav
    _cached_nav = nav


def _is_non_retryable(error_text: str) -> bool:
    """Return True if the error is permanent and retrying will not help."""
    low = (error_text or "").lower()
    for pattern in NON_RETRYABLE_PATTERNS:
        if pattern.lower() in low:
            return True
    return False


def _ib_async_available() -> bool:
    try:
        import ib_async  # noqa: F401
        return True
    except ImportError:
        return False


def _parse_ibkr_error(error_str: str) -> str:
    """Parse IBKR error codes and return human-readable message."""
    error_map = {
        "110": "Price out of range - limit price may be too far from market",
        "200": "No security definition found for the request",
        "201": "Order rejected — check contract or order details",
        "202": "Order cancelled by IBKR — see cancel reason in message",
        "309": "Max number of market depth requests reached",
        "316": "Market depth data halted - resubscribe required",
        "317": "Market depth data reset - deep book must be cleared",
        "321": "Error validating request - check contract/order details",
        "354": "Requested market data is not subscribed",
        "404": "Order ID not found",
        "434": "Order size does not comply with market rules",
        "10090": "Part of requested market data is not subscribed",
        "10186": "Requested market data is not subscribed and delayed data is disabled",
        "10197": "No market data during competing session",
        "10147": "OrderId must be specified for modify",
        "10148": "Can't modify a filled order",
        "2104": "Market data farm connection is OK (info only)",
        "2106": "HMDS data farm connection is OK (info only)",
    }

    for code, msg in error_map.items():
        if code in error_str:
            return f"[IBKR Error {code}] {msg}"

    return error_str


def _calc_qty(bot_row: dict, cfg: dict, price: Optional[float] = None) -> float:
    """Calculate order quantity from bot settings."""
    size_type = bot_row.get("order_size_type") or "fixed"
    size_value = float(bot_row.get("order_size_value") or 1.0)

    if size_type == "fixed":
        return max(1.0, round(size_value))

    # Dollar amount - calculate shares from dollar value
    if size_type == "dollars" and price is not None and price > 0:
        qty = size_value / float(price)
        return max(1.0, round(qty))

    # Percent of account net liquidation value
    if size_type == "percent":
        try:
            from ibkr.account import get_account_value
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                nav = _cached_nav if _cached_nav > 0 else 10000.0
            else:
                nav = loop.run_until_complete(get_account_value())
            share_price = float(price) if price and price > 0 else 100.0
            qty = (nav * (size_value / 100.0)) / share_price
            return max(1.0, round(qty))
        except Exception:
            return 1.0

    return 1.0
