"""
Trade Screenshot Recorder: Captures screenshots before, during, and after trades.
"""

import os
import shutil
import json
from datetime import datetime
from collections import deque
from typing import Optional, List, Dict


class TradeScreenshotRecorder:
    """Records screenshots during trading sessions with context (before/during/after)."""
    
    def __init__(self, base_dir: str, pre_count: int = 5, post_count: int = 5):
        """
        Initialize the trade screenshot recorder.
        
        Args:
            base_dir: Base directory for storing screenshots
            pre_count: Number of frames to capture before trade
            post_count: Number of frames to capture after trade
        """
        self.base_dir = base_dir
        self.pre_count = max(1, int(pre_count))
        self.post_count = max(1, int(post_count))
        self.pre_buffer = deque(maxlen=self.pre_count)
        
        # Trade state
        self.active_trade = False
        self.after_remaining = 0
        self.trade_dir: Optional[str] = None
        self.current_day: Optional[str] = None
        self.hwnd: Optional[int] = None
        self.current_ticker: Optional[str] = None
        self.buy_price: Optional[float] = None
        self.buy_time: Optional[str] = None
        self.screenshots_metadata: List[Dict] = []
    
    def set_hwnd(self, hwnd: int):
        """Set the window handle for this recorder."""
        self.hwnd = hwnd
    
    def _ensure_day_dir(self) -> str:
        """Ensure daily directory exists, cleanup if new day."""
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
        """Copy screenshot file to target folder."""
        try:
            os.makedirs(folder, exist_ok=True)
            if src and os.path.exists(src):
                shutil.copy2(src, os.path.join(folder, os.path.basename(src)))
        except Exception:
            pass
    
    def register_capture(self, img_path: str, current_price: Optional[float] = None):
        """
        Register a screenshot capture.
        
        Args:
            img_path: Path to the captured screenshot
            current_price: Current price at time of capture
        """
        self._ensure_day_dir()
        capture_time = datetime.utcnow().isoformat()
        
        # Always add to pre-buffer
        if img_path:
            self.pre_buffer.append({
                'path': img_path,
                'time': capture_time,
                'price': current_price
            })
        
        # If active trade, copy to trade directory
        if self.active_trade and self.trade_dir:
            self._copy_to(self.trade_dir, img_path)
            self.screenshots_metadata.append({
                'path': img_path,
                'time': capture_time,
                'price': current_price,
                'ticker': self.current_ticker
            })
        # Post-trade capture window
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
    
    def start_trade(self, ticker: str, trade_ts: Optional[str] = None, 
                   buy_price: Optional[float] = None):
        """
        Start recording a trade session.
        
        Args:
            ticker: Ticker symbol being traded
            trade_ts: Timestamp of the trade
            buy_price: Buy price of the trade
        """
        day = self._ensure_day_dir()
        safe_ticker = (ticker or "UNKNOWN").replace(os.sep, "_")
        trade_id = (trade_ts or datetime.utcnow().isoformat()).replace(":", "-")
        
        # Build directory path: base_dir/day/hwnd_X/ticker/trade_timestamp
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
        
        # Copy pre-buffer frames
        for item in list(self.pre_buffer):
            if isinstance(item, dict):
                self._copy_to(trade_dir, item.get('path'))
                self.screenshots_metadata.append(item)
            else:
                # Backward compatibility
                self._copy_to(trade_dir, item)
                self.screenshots_metadata.append({
                    'path': item,
                    'time': None,
                    'price': None
                })
        
        self.active_trade = True
        self.after_remaining = 0
    
    def end_trade(self):
        """End the current trade recording session."""
        # Capture at least one closing frame
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
    
    def get_metadata(self) -> Dict:
        """Get all screenshot metadata for current trade."""
        return {
            'screenshots': self.screenshots_metadata,
            'ticker': self.current_ticker,
            'buy_price': self.buy_price,
            'buy_time': self.buy_time
        }
