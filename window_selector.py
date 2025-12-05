"""
Window Selector Module

This module provides functionality to enumerate and select open windows
on Windows OS using the Windows API.
"""

import win32gui
import win32con
import win32process
import psutil


class WindowSelector:
    """
    A class to enumerate and manage open windows on Windows OS.
    """
    
    def __init__(self):
        self.windows = []
    
    def enumerate_windows(self):
        """
        Enumerate all visible windows with titles.
        
        Returns:
            list: List of tuples containing (hwnd, title, process_name)
        """
        self.windows = []
        
        def callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                title = win32gui.GetWindowText(hwnd)
                # Get process name
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    process = psutil.Process(pid)
                    process_name = process.name()
                except:
                    process_name = "Unknown"
                
                # Filter out empty titles and system windows
                if title and len(title.strip()) > 0:
                    windows.append((hwnd, title, process_name))
            return True
        
        win32gui.EnumWindows(callback, self.windows)
        return self.windows
    
    def get_browser_windows(self):
        """
        Get only browser windows (Chrome, Firefox, Edge, etc.)
        
        Returns:
            list: List of browser window tuples (hwnd, title, process_name)
        """
        all_windows = self.enumerate_windows()
        browser_processes = ['chrome.exe', 'firefox.exe', 'msedge.exe', 
                           'brave.exe', 'opera.exe', 'iexplore.exe']
        
        browser_windows = [
            w for w in all_windows 
            if w[2].lower() in browser_processes
        ]
        return browser_windows
    
    def get_window_by_handle(self, hwnd):
        """
        Get window information by handle.
        
        Args:
            hwnd: Window handle
            
        Returns:
            tuple: (hwnd, title, process_name) or None if not found
        """
        if not win32gui.IsWindow(hwnd):
            return None
        
        try:
            title = win32gui.GetWindowText(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            process = psutil.Process(pid)
            process_name = process.name()
            return (hwnd, title, process_name)
        except:
            return None
    
    def is_window_valid(self, hwnd):
        """
        Check if a window handle is still valid.
        
        Args:
            hwnd: Window handle to check
            
        Returns:
            bool: True if window exists and is visible
        """
        return win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd)
    
    def bring_window_to_front(self, hwnd):
        """
        Bring a window to the foreground.
        
        Args:
            hwnd: Window handle to bring to front
        """
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        except Exception as e:
            print(f"Could not bring window to front: {e}")
    
    def get_window_rect(self, hwnd):
        """
        Get the window's position and size.
        
        Args:
            hwnd: Window handle
            
        Returns:
            tuple: (left, top, right, bottom) or None if failed
        """
        try:
            return win32gui.GetWindowRect(hwnd)
        except:
            return None


if __name__ == "__main__":
    # Test the window selector
    selector = WindowSelector()
    windows = selector.enumerate_windows()
    
    print("All visible windows:")
    for i, (hwnd, title, process) in enumerate(windows):
        print(f"{i+1}. [{process}] {title}")
    
    print("\n" + "="*50)
    print("Browser windows only:")
    browser_windows = selector.get_browser_windows()
    for i, (hwnd, title, process) in enumerate(browser_windows):
        print(f"{i+1}. [{process}] {title}")
