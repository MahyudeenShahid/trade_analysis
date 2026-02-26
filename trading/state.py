"""
State management for trading positions and ticker tracking.
"""

from typing import Dict, List, Optional
from datetime import datetime


class TickerState:
    """Manages state for a single ticker/bot combination."""
    
    def __init__(self, ticker: Optional[str] = None, bot_id: Optional[str] = None, 
                 bot_name: Optional[str] = None):
        self.ticker = ticker
        self.bot_id = bot_id
        self.bot_name = bot_name
        self.position: Optional[Dict] = None
        self.first_cycle_done = False
        self.waiting_for_second_down = False
        self.last_direction: Optional[str] = None
        self.trade_history: List[Dict] = []
        
        # Rule state tracking
        self.last_price: Optional[float] = None
        self.peak_price: Optional[float] = None
        self.drop_count = 0
        
        # Rule 5 state
        self.rule5_down_start: Optional[datetime] = None
        self.rule5_ready_for_reversal: bool = False
        self.rule5_reversal_active: bool = False
        self.rule5_reversal_price: Optional[float] = None
        self.rule5_scalp_active: bool = False
        
        # Rule 6 state
        self.rule6_down_start: Optional[datetime] = None
        self.rule6_ready_for_buy: bool = False
        self.rule6_active: bool = False
        
        # Rule 7 state
        self.rule7_up_start: Optional[datetime] = None
        self.rule7_active = False
        self.rule7_ready_for_buy = False  # True once timer has elapsed, waiting to buy
        
        # Rule 8 state
        self.rule8_watch_price: Optional[float] = None  # rolling peak while waiting to buy

        # Rule 9 state
        self.rule9_flips: List[Dict] = []
        self.rule9_last_sell_time: Optional[datetime] = None  # cooldown start timestamp
    
    def to_dict(self) -> Dict:
        """Convert state to dictionary for serialization."""
        return {
            "ticker": self.ticker,
            "bot_id": self.bot_id,
            "bot_name": self.bot_name,
            "position": self.position,
            "first_cycle_done": self.first_cycle_done,
            "waiting_for_second_down": self.waiting_for_second_down,
            "last_direction": self.last_direction,
            "trade_history": self.trade_history.copy(),
            "last_price": self.last_price,
            "peak_price": self.peak_price,
            "drop_count": self.drop_count,
            "rule5_down_start": self.rule5_down_start,
            "rule5_ready_for_reversal": self.rule5_ready_for_reversal,
            "rule5_reversal_active": self.rule5_reversal_active,
            "rule5_reversal_price": self.rule5_reversal_price,
            "rule5_scalp_active": self.rule5_scalp_active,
            "rule6_down_start": self.rule6_down_start,
            "rule6_ready_for_buy": self.rule6_ready_for_buy,
            "rule6_active": self.rule6_active,
            "rule7_up_start": self.rule7_up_start,
            "rule7_active": self.rule7_active,
            "rule7_ready_for_buy": self.rule7_ready_for_buy,
            "rule8_watch_price": self.rule8_watch_price,
            "rule9_flips": self.rule9_flips.copy(),
            "rule9_last_sell_time": self.rule9_last_sell_time,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TickerState':
        """Create TickerState from dictionary."""
        state = cls(
            ticker=data.get("ticker"),
            bot_id=data.get("bot_id"),
            bot_name=data.get("bot_name")
        )
        state.position = data.get("position")
        state.first_cycle_done = data.get("first_cycle_done", False)
        state.waiting_for_second_down = data.get("waiting_for_second_down", False)
        state.last_direction = data.get("last_direction")
        state.trade_history = data.get("trade_history", []).copy()
        state.last_price = data.get("last_price")
        state.peak_price = data.get("peak_price")
        state.drop_count = data.get("drop_count", 0)
        state.rule5_down_start = data.get("rule5_down_start")
        state.rule5_ready_for_reversal = data.get("rule5_ready_for_reversal", False)
        state.rule5_reversal_active = data.get("rule5_reversal_active", False)
        state.rule5_reversal_price = data.get("rule5_reversal_price")
        state.rule5_scalp_active = data.get("rule5_scalp_active", False)
        state.rule6_down_start = data.get("rule6_down_start")
        state.rule6_ready_for_buy = data.get("rule6_ready_for_buy", False)
        state.rule6_active = data.get("rule6_active", False)
        state.rule7_up_start = data.get("rule7_up_start")
        state.rule7_active = data.get("rule7_active", False)
        state.rule7_ready_for_buy = data.get("rule7_ready_for_buy", False)
        state.rule8_watch_price = data.get("rule8_watch_price")
        state.rule9_flips = data.get("rule9_flips", []).copy()
        state.rule9_last_sell_time = data.get("rule9_last_sell_time")
        return state


class StateManager:
    """Manages states for all tickers/bots."""
    
    def __init__(self):
        self.states: Dict[str, TickerState] = {}
    
    def get_or_create(self, key: str, ticker: Optional[str] = None, 
                      bot_id: Optional[str] = None, bot_name: Optional[str] = None) -> TickerState:
        """Get existing state or create new one."""
        if key not in self.states:
            self.states[key] = TickerState(ticker=ticker, bot_id=bot_id, bot_name=bot_name)
        else:
            # Update metadata if provided
            if ticker and not self.states[key].ticker:
                self.states[key].ticker = ticker
            if bot_id and not self.states[key].bot_id:
                self.states[key].bot_id = bot_id
            if bot_name and not self.states[key].bot_name:
                self.states[key].bot_name = bot_name
        return self.states[key]
    
    def get(self, key: str) -> Optional[TickerState]:
        """Get state by key."""
        return self.states.get(key)
    
    def delete(self, key: str):
        """Delete state by key."""
        if key in self.states:
            del self.states[key]
    
    def clear_all(self):
        """Clear all states."""
        self.states.clear()
    
    def all_states(self) -> Dict[str, TickerState]:
        """Get all states."""
        return self.states
