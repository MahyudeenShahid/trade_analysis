"""WebSocket endpoints for real-time updates."""

import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ws.manager import manager

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)


async def _keepalive_loop(websocket: WebSocket):
    """Keep the connection open by sleeping periodically, handled cleanly on disconnect/cancellation."""
    try:
        while True:
            await asyncio.sleep(10)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as e:
        print(f"[WS] Keepalive loop exception: {type(e).__name__}: {e}")
    finally:
        manager.disconnect(websocket)
        print(f"[WS] Closed connection for {websocket.client}")


@router.websocket("/")
async def websocket_root(websocket: WebSocket):
    """
    WebSocket endpoint at root path.

    Accept connections made to the root path (some clients/tunnels connect here).
    Maintains connection for real-time updates from broadcaster.
    """
    try:
        logger.info(f"[WS] incoming connection at / from {websocket.client}")
    except Exception:
        pass
    await manager.connect(websocket)
    await _keepalive_loop(websocket)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint at /ws path.

    Primary WebSocket endpoint for real-time status updates.
    Broadcaster sends updates to all connected clients.
    """
    try:
        logger.info(f"[WS] incoming connection at /ws from {websocket.client}")
    except Exception:
        pass
    await manager.connect(websocket)
    await _keepalive_loop(websocket)


__all__ = ["router"]
