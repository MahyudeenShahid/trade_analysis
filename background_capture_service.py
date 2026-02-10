"""
Background Screenshot Service

This module provides a service that continuously captures screenshots
of a selected window at specified intervals in the background.
"""

import threading
import time
from datetime import datetime
from collections import deque
import shutil
from screenshot_capture import ScreenshotCapture
from window_selector import WindowSelector
from title_extractor import extract_from_title
import csv
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import numpy as np


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

                # Debug: print target window info
                try:
                    win_info = self.selector.get_window_by_handle(self.target_hwnd)
                    print(f"[BackgroundCapture] Capturing window: {win_info['title']} (hwnd={self.target_hwnd})")
                except Exception as e:
                    print(f"[BackgroundCapture] Could not get window info: {e}")
                
                # Capture screenshot (do not save immediately to reduce IO latency)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                filename = f"capture_{timestamp}.jpg"
                img_path = os.path.join(self.capture.output_folder, filename)
                img = self.capture.capture_window(self.target_hwnd)

                # If we didn't get an image, try a direct array capture
                if img is None:
                    print("BackgroundCaptureService: initial capture returned None, trying array capture...")
                    arr = self.capture.capture_window_to_array(self.target_hwnd)
                    if arr is not None:
                        import cv2 as _cv2
                        try:
                            _cv2.imwrite(img_path, arr, [int(_cv2.IMWRITE_JPEG_QUALITY), 30])
                            from PIL import Image as _I
                            img = _I.fromarray(arr[:, :, ::-1])
                        except Exception as e:
                            print(f"BackgroundCaptureService: failed to write array capture: {e}")
                    else:
                        print("BackgroundCaptureService: array capture returned None.")

                # If the saved image is unexpectedly small, attempt array-capture fallback to overwrite
                def _pil_img_too_small(pil_img):
                    try:
                        w, h = pil_img.size
                        return h < 64
                    except Exception:
                        return True

                if img is not None and _pil_img_too_small(img):
                    print("BackgroundCaptureService: captured image too small, attempting array-capture fallback...")
                    try:
                        arr = self.capture.capture_window_to_array(self.target_hwnd)
                        if arr is not None:
                            import cv2 as _cv2
                            _cv2.imwrite(img_path, arr, [int(_cv2.IMWRITE_JPEG_QUALITY), 30])
                            from PIL import Image as _I
                            img = _I.fromarray(arr[:, :, ::-1])
                            if _pil_img_too_small(img):
                                print("BackgroundCaptureService: fallback array capture still small or invalid image.")
                        else:
                            print("BackgroundCaptureService: array capture returned None.")
                    except Exception as e:
                        print(f"BackgroundCaptureService: array-capture fallback failed: {e}")
                
                self.total_captures += 1

                if img is not None:
                    # Save the image after quick OCR check to reduce blocking earlier
                    try:
                        img = img.convert('RGB')
                        img.save(img_path, format='JPEG', quality=30, optimize=True)
                        print(f"Screenshot saved to: {img_path}")
                    except Exception:
                        pass
                    self.successful_captures += 1
                    try:
                        self.trade_recorder.register_capture(img_path, price_value)
                    except Exception:
                        pass
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

                    unified_csv = os.path.join(self.capture.output_folder, 'results.csv')
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


class TradeScreenshotRecorder:
    def __init__(self, base_dir: str, pre_count: int = 5, post_count: int = 5):
        self.base_dir = base_dir
        self.pre_count = max(1, int(pre_count))
        self.post_count = max(1, int(post_count))
        self.pre_buffer = deque(maxlen=self.pre_count)
        self.active_trade = False
        self.after_remaining = 0
        self.trade_dir = None
        self.current_day = None
        self.hwnd = None
        self.current_ticker = None
        self.buy_price = None
        self.buy_time = None
        self.screenshots_metadata = []

    def set_hwnd(self, hwnd: int):
        self.hwnd = hwnd

    def _ensure_day_dir(self):
        day = datetime.utcnow().strftime("%Y%m%d")
        if self.current_day != day:
            try:
                if os.path.exists(self.base_dir):
                    shutil.rmtree(self.base_dir)
            except Exception:
                pass
            os.makedirs(self.base_dir, exist_ok=True)
            self.current_day = day
        return day

    def _copy_to(self, folder: str, src: str):
        try:
            os.makedirs(folder, exist_ok=True)
            if src and os.path.exists(src):
                shutil.copy2(src, os.path.join(folder, os.path.basename(src)))
        except Exception:
            pass

    def register_capture(self, img_path: str, current_price: float = None):
        self._ensure_day_dir()
        capture_time = datetime.utcnow().isoformat()
        if img_path:
            self.pre_buffer.append({'path': img_path, 'time': capture_time, 'price': current_price})
        if self.active_trade and self.trade_dir:
            # store all frames in a single trade folder (no pre/during/post subfolders)
            self._copy_to(self.trade_dir, img_path)
            self.screenshots_metadata.append({
                'path': img_path,
                'time': capture_time,
                'price': current_price,
                'ticker': self.current_ticker
            })
        elif self.after_remaining > 0 and self.trade_dir:
            self._copy_to(self.trade_dir, img_path)
            self.screenshots_metadata.append({
                'path': img_path,
                'time': capture_time,
                'price': current_price,
                'ticker': self.current_ticker
            })
            self.after_remaining -= 1
            if self.after_remaining <= 0:
                self.trade_dir = None

    def start_trade(self, ticker: str, trade_ts: str = None, buy_price: float = None):
        day = self._ensure_day_dir()
        safe_ticker = (ticker or "UNKNOWN").replace(os.sep, "_")
        trade_id = (trade_ts or datetime.utcnow().isoformat()).replace(":", "-")
        base = os.path.join(self.base_dir, day)
        if self.hwnd is not None:
            base = os.path.join(base, f"hwnd_{int(self.hwnd)}")
        trade_dir = os.path.join(base, safe_ticker, f"trade_{trade_id}")
        self.trade_dir = trade_dir
        self.current_ticker = ticker
        self.buy_price = buy_price
        self.buy_time = trade_ts or datetime.utcnow().isoformat()
        self.screenshots_metadata = []
        print(f"[TradeRecorder] Starting trade for {ticker} at ${buy_price}, dir: {trade_dir}")
        # copy pre-buffer
        for item in list(self.pre_buffer):
            # keep pre-trade frames in the same folder to preserve sequence
            if isinstance(item, dict):
                self._copy_to(trade_dir, item.get('path'))
                self.screenshots_metadata.append(item)
            else:
                # backward compatibility
                self._copy_to(trade_dir, item)
                self.screenshots_metadata.append({'path': item, 'time': None, 'price': None})
        self.active_trade = True
        self.after_remaining = 0

    def end_trade(self):
        # ensure at least one closing frame is kept
        if self.trade_dir and self.pre_buffer:
            try:
                last = list(self.pre_buffer)[-1]
                if isinstance(last, dict):
                    self._copy_to(self.trade_dir, last.get('path'))
                    self.screenshots_metadata.append(last)
                else:
                    self._copy_to(self.trade_dir, last)
            except Exception:
                pass
        
        # Save metadata to JSON file
        if self.trade_dir and self.screenshots_metadata:
            try:
                import json
                metadata_file = os.path.join(self.trade_dir, 'metadata.json')
                metadata = {
                    'ticker': self.current_ticker,
                    'buy_price': self.buy_price,
                    'buy_time': self.buy_time,
                    'screenshots': self.screenshots_metadata
                }
                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)
            except Exception as e:
                print(f"Failed to save metadata: {e}")
        
        self.active_trade = False
        self.after_remaining = max(1, self.post_count)

    def get_metadata(self):
        """Get all screenshot metadata for current trade."""
        return {
            'screenshots': self.screenshots_metadata,
            'ticker': self.current_ticker,
            'buy_price': self.buy_price,
            'buy_time': self.buy_time
        }


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
