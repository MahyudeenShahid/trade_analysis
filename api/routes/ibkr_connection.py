"""IBKR status and connection management REST API routes."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from api.dependencies import require_api_key
from db.queries import get_app_settings, set_app_setting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["ibkr"])


@router.get("/status")
async def ibkr_status(_auth=Depends(require_api_key)):
    """Return current IBKR connection state and settings."""
    from ibkr.client import is_connected
    from ibkr.account import get_account_summary

    connected = is_connected()
    cfg = get_app_settings()
    account = {}
    if connected:
        try:
            account = await get_account_summary()
        except Exception:
            account = {}

    return {
        "connected": connected,
        "ibkr_enabled": cfg.get("ibkr_enabled", "0") == "1",
        "host": cfg.get("ibkr_host", "127.0.0.1"),
        "port": int(cfg.get("ibkr_port", "4002")),
        "client_id": int(cfg.get("ibkr_client_id", "1")),
        "account": account,
    }


@router.post("/connect")
async def ibkr_connect(payload: dict = None, _auth=Depends(require_api_key)):
    """Manually trigger an IBKR connection.

    Optionally accepts { host, port, client_id } to override app_settings.
    """
    from ibkr.client import connect, is_connected

    cfg = get_app_settings()
    host = (payload or {}).get("host") or cfg.get("ibkr_host", "127.0.0.1")
    port = int((payload or {}).get("port") or cfg.get("ibkr_port", 4002))
    client_id = int((payload or {}).get("client_id") or cfg.get("ibkr_client_id", 1))

    if is_connected():
        return {"ok": True, "message": "Already connected"}

    ok = await connect(host, port, client_id)
    if not ok:
        raise HTTPException(status_code=502, detail="Could not connect to IB Gateway")
    return {"ok": True, "message": f"Connected to {host}:{port}"}


@router.post("/disconnect")
async def ibkr_disconnect(_auth=Depends(require_api_key)):
    """Disconnect from IB Gateway."""
    from ibkr.order_book import unsubscribe_all
    from ibkr.client import disconnect

    # Clear depth subscriptions so reconnect can cleanly resubscribe.
    try:
        await unsubscribe_all()
    except Exception as e:
        logger.warning(f"[IBKR] Failed to clear order-book subscriptions on disconnect: {e}")

    disconnect()
    return {"ok": True, "message": "Disconnected"}


@router.get("/settings")
def ibkr_get_settings(_auth=Depends(require_api_key)):
    """Return IBKR-related app_settings keys."""
    cfg = get_app_settings()
    return {
        "ibkr_enabled": cfg.get("ibkr_enabled", "0"),
        "ibkr_host": cfg.get("ibkr_host", "127.0.0.1"),
        "ibkr_port": cfg.get("ibkr_port", "4002"),
        "ibkr_client_id": cfg.get("ibkr_client_id", "1"),
        "require_live_confirm": cfg.get("require_live_confirm", "1"),
    }


@router.post("/settings")
def ibkr_update_settings(payload: dict, _auth=Depends(require_api_key)):
    """Update IBKR connection settings in app_settings."""
    allowed = {"ibkr_enabled", "ibkr_host", "ibkr_port", "ibkr_client_id"}
    # allow updating the optional safety toggle
    allowed.add("require_live_confirm")
    updated = {}
    for key in allowed:
        if key in payload:
            set_app_setting(key, str(payload[key]))
            updated[key] = payload[key]
    return {"ok": True, "updated": updated}
