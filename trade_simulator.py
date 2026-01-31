"""
Improved Per-Ticker Trade Simulator for Demo/Testing

Enhancements:
- Handles multiple tickers independently
- First-cycle special rule for first DOWN signal
- Normal trading logic after first cycle per ticker
- Full trade logging per ticker
- PnL statistics, win/loss counts, win rate
- Optional callback on each trade
- Manual toggle per ticker
- Robust price parsing with $, commas, spaces
"""

from typing import Optional, List, Dict, Callable
from datetime import datetime


class TradeSimulator:
    def __init__(self, on_trade: Optional[Callable[[Dict], None]] = None):
        # Each ticker has its own state
        self.tickers: Dict[str, Dict] = {}
        # Full global trade history (all tickers)
        self.trade_history: List[Dict] = []
        # Optional callback
        self.on_trade = on_trade

    # ---------------------------------------------------------------
    # PRICE PARSER
    # ---------------------------------------------------------------
    def _parse_price(self, price_str: Optional[str]) -> Optional[float]:
        """Convert price string to float, handling $, commas, and spaces."""
        if not price_str:
            return None
        try:
            clean = str(price_str).strip().replace("$", "").replace(",", "").replace(" ", "")
            return float(clean)
        except ValueError:
            return None

    # ---------------------------------------------------------------
    # ENSURE TICKER STATE
    # ---------------------------------------------------------------
    def _normalize_ticker(self, ticker: str) -> str:
        try:
            return str(ticker or '').strip().upper()
        except Exception:
            return ''

    def _ensure_ticker(self, ticker: str):
        ticker = self._normalize_ticker(ticker)
        if not ticker:
            return
        if ticker not in self.tickers:
            self.tickers[ticker] = {
                "position": None,                 # current open trade
                "first_cycle_done": False,        # special first-cycle completed
                "waiting_for_second_down": False, # first-cycle flag
                "trade_history": [],              # ticker-specific trades
                "last_direction": None,
                "last_price": None,
                "peak_price": None,
                "drop_count": 0
            }

    # ---------------------------------------------------------------
    # RULE #4 - TRADING HOURS
    # ---------------------------------------------------------------
    def _is_trading_hours(self) -> bool:
        """Return True if local time is Mon-Fri 9:30am–4:00pm."""
        try:
            now = datetime.now()
            # Monday=0 ... Sunday=6
            if now.weekday() > 4:
                return False
            total_minutes = now.hour * 60 + now.minute
            return (total_minutes >= (9 * 60 + 30)) and (total_minutes <= (16 * 60))
        except Exception:
            return True

    # ---------------------------------------------------------------
    # SIGNAL HANDLER
    # ---------------------------------------------------------------
    def on_signal(self, trend: str, price_str: Optional[str], ticker: str, auto: bool = True, rule_2_enabled: bool = False, stop_loss_amount: Optional[float] = None, rule_3_enabled: bool = False, rule_3_drop_count: Optional[int] = None, rule_4_enabled: bool = True) -> Dict:
        """Handle signal for a given ticker."""
        ticker = self._normalize_ticker(ticker)
        price = self._parse_price(price_str)
        if price is None or not ticker:
            return self.summary()

        trend = trend.lower()
        self._ensure_ticker(ticker)
        state = self.tickers[ticker]

        # RULE #2: stop loss at buy price - stop_loss_amount
        if rule_2_enabled:
            try:
                if self.maybe_stop_loss_sell(ticker, price, stop_loss_amount):
                    return self.summary()
            except Exception:
                pass

        # RULE #3: consecutive drops from peak
        if rule_3_enabled:
            try:
                if self.maybe_consecutive_drops_sell(ticker, price, rule_3_drop_count):
                    return self.summary()
            except Exception:
                pass

        if auto:
            # RULE #4: trade only during market hours (Mon–Fri 9:30–16:00)
            if rule_4_enabled and not self._is_trading_hours():
                return self.summary()
            # --------------------------
            # FIRST CYCLE LOGIC (first DOWN special)
            # --------------------------
            if not state["first_cycle_done"]:
                if trend == "down" and state["position"] is None:
                    self._buy(ticker, price)
                    state["waiting_for_second_down"] = True
                    return self.summary()

                if trend == "up" and state["waiting_for_second_down"]:
                    # ignore UP after first buy
                    return self.summary()

                if trend == "down" and state["waiting_for_second_down"]:
                    self._sell(ticker, price)
                    state["first_cycle_done"] = True
                    state["waiting_for_second_down"] = False
                    return self.summary()

                # If first trend is UP → start normal mode
                if trend == "up" and state["position"] is None:
                    state["first_cycle_done"] = True
                    self._buy(ticker, price)
                    return self.summary()

            # --------------------------
            # NORMAL MODE
            # --------------------------
            if trend == "up" and state["position"] is None:
                self._buy(ticker, price)

            elif trend == "down" and state["position"] is not None:
                self._sell(ticker, price)

        return self.summary()

    # ---------------------------------------------------------------
    # MANUAL TOGGLE (per ticker)
    # ---------------------------------------------------------------
    def manual_toggle(self, price_str: Optional[str], ticker: str) -> Dict:
        ticker = self._normalize_ticker(ticker)
        price = self._parse_price(price_str)
        if price is None or not ticker:
            return self.summary()

        self._ensure_ticker(ticker)
        state = self.tickers[ticker]

        if state["position"] is None:
            self._buy(ticker, price)
        else:
            self._sell(ticker, price)

        return self.summary()

    # ---------------------------------------------------------------
    # BUY / SELL
    # ---------------------------------------------------------------
    def _buy(self, ticker: str, price: float):
        ticker = self._normalize_ticker(ticker)
        if not ticker:
            return
        self.tickers[ticker]["position"] = {
            "entry": price,
            "ticker": ticker,
            "ts": datetime.utcnow().isoformat() + 'Z'
        }
        self.tickers[ticker]["last_direction"] = "buy"
        # initialize rule state
        try:
            self.tickers[ticker]["last_price"] = float(price)
            self.tickers[ticker]["peak_price"] = float(price)
            self.tickers[ticker]["drop_count"] = 0
        except Exception:
            self.tickers[ticker]["last_price"] = None
            self.tickers[ticker]["peak_price"] = None
            self.tickers[ticker]["drop_count"] = 0
        self._log_trade(ticker, "buy", price, None, win_reason=None)

    def _sell(self, ticker: str, price: float, win_reason: Optional[str] = None):
        ticker = self._normalize_ticker(ticker)
        if not ticker:
            return
        pos = self.tickers[ticker]["position"]
        if pos is None:
            return

        profit = price - pos["entry"]
        self.tickers[ticker]["last_direction"] = "sell"
        self._log_trade(ticker, "sell", price, profit, win_reason=win_reason)
        self.tickers[ticker]["position"] = None
        # reset rule state
        self.tickers[ticker]["last_price"] = None
        self.tickers[ticker]["peak_price"] = None
        self.tickers[ticker]["drop_count"] = 0

    # ---------------------------------------------------------------
    # LOGGING
    # ---------------------------------------------------------------
    def _log_trade(self, ticker: str, direction: str, price: float, profit: Optional[float], win_reason: Optional[str] = None):
        entry = {
            "ticker": ticker,
            "direction": direction,
            "price": price,
            "profit": profit,
            "win_reason": win_reason,
            "ts": datetime.utcnow().isoformat() + 'Z'
        }

        # Add to global history and ticker-specific history
        self.trade_history.append(entry)
        self.tickers[ticker]["trade_history"].append(entry)

        # Optional callback
        if self.on_trade:
            try:
                self.on_trade(entry)
            except Exception:
                pass

    # ---------------------------------------------------------------
    # RULE #1 - TAKE PROFIT
    # ---------------------------------------------------------------
    def maybe_take_profit_sell(self, ticker: str, current_price, take_profit_amount) -> bool:
        """Sell only when current_price >= entry + take_profit_amount.

        Returns True when a sell was executed.
        """
        ticker = self._normalize_ticker(ticker)
        if not ticker:
            return False
        self._ensure_ticker(ticker)
        state = self.tickers[ticker]
        pos = state.get('position')
        if not pos:
            return False
        entry = None
        try:
            entry = pos.get('entry')
        except Exception:
            entry = None
        if entry is None:
            return False

        try:
            tp = float(take_profit_amount)
        except Exception:
            return False
        if not (tp > 0):
            return False

        cp = None
        try:
            if isinstance(current_price, (int, float)):
                cp = float(current_price)
            else:
                cp = self._parse_price(current_price)
        except Exception:
            cp = None
        if cp is None:
            return False
        try:
            if cp >= (float(entry) + tp):
                self._sell(ticker, cp, win_reason="TAKE_PROFIT_RULE_1")
                return True
        except Exception:
            return False
        return False

    # ---------------------------------------------------------------
    # RULE #2 - STOP LOSS AT BUY PRICE
    # ---------------------------------------------------------------
    def maybe_stop_loss_sell(self, ticker: str, current_price, stop_loss_amount: Optional[float] = None) -> bool:
        """Sell immediately when current_price <= entry - stop_loss_amount (Rule #2)."""
        ticker = self._normalize_ticker(ticker)
        if not ticker:
            return False
        self._ensure_ticker(ticker)
        state = self.tickers[ticker]
        pos = state.get('position')
        if not pos:
            return False
        entry = None
        try:
            entry = pos.get('entry')
        except Exception:
            entry = None
        if entry is None:
            return False

        cp = None
        try:
            if isinstance(current_price, (int, float)):
                cp = float(current_price)
            else:
                cp = self._parse_price(current_price)
        except Exception:
            cp = None
        if cp is None:
            return False

        sl = 0.0
        try:
            if stop_loss_amount is not None:
                sl = float(stop_loss_amount)
        except Exception:
            sl = 0.0
        if sl < 0:
            sl = 0.0

        try:
            if cp <= (float(entry) - sl):
                self._sell(ticker, cp, win_reason="STOP_LOSS_RULE_2")
                return True
        except Exception:
            return False
        return False

    # ---------------------------------------------------------------
    # RULE #3 - CONSECUTIVE DROPS FROM PEAK
    # ---------------------------------------------------------------
    def maybe_consecutive_drops_sell(self, ticker: str, current_price, drop_count_required: Optional[int] = None) -> bool:
        """Sell when price has dropped N consecutive times from the peak (Rule #3)."""
        ticker = self._normalize_ticker(ticker)
        if not ticker:
            return False
        self._ensure_ticker(ticker)
        state = self.tickers[ticker]
        pos = state.get('position')
        if not pos:
            return False

        try:
            n_required = int(drop_count_required) if drop_count_required is not None else 0
        except Exception:
            n_required = 0
        if n_required <= 0:
            return False

        cp = None
        try:
            if isinstance(current_price, (int, float)):
                cp = float(current_price)
            else:
                cp = self._parse_price(current_price)
        except Exception:
            cp = None
        if cp is None:
            return False

        # initialize last if needed
        if state.get('last_price') is None:
            state['last_price'] = float(cp)

        # update consecutive drop count (double lower = sell)
        try:
            last_price = float(state['last_price'])
            if cp < last_price:
                state['drop_count'] = int(state.get('drop_count') or 0) + 1
            elif cp > last_price:
                # reset on uptick
                state['drop_count'] = 0
            state['last_price'] = float(cp)
        except Exception:
            pass

        try:
            if int(state.get('drop_count') or 0) >= n_required:
                self._sell(ticker, cp, win_reason="CONSECUTIVE_DROPS_RULE_3")
                return True
        except Exception:
            return False
        return False

    # ---------------------------------------------------------------
    # RULE #1 MODE - BUY AS USUAL, SELL ONLY ON TAKE PROFIT
    # ---------------------------------------------------------------
    def on_signal_take_profit_mode(self, trend: str, price_str: Optional[str], ticker: str, take_profit_amount, auto: bool = True, rule_2_enabled: bool = False, stop_loss_amount: Optional[float] = None, rule_3_enabled: bool = False, rule_3_drop_count: Optional[int] = None, rule_4_enabled: bool = True) -> Dict:
        """In Rule #1 mode, buys may still be opened, but sells only occur via take-profit.

        This keeps the system able to enter positions, while overriding all other sell logic.
        """
        ticker = self._normalize_ticker(ticker)
        price = self._parse_price(price_str)
        if price is None or not ticker:
            return self.summary()

        trend = (trend or '').lower()
        self._ensure_ticker(ticker)
        state = self.tickers[ticker]

        # First, attempt Rule #2 stop-loss sell if enabled.
        if rule_2_enabled:
            try:
                if self.maybe_stop_loss_sell(ticker, price, stop_loss_amount):
                    return self.summary()
            except Exception:
                pass

        # Then, attempt Rule #3 consecutive drops if enabled.
        if rule_3_enabled:
            try:
                if self.maybe_consecutive_drops_sell(ticker, price, rule_3_drop_count):
                    return self.summary()
            except Exception:
                pass

        # Then, attempt take-profit sell if we already have a position.
        try:
            self.maybe_take_profit_sell(ticker, price, take_profit_amount)
        except Exception:
            pass

        if not auto:
            return self.summary()

        # RULE #4: trade only during market hours (Mon–Fri 9:30–16:00)
        if rule_4_enabled and not self._is_trading_hours():
            return self.summary()

        # If position still open, do not sell on down/other signals.
        if state.get('position') is not None:
            return self.summary()

        # No open position: allow normal buy behavior, but never sell.
        if not state.get('first_cycle_done'):
            if trend == 'down' and state.get('position') is None:
                self._buy(ticker, price)
                state['waiting_for_second_down'] = True
                return self.summary()

            if trend == 'up' and state.get('waiting_for_second_down'):
                # ignore UP after first buy
                return self.summary()

            if trend == 'down' and state.get('waiting_for_second_down'):
                # normally this would sell; in Rule #1 mode we just exit first-cycle
                state['first_cycle_done'] = True
                state['waiting_for_second_down'] = False
                return self.summary()

            # If first trend is UP → start normal mode and buy
            if trend == 'up' and state.get('position') is None:
                state['first_cycle_done'] = True
                self._buy(ticker, price)
                return self.summary()

        # Normal mode buy rules (sell rules intentionally disabled)
        if trend == 'up' and state.get('position') is None:
            self._buy(ticker, price)

        return self.summary()

    # ---------------------------------------------------------------
    # SUMMARY
    # ---------------------------------------------------------------
    def summary(self) -> Dict:
        summary_dict = {}

        for ticker, state in self.tickers.items():
            closed_profits = [t["profit"] for t in state["trade_history"] if t["profit"] is not None]
            total_pnl = sum(closed_profits) if closed_profits else 0
            wins = sum(1 for p in closed_profits if p > 0)
            losses = sum(1 for p in closed_profits if p <= 0)
            win_rate = (wins / len(closed_profits) * 100) if closed_profits else 0
            last_trade = state["trade_history"][-1] if state["trade_history"] else None

            summary_dict[ticker] = {
                "position": "long" if state["position"] else "flat",
                "entry_price": state["position"]["entry"] if state["position"] else None,
                "first_cycle_done": state["first_cycle_done"],
                "last_direction": state["last_direction"],
                "last_trade": last_trade,
                "total_pnl": total_pnl,
                "wins": wins,
                "losses": losses,
                "win_rate": round(win_rate, 2),
                "trade_history": state["trade_history"].copy()
            }

        return {
            "tickers": summary_dict,
            "total_pnl_all_tickers": sum(t["total_pnl"] for t in summary_dict.values()),
            "all_trades": self.trade_history.copy()
        }
