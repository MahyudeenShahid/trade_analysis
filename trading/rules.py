"""
Trading rules implementation (Rules 1-9).
Each rule modifies trading behavior based on specific conditions.
"""

from typing import TYPE_CHECKING, Optional
import math
import time
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
    down_m = max(int(down_minutes) if down_minutes else 3, 1)
    rev_amt = max(float(reversal_amount) if reversal_amount else 2.0, 0.1)
    scalp_amt = max(float(scalp_amount) if scalp_amount else 0.25, 0.01)

    now = datetime.utcnow()
    trend = (trend or '').lower()

    # Stage 2: in reversal trade — waiting for profit target
    if state.rule5_reversal_active:
        if state.rule5_reversal_price is not None and current_price >= (state.rule5_reversal_price + rev_amt):
            sell_callback(current_price, win_reason="RULE_5")
            state.rule5_reversal_active = False
            state.rule5_reversal_price = None
            state.rule5_scalp_active = True
        return True  # block normal logic while waiting

    # Stage 3: scalp mode — quick buy+sell on each up tick
    if state.rule5_scalp_active:
        if trend != 'up':
            state.rule5_scalp_active = False
        else:
            if state.position is None:
                buy_callback(current_price)
                sell_callback(current_price + scalp_amt, win_reason="RULE_5")
                return True
            return True

    # Stage 1: track continuous downtrend duration
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

    # Trigger: first up tick after long downtrend
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
    """
    Rule #6: Long wait (down > N minutes) → up buy → sell at profit target.
    """
    down_m = max(int(down_minutes) if down_minutes else 5, 1)
    prof_amt = max(float(profit_amount) if profit_amount else 2.0, 0.1)

    now = datetime.utcnow()
    trend = (trend or '').lower()

    # Holding a Rule 6 position — wait for profit target
    if state.rule6_active and state.position is not None:
        entry = state.position.get('entry')
        if entry is not None and current_price >= (float(entry) + prof_amt):
            sell_callback(current_price, win_reason="RULE_6")
            state.rule6_active = False
        return True  # block normal logic while waiting

    # Track continuous downtrend duration
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

    # Trigger: first up tick after long downtrend
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
    After a sell, the timer fully resets and must count N seconds again before next buy.
    """
    # Treat the 'up_minutes' setting as seconds (UI will show 'sec' label)
    up_s = max(int(up_minutes) if up_minutes else 30, 1)

    now = datetime.utcnow()
    trend = (trend or '').lower()

    # Holding a Rule 7 position — let normal sell logic do the sell (return False so
    # the default down=sell path runs), then we reset on next tick
    if state.rule7_active and state.position is not None:
        return False

    # Position was just sold — reset the whole cycle so timer starts fresh
    if state.rule7_active and state.position is None:
        state.rule7_active = False
        state.rule7_up_start = None
        state.rule7_ready_for_buy = False
        return False

    # Any DOWN tick breaks the streak — reset timer and ready flag
    if trend != 'up':
        state.rule7_up_start = None
        state.rule7_ready_for_buy = False
        return False

    # Trending UP — start or continue the timer
    if state.rule7_up_start is None:
        state.rule7_up_start = now
    else:
        elapsed = (now - state.rule7_up_start).total_seconds()
        if elapsed >= up_s:
            state.rule7_ready_for_buy = True

    # Timer has elapsed and no open position — BUY
    if state.rule7_ready_for_buy and state.position is None:
        state.rule7_ready_for_buy = False
        state.rule7_up_start = None
        buy_callback(current_price)
        state.rule7_active = True
        return True

    # Still counting up time — block normal logic so default buy doesn't fire early
    return True


def maybe_rule8_trade(state: 'TickerState', current_price: float,
                     buy_offset: Optional[float], sell_offset: Optional[float],
                     buy_callback, sell_callback) -> bool:
    """
    Rule #8: Limit-order style offset trading.
    - While flat: tracks a rolling peak price. Buys only when price drops
      buy_offset below that peak (i.e. waits for a pullback).
    - While in position: sells only when price rises sell_offset above entry.
    Always returns True to block default buy/sell logic while Rule 8 is active.
    """
    bo = float(buy_offset) if buy_offset is not None else 0.25
    so = float(sell_offset) if sell_offset is not None else 0.25

    if state.position is None:
        # Track the rolling peak upward as price rises
        if state.rule8_watch_price is None or current_price > state.rule8_watch_price:
            state.rule8_watch_price = current_price

        # Only buy once price has pulled back buy_offset below the peak
        if current_price <= state.rule8_watch_price - bo:
            buy_callback(current_price)
            state.rule8_watch_price = None  # reset so it re-tracks after buying
    else:
        # In position — wait until price rises sell_offset above entry
        entry = state.position.get('entry')
        if entry is not None and current_price >= float(entry) + so:
            sell_callback(current_price, win_reason="RULE_8")
            state.rule8_watch_price = None

    return True  # always block default logic when Rule 8 is enabled


def maybe_rule9_trade(state: 'TickerState', trend: str, current_price: float,
                     amount: Optional[float], flips: Optional[int],
                     window_minutes: Optional[int], buy_callback, sell_callback) -> bool:
    """
    Rule #9: Cooldown gate — after a buy+sell cycle, block any new buy for N seconds.
    'window_minutes' is reused as the cooldown duration in seconds (default 15).
    Returns True (blocks normal logic) only during the cooldown window after a sell.
    Returns False at all other times so normal buy/sell logic runs freely.
    """
    cooldown_s = max(int(window_minutes) if window_minutes else 15, 1)
    now = datetime.utcnow()

    # Only apply gate when flat (no open position) and a sell has happened before
    if state.position is None and state.rule9_last_sell_time is not None:
        elapsed = (now - state.rule9_last_sell_time).total_seconds()
        if elapsed < cooldown_s:
            # Still in cooldown — block any buy
            return True

    # In position or cooldown expired — don't interfere, let normal logic run
    return False


def _compute_rsi(prices: list, period: int) -> Optional[float]:
    if period <= 0 or len(prices) < period + 1:
        return None

    gains = 0.0
    losses = 0.0
    start = len(prices) - period
    for i in range(start, len(prices)):
        delta = prices[i] - prices[i - 1]
        if delta > 0:
            gains += delta
        elif delta < 0:
            losses -= delta

    if losses == 0:
        return 100.0 if gains > 0 else 50.0

    rs = gains / losses
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_bollinger(prices: list, length: int, stdev_mult: float) -> Optional[tuple]:
    if length <= 1 or len(prices) < length:
        return None

    window = prices[-length:]
    mean = sum(window) / float(length)
    variance = sum((p - mean) ** 2 for p in window) / float(length)
    stdev = math.sqrt(variance)
    upper = mean + stdev_mult * stdev
    lower = mean - stdev_mult * stdev
    return mean, upper, lower


def maybe_rsi_bollinger_trade(state: 'TickerState', current_price: float,
                              price_history: list,
                              rsi_length: Optional[int], rsi_threshold: Optional[float],
                              bb_length: Optional[int], bb_stdev: Optional[float],
                              profit_pct: Optional[float], stop_pct: Optional[float],
                              buy_callback, sell_callback) -> bool:
    """
    RSI + Bollinger Reversal:
    - Buy when RSI <= threshold and price touches lower BB
    - Sell at profit/stop percent from entry
    Always returns True to block default logic while enabled.
    """
    rsi_len = max(int(rsi_length) if rsi_length else 14, 2)
    rsi_th = float(rsi_threshold) if rsi_threshold is not None else 30.0
    rsi_th = min(max(rsi_th, 1.0), 100.0)
    bb_len = max(int(bb_length) if bb_length else 20, 2)
    bb_sd = max(float(bb_stdev) if bb_stdev else 2.0, 0.1)
    profit = float(profit_pct) if profit_pct is not None else 0.2
    stop = float(stop_pct) if stop_pct is not None else 0.4
    if profit < 0:
        profit = 0.0
    if stop < 0:
        stop = 0.0

    entry = state.position.get('entry') if state.position else None
    if entry is not None:
        if profit > 0:
            target = float(entry) * (1.0 + (profit / 100.0))
            if current_price >= target:
                sell_callback(current_price, win_reason="RSI_BB_PROFIT")
                return True

        if stop > 0:
            stop_price = float(entry) * (1.0 - (stop / 100.0))
            if current_price <= stop_price:
                sell_callback(current_price, win_reason="RSI_BB_STOP")
                return True

        return True

    history = price_history if isinstance(price_history, list) else []
    required = max(rsi_len + 1, bb_len)
    if len(history) < required:
        return True

    rsi = _compute_rsi(history, rsi_len)
    bands = _compute_bollinger(history, bb_len, bb_sd)
    if rsi is None or bands is None:
        return True

    _, _upper, lower = bands
    if rsi <= rsi_th and current_price <= lower:
        buy_callback(current_price)
    return True


def maybe_rule11_trade(state: 'TickerState', trend: str, current_price: float,
                       price_jump: Optional[float], window_seconds: Optional[int],
                       volume_threshold: Optional[int], limit_offset: Optional[float],
                       price_volume_history: Optional[list],
                       buy_callback, sell_callback) -> bool:
    """
    Rule #11: Momentum tick breakout (very short window).
    Conservative default implementation: detect an immediate price jump from the previous tick
    greater than or equal to `price_jump` and execute a buy at `current_price + limit_offset`.
    Volume threshold is accepted but not enforced if no volume data available.
    Returns True when rule handled (blocks default logic).
    """
    try:
        pj = float(price_jump) if price_jump is not None else 0.0
    except (ValueError, TypeError):
        pj = 0.0

    if pj <= 0:
        return False

    # Prefer using the provided price+volume history (list of {ts, price, volume}).
    pv = None
    try:
        if isinstance(price_volume_history, list) and price_volume_history:
            pv = price_volume_history
        else:
            # fallback: try to read state.price_history if available (older format)
            hist = getattr(state, 'price_history', None)
            if isinstance(hist, list) and len(hist) >= 2:
                # synthesize volume=0.0 entries for compatibility
                now = getattr(state, 'last_ts', time.time()) if hasattr(state, 'last_ts') else time.time()
                pv = []
                ts_base = now - len(hist)
                for i, p in enumerate(hist[-int(min(len(hist), 50)):]):
                    pv.append({'ts': ts_base + i, 'price': float(p), 'volume': 0.0})
    except Exception:
        pv = None

    if not pv:
        return False

    try:
        prices = [float(x.get('price')) for x in pv if x.get('price') is not None]
        volumes = [float(x.get('volume') or 0.0) for x in pv]
    except Exception:
        return False

    if not prices:
        return False

    # Compute baseline price (minimum in the window) and aggregate volume
    try:
        baseline = min(prices)
        price_jump_actual = float(current_price) - float(baseline)
    except Exception:
        return False

    total_vol = sum(volumes) if volumes else 0.0

    # Volume check (if provided) and price jump check
    vol_ok = True if (volume_threshold is None or volume_threshold <= 0) else (total_vol >= float(volume_threshold))
    jump_ok = price_jump_actual >= float(pj)

    if jump_ok and vol_ok:
        lo = float(limit_offset) if limit_offset is not None else 0.01
        buy_price = float(current_price) + (lo if lo >= 0 else 0.0)
        buy_callback(buy_price)
        return True

    return False
