"""WebSocket connection manager."""

from typing import List
from fastapi import WebSocket


class ConnectionManager:
    """Manages active WebSocket connections."""
    
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Unregister a WebSocket connection."""
        try:
            self.active.remove(websocket)
        except ValueError:
            pass

    async def broadcast(self, message: str):
        """Broadcast a message to all active connections."""
        to_remove = []
        for ws in list(self.active):
            try:
                await ws.send_text(message)
            except Exception:
                to_remove.append(ws)
        for ws in to_remove:
            self.disconnect(ws)


# Global connection manager instance
manager = ConnectionManager()

__all__ = ["ConnectionManager", "manager"]
