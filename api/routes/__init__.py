"""Routes module initialization."""

from . import windows
from . import capture
from . import history
from . import trades
from . import bots
from . import websocket
from . import chart
from . import settings

__all__ = [
    "windows",
    "capture",
    "history",
    "trades",
    "bots",
    "websocket",
    "chart",
    "settings",
]
