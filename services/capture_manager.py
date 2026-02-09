"""Multi-worker capture manager for managing multiple BackgroundCaptureService instances."""

import os
import threading
from typing import Optional

from background_capture_service import BackgroundCaptureService
from services.bot_registry import get_crop


class CaptureManager:
    """
    Manage multiple BackgroundCaptureService instances keyed by hwnd.
    
    This allows concurrent capture from multiple windows, each with isolated
    output folders and independent configurations.
    """

    def __init__(self):
        # map hwnd (int) -> BackgroundCaptureService
        self._services = {}
        self._lock = threading.Lock()

    def start_worker(self, hwnd: int, interval: float = 1.0, bring_to_foreground: Optional[bool] = None):
        """
        Start a capture worker for a specific window handle.
        
        Args:
            hwnd: Window handle to capture
            interval: Capture interval in seconds
            bring_to_foreground: Whether to bring window to foreground before capture
            
        Returns:
            bool: True if worker started successfully, False otherwise
        """
        with self._lock:
            if hwnd in self._services:
                # already running for this hwnd
                return False
            svc = BackgroundCaptureService()
            # use per-hwnd folder to avoid filename collisions
            out_folder = os.path.join(svc.capture.output_folder, f"hwnd_{hwnd}")
            try:
                os.makedirs(out_folder, exist_ok=True)
                svc.capture.set_output_folder(out_folder)
            except Exception:
                pass
            if bring_to_foreground is not None:
                try:
                    svc.capture.bring_to_foreground = bool(bring_to_foreground)
                except Exception:
                    pass
            svc.set_interval(max(0.5, float(interval)))
            if not svc.set_target_window(hwnd):
                return False
            # Apply any in-memory crop settings for this hwnd before starting
            try:
                crop = get_crop(hwnd)
                if isinstance(crop, dict):
                    if 'left' in crop:
                        try: svc.capture.left_crop_frac = float(crop.get('left'))
                        except Exception: pass
                    if 'right' in crop:
                        try: svc.capture.right_crop_frac = float(crop.get('right'))
                        except Exception: pass
                    if 'top' in crop:
                        try: svc.capture.top_crop_frac = float(crop.get('top'))
                        except Exception: pass
                    if 'bottom' in crop:
                        try: svc.capture.bottom_crop_frac = float(crop.get('bottom'))
                        except Exception: pass
            except Exception:
                pass
            started = svc.start()
            if started:
                self._services[hwnd] = svc
            return started

    def stop_worker(self, hwnd: int):
        """
        Stop a capture worker for a specific window handle.
        
        Args:
            hwnd: Window handle to stop capturing
            
        Returns:
            bool: True if worker stopped successfully, False if not found
        """
        with self._lock:
            svc = self._services.get(hwnd)
            if not svc:
                return False
            try:
                svc.stop()
            except Exception:
                pass
            try:
                del self._services[hwnd]
            except Exception:
                pass
            return True

    def list_workers(self):
        """
        Get list of all active worker hwnds.
        
        Returns:
            list: List of active window handles
        """
        with self._lock:
            return list(self._services.keys())

    def iter_services(self):
        """
        Yield (hwnd, service) pairs for all managed services.
        
        Yields:
            tuple: (hwnd, BackgroundCaptureService) pairs
        """
        with self._lock:
            for hwnd, svc in list(self._services.items()):
                yield hwnd, svc

    def get_worker(self, hwnd: int):
        """
        Get a specific worker service by hwnd.
        
        Args:
            hwnd: Window handle to retrieve
            
        Returns:
            BackgroundCaptureService or None: The service instance if found
        """
        with self._lock:
            return self._services.get(hwnd)

    def all_statuses(self):
        """
        Get status information for all workers.
        
        Returns:
            list: List of status dictionaries for each worker
        """
        out = []
        with self._lock:
            for hwnd, svc in list(self._services.items()):
                try:
                    st = svc.get_status()
                except Exception:
                    st = {}
                out.append({
                    "hwnd": int(hwnd),
                    "status": st,
                    "last_result": st.get('last_result') if isinstance(st, dict) else None
                })
        return out


# Global capture manager instance
manager_services = CaptureManager()

__all__ = ["CaptureManager", "manager_services"]
