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
        self.last_trade_dir: Optional[str] = None  # folder of the most recently completed trade
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
        """Ensure daily directory exists. On day change, prune folders older than 3 days
        instead of deleting everything (preserves yesterday's data)."""
        day = datetime.utcnow().strftime("%Y%m%d")
        if self.current_day != day:
            # Delete day-folders that are more than 3 days old
            try:
                from datetime import timedelta
                cutoff = (datetime.utcnow() - timedelta(days=3)).strftime("%Y%m%d")
                if os.path.exists(self.base_dir):
                    for entry in os.listdir(self.base_dir):
                        if entry.isdigit() and entry < cutoff:
                            try:
                                shutil.rmtree(os.path.join(self.base_dir, entry))
                            except Exception:
                                pass
            except Exception:
                pass
            os.makedirs(self.base_dir, exist_ok=True)
            self.current_day = day
        return day
    
    def _copy_to(self, folder: str, src: str):
        """Copy screenshot into trade folder, recompressing to JPEG quality 25.
        The source files are already 85q JPEGs (~400 KB each). At quality 25 they
        drop to ~60 KB — a 85% reduction — while remaining readable for review."""
        try:
            os.makedirs(folder, exist_ok=True)
            if src and os.path.exists(src):
                dst = os.path.join(folder, os.path.basename(src))
                try:
                    from PIL import Image as _PIL
                    with _PIL.open(src) as im:
                        im.convert('RGB').save(dst, format='JPEG', quality=25, optimize=True)
                except Exception:
                    # Fallback to raw copy if PIL fails
                    shutil.copy2(src, dst)
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

        print(f"[TradeRecorder] Starting trade for {ticker} at ${buy_price}")

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
        # Remember this directory so the broadcaster can attach screenshots to the sell event
        self.last_trade_dir = self.trade_dir
    
    def get_last_screenshots(self) -> List[Dict]:
        """
        Return a list of screenshot dicts {url, time, price} for the most recently
        completed trade. Called by the broadcaster so screenshots can be embedded in
        the sell event and delivered to the frontend via WebSocket without needing a
        separate HTTP request.
        """
        target_dir = self.last_trade_dir
        if not target_dir or not os.path.exists(target_dir):
            return []

        screenshots = []
        try:
            meta_path = os.path.join(target_dir, 'metadata.json')
            saved_meta = None
            if os.path.exists(meta_path):
                try:
                    import json as _json
                    with open(meta_path, 'r') as f:
                        saved_meta = _json.load(f)
                except Exception:
                    pass

            buy_price = (saved_meta or {}).get('buy_price')

            for fname in sorted(os.listdir(target_dir)):
                if fname == 'metadata.json':
                    continue
                if not fname.lower().endswith(('.jpg', '.jpeg', '.png')):
                    continue
                full_path = os.path.join(target_dir, fname)
                # Build a URL relative to the trade_screenshots root
                try:
                    base = os.path.abspath(os.path.dirname(os.path.dirname(target_dir)))
                    # Walk up to find the trade_screenshots root
                    rel = os.path.relpath(full_path, os.path.abspath(
                        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'trade_screenshots')
                    )).replace(os.sep, '/')
                except Exception:
                    rel = fname

                time_str = None
                screenshot_price = buy_price
                try:
                    if 'capture_' in fname:
                        parts = fname.split('_')
                        if len(parts) >= 3:
                            dp, tp = parts[1], parts[2].split('.')[0]
                            time_str = f"{dp[:4]}-{dp[4:6]}-{dp[6:8]}T{tp[:2]}:{tp[2:4]}:{tp[4:6]}"
                    if saved_meta and saved_meta.get('screenshots'):
                        for sm in saved_meta['screenshots']:
                            if isinstance(sm, dict) and os.path.basename(sm.get('path', '')) == fname:
                                if sm.get('price') is not None:
                                    screenshot_price = sm['price']
                                if sm.get('time') and not time_str:
                                    time_str = sm['time']
                                break
                except Exception:
                    pass

                screenshots.append({'url': f'/trade_screenshots/{rel}', 'time': time_str, 'price': screenshot_price})
        except Exception:
            pass

        return screenshots

    def get_metadata(self) -> Dict:
        """Get all screenshot metadata for current trade."""
        return {
            'screenshots': self.screenshots_metadata,
            'ticker': self.current_ticker,
            'buy_price': self.buy_price,
            'buy_time': self.buy_time
        }
