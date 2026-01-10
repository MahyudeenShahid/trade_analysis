"""Routes module initialization."""

from . import windows
from . import capture
from . import history
from . import trades
from . import bots
from . import websocket

__all__ = [
    "windows",
    "capture",
    "history",
    "trades",
    "bots",
    "websocket",
]
