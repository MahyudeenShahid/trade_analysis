"""
Background Screenshot Service

This module provides a service that continuously captures screenshots
of a selected window at specified intervals in the background.
"""

import csv
import threading
import time
import os
from datetime import datetime
from screenshot_capture import ScreenshotCapture
from window_selector import WindowSelector
from title_extractor import extract_from_title
from services.trade_recorder import TradeScreenshotRecorder


class BackgroundCaptureService:
    """
    A service that captures screenshots of a specific window in the background.
    """
    
    def __init__(self, output_folder="screenshots"):
        """
        Initialize the background capture service.
        
        Args:
            output_folder: Directory to save screenshots
        """
        self.capture = ScreenshotCapture(output_folder)
        self.selector = WindowSelector()
        
        self.target_hwnd = None
        self.is_running = False
        self.capture_thread = None
        self.interval = 5  # seconds
        self.auto_cleanup = True
        self.keep_last_n = 1  # Keep only the last screenshot by default
        # Prefer fast title-based extraction when available (avoids OCR)
        self.use_title_extraction = True
        # Line detection options
        # Enable line detection by default
        self.enable_line_detect = True
        self.line_output_csv = os.path.join(output_folder, "line_results.csv")
        # Detector instance (import lazily to avoid hard dependency at import time)
        try:
            from chart_line_detector import ChartLineDetector
            self.line_detector = ChartLineDetector()
        except Exception:
            self.line_detector = None
        # Last result cache for UI
        self.last_result = {}
        
        # Statistics
        self.total_captures = 0
        self.successful_captures = 0
        self.failed_captures = 0
        self.start_time = None
        # Internal flag: whether we've temporarily brought the target to front
        # since the service started. When `capture.bring_to_foreground` is enabled
        # we only force-foreground once to avoid continuously stealing focus.
        self._brought_to_foreground = False
        # Trade screenshot capture
        self.trade_screens_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_screenshots")
        self.trade_recorder = TradeScreenshotRecorder(self.trade_screens_dir, pre_count=5, post_count=5)
        # Daily CSV rotation tracking
        self._csv_date: str = ''
    
    def set_target_window(self, hwnd):
        """
        Set the target window to capture.
        
        Args:
            hwnd: Window handle to capture
            
        Returns:
            bool: True if window is valid, False otherwise
        """
        if self.selector.is_window_valid(hwnd):
            self.target_hwnd = hwnd
            try:
                self.trade_recorder.set_hwnd(int(hwnd))
            except Exception:
                pass
            return True
        return False

    def handle_trade_event(self, direction: str, ticker: str, trade_ts: str = None, price: float = None):
        """Notify trade recorder about buy/sell events."""
        try:
            if direction == 'buy':
                self.trade_recorder.start_trade(ticker, trade_ts, price)
            elif direction == 'sell':
                self.trade_recorder.end_trade()
        except Exception:
            pass
    
    def set_interval(self, seconds):
        """
        Set the capture interval.
        
        Args:
            seconds: Time in seconds between captures (minimum: 0.5)
        """
        self.interval = max(0.5, seconds)
    
    def set_auto_cleanup(self, enabled, keep_last_n=100):
        """
        Enable/disable automatic cleanup of old screenshots.
        
        Args:
            enabled: Whether to enable auto cleanup
            keep_last_n: Number of recent screenshots to keep
        """
        self.auto_cleanup = enabled
        self.keep_last_n = keep_last_n

    def set_enable_line_detect(self, enabled: bool, csv_path: str = None):
        """
        Enable or disable line detection after each capture and optionally set CSV path.
        """
        self.enable_line_detect = bool(enabled)
        if csv_path:
            self.line_output_csv = csv_path

    def set_use_title_extraction(self, enabled: bool):
        """Enable or disable title-based extraction (fast, OCR-free)."""
        self.use_title_extraction = bool(enabled)

    def start(self):
        """
        Start the background capture service.
        
        Returns:
            bool: True if started successfully, False otherwise
        """
        if self.is_running:
            print("Service is already running.")
            return False
        
        if not self.target_hwnd:
            print("No target window set.")
            return False
        
        if not self.selector.is_window_valid(self.target_hwnd):
            print("Target window is not valid.")
            return False
        
        self.is_running = True
        self.start_time = datetime.now()
        self.total_captures = 0
        self.successful_captures = 0
        self.failed_captures = 0
        # reset foreground flag on each start so we can bring-to-front once
        # at the beginning of a new capture session if requested
        self._brought_to_foreground = False
        
        self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.capture_thread.start()
        
        print("Background capture service started.")
        return True
    
    def stop(self):
        """
        Stop the background capture service.
        """
        if not self.is_running:
            print("Service is not running.")
            return
        
        self.is_running = False
        if self.capture_thread:
            self.capture_thread.join(timeout=2)
        
        print("Background capture service stopped.")
    
    def _capture_loop(self):
        """
        Main capture loop running in background thread.
        """
        while self.is_running:
            try:
                # Check if window is still valid
                if not self.selector.is_window_valid(self.target_hwnd):
                    print("Target window is no longer valid. Stopping service.")
                    self.is_running = False
                    break

                # If configured, bring the target to the foreground once at
                # the beginning of the session. This helps ensure PrintWindow
                # or subsequent fallbacks capture the selected tab/window
                # instead of whatever is currently on top.
                try:
                    if getattr(self.capture, 'bring_to_foreground', False) and not self._brought_to_foreground:
                        try:
                            # prefer selector helper to set foreground
                            self.selector.bring_window_to_front(self.target_hwnd)
                        except Exception:
                            try:
                                import win32gui
                                import win32con
                                if win32gui.IsIconic(self.target_hwnd):
                                    win32gui.ShowWindow(self.target_hwnd, win32con.SW_RESTORE)
                                win32gui.SetForegroundWindow(self.target_hwnd)
                            except Exception:
                                pass
                        # give the OS a moment to render the window in front
                        time.sleep(0.12)
                        self._brought_to_foreground = True
                except Exception:
                    pass

                # Throttled status print — once every 60 captures (~5 min at 5s interval)
                if self.total_captures % 60 == 0:
                    try:
                        win_info = self.selector.get_window_by_handle(self.target_hwnd)
                        print(f"[BackgroundCapture] Still running — {self.total_captures} captures, window: {win_info['title']} (hwnd={self.target_hwnd})")
                    except Exception:
                        pass
                
                # Capture screenshot (do not save immediately to reduce IO latency)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                filename = f"capture_{timestamp}.jpg"
                img_path = os.path.join(self.capture.output_folder, filename)
                img = self.capture.capture_window(self.target_hwnd)

                # If we didn't get an image, try a direct array capture
                # --- Helpers for image quality checks ---
                def _img_too_small(pil_img):
                    try:
                        w, h = pil_img.size
                        return h < 64 or w < 64
                    except Exception:
                        return True

                def _img_mostly_black(pil_img, threshold=0.92):
                    """Return True when > threshold fraction of pixels are pure black.
                    PrintWindow silently returns an all-black bitmap for GPU-accelerated
                    or minimized windows — this catches those silent failures."""
                    try:
                        import numpy as _np
                        arr = _np.array(pil_img.convert('RGB'))
                        black_pixels = _np.all(arr == 0, axis=2).sum()
                        total = arr.shape[0] * arr.shape[1]
                        return total > 0 and (black_pixels / total) >= threshold
                    except Exception:
                        return False

                def _try_array_fallback(hwnd, out_path):
                    """Attempt capture via capture_window_to_array and return PIL image or None."""
                    try:
                        arr = self.capture.capture_window_to_array(hwnd)
                        if arr is not None:
                            import cv2 as _cv2
                            from PIL import Image as _I
                            _cv2.imwrite(out_path, arr, [int(_cv2.IMWRITE_JPEG_QUALITY), 85])
                            return _I.fromarray(arr[:, :, ::-1])
                    except Exception as e:
                        print(f"BackgroundCaptureService: array-capture fallback failed: {e}")
                    return None

                # Primary capture failed entirely
                if img is None:
                    print("BackgroundCaptureService: initial capture returned None, trying array capture...")
                    img = _try_array_fallback(self.target_hwnd, img_path)
                    if img is None:
                        print("BackgroundCaptureService: array capture also returned None.")

                # Image captured but too small — try fallback
                if img is not None and _img_too_small(img):
                    print("BackgroundCaptureService: captured image too small, attempting array-capture fallback...")
                    fallback = _try_array_fallback(self.target_hwnd, img_path)
                    if fallback is not None and not _img_too_small(fallback):
                        img = fallback
                    else:
                        print("BackgroundCaptureService: fallback still small or invalid.")

                # Image is all black — PrintWindow returned a blank bitmap (GPU/minimized window)
                if img is not None and _img_mostly_black(img):
                    print("BackgroundCaptureService: captured image is mostly black (GPU/minimized window), trying array fallback...")
                    fallback = _try_array_fallback(self.target_hwnd, img_path)
                    if fallback is not None and not _img_mostly_black(fallback):
                        img = fallback
                    else:
                        print("BackgroundCaptureService: fallback also black — skipping this capture tick.")
                        img = None
                
                self.total_captures += 1

                if img is not None:
                    # Save the image after quick OCR check to reduce blocking earlier
                    try:
                        img = img.convert('RGB')
                        img.save(img_path, format='JPEG', quality=85, optimize=True)
                    except Exception:
                        pass
                    self.successful_captures += 1
                    trend = None
                    ocr_ran = False
                    ocr_timed_out = False

                    # Title-based extraction (fast, no OCR)
                    name = ''
                    ticker = ''
                    price_text = ''
                    price_value = None
                    try:
                        if self.use_title_extraction:
                            win = self.selector.get_window_by_handle(self.target_hwnd)
                            if win:
                                _, title, _ = win
                                title_res = extract_from_title(title)
                                if title_res:
                                    name = title_res.name or ''
                                    ticker = title_res.ticker or ''
                                    price_text = title_res.price_text or (f"${title_res.price_value:.2f}" if title_res.price_value is not None else '')
                                    price_value = title_res.price_value
                                    ocr_ran = True
                    except Exception as e:
                        print(f"Title extraction error for {img_path}: {e}")

                    # Optionally run line detector
                    if self.enable_line_detect and self.line_detector:
                        try:
                            trend = self.line_detector(img_path)
                        except Exception as e:
                            print(f"Line detection failed for {img_path}: {e}")

                    try:
                        self.trade_recorder.register_capture(img_path, price_value)
                    except Exception:
                        pass

                    self.last_result = {
                        'timestamp': datetime.utcnow().isoformat() + 'Z',
                        'image_path': img_path,
                        'name': name,
                        'ticker': ticker,
                        'price': price_text,
                        'price_value': price_value,
                        'trend': trend or '',
                        'ocr_ran': bool(ocr_ran),
                        'ocr_timed_out': bool(ocr_timed_out)
                    }

                    today = datetime.utcnow().strftime('%Y%m%d')
                    # Rotate CSV daily — prevents unbounded growth in long sessions
                    if today != self._csv_date:
                        self._csv_date = today
                        # Delete CSV files older than 3 days to free disk space
                        try:
                            import glob as _glob
                            from datetime import timedelta as _td
                            cutoff = (datetime.utcnow() - _td(days=3)).strftime('%Y%m%d')
                            for old in _glob.glob(os.path.join(self.capture.output_folder, 'results_*.csv')):
                                day_str = os.path.basename(old).replace('results_', '').replace('.csv', '')
                                if day_str.isdigit() and day_str < cutoff:
                                    try:
                                        os.remove(old)
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                    unified_csv = os.path.join(self.capture.output_folder, f'results_{today}.csv')
                    header_needed = not os.path.exists(unified_csv)
                    try:
                        with open(unified_csv, 'a', newline='', encoding='utf-8') as f:
                            writer = csv.writer(f)
                            if header_needed:
                                writer.writerow(['timestamp', 'image_path', 'name', 'ticker', 'price', 'trend'])
                            writer.writerow([
                                self.last_result['timestamp'],
                                img_path,
                                self.last_result['name'],
                                self.last_result['ticker'],
                                self.last_result['price'],
                                self.last_result['trend']
                            ])
                    except Exception as e:
                        print(f"Failed to write results CSV: {e}")
                else:
                    self.failed_captures += 1
                
                # Auto cleanup if enabled
                if self.auto_cleanup and self.successful_captures % 10 == 0:
                    self.capture.clear_screenshots(keep_last_n=self.keep_last_n)
                
                # Wait for next interval
                time.sleep(self.interval)
                
            except Exception as e:
                print(f"Error in capture loop: {e}")
                self.failed_captures += 1
                time.sleep(self.interval)
    
    def get_status(self):
        """
        Get current service status.
        
        Returns:
            dict: Status information
        """
        runtime = None
        if self.start_time and self.is_running:
            runtime = (datetime.now() - self.start_time).total_seconds()
        
        window_info = None
        if self.target_hwnd:
            window_info = self.selector.get_window_by_handle(self.target_hwnd)
        
        return {
            'is_running': self.is_running,
            'target_window': window_info,
            'interval': self.interval,
            'total_captures': self.total_captures,
            'successful_captures': self.successful_captures,
            'failed_captures': self.failed_captures,
            'runtime_seconds': runtime,
            'output_folder': self.capture.output_folder,
            'auto_cleanup': self.auto_cleanup,
            'keep_last_n': self.keep_last_n
            , 'last_result': self.last_result,
            # expose whether capture brings window to foreground
            'bring_to_foreground': getattr(self.capture, 'bring_to_foreground', False)
        }
    
    def pause(self):
        """
        Pause capturing (stop without resetting statistics).
        """
        self.stop()
    
    def resume(self):
        """
        Resume capturing after pause.
        """
        if not self.is_running:
            self.is_running = True
            self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.capture_thread.start()
            print("Background capture service resumed.")


if __name__ == "__main__":
    # Test the background service
    from window_selector import WindowSelector
    
    selector = WindowSelector()
    windows = selector.get_browser_windows()
    
    if not windows:
        windows = selector.enumerate_windows()[:10]
    
    if windows:
        print("Available windows:")
        for i, (hwnd, title, process) in enumerate(windows):
            print(f"{i+1}. [{process}] {title}")
        
        choice = input("\nEnter window number to capture: ")
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(windows):
                hwnd, title, process = windows[idx]
                print(f"\nSelected: {title}")
                
                service = BackgroundCaptureService()
                service.set_target_window(hwnd)
                service.set_interval(2)  # 2 seconds
                service.start()
                
                print("\nService running. Press Ctrl+C to stop...")
                try:
                    while True:
                        time.sleep(5)
                        status = service.get_status()
                        print(f"Captures: {status['successful_captures']}/{status['total_captures']}")
                except KeyboardInterrupt:
                    print("\nStopping service...")
                    service.stop()
        except ValueError:
            print("Invalid input.")

if __name__ == "__main__":
    # Test the background service
    from window_selector import WindowSelector
    
    selector = WindowSelector()
    windows = selector.get_browser_windows()
    
    if not windows:
        windows = selector.enumerate_windows()[:10]
    
    if windows:
        print("Available windows:")
        for i, (hwnd, title, process) in enumerate(windows):
            print(f"{i+1}. [{process}] {title}")
        
        choice = input("\nEnter window number to capture: ")
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(windows):
                hwnd, title, process = windows[idx]
                print(f"\nSelected: {title}")
                
                service = BackgroundCaptureService()
                service.set_target_window(hwnd)
                service.set_interval(2)  # 2 seconds
                service.start()
                
                print("\nService running. Press Ctrl+C to stop...")
                try:
                    while True:
                        time.sleep(5)
                        status = service.get_status()
                        print(f"Captures: {status['successful_captures']}/{status['total_captures']}")
                except KeyboardInterrupt:
                    print("\nStopping service...")
                    service.stop()
        except ValueError:
            print("Invalid input.")
