"""
Core trading operations: buy, sell, position management, and summary generation.
"""

from typing import Dict, List, Optional, Callable
from datetime import datetime
from trading.state import TickerState, StateManager


class TradingCore:
    """Handles core trading operations."""
    
    def __init__(self, state_manager: StateManager, 
                 on_trade_callback: Optional[Callable[[Dict], None]] = None):
        self.state_manager = state_manager
        self.trade_history: List[Dict] = []
        self.on_trade_callback = on_trade_callback
    
    def buy(self, key: str, price: float, state: TickerState):
        """Execute a buy operation."""
        if not key:
            return
        
        ts = datetime.utcnow().isoformat() + 'Z'
        trade_id = ts
        
        state.position = {
            "entry": price,
            "ticker": state.ticker or key,
            "ts": ts,
            "trade_id": trade_id,
        }
        state.last_direction = "buy"
        
        # Initialize rule state
        state.last_price = float(price)
        state.peak_price = float(price)
        state.drop_count = 0
        
        self._log_trade(key, state, "buy", price, None, None, trade_id)
    
    def sell(self, key: str, price: float, state: TickerState, 
             win_reason: Optional[str] = None):
        """Execute a sell operation."""
        if not key:
            return
        
        pos = state.position
        if not pos:
            return
        
        entry = pos.get("entry")
        if entry is None:
            return
        
        profit = price - entry
        ts = datetime.utcnow().isoformat() + 'Z'
        trade_id = pos.get('trade_id') or ts
        
        state.position = None
        state.last_direction = "sell"
        state.last_price = None
        state.peak_price = None
        state.drop_count = 0
        
        self._log_trade(key, state, "sell", price, profit, win_reason, trade_id)
    
    def _log_trade(self, key: str, state: TickerState, direction: str, 
                   price: float, profit: Optional[float], 
                   win_reason: Optional[str], trade_id: Optional[str]):
        """Log trade to history."""
        ts = datetime.utcnow().isoformat() + 'Z'
        
        trade = {
            "ticker": state.ticker or key,
            "bot_id": state.bot_id,
            "bot_name": state.bot_name,
            "direction": direction,
            "price": price,
            "profit": profit,
            "ts": ts,
            "trade_id": trade_id,
            "win_reason": win_reason
        }
        
        state.trade_history.append(trade)
        self.trade_history.append(trade)
        
        if self.on_trade_callback:
            try:
                self.on_trade_callback(trade)
            except Exception:
                pass
    
    def is_trading_hours(self, start_time_str=None, end_time_str=None, allowed_days=None) -> bool:
        """Check if current time is within trading hours.

        Custom start/end times and allowed_days are compared against the SERVER's
        local clock so the user's configured times are always honoured regardless
        of timezone.  When no custom parameters are supplied the legacy behaviour
        (Mon–Fri 9:30–16:00 ET) is preserved for backward compatibility.
        """
        from datetime import datetime, time as dt_time

        try:
            using_custom = (start_time_str is not None or end_time_str is not None or allowed_days is not None)

            if using_custom:
                # Use the server's local time when the user has provided custom settings
                now = datetime.now()
            else:
                # Legacy: use Eastern Time for the default market-hours check
                try:
                    import pytz
                    et_tz = pytz.timezone('America/New_York')
                    now = datetime.now(et_tz)
                except Exception:
                    now = datetime.now()

            weekday = now.weekday()  # Monday=0, Sunday=6

            # Resolve allowed days
            if allowed_days is not None:
                try:
                    days = [int(d) for d in allowed_days]
                except Exception:
                    days = list(range(7))
            elif using_custom:
                # Custom time set but no explicit days → allow all days (time-only restriction)
                days = list(range(7))
            else:
                # Legacy default ET market hours → Mon–Fri only
                days = list(range(5))  # 0-4 = Mon-Fri

            if weekday not in days:
                return False

            current_time = now.time().replace(second=0, microsecond=0)

            # Parse start time (default 09:30)
            if start_time_str:
                try:
                    parts = str(start_time_str).split(':')
                    start_t = dt_time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
                except Exception:
                    start_t = dt_time(9, 30)
            else:
                start_t = dt_time(9, 30)

            # Parse end time (default 16:00)
            if end_time_str:
                try:
                    parts = str(end_time_str).split(':')
                    end_t = dt_time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
                except Exception:
                    end_t = dt_time(16, 0)
            else:
                end_t = dt_time(16, 0)

            return start_t <= current_time <= end_t
        except Exception:
            return True
    
    def generate_summary(self) -> Dict:
        """Generate summary of all trading positions and history."""
        summary_dict = {}
        bots_dict = {}
        
        for key, state in self.state_manager.all_states().items():
            closed_profits = [t["profit"] for t in state.trade_history 
                            if t["profit"] is not None]
            total_pnl = sum(closed_profits) if closed_profits else 0
            wins = sum(1 for p in closed_profits if p > 0)
            losses = sum(1 for p in closed_profits if p <= 0)
            win_rate = (wins / len(closed_profits) * 100) if closed_profits else 0
            last_trade = state.trade_history[-1] if state.trade_history else None
            
            bot_id = state.bot_id or key
            bot_name = state.bot_name
            ticker = state.ticker or key
            
            bot_summary = {
                "bot_id": bot_id,
                "bot_name": bot_name,
                "ticker": ticker,
                "position": "long" if state.position else "flat",
                "entry_price": state.position["entry"] if state.position else None,
                "first_cycle_done": state.first_cycle_done,
                "last_direction": state.last_direction,
                "last_trade": last_trade,
                "total_pnl": total_pnl,
                "wins": wins,
                "losses": losses,
                "win_rate": round(win_rate, 2),
                "trade_history": state.trade_history.copy()
            }
            
            bots_dict[bot_id] = bot_summary
            if not state.bot_id:
                summary_dict[ticker] = bot_summary
        
        return {
            "tickers": summary_dict,
            "bots": bots_dict,
            "total_pnl_all_tickers": sum(t["total_pnl"] for t in bots_dict.values()),
            "all_trades": self.trade_history.copy()
        }
    
    def clear_bot(self, bot_id: Optional[str], ticker: Optional[str] = None, 
                  state_key: str = None):
        """Clear specific bot's state and history."""
        if state_key:
            self.state_manager.delete(state_key)
        
        if bot_id:
            self.trade_history = [t for t in self.trade_history 
                                if t.get("bot_id") != bot_id]
    
    def clear_all(self):
        """Clear all states and history."""
        self.state_manager.clear_all()
        self.trade_history.clear()
