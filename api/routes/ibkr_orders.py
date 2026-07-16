"""IBKR orders and positions REST API routes."""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from api.dependencies import require_api_key
from db.queries import count_live_orders, get_live_orders

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["ibkr"])


@router.get("/orders")
def ibkr_orders(
    hwnd: int = None,
    bot_id: str = None,
    limit: Optional[int] = None,
    offset: int = 0,
    _auth=Depends(require_api_key),
):
    """Return live orders with optional filters and optional pagination."""
    total = count_live_orders(hwnd=hwnd, bot_id=bot_id)
    orders = get_live_orders(hwnd=hwnd, bot_id=bot_id, limit=limit, offset=offset)
    return JSONResponse(content={"orders": orders}, headers={"X-Total-Count": str(total)})


@router.get("/positions")
async def ibkr_positions(_auth=Depends(require_api_key)):
    """Return current account positions from IBKR."""
    from ibkr.account import get_positions

    return {"positions": await get_positions()}


@router.post("/refresh")
async def ibkr_refresh(_auth=Depends(require_api_key)):
    """Force refresh of IBKR account data (positions, account summary, orders)."""
    from ibkr.client import is_connected
    from ibkr.account import get_positions, get_account_summary, get_open_orders

    if not is_connected():
        raise HTTPException(status_code=503, detail="Not connected to IB Gateway")

    try:
        # Fetch fresh data from IBKR
        account = await get_account_summary()
        positions = await get_positions()
        open_orders = await get_open_orders()

        return {
            "ok": True,
            "account": account,
            "positions": positions,
            "open_orders": open_orders,
        }
    except Exception as e:
        logger.error(f"[IBKR] Refresh failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/open_orders")
async def ibkr_open_orders(_auth=Depends(require_api_key)):
    """Return currently open orders from IBKR."""
    from ibkr.account import get_open_orders

    return {"open_orders": await get_open_orders()}
