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
ib = IB() if _ib_available else None
_connected = False
_error_handler_registered = False


def _attach_error_handler_once():
    """Attach a global IB error handler once per process.

    Handles official market-data recovery cases:
    - 1101: data lost after reconnect -> resubscribe market-data requests
    - 316: market depth halted -> resubscribe depth
    - 317: market depth reset -> clear DOM cache before applying updates
    """
    global _error_handler_registered

    if _error_handler_registered or ib is None:
        return
    if not hasattr(ib, "errorEvent"):
        return

    def _on_ib_error(*args):
        try:
            req_id = args[0] if len(args) > 0 else None
            code = args[1] if len(args) > 1 else None
            msg = args[2] if len(args) > 2 else ""
        except Exception:
            req_id = None
            code = None
            msg = ""

        try:
            code_int = int(code) if code is not None else None
        except Exception:
            code_int = None

        ticker = None
        try:
            from .order_book import record_ib_error
            ticker = record_ib_error(req_id, code_int if code_int is not None else code, msg)
        except Exception:
            ticker = None

        if code_int in (1101, 316):
            if ticker:
                logger.warning(
                    "[IBKR] Error %s (reqId=%s ticker=%s): %s. Re-subscribing all depth feeds.",
                    code_int,
                    req_id,
                    ticker,
                    msg,
                )
            else:
                logger.warning(
                    "[IBKR] Error %s (reqId=%s): %s. Re-subscribing all depth feeds.",
                    code_int,
                    req_id,
                    msg,
                )
            try:
                from .order_book import resubscribe_all
                asyncio.create_task(resubscribe_all(force=True))
            except Exception as e:
                logger.warning(f"[IBKR] Could not trigger depth resubscribe: {e}")
        elif code_int == 317:
            if ticker:
                logger.warning(
                    "[IBKR] Error 317 (reqId=%s ticker=%s): %s. Clearing cached depth books.",
                    req_id,
                    ticker,
                    msg,
                )
            else:
                logger.warning(
                    "[IBKR] Error 317 (reqId=%s): %s. Clearing cached depth books.",
                    req_id,
                    msg,
                )
            try:
                from .order_book import clear_all_depth_cache
                clear_all_depth_cache()
            except Exception as e:
                logger.warning(f"[IBKR] Could not clear depth cache after 317: {e}")
        elif code_int in (309, 354, 10090, 10186, 10197):
            if ticker:
                logger.warning(
                    "[IBKR] Market-data warning/error %s (reqId=%s ticker=%s): %s",
                    code_int,
                    req_id,
                    ticker,
                    msg,
                )
            else:
                logger.warning(
                    "[IBKR] Market-data warning/error %s (reqId=%s): %s",
                    code_int,
                    req_id,
                    msg,
                )

    try:
        ib.errorEvent += _on_ib_error
        _error_handler_registered = True
    except Exception as e:
        logger.warning(f"[IBKR] Failed to attach error handler: {e}")


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
        _connected = True
        _attach_error_handler_once()

        # After any reconnect, previously tracked depth subscriptions may be stale
        # even if IB reports connected. Force a clean re-subscribe for all symbols.
        try:
            from .order_book import resubscribe_all
            await resubscribe_all(force=True)
        except Exception as e:
            logger.warning(f"[IBKR] Post-connect depth resubscribe failed: {e}")

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
