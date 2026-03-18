"""IBKR account helpers — positions, account summary, open orders."""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


async def get_positions() -> List[dict]:
    """Return current account positions as a list of dicts."""
    from .client import ib, is_connected

    if not is_connected() or ib is None:
        return []
    try:
        positions = await ib.reqPositionsAsync()
        result = []
        for p in positions:
            result.append(
                {
                    "account": p.account,
                    "ticker": p.contract.symbol,
                    "secType": p.contract.secType,
                    "position": p.position,
                    "avgCost": p.avgCost,
                }
            )
        return result
    except Exception as e:
        logger.error(f"[IBKR Account] get_positions failed: {e}")
        return []


async def get_account_summary() -> Dict[str, str]:
    """Return account summary values as {tag: value} dict."""
    from .client import ib, is_connected

    if not is_connected() or ib is None:
        return {}
    try:
        values = ib.accountValues()
        return {v.tag: v.value for v in values if v.currency in ("USD", "")}
    except Exception as e:
        logger.error(f"[IBKR Account] get_account_summary failed: {e}")
        return {}


async def get_open_orders() -> List[dict]:
    """Return all open orders from IBKR."""
    from .client import ib, is_connected

    if not is_connected() or ib is None:
        return []
    try:
        trades = await ib.reqOpenOrdersAsync()
        result = []
        for t in trades:
            result.append(
                {
                    "orderId": t.order.orderId,
                    "ticker": t.contract.symbol,
                    "action": t.order.action,
                    "orderType": t.order.orderType,
                    "totalQty": t.order.totalQuantity,
                    "lmtPrice": getattr(t.order, "lmtPrice", None),
                    "status": t.orderStatus.status,
                }
            )
        return result
    except Exception as e:
        logger.error(f"[IBKR Account] get_open_orders failed: {e}")
        return []


async def get_account_value(tag: str = "NetLiquidation") -> float:
    """Return a single account value by tag (default: net liquidation value in USD)."""
    summary = await get_account_summary()
    try:
        return float(summary.get(tag, 0))
    except Exception:
        return 0.0
