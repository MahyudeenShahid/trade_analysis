"""Mixin for legacy rules testing on TradeSimulator."""

from typing import Optional, Dict
from trading import rules


class LegacyRulesMixin:
    """Mixin containing legacy/direct rule invocation testing methods for TradeSimulator."""

    def on_signal_take_profit_mode(self, *args, **kwargs) -> Dict:
        """
        Legacy method for backward compatibility.
        Now redirects to on_signal with rule_1_enabled=True.
        """
        kwargs['rule_1_enabled'] = True
        return self.on_signal(*args, **kwargs)

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
