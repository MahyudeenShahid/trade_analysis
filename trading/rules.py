"""
Trading rules implementation (Rules 1-9).
Each rule modifies trading behavior based on specific conditions.
"""

from typing import TYPE_CHECKING, Optional
from datetime import datetime

if TYPE_CHECKING:
    from trading.state import TickerState


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
    """
    Rule #2: Sell immediately when current_price <= entry - stop_loss_amount.
    """
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
    """
    Rule #3: Sell when price has dropped N consecutive times from the peak.
    """
    if not state.position:
        return False

    try:
        n_required = int(drop_count_required) if drop_count_required is not None else 0
        if n_required <= 0:
            return False
    except (ValueError, TypeError):
        return False

    # Initialize last price if needed
    if state.last_price is None:
        state.last_price = float(current_price)
        return False

    # Update consecutive drop count
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
    # Normalize parameters
    down_m = max(int(down_minutes) if down_minutes else 3, 1)
    rev_amt = max(float(reversal_amount) if reversal_amount else 2.0, 0.1)
    scalp_amt = max(float(scalp_amount) if scalp_amount else 0.25, 0.01)

    now = datetime.utcnow()
    trend = (trend or '').lower()

    # Check if in reversal trade (waiting for target)
    if state.to_dict().get('rule5_reversal_active'):
        data = state.to_dict()
        rp = data.get('rule5_reversal_price')
        if rp is not None and current_price >= (float(rp) + rev_amt):
            sell_callback(current_price, win_reason="RULE_5")
            data['rule5_reversal_active'] = False
            data['rule5_reversal_price'] = None
            data['rule5_scalp_active'] = True
            return True
        return True  # Block normal trading while waiting

    # Check if in scalp mode
    data = state.to_dict()
    if data.get('rule5_scalp_active'):
        if trend != 'up':
            data['rule5_scalp_active'] = False
        else:
            # Execute quick scalp trades on each up tick
            if state.position is None:
                buy_price = current_price - scalp_amt
                sell_price = current_price + scalp_amt
                buy_callback(buy_price)
                sell_callback(sell_price, win_reason="RULE_5")
                return True
            return True

    # Track continuous downtrend duration
    if trend == 'down':
        if state.rule5_down_start is None:
            state.rule5_down_start = now
        else:
            elapsed = (now - state.rule5_down_start).total_seconds() / 60.0
            if elapsed >= down_m:
                data['rule5_ready_for_reversal'] = True
    else:
        if not data.get('rule5_ready_for_reversal'):
            state.rule5_down_start = None

    # Wait for uptrend to start reversal trade
    if data.get('rule5_ready_for_reversal') and trend == 'up':
        data['rule5_ready_for_reversal'] = False
        state.rule5_down_start = None
        data['rule5_reversal_price'] = float(current_price)
        data['rule5_reversal_active'] = True
        if state.position is None:
            buy_callback(current_price)
        return True

    return False


def maybe_rule6_trade(state: 'TickerState', trend: str, current_price: float,
                     down_minutes: Optional[int], profit_amount: Optional[float],
                     buy_callback, sell_callback) -> bool:
    """
    Rule #6: Long wait (down > N minutes) → up buy → sell at profit target.
    """
    down_m = max(int(down_minutes) if down_minutes else 5, 1)
    prof_amt = max(float(profit_amount) if profit_amount else 2.0, 0.1)

    now = datetime.utcnow()
    trend = (trend or '').lower()

    # If active, sell when target reached
    data = state.to_dict()
    if data.get('rule6_active') and state.position is not None:
        entry = state.position.get('entry')
        if entry is not None and current_price >= (float(entry) + prof_amt):
            sell_callback(current_price, win_reason="RULE_6")
            data['rule6_active'] = False
            return True
        return True  # Block normal trading while waiting

    # Track continuous downtrend duration
    if trend == 'down':
        if state.rule6_down_start is None:
            state.rule6_down_start = now
        else:
            elapsed = (now - state.rule6_down_start).total_seconds() / 60.0
            if elapsed >= down_m:
                data['rule6_ready_for_buy'] = True
    else:
        if not data.get('rule6_ready_for_buy'):
            state.rule6_down_start = None

    # When trend flips up and ready, buy and hold for profit target
    if data.get('rule6_ready_for_buy') and trend == 'up':
        data['rule6_ready_for_buy'] = False
        state.rule6_down_start = None
        if state.position is None:
            buy_callback(current_price)
        data['rule6_active'] = True
        return True

    return False


def maybe_rule7_trade(state: 'TickerState', trend: str, current_price: float,
                     up_minutes: Optional[int], buy_callback) -> bool:
    """
    Rule #7: Strong momentum buy after uptrend duration.
    Buy after continuous uptrend for N minutes.
    """
    up_m = max(int(up_minutes) if up_minutes else 3, 1)

    now = datetime.utcnow()
    trend = (trend or '').lower()

    # If already in position via Rule #7, do not block normal logic
    if state.rule7_active and state.position is not None:
        return False

    # Track continuous uptrend duration
    data = state.to_dict()
    if trend == 'up':
        if state.rule7_up_start is None:
            state.rule7_up_start = now
        else:
            elapsed = (now - state.rule7_up_start).total_seconds() / 60.0
            if elapsed >= up_m:
                data['rule7_ready_for_buy'] = True
    else:
        if not data.get('rule7_ready_for_buy'):
            state.rule7_up_start = None

    # When ready and still trending up, buy
    if data.get('rule7_ready_for_buy') and trend == 'up':
        data['rule7_ready_for_buy'] = False
        state.rule7_up_start = None
        if state.position is None:
            buy_callback(current_price)
        state.rule7_active = True
        return True

    return False


def maybe_rule8_trade(state: 'TickerState', current_price: float,
                     buy_offset: Optional[float], sell_offset: Optional[float],
                     buy_callback, sell_callback) -> bool:
    """
    Rule #8: Always place offset buy/sell.
    Buy at current - offset, sell at current + offset.
    """
    bo = float(buy_offset) if buy_offset is not None else 0.25
    so = float(sell_offset) if sell_offset is not None else 0.25

    data = state.to_dict()
    if state.position is None:
        buy_price = float(current_price) - bo
        buy_callback(buy_price)
        data['rule8_active'] = True
        return True
    
    # If holding, sell using offset from current price
    sell_price = float(current_price) + so
    sell_callback(sell_price, win_reason="RULE_8")
    data['rule8_active'] = False
    return True


def maybe_rule9_trade(state: 'TickerState', trend: str, current_price: float,
                     amount: Optional[float], flips: Optional[int],
                     window_minutes: Optional[int], buy_callback, sell_callback) -> bool:
    """
    Rule #9: Up/down flips (N cycles in M minutes) → quick scalp.
    When sufficient trend flips detected within time window, execute scalp.
    """
    amt = max(float(amount) if amount else 0.25, 0.01)
    flips_needed = max(int(flips) if flips else 3, 1)
    window_minutes_val = max(int(window_minutes) if window_minutes else 3, 1)
    window_seconds = window_minutes_val * 60

    now = datetime.utcnow()
    trend = (trend or '').lower()
    if trend not in ('up', 'down'):
        return False

    data = state.to_dict()
    
    # Reset window if expired or not started
    if data.get('rule9_window_start') is None:
        data['rule9_window_start'] = now
        data['rule9_flip_count'] = 0
        data['rule9_last_trend'] = trend
    else:
        elapsed = (now - data['rule9_window_start']).total_seconds()
        if elapsed > window_seconds:
            data['rule9_window_start'] = now
            data['rule9_flip_count'] = 0
            data['rule9_last_trend'] = trend

    # Count flips
    last_trend = data.get('rule9_last_trend')
    if last_trend and trend != last_trend:
        data['rule9_flip_count'] = int(data.get('rule9_flip_count', 0)) + 1
        data['rule9_last_trend'] = trend

    # When threshold reached, execute quick scalp
    if int(data.get('rule9_flip_count', 0)) >= flips_needed:
        data['rule9_window_start'] = None
        data['rule9_flip_count'] = 0
        data['rule9_last_trend'] = None
        if state.position is None:
            buy_price = float(current_price) - amt
            sell_price = buy_price + amt
            buy_callback(buy_price)
            sell_callback(sell_price, win_reason="RULE_9")
            return True
    
    return False
