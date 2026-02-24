"""
Improved Per-Ticker Trade Simulator for Demo/Testing

This refactored version delegates to specialized modules:
- trading.utils: Helper functions (price parsing, normalization)
- trading.state: State management for tickers and positions
- trading.rules: Trading rule implementations (Rules 1-9)
- trading.core: Core operations (buy, sell, summary)
"""

from typing import Optional, Dict, Callable
from datetime import datetime

from trading.utils import parse_price, normalize_ticker, normalize_bot_id, make_state_key
from trading.state import StateManager
from trading.core import TradingCore
from trading import rules


class TradeSimulator:
    """Orchestrates trading operations using modular components."""
    
    def __init__(self, on_trade: Optional[Callable[[Dict], None]] = None):
        self.state_manager = StateManager()
        self.core = TradingCore(self.state_manager, on_trade)
        self.on_trade = on_trade
    
    @property
    def tickers(self):
        """Backward compatibility: access states as dict."""
        return {k: v.to_dict() for k, v in self.state_manager.all_states().items()}
    
    @property
    def trade_history(self):
        """Access global trade history."""
        return self.core.trade_history
    
    # ---------------------------------------------------------------
    # UTILITY METHODS
    # ---------------------------------------------------------------
    def _parse_price(self, price_str: Optional[str]) -> Optional[float]:
        return parse_price(price_str)
    
    def _normalize_ticker(self, ticker: str) -> str:
        return normalize_ticker(ticker)
    
    def _normalize_bot_id(self, bot_id: Optional[str]) -> str:
        return normalize_bot_id(bot_id)
    
    def _state_key(self, bot_id: Optional[str], ticker: str) -> str:
        return make_state_key(bot_id, ticker)
    
    def _ensure_ticker(self, key: str, ticker: Optional[str] = None, 
                      bot_id: Optional[str] = None, bot_name: Optional[str] = None):
        """Ensure ticker state exists."""
        self.state_manager.get_or_create(key, ticker, bot_id, bot_name)
    
    def _is_trading_hours(self, start_time=None, end_time=None, days=None) -> bool:
        return self.core.is_trading_hours(start_time, end_time, days)
    
    def _buy(self, key: str, price: float):
        """Execute buy operation."""
        state = self.state_manager.get(key)
        if state:
            self.core.buy(key, price, state)
    
    def _sell(self, key: str, price: float, win_reason: Optional[str] = None):
        """Execute sell operation."""
        state = self.state_manager.get(key)
        if state:
            self.core.sell(key, price, state, win_reason)
    
    # ---------------------------------------------------------------
    # MAIN SIGNAL HANDLER
    # ---------------------------------------------------------------
    def on_signal(self, trend: str, price_str: Optional[str], ticker: str, 
                  auto: bool = True, rule_1_enabled: bool = False, 
                  take_profit_amount: Optional[float] = None, 
                  rule_2_enabled: bool = False, stop_loss_amount: Optional[float] = None,
                  rule_3_enabled: bool = False, rule_3_drop_count: Optional[int] = None,
                  rule_4_enabled: bool = True, rule_5_enabled: bool = False, 
                  rule_5_down_minutes: Optional[int] = None, 
                  rule_5_reversal_amount: Optional[float] = None, 
                  rule_5_scalp_amount: Optional[float] = None,
                  rule_6_enabled: bool = False, rule_6_down_minutes: Optional[int] = None, 
                  rule_6_profit_amount: Optional[float] = None,
                  rule_7_enabled: bool = False, rule_7_up_minutes: Optional[int] = None,
                  rule_8_enabled: bool = False, rule_8_buy_offset: Optional[float] = None, 
                  rule_8_sell_offset: Optional[float] = None,
                  rule_9_enabled: bool = False, rule_9_amount: Optional[float] = None, 
                  rule_9_flips: Optional[int] = None, 
                  rule_9_window_minutes: Optional[int] = None,
                  rule_4_start_time: Optional[str] = None,
                  rule_4_end_time: Optional[str] = None,
                  rule_4_days=None,
                  default_trade_enabled: bool = True,
                  bot_id: Optional[str] = None, bot_name: Optional[str] = None) -> Dict:
        """Handle signal for a given ticker."""
        ticker = self._normalize_ticker(ticker)
        price = self._parse_price(price_str)
        state_key = self._state_key(bot_id, ticker)
        
        if price is None or not state_key:
            return self.summary()
        
        trend = trend.lower()
        self._ensure_ticker(state_key, ticker=ticker, bot_id=bot_id, bot_name=bot_name)
        state = self.state_manager.get(state_key)
        
        # Create callback wrappers
        sell_cb = lambda p, win_reason=None: self._sell(state_key, p, win_reason)
        buy_cb = lambda p: self._buy(state_key, p)
        
        # RULE #1: take-profit sell (works alongside default logic)
        if rule_1_enabled:
            try:
                if rules.maybe_take_profit_sell(state, price, take_profit_amount, sell_cb):
                    return self.summary()
            except Exception:
                pass
        
        # RULE #2: stop loss
        if rule_2_enabled:
            try:
                if rules.maybe_stop_loss_sell(state, price, stop_loss_amount, sell_cb):
                    return self.summary()
            except Exception:
                pass
        
        # RULE #3: consecutive drops from peak
        if rule_3_enabled:
            try:
                if rules.maybe_consecutive_drops_sell(state, price, rule_3_drop_count, sell_cb):
                    return self.summary()
            except Exception:
                pass
        
        if auto:
            # RULE #4: trade only during market hours (optionally custom time/days)
            if rule_4_enabled and not self._is_trading_hours(rule_4_start_time, rule_4_end_time, rule_4_days):
                return self.summary()
            
            # RULE #5: 3-minute downtrend → reversal + scalp
            if rule_5_enabled:
                try:
                    if rules.maybe_rule5_trade(state, trend, price, rule_5_down_minutes,
                                               rule_5_reversal_amount, rule_5_scalp_amount,
                                               buy_cb, sell_cb):
                        return self.summary()
                except Exception:
                    pass
            
            # RULE #6: long wait → buy on reversal and sell at profit target
            if rule_6_enabled:
                try:
                    if rules.maybe_rule6_trade(state, trend, price, rule_6_down_minutes,
                                               rule_6_profit_amount, buy_cb, sell_cb):
                        return self.summary()
                except Exception:
                    pass
            
            # RULE #7: strong momentum buy after uptrend duration
            if rule_7_enabled:
                try:
                    if rules.maybe_rule7_trade(state, trend, price, rule_7_up_minutes, buy_cb):
                        return self.summary()
                except Exception:
                    pass
            
            # RULE #8: always buy/sell using offsets from current price
            if rule_8_enabled:
                try:
                    if rules.maybe_rule8_trade(state, price, rule_8_buy_offset, 
                                               rule_8_sell_offset, buy_cb, sell_cb):
                        return self.summary()
                except Exception:
                    pass
            
            # RULE #9: N up/down flips within M minutes → quick scalp
            if rule_9_enabled:
                try:
                    if rules.maybe_rule9_trade(state, trend, price, rule_9_amount, 
                                               rule_9_flips, rule_9_window_minutes, 
                                               buy_cb, sell_cb):
                        return self.summary()
                except Exception:
                    pass
            
            # Default: buy every rise, sell every fall (can be disabled per-bot)
            if default_trade_enabled:
                if trend == "up" and state.position is None:
                    self._buy(state_key, price)
                elif trend == "down" and state.position is not None:
                    win_reason = "RULE_7" if state.rule7_active else None
                    self._sell(state_key, price, win_reason=win_reason)
                    # Full Rule 7 reset so the 'active' flag is seen on the next tick
                    state.rule7_active = False
                    state.rule7_up_start = None
                    state.rule7_ready_for_buy = False
        
        return self.summary()
    
    # ---------------------------------------------------------------
    # MANUAL TOGGLE
    # ---------------------------------------------------------------
    def manual_toggle(self, price_str: Optional[str], ticker: str, 
                     bot_id: Optional[str] = None, bot_name: Optional[str] = None) -> Dict:
        """Manually toggle position (buy if flat, sell if long)."""
        ticker = self._normalize_ticker(ticker)
        price = self._parse_price(price_str)
        state_key = self._state_key(bot_id, ticker)
        
        if price is None or not state_key:
            return self.summary()
        
        self._ensure_ticker(state_key, ticker=ticker, bot_id=bot_id, bot_name=bot_name)
        state = self.state_manager.get(state_key)
        
        if state.position is None:
            self._buy(state_key, price)
        else:
            self._sell(state_key, price)
        
        return self.summary()
    
    # ---------------------------------------------------------------
    # LEGACY METHOD (Rule #1 take-profit mode - deprecated, use on_signal with rule_1_enabled)
    # ---------------------------------------------------------------
    def on_signal_take_profit_mode(self, *args, **kwargs) -> Dict:
        """
        Legacy method for backward compatibility.
        Now redirects to on_signal with rule_1_enabled=True.
        """
        kwargs['rule_1_enabled'] = True
        return self.on_signal(*args, **kwargs)
    
    # ---------------------------------------------------------------
    # INDIVIDUAL RULE METHODS (for direct invocation if needed)
    # ---------------------------------------------------------------
    def maybe_take_profit_sell(self, ticker: str, current_price, take_profit_amount) -> bool:
        """Direct invocation of Rule #1."""
        state = self.state_manager.get(ticker)
        if not state:
            return False
        sell_cb = lambda p, win_reason=None: self._sell(ticker, p, win_reason)
        return rules.maybe_take_profit_sell(state, current_price, take_profit_amount, sell_cb)
    
    def maybe_stop_loss_sell(self, ticker: str, current_price, 
                            stop_loss_amount: Optional[float] = None) -> bool:
        """Direct invocation of Rule #2."""
        state = self.state_manager.get(ticker)
        if not state:
            return False
        sell_cb = lambda p, win_reason=None: self._sell(ticker, p, win_reason)
        return rules.maybe_stop_loss_sell(state, current_price, stop_loss_amount, sell_cb)
    
    def maybe_consecutive_drops_sell(self, ticker: str, current_price, 
                                    drop_count_required: Optional[int] = None) -> bool:
        """Direct invocation of Rule #3."""
        state = self.state_manager.get(ticker)
        if not state:
            return False
        sell_cb = lambda p, win_reason=None: self._sell(ticker, p, win_reason)
        return rules.maybe_consecutive_drops_sell(state, current_price, 
                                                 drop_count_required, sell_cb)
    
    def maybe_rule5_trade(self, ticker: str, trend: str, current_price: float,
                         down_minutes: Optional[int] = None, 
                         reversal_amount: Optional[float] = None,
                         scalp_amount: Optional[float] = None) -> bool:
        """Direct invocation of Rule #5."""
        state = self.state_manager.get(ticker)
        if not state:
            return False
        buy_cb = lambda p: self._buy(ticker, p)
        sell_cb = lambda p, win_reason=None: self._sell(ticker, p, win_reason)
        return rules.maybe_rule5_trade(state, trend, current_price, down_minutes,
                                       reversal_amount, scalp_amount, buy_cb, sell_cb)
    
    def maybe_rule6_trade(self, ticker: str, trend: str, current_price: float,
                         down_minutes: Optional[int] = None, 
                         profit_amount: Optional[float] = None) -> bool:
        """Direct invocation of Rule #6."""
        state = self.state_manager.get(ticker)
        if not state:
            return False
        buy_cb = lambda p: self._buy(ticker, p)
        sell_cb = lambda p, win_reason=None: self._sell(ticker, p, win_reason)
        return rules.maybe_rule6_trade(state, trend, current_price, down_minutes,
                                       profit_amount, buy_cb, sell_cb)
    
    def maybe_rule7_trade(self, ticker: str, trend: str, current_price: float,
                         up_minutes: Optional[int] = None) -> bool:
        """Direct invocation of Rule #7."""
        state = self.state_manager.get(ticker)
        if not state:
            return False
        buy_cb = lambda p: self._buy(ticker, p)
        return rules.maybe_rule7_trade(state, trend, current_price, up_minutes, buy_cb)
    
    def maybe_rule8_trade(self, ticker: str, current_price: float,
                         buy_offset: Optional[float] = None, 
                         sell_offset: Optional[float] = None) -> bool:
        """Direct invocation of Rule #8."""
        state = self.state_manager.get(ticker)
        if not state:
            return False
        buy_cb = lambda p: self._buy(ticker, p)
        sell_cb = lambda p, win_reason=None: self._sell(ticker, p, win_reason)
        return rules.maybe_rule8_trade(state, current_price, buy_offset, 
                                       sell_offset, buy_cb, sell_cb)
    
    def maybe_rule9_trade(self, ticker: str, trend: str, current_price: float,
                         amount: Optional[float] = None, flips: Optional[int] = None,
                         window_minutes: Optional[int] = None) -> bool:
        """Direct invocation of Rule #9."""
        state = self.state_manager.get(ticker)
        if not state:
            return False
        buy_cb = lambda p: self._buy(ticker, p)
        sell_cb = lambda p, win_reason=None: self._sell(ticker, p, win_reason)
        return rules.maybe_rule9_trade(state, trend, current_price, amount, 
                                       flips, window_minutes, buy_cb, sell_cb)
    
    # ---------------------------------------------------------------
    # SUMMARY & RESET
    # ---------------------------------------------------------------
    def summary(self) -> Dict:
        """Generate summary of all positions and trading history."""
        return self.core.generate_summary()
    
    def clear_bot(self, bot_id: Optional[str], ticker: Optional[str] = None):
        """Clear specific bot's state and history."""
        key = self._state_key(bot_id, ticker or '')
        self.core.clear_bot(bot_id, ticker, key)
    
    def clear_all(self):
        """Clear all states and history."""
        self.core.clear_all()
