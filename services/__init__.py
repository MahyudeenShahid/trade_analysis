"""Services module for background capture and worker management."""

from .capture_manager import CaptureManager, manager_services
from .background_service import selector
from .trade_recorder import TradeScreenshotRecorder

__all__ = [
    "CaptureManager",
    "manager_services",
    "selector",
    "TradeScreenshotRecorder",
]

