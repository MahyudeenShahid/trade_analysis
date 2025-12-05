"""
Screenshot Capture Module

This module provides functionality to capture screenshots of specific windows
using their window handles, even when they're not in the foreground.
"""

import win32gui
import win32ui
import win32con
import time
from PIL import Image, ImageGrab
import numpy as np
from ctypes import windll
import os
from datetime import datetime


class ScreenshotCapture:
    """
    A class to capture screenshots of specific windows by their handle.
    """
    
    def __init__(self, output_folder="screenshots"):
        """
        Initialize the screenshot capture.
        
        Args:
            output_folder: Directory to save screenshots (default: "screenshots")
        """
        self.output_folder = output_folder
        os.makedirs(output_folder, exist_ok=True)
        # Per-edge crop fractions (0.0 - 0.5). These indicate the fraction
        # of the corresponding edge to remove from the captured image.
        # left_crop_frac: fraction to crop from the left edge
        # right_crop_frac: fraction to crop from the right edge
        # top_crop_frac: fraction to crop from the top edge
        # bottom_crop_frac: fraction to crop from the bottom edge
        self.left_crop_frac = 0.0
        self.right_crop_frac = 0.16
        self.top_crop_frac = 0.0
        self.bottom_crop_frac = 0.0
        # Whether to bring window to foreground for capture (needed for accurate background captures)
        # Default set to False to avoid popping selected windows up. Toggle via API `/settings/bring_to_foreground`.
        self.bring_to_foreground = False

    def set_top_crop_frac(self, frac: float):
        """Set fraction of the top to crop from captures.

        Args:
            frac: Float between 0.0 and 1.0 (e.g., 0.08 to crop top 8%)
        """
        try:
            f = float(frac)
        except Exception:
            raise ValueError("top_crop_frac must be a number between 0.0 and 1.0")
        if f < 0.0 or f > 1.0:
            raise ValueError("top_crop_frac must be between 0.0 and 1.0")
        self.top_crop_frac = f
    
    def capture_window(self, hwnd, save_path=None):
        """
        Capture a screenshot of a specific window by its handle.
        
        Args:
            hwnd: Window handle to capture
            save_path: Optional path to save the image. If None, auto-generates filename
            
        Returns:
            PIL.Image: The captured screenshot image, or None if failed
        """
        try:
            foreground_hwnd = None
            
            # Bring target window to foreground if enabled (needed for background captures)
            if self.bring_to_foreground:
                try:
                    foreground_hwnd = win32gui.GetForegroundWindow()
                    if foreground_hwnd != hwnd:
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                        win32gui.SetForegroundWindow(hwnd)
                        time.sleep(0.15)  # Brief pause for window rendering
                except Exception as e:
                    print(f"[ScreenshotCapture] Could not bring window to foreground: {e}")
            
            # Get window dimensions
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top
            
            # Check if window has valid dimensions
            if width <= 0 or height <= 0:
                print(f"Invalid window dimensions: {width}x{height}")
                return None
            
            # Get window device context
            hwndDC = win32gui.GetWindowDC(hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()
            
            # Create bitmap
            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
            saveDC.SelectObject(saveBitMap)
            
            # Capture the window
            # Try flag 2 (PW_RENDERFULLCONTENT) first, then flag 0 if that fails
            result = windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)
            
            if result == 0:
                print("[ScreenshotCapture] PrintWindow with flag 2 failed, trying flag 0")
                result = windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 0)
                if result == 0:
                    print("[ScreenshotCapture] PrintWindow with flag 0 also failed")
                    # Don't return None yet - try to get the bitmap anyway
                    pass
            
            # Convert to PIL Image
            bmpinfo = saveBitMap.GetInfo()
            bmpstr = saveBitMap.GetBitmapBits(True)
            
            img = Image.frombuffer(
                'RGB',
                (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                bmpstr, 'raw', 'BGRX', 0, 1
            )
            
            # Clean up
            win32gui.DeleteObject(saveBitMap.GetHandle())
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwndDC)
            
            # Apply per-edge crop fractions to compute new crop rectangle.
            w_img = img.width
            h_img = img.height

            # Clamp fractions to sensible range
            # Allow values up to 1.0 per user's request
            def _clamp_frac(v):
                try:
                    f = float(v)
                except Exception:
                    return 0.0
                if f < 0.0:
                    return 0.0
                if f > 1.0:
                    return 1.0
                return f

            lf = _clamp_frac(self.left_crop_frac)
            rf = _clamp_frac(self.right_crop_frac)
            tf = _clamp_frac(self.top_crop_frac)
            bf = _clamp_frac(self.bottom_crop_frac)

            left_px = int(w_img * lf)
            right_px = int(w_img * (1.0 - rf))
            top_px = int(h_img * tf)
            bottom_px = int(h_img * (1.0 - bf))

            # Ensure coordinates are within the image bounds
            left_px = max(0, min(left_px, w_img - 1))
            right_px = max(left_px + 1, min(right_px, w_img))
            top_px = max(0, min(top_px, h_img - 1))
            bottom_px = max(top_px + 1, min(bottom_px, h_img))

            try:
                print(f"[ScreenshotCapture] Applying crop L={lf} R={rf} T={tf} B={bf} -> coords: ({left_px},{top_px}) - ({right_px},{bottom_px}) on {w_img}x{h_img}")
            except Exception:
                pass

            img = img.crop((left_px, top_px, right_px, bottom_px))
            
            # Apply additional top crop if configured (legacy support)
            if self.top_crop_frac and self.top_crop_frac > 0.0:
                h_img = img.height
                try:
                    crop_px = int(height * self.top_crop_frac)
                except Exception:
                    crop_px = int(h_img * self.top_crop_frac)

                if h_img > 1:
                    crop_px = min(crop_px, h_img - 1)
                else:
                    crop_px = 0

                if crop_px > 0 and crop_px < h_img:
                    try:
                        print(f"[ScreenshotCapture] Applying additional top crop: {crop_px}px of {h_img}px (frac={self.top_crop_frac})")
                    except Exception:
                        pass
                    img = img.crop((0, crop_px, img.width, img.height))

            # NOTE: ImageGrab fallback removed intentionally.
            # DO NOT use ImageGrab here — it captures the current screen contents
            # (which may be a different window if the target is occluded/minimized).
            # Previously the code attempted to re-grab the desktop when the
            # captured image appeared mostly black; that produced incorrect
            # captures when the target window was not topmost. We now skip that
            # fallback and keep the original captured image as-is.
            pass

            # NOTE: ImageGrab fallback for very small captures has been removed.
            # Using ImageGrab would capture the current screen content (not the
            # target window) when the target is not topmost. Instead of doing
            # a desktop grab, we prefer to return the captured image as-is and
            # rely on ensuring the target window is topmost via
            # `bring_to_foreground` when accurate captures are required.
            pass

            # Save if path provided
            if save_path:
                img.save(save_path)
                print(f"Screenshot saved to: {save_path}")
            
            # Restore previous foreground window if we changed it
            if self.bring_to_foreground and foreground_hwnd and foreground_hwnd != hwnd:
                try:
                    time.sleep(0.05)  # Small delay before restoring
                    win32gui.SetForegroundWindow(foreground_hwnd)
                except Exception as e:
                    print(f"[ScreenshotCapture] Could not restore foreground window: {e}")
            
            return img
            
        except Exception as e:
            print(f"Error capturing window: {e}")
            return None
    
    def capture_window_auto_save(self, hwnd, prefix="screenshot"):
        """
        Capture window and auto-save with timestamp.
        
        Args:
            hwnd: Window handle to capture
            prefix: Filename prefix (default: "screenshot")
            
        Returns:
            str: Path to saved screenshot, or None if failed
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"{prefix}_{timestamp}.png"
        save_path = os.path.join(self.output_folder, filename)
        
        img = self.capture_window(hwnd, save_path)
        return save_path if img else None
    
    def capture_window_to_array(self, hwnd):
        """
        Capture window as numpy array for processing.
        
        Args:
            hwnd: Window handle to capture
            
        Returns:
            numpy.ndarray: Screenshot as BGR numpy array, or None if failed
        """
        img = self.capture_window(hwnd)
        if img:
            # Convert RGB to BGR for OpenCV compatibility
            arr = np.array(img)[:, :, ::-1].copy()
            return arr
        return None
    
    def set_output_folder(self, folder_path):
        """
        Change the output folder for screenshots.
        
        Args:
            folder_path: New output folder path
        """
        self.output_folder = folder_path
        os.makedirs(folder_path, exist_ok=True)
    
    def get_last_screenshot(self):
        """
        Get the path to the most recently saved screenshot.
        
        Returns:
            str: Path to last screenshot, or None if no screenshots exist
        """
        try:
            files = [
                os.path.join(self.output_folder, f) 
                for f in os.listdir(self.output_folder) 
                if f.endswith('.png')
            ]
            if files:
                return max(files, key=os.path.getctime)
            return None
        except:
            return None
    
    def clear_screenshots(self, keep_last_n=0):
        """
        Clear old screenshots from the output folder.
        
        Args:
            keep_last_n: Number of most recent screenshots to keep (default: 0 - delete all)
        """
        try:
            files = [
                os.path.join(self.output_folder, f) 
                for f in os.listdir(self.output_folder) 
                if f.endswith('.png')
            ]
            
            # Sort by creation time
            files.sort(key=os.path.getctime)
            
            # Delete older files
            files_to_delete = files[:-keep_last_n] if keep_last_n > 0 else files
            
            for file_path in files_to_delete:
                try:
                    os.remove(file_path)
                    print(f"Deleted: {file_path}")
                except Exception as e:
                    print(f"Could not delete {file_path}: {e}")
                    
        except Exception as e:
            print(f"Error clearing screenshots: {e}")


if __name__ == "__main__":
    # Test the screenshot capture
    from backend.window_selector import WindowSelector
    
    selector = WindowSelector()
    windows = selector.enumerate_windows()
    
    if windows:
        print("Available windows:")
        for i, (hwnd, title, process) in enumerate(windows[:10]):
            print(f"{i+1}. [{process}] {title}")
        
        choice = input("\nEnter window number to capture (1-10): ")
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(windows):
                hwnd, title, process = windows[idx]
                print(f"\nCapturing: {title}")
                
                capture = ScreenshotCapture()
                img_path = capture.capture_window_auto_save(hwnd, prefix="test")
                
                if img_path:
                    print(f"Success! Screenshot saved.")
                else:
                    print("Failed to capture screenshot.")
        except ValueError:
            print("Invalid input.")
