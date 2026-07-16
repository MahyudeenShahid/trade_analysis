"""Trading rules implementation (Rules 1-13).

Each rule modifies trading behavior based on specific conditions.
"""

from typing import TYPE_CHECKING, Optional
import logging
from datetime import datetime

if TYPE_CHECKING:
    from trading.state import TickerState

logger = logging.getLogger(__name__)

# Rule 13 — Blue Graph Direction (slope-based buy/sell)
from .rule13 import maybe_rule13_trade, _compute_slope_pct  # noqa: E402,F401

# Rule 10 — RSI + Bollinger Reversal
from .rules_rsi_bollinger import maybe_rsi_bollinger_trade  # noqa: E402,F401

# Rule 11 — Momentum Tick Breakout
from .rules_breakout import maybe_rule11_trade  # noqa: E402,F401

# Rule 12 — Tape + Order Book Meter
from .rules_tape_meter import maybe_rule12_trade  # noqa: E402,F401


def graph_trend_filter_ok(price_history: list, lookback: int = 5, threshold_pct: float = 0.0005) -> bool:
    """
    Returns True when recent prices are sloping UP (blue graph pointing up).

    Used as an optional gate inside Rule 10 (rsi_bollinger_graph_trend_enabled).
    """
    slope = _compute_slope_pct(price_history, lookback)
    if slope is None:
        return True  # insufficient data — do not block the trade
    return slope > threshold_pct


def maybe_take_profit_sell(state: 'TickerState', current_price: float,
                           take_profit_amount: Optional[float],
                           sell_callback) -> bool:
    """
    Rule #1: Sell only when current_price >= entry + take_profit_amount.

    Returns True when a sell was executed.
    """
    pos = state.position
    if not pos:
        return False

    entry = pos.get('entry')
    if entry is None:
        return False

    try:
        tp = float(take_profit_amount)
        if tp <= 0:
            return False
    except (ValueError, TypeError):
        return False

    if current_price >= (float(entry) + tp):
        sell_callback(current_price, win_reason="TAKE_PROFIT_RULE_1")
        return True
    return False


def maybe_stop_loss_sell(state: 'TickerState', current_price: float,
                         stop_loss_amount: Optional[float],
                         sell_callback) -> bool:
    """Rule #2: Sell immediately when current_price <= entry - stop_loss_amount."""
    pos = state.position
    if not pos:
        return False

    entry = pos.get('entry')
    if entry is None:
        return False

    try:
        sl = float(stop_loss_amount) if stop_loss_amount is not None else 0.0
        if sl < 0:
            sl = 0.0
    except (ValueError, TypeError):
        sl = 0.0

    if current_price <= (float(entry) - sl):
        sell_callback(current_price, win_reason="STOP_LOSS_RULE_2")
        return True
    return False


def maybe_consecutive_drops_sell(state: 'TickerState', current_price: float,
                                 drop_count_required: Optional[int],
                                 sell_callback) -> bool:
    """Rule #3: Sell when price has dropped N consecutive times from the peak."""
    if not state.position:
        return False

    try:
        n_required = int(drop_count_required) if drop_count_required is not None else 0
        if n_required <= 0:
            return False
    except (ValueError, TypeError):
        return False

    if state.last_price is None:
        state.last_price = float(current_price)
        return False

    try:
        last_price = float(state.last_price)
        if current_price < last_price:
            state.drop_count += 1
        elif current_price > last_price:
            state.drop_count = 0
        state.last_price = float(current_price)
    except (ValueError, TypeError):
        pass

    if state.drop_count >= n_required:
        sell_callback(current_price, win_reason="CONSECUTIVE_DROPS_RULE_3")
        state.drop_count = 0
        return True
    return False


def maybe_rule5_trade(state: 'TickerState', trend: str, current_price: float,
                     down_minutes: Optional[int], reversal_amount: Optional[float],
                     scalp_amount: Optional[float], buy_callback, sell_callback) -> bool:
    """
    Rule #5: 3-minute downtrend → reversal + scalp.

    1. Track continuous downtrend for N minutes
    2. On reversal, buy and wait for reversal_amount profit
    3. After reversal profit, enter scalp mode (quick trades)
    """
    down_m = max(int(down_minutes) if down_minutes else 3, 1)
    rev_amt = max(float(reversal_amount) if reversal_amount else 2.0, 0.1)
    scalp_amt = max(float(scalp_amount) if scalp_amount else 0.25, 0.01)

    now = datetime.utcnow()
    trend = (trend or '').lower()

    if state.rule5_reversal_active:
        if state.rule5_reversal_price is not None and current_price >= (state.rule5_reversal_price + rev_amt):
            sell_callback(current_price, win_reason="RULE_5")
            state.rule5_reversal_active = False
            state.rule5_reversal_price = None
            state.rule5_scalp_active = True
        return True

    if state.rule5_scalp_active:
        if trend != 'up':
            state.rule5_scalp_active = False
        else:
            if state.position is None:
                buy_callback(current_price)
                sell_callback(current_price + scalp_amt, win_reason="RULE_5")
                return True
            return True

    if trend == 'down':
        if state.rule5_down_start is None:
            state.rule5_down_start = now
        else:
            elapsed = (now - state.rule5_down_start).total_seconds() / 60.0
            if elapsed >= down_m:
                state.rule5_ready_for_reversal = True
    else:
        if not state.rule5_ready_for_reversal:
            state.rule5_down_start = None

    if state.rule5_ready_for_reversal and trend == 'up':
        state.rule5_ready_for_reversal = False
        state.rule5_down_start = None
        state.rule5_reversal_price = float(current_price)
        state.rule5_reversal_active = True
        if state.position is None:
            buy_callback(current_price)
        return True

    return False


def maybe_rule6_trade(state: 'TickerState', trend: str, current_price: float,
                     down_minutes: Optional[int], profit_amount: Optional[float],
                     buy_callback, sell_callback) -> bool:
    """Rule #6: Long wait (down > N minutes) → up buy → sell at profit target."""
    down_m = max(int(down_minutes) if down_minutes else 5, 1)
    prof_amt = max(float(profit_amount) if profit_amount else 2.0, 0.1)

    now = datetime.utcnow()
    trend = (trend or '').lower()

    if state.rule6_active and state.position is not None:
        entry = state.position.get('entry')
        if entry is not None and current_price >= (float(entry) + prof_amt):
            sell_callback(current_price, win_reason="RULE_6")
            state.rule6_active = False
        return True

    if trend == 'down':
        if state.rule6_down_start is None:
            state.rule6_down_start = now
        else:
            elapsed = (now - state.rule6_down_start).total_seconds() / 60.0
            if elapsed >= down_m:
                state.rule6_ready_for_buy = True
    else:
        if not state.rule6_ready_for_buy:
            state.rule6_down_start = None

    if state.rule6_ready_for_buy and trend == 'up':
        state.rule6_ready_for_buy = False
        state.rule6_down_start = None
        if state.position is None:
            buy_callback(current_price)
        state.rule6_active = True
        return True

    return False


def maybe_rule7_trade(state: 'TickerState', trend: str, current_price: float,
                     up_minutes: Optional[int], buy_callback) -> bool:
    """
    Rule #7: Buy after price has been continuously going UP for N seconds.

    After a sell, the timer fully resets and must count N seconds again.
    """
    up_s = max(int(up_minutes) if up_minutes else 30, 1)

    now = datetime.utcnow()
    trend = (trend or '').lower()

    if state.rule7_active and state.position is not None:
        return False

    if state.rule7_active and state.position is None:
        state.rule7_active = False
        state.rule7_up_start = None
        state.rule7_ready_for_buy = False
        return False

    if trend != 'up':
        state.rule7_up_start = None
        state.rule7_ready_for_buy = False
        return False

    if state.rule7_up_start is None:
        state.rule7_up_start = now
    else:
        elapsed = (now - state.rule7_up_start).total_seconds()
        if elapsed >= up_s:
            state.rule7_ready_for_buy = True

    if state.rule7_ready_for_buy and state.position is None:
        state.rule7_ready_for_buy = False
        state.rule7_up_start = None
        buy_callback(current_price)
        state.rule7_active = True
        return True

    return True


def maybe_rule8_trade(state: 'TickerState', current_price: float,
                     buy_offset: Optional[float], sell_offset: Optional[float],
                     buy_callback, sell_callback) -> bool:
    """
    Rule #8: Limit-order style offset trading.

    - While flat: tracks a rolling peak. Buys when price drops buy_offset below peak.
    - While in position: sells when price rises sell_offset above entry.
    """
    bo = float(buy_offset) if buy_offset is not None else 0.25
    so = float(sell_offset) if sell_offset is not None else 0.25

    if state.position is None:
        if state.rule8_watch_price is None or current_price > state.rule8_watch_price:
            state.rule8_watch_price = current_price

        if current_price <= state.rule8_watch_price - bo:
            buy_callback(current_price)
            state.rule8_watch_price = None
    else:
        entry = state.position.get('entry')
        if entry is not None and current_price >= float(entry) + so:
            sell_callback(current_price, win_reason="RULE_8")
            state.rule8_watch_price = None

    return True


def maybe_rule9_trade(state: 'TickerState', trend: str, current_price: float,
                     amount: Optional[float], flips: Optional[int],
                     window_minutes: Optional[int], buy_callback, sell_callback) -> bool:
    """
    Rule #9: Cooldown gate — after a buy+sell cycle, block any new buy for N seconds.

    'window_minutes' is reused as the cooldown duration in seconds (default 15).
    """
    cooldown_s = max(int(window_minutes) if window_minutes else 15, 1)
    now = datetime.utcnow()

    if state.position is None and state.rule9_last_sell_time is not None:
        elapsed = (now - state.rule9_last_sell_time).total_seconds()
        if elapsed < cooldown_s:
            return True

    return False
