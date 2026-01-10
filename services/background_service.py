"""Background capture service and window selector."""

from background_capture_service import BackgroundCaptureService
from window_selector import WindowSelector

# Global instances for backwards compatibility
service = BackgroundCaptureService()
selector = WindowSelector()

__all__ = ["service", "selector"]
