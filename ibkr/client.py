"""IBKR connection singleton and keepalive loop.

Uses ib-async v2.1.0+ (pip install ib-async).
Import: from ib_async import IB
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

try:
    from ib_async import IB
    _ib_available = True
except ImportError:
    IB = None  # type: ignore
    _ib_available = False

# Module-level singleton
ib: "IB | None" = IB() if _ib_available else None
_connected = False


def is_connected() -> bool:
    """Return True if the IB client is currently connected."""
    if not _ib_available or ib is None:
        return False
    try:
        return ib.isConnected()
    except Exception:
        return False


async def connect(host: str = "127.0.0.1", port: int = 4002, client_id: int = 1) -> bool:
    """Connect to IB Gateway. Returns True on success."""
    global _connected
    if not _ib_available or ib is None:
        logger.error("[IBKR] ib-async not installed. Run: pip install ib-async")
        return False
    try:
        if ib.isConnected():
            return True
        await ib.connectAsync(host, port, clientId=client_id, timeout=15)
        # Request next valid order ID (IBKR best practice)
        ib.reqIds(-1)
        _connected = True
        logger.info(f"[IBKR] Connected to {host}:{port} clientId={client_id}")
        return True
    except Exception as e:
        _connected = False
        logger.error(f"[IBKR] Connection failed: {e}")
        return False


def disconnect():
    """Disconnect from IB Gateway."""
    global _connected
    if ib is None:
        return
    try:
        ib.disconnect()
    except Exception:
        pass
    _connected = False
    logger.info("[IBKR] Disconnected.")


async def ensure_connected(host: str = "127.0.0.1", port: int = 4002, client_id: int = 1):
    """Reconnect if not already connected. Raises on failure."""
    if not is_connected():
        ok = await connect(host, port, client_id)
        if not ok:
            raise ConnectionError(f"[IBKR] Cannot connect to {host}:{port}")


async def ibkr_keepalive_loop():
    """Background task: reconnect every 30 s if IBKR is enabled in app_settings."""
    while True:
        try:
            from db.queries import get_app_settings
            cfg = get_app_settings()
            ibkr_enabled_raw = cfg.get("ibkr_enabled", "0")
            if isinstance(ibkr_enabled_raw, str):
                ibkr_enabled = ibkr_enabled_raw.strip().lower() in ("1", "true", "yes", "on")
            else:
                ibkr_enabled = bool(ibkr_enabled_raw)
            if ibkr_enabled:
                if not is_connected():
                    host = cfg.get("ibkr_host", "127.0.0.1")
                    port = int(cfg.get("ibkr_port", "4002"))
                    cid = int(cfg.get("ibkr_client_id", "1"))
                    logger.info("[IBKR] Keepalive: attempting reconnect …")
                    await connect(host, port, cid)
        except Exception as e:
            logger.warning(f"[IBKR] Keepalive error: {e}")
        await asyncio.sleep(30)
