"""WebSocket endpoints for real-time updates."""

import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ws.manager import manager

router = APIRouter(tags=["websocket"])


@router.websocket("/")
async def websocket_root(websocket: WebSocket):
    """
    WebSocket endpoint at root path.
    
    Accept connections made to the root path (some clients/tunnels connect here).
    Maintains connection for real-time updates from broadcaster.
    """
    try:
        print(f"[WS] incoming connection at / from {websocket.client}")
    except Exception:
        pass
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(10)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint at /ws path.
    
    Primary WebSocket endpoint for real-time status updates.
    Broadcaster sends updates to all connected clients.
    """
    try:
        print(f"[WS] incoming connection at /ws from {websocket.client}")
    except Exception:
        pass
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(10)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


__all__ = ["router"]
