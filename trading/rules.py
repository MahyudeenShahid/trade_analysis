"""
Trading rules implementation (Rules 1-13).
Each rule modifies trading behavior based on specific conditions.
"""

from typing import TYPE_CHECKING, Optional
import logging
import math
import time
from datetime import datetime

if TYPE_CHECKING:
    from trading.state import TickerState


logger = logging.getLogger(__name__)

# Rule 13 — Blue Graph Direction (slope-based buy/sell)
from .rule13 import maybe_rule13_trade, _compute_slope_pct  # noqa: E402,F401


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


def _parse_iso_ts(ts_val) -> Optional[datetime]:
    if ts_val is None:
        return None
    if isinstance(ts_val, datetime):
        return ts_val
    try:
        raw = str(ts_val)
        if raw.endswith('Z'):
            raw = raw[:-1]
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _log_rsi_bb_block(state: 'TickerState', reason: str, details: Optional[str] = None):
    try:
        last_reason = getattr(state, "rsi_bollinger_last_block_reason", None)
        last_ts = float(getattr(state, "rsi_bollinger_last_block_ts", 0.0) or 0.0)
        now = time.time()
        if reason != last_reason or (now - last_ts) >= 5.0:
            msg = f"[Rule10] Blocked: {reason}"
            if details:
                msg = f"{msg} | {details}"
            logger.info(msg)
            setattr(state, "rsi_bollinger_last_block_reason", reason)
            setattr(state, "rsi_bollinger_last_block_ts", now)
    except Exception:
        pass


def maybe_rsi_bollinger_trade(state: 'TickerState', current_price: float,
                              price_history: list,
                              rsi_length: Optional[int], rsi_threshold: Optional[float],
                              bb_length: Optional[int], bb_stdev: Optional[float],
                              profit_pct: Optional[float], stop_pct: Optional[float],
                              stop_enabled: Optional[bool] = None,
                              strict_enabled: Optional[bool] = None,
                              strict_bars: Optional[int] = None,
                              bounce_enabled: Optional[bool] = None,
                              bounce_pct: Optional[float] = None,
                              cooldown_enabled: Optional[bool] = None,
                              cooldown_minutes: Optional[float] = None,
                              time_exit_enabled: Optional[bool] = None,
                              time_exit_minutes: Optional[float] = None,
                              only_profit: Optional[bool] = None,
                              # New safety features
                              daily_max_loss: Optional[float] = None,
                              max_losses_per_day: Optional[int] = None,
                              size_multiplier: Optional[float] = None,
                              trend_enabled: Optional[bool] = None,
                              trend_ma: Optional[int] = None,
                              liquidity_enabled: Optional[bool] = None,
                              min_avg_volume: Optional[int] = None,
                              avg_volume: Optional[float] = None,
                              # Trailing Stop and RSI Slope Optimizations
                              trailing_stop_enabled: Optional[bool] = None,
                              trailing_stop_pct: Optional[float] = None,
                              rsi_slope_enabled: Optional[bool] = None,
                              min_reentry_seconds: Optional[int] = None,
                              buy_callback=None, sell_callback=None) -> bool:
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

    stop_on = True if stop_enabled is None else bool(stop_enabled)
    strict_on = bool(strict_enabled)
    strict_n = max(int(strict_bars) if strict_bars else 2, 1)
    bounce_on = bool(bounce_enabled)
    bounce_p = float(bounce_pct) if bounce_pct is not None else 0.05
    if bounce_p < 0:
        bounce_p = 0.0
    cooldown_on = bool(cooldown_enabled)
    cooldown_m = float(cooldown_minutes) if cooldown_minutes is not None else 5.0
    if cooldown_m < 0:
        cooldown_m = 0.0
    time_exit_on = bool(time_exit_enabled)
    time_exit_m = float(time_exit_minutes) if time_exit_minutes is not None else 5.0
    if time_exit_m < 0:
        time_exit_m = 0.0
    profit_only = bool(only_profit)

    # Safety: enforce daily caps before allowing new buys
    try:
        if daily_max_loss is not None:
            dm = float(daily_max_loss)
            if dm > 0 and getattr(state, 'daily_loss_total', 0.0) >= dm:
                _log_rsi_bb_block(state, "daily_max_loss", f"loss={getattr(state, 'daily_loss_total', 0.0):.2f} >= {dm:.2f}")
                return True
    except Exception:
        pass
    try:
        if max_losses_per_day is not None:
            ml = int(max_losses_per_day)
            if ml > 0 and getattr(state, 'daily_loss_count', 0) >= ml:
                _log_rsi_bb_block(state, "max_losses_per_day", f"count={getattr(state, 'daily_loss_count', 0)} >= {ml}")
                return True
    except Exception:
        pass

    # Trend filter: require price >= moving average when enabled
    try:
        if trend_enabled:
            ma_len = int(trend_ma) if trend_ma is not None else 50
            if ma_len > 1 and isinstance(price_history, list) and len(price_history) >= ma_len:
                ma = sum(price_history[-ma_len:]) / float(ma_len)
                if float(current_price) < ma:
                    _log_rsi_bb_block(state, "trend_filter", f"price={float(current_price):.4f} < ma({ma_len})={ma:.4f}")
                    return True
    except Exception:
        pass

    # Liquidity filter: require average volume >= threshold when enabled
    try:
        if liquidity_enabled and min_avg_volume is not None:
            if avg_volume is None:
                # no volume info available — block by default to be safe
                _log_rsi_bb_block(state, "liquidity_filter", "avg_volume=none")
                return True
            try:
                if float(avg_volume) < float(min_avg_volume):
                    _log_rsi_bb_block(state, "liquidity_filter", f"avg_volume={float(avg_volume):.2f} < {float(min_avg_volume):.2f}")
                    return True
            except Exception:
                _log_rsi_bb_block(state, "liquidity_filter", "avg_volume=parse_error")
                return True
    except Exception:
        pass

    entry = state.position.get('entry') if state.position else None
    if entry is not None:
        now = datetime.utcnow()

        # Trailing stop loss logic
        trailing_stop_on = bool(trailing_stop_enabled)
        if trailing_stop_on:
            if state.rsi_bollinger_peak_price is None or current_price > state.rsi_bollinger_peak_price:
                state.rsi_bollinger_peak_price = current_price
            
            ts_pct = float(trailing_stop_pct) if trailing_stop_pct is not None else 0.1
            if ts_pct > 0:
                ts_stop_price = state.rsi_bollinger_peak_price * (1.0 - (ts_pct / 100.0))
                if current_price <= ts_stop_price:
                    if current_price < float(entry):
                        state.rsi_bollinger_last_loss_time = now
                    sell_callback(current_price, win_reason="RSI_BB_TRAILING_STOP")
                    state.rsi_bollinger_waiting_bounce = False
                    state.rsi_bollinger_trigger_price = None
                    state.rsi_bollinger_oversold_count = 0
                    state.rsi_bollinger_peak_price = None
                    return True

        if profit > 0:
            target = float(entry) * (1.0 + (profit / 100.0))
            if current_price >= target:
                sell_callback(current_price, win_reason="RSI_BB_PROFIT")
                state.rsi_bollinger_waiting_bounce = False
                state.rsi_bollinger_trigger_price = None
                state.rsi_bollinger_oversold_count = 0
                state.rsi_bollinger_peak_price = None
                return True

        if time_exit_on and time_exit_m > 0:
            entry_ts = _parse_iso_ts(state.position.get('ts'))
            if entry_ts is not None:
                held_min = (now - entry_ts).total_seconds() / 60.0
                if held_min >= time_exit_m:
                    if (not profit_only) or current_price >= float(entry):
                        if current_price < float(entry):
                            state.rsi_bollinger_last_loss_time = now
                        sell_callback(current_price, win_reason="RSI_BB_TIME")
                        state.rsi_bollinger_waiting_bounce = False
                        state.rsi_bollinger_trigger_price = None
                        state.rsi_bollinger_oversold_count = 0
                        state.rsi_bollinger_peak_price = None
                        return True

        if stop > 0 and stop_on and not profit_only:
            stop_price = float(entry) * (1.0 - (stop / 100.0))
            if current_price <= stop_price:
                state.rsi_bollinger_last_loss_time = datetime.utcnow()
                sell_callback(current_price, win_reason="RSI_BB_STOP")
                state.rsi_bollinger_waiting_bounce = False
                state.rsi_bollinger_trigger_price = None
                state.rsi_bollinger_oversold_count = 0
                state.rsi_bollinger_peak_price = None
                return True

        return True

    # Flat state: reset trailing peak
    state.rsi_bollinger_peak_price = None

    # Minimum re-entry interval: block new buys within N seconds of the last buy
    try:
        min_s = int(min_reentry_seconds) if min_reentry_seconds is not None else 0
        if min_s > 0 and getattr(state, 'rsi_bollinger_last_buy_time', None) is not None:
            elapsed = (datetime.utcnow() - state.rsi_bollinger_last_buy_time).total_seconds()
            if elapsed < min_s:
                _log_rsi_bb_block(state, "min_reentry", f"elapsed={elapsed:.1f}s < {min_s}s")
                return True
    except Exception:
        pass

    history = price_history if isinstance(price_history, list) else []
    required = max(rsi_len + 1, bb_len)
    if len(history) < required:
        _log_rsi_bb_block(state, "insufficient_history", f"have={len(history)} need={required}")
        return True

    if cooldown_on and state.rsi_bollinger_last_loss_time is not None:
        try:
            elapsed = (datetime.utcnow() - state.rsi_bollinger_last_loss_time).total_seconds() / 60.0
            if elapsed < cooldown_m:
                state.rsi_bollinger_waiting_bounce = False
                state.rsi_bollinger_trigger_price = None
                state.rsi_bollinger_oversold_count = 0
                _log_rsi_bb_block(state, "cooldown", f"elapsed={elapsed:.2f}m < {cooldown_m:.2f}m")
                return True
        except Exception:
            pass

    rsi = _compute_rsi(history, rsi_len)
    bands = _compute_bollinger(history, bb_len, bb_sd)
    if rsi is None or bands is None:
        _log_rsi_bb_block(state, "indicator_unavailable")
        return True

    _, _upper, lower = bands
    rsi_ok = rsi <= rsi_th
    touch_lower = current_price <= lower

    if strict_on:
        if rsi_ok and touch_lower:
            state.rsi_bollinger_oversold_count += 1
        else:
            state.rsi_bollinger_oversold_count = 0
        ready = state.rsi_bollinger_oversold_count >= strict_n
    else:
        ready = rsi_ok and touch_lower
        if not ready:
            state.rsi_bollinger_oversold_count = 0

    if not rsi_ok:
        _log_rsi_bb_block(state, "rsi_gate", f"rsi={rsi:.2f} > {rsi_th:.2f}")
    elif not touch_lower:
        _log_rsi_bb_block(state, "bollinger_gate", f"price={float(current_price):.4f} > lower={float(lower):.4f}")
    elif strict_on and not ready:
        _log_rsi_bb_block(state, "strict_bars", f"count={state.rsi_bollinger_oversold_count} < {strict_n}")

    # RSI Slope reversal confirmation
    if ready and bool(rsi_slope_enabled):
        rsi_prev = _compute_rsi(history[:-1], rsi_len)
        if rsi_prev is not None:
            # RSI must be strictly ascending (reversing upwards from oversold)
            if rsi <= rsi_prev:
                _log_rsi_bb_block(state, "rsi_slope", f"rsi={rsi:.2f} <= prev={rsi_prev:.2f}")
                ready = False

    if bounce_on:
        if state.rsi_bollinger_waiting_bounce:
            trigger_price = state.rsi_bollinger_trigger_price
            if trigger_price is None:
                state.rsi_bollinger_waiting_bounce = False
            else:
                bounce_target = float(trigger_price) * (1.0 + (bounce_p / 100.0))
                if current_price >= bounce_target:
                    state.rsi_bollinger_waiting_bounce = False
                    state.rsi_bollinger_trigger_price = None
                    state.rsi_bollinger_oversold_count = 0
                    try:
                        setattr(state, "rsi_bollinger_last_block_reason", None)
                    except Exception:
                        pass
                    state.rsi_bollinger_last_buy_time = datetime.utcnow()
                    buy_callback(current_price)
                else:
                    _log_rsi_bb_block(state, "bounce_wait", f"price={float(current_price):.4f} < target={bounce_target:.4f}")
            return True

        if ready:
            state.rsi_bollinger_waiting_bounce = True
            state.rsi_bollinger_trigger_price = float(current_price)
        return True

    if ready:
        state.rsi_bollinger_waiting_bounce = False
        state.rsi_bollinger_trigger_price = None
        state.rsi_bollinger_oversold_count = 0
        try:
            setattr(state, "rsi_bollinger_last_block_reason", None)
        except Exception:
            pass
        state.rsi_bollinger_last_buy_time = datetime.utcnow()
        buy_callback(current_price)
    return True


def maybe_rule11_trade(state: 'TickerState', trend: str, current_price: float,
                       price_jump: Optional[float], window_seconds: Optional[int],
                       volume_threshold: Optional[int], limit_offset: Optional[float],
                       price_volume_history: Optional[list],
                       profit_pct: Optional[float] = None, stop_pct: Optional[float] = None,
                       stop_enabled: Optional[bool] = None, only_profit: Optional[bool] = None,
                       trailing_stop_enabled: Optional[bool] = None, trailing_stop_pct: Optional[float] = None,
                       cooldown_enabled: Optional[bool] = None, cooldown_minutes: Optional[float] = None,
                       size_multiplier: Optional[float] = None, daily_max_loss: Optional[float] = None,
                       max_losses_per_day: Optional[int] = None, trend_enabled: Optional[bool] = None,
                       trend_ma: Optional[int] = None, liquidity_enabled: Optional[bool] = None,
                       min_avg_volume: Optional[int] = None, avg_volume: Optional[float] = None,
                       min_tick_density: Optional[int] = None, price_history: Optional[list] = None,
                       buy_callback=None, sell_callback=None) -> bool:
    """
    Rule #11: Momentum tick breakout with advanced safety, stops, and tick density filtering.
    Always returns True when rule handled (blocks default logic).
    """
    # 1. Position management (Exit logic)
    entry = state.position.get('entry') if state.position else None
    if entry is not None:
        now = datetime.utcnow()

        # Trailing stop loss logic
        trailing_stop_on = bool(trailing_stop_enabled)
        if trailing_stop_on:
            peak = getattr(state, 'rule11_peak_price', None)
            if peak is None or current_price > peak:
                state.rule11_peak_price = current_price
                peak = current_price
            
            ts_pct = float(trailing_stop_pct) if trailing_stop_pct is not None else 0.1
            if ts_pct > 0:
                ts_stop_price = peak * (1.0 - (ts_pct / 100.0))
                if current_price <= ts_stop_price:
                    if current_price < float(entry):
                        state.rule11_last_loss_time = now
                    sell_callback(current_price, win_reason="RULE_11_TRAILING_STOP")
                    state.rule11_peak_price = None
                    return True

        # Profit target
        try:
            profit = float(profit_pct) if profit_pct is not None else 0.2
            if profit > 0:
                target = float(entry) * (1.0 + (profit / 100.0))
                if current_price >= target:
                    sell_callback(current_price, win_reason="RULE_11_PROFIT")
                    state.rule11_peak_price = None
                    return True
        except Exception:
            pass

        # Stop loss
        try:
            stop_on = True if stop_enabled is None else bool(stop_enabled)
            profit_only = bool(only_profit)
            stop = float(stop_pct) if stop_pct is not None else 0.4
            if stop > 0 and stop_on and not profit_only:
                stop_price = float(entry) * (1.0 - (stop / 100.0))
                if current_price <= stop_price:
                    state.rule11_last_loss_time = now
                    sell_callback(current_price, win_reason="RULE_11_STOP")
                    state.rule11_peak_price = None
                    return True
        except Exception:
            pass

        return True

    # Flat state: reset trailing peak
    state.rule11_peak_price = None

    # 2. Safety overrides (Daily max loss cap, max losses per day)
    try:
        if daily_max_loss is not None:
            dm = float(daily_max_loss)
            if dm > 0 and getattr(state, 'daily_loss_total', 0.0) >= dm:
                return True
    except Exception:
        pass
    try:
        if max_losses_per_day is not None:
            ml = int(max_losses_per_day)
            if ml > 0 and getattr(state, 'daily_loss_count', 0) >= ml:
                return True
    except Exception:
        pass

    # 3. Cooldown after a loss check
    if bool(cooldown_enabled) and getattr(state, 'rule11_last_loss_time', None) is not None:
        try:
            cooldown_m = float(cooldown_minutes) if cooldown_minutes is not None else 5.0
            elapsed = (datetime.utcnow() - state.rule11_last_loss_time).total_seconds() / 60.0
            if elapsed < cooldown_m:
                return True
        except Exception:
            pass

    # 4. Trend filter (Price >= SMA(N))
    try:
        if trend_enabled:
            ma_len = int(trend_ma) if trend_ma is not None else 50
            if ma_len > 1 and isinstance(price_history, list) and len(price_history) >= ma_len:
                ma = sum(price_history[-ma_len:]) / float(ma_len)
                if float(current_price) < ma:
                    return True
    except Exception:
        pass

    # 5. Liquidity filter (Average Volume >= Threshold)
    try:
        if liquidity_enabled and min_avg_volume is not None:
            if avg_volume is None:
                return True
            if float(avg_volume) < float(min_avg_volume):
                return True
    except Exception:
        pass

    # 6. Parse and evaluate price and volume jump
    try:
        pj = float(price_jump) if price_jump is not None else 0.0
    except (ValueError, TypeError):
        pj = 0.0

    if pj <= 0:
        # price_jump is misconfigured or zero — block default logic but don't buy
        return True

    pv = None
    try:
        if isinstance(price_volume_history, list) and price_volume_history:
            pv = price_volume_history
        else:
            hist = getattr(state, 'price_history', None)
            if isinstance(hist, list) and len(hist) >= 2:
                now = getattr(state, 'last_ts', time.time()) if hasattr(state, 'last_ts') else time.time()
                pv = []
                ts_base = now - len(hist)
                for i, p in enumerate(hist[-int(min(len(hist), 50)):]):
                    pv.append({'ts': ts_base + i, 'price': float(p), 'volume': 0.0})
    except Exception:
        pv = None

    if not pv:
        # No tick data available — block default logic but don't buy
        return True

    try:
        prices = [float(x.get('price')) for x in pv if x.get('price') is not None]
        volumes = [float(x.get('volume') or 0.0) for x in pv]
    except Exception:
        return False

    if not prices:
        return False

    try:
        baseline = min(prices)
        price_jump_actual = float(current_price) - float(baseline)
    except Exception:
        return False

    total_vol = sum(volumes) if volumes else 0.0
    vol_ok = True if (volume_threshold is None or volume_threshold <= 0) else (total_vol >= float(volume_threshold))
    jump_ok = price_jump_actual >= float(pj)

    # 7. Tick Density Filter (The Crowd Check)
    try:
        min_density = int(min_tick_density) if min_tick_density is not None else 3
    except Exception:
        min_density = 3

    if min_density > 1 and len(prices) >= 2:
        up_ticks = 0
        for i in range(1, len(prices)):
            if prices[i] > prices[i-1]:
                up_ticks += 1
        if up_ticks < min_density:
            return True

    # 8. Entry execution
    if jump_ok and vol_ok:
        lo = float(limit_offset) if limit_offset is not None else 0.01
        buy_price = float(current_price) + (lo if lo >= 0 else 0.0)
        buy_callback(buy_price)
        return True

    return False


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _score_to_pct(score: float) -> float:
    return _clamp((score + 1.0) * 50.0, 0.0, 100.0)


def _calc_rule12_tape_pct(price_volume_history: list, top_book: Optional[dict], min_trades: int) -> float:
    rows = [r for r in price_volume_history if isinstance(r, dict) and r.get("price") is not None]
    if not rows:
        return 50.0

    trade_rows = [r for r in rows if str(r.get("source") or "").lower() == "trade"]
    if trade_rows:
        rows = trade_rows

    if len(rows) < max(1, int(min_trades)):
        return 50.0

    bid = None
    ask = None
    mid = None
    if isinstance(top_book, dict):
        try:
            bid = float(top_book.get("bid")) if top_book.get("bid") is not None else None
        except Exception:
            bid = None
        try:
            ask = float(top_book.get("ask")) if top_book.get("ask") is not None else None
        except Exception:
            ask = None
    if bid is not None and ask is not None:
        mid = (bid + ask) / 2.0

    ask_vol = 0.0
    bid_vol = 0.0
    for r in rows:
        try:
            price = float(r.get("price"))
        except Exception:
            continue
        try:
            vol = float(r.get("volume") or 1.0)
        except Exception:
            vol = 1.0

        if ask is not None and price >= ask:
            ask_vol += vol
        elif bid is not None and price <= bid:
            bid_vol += vol
        elif mid is not None:
            if price > mid:
                ask_vol += vol
            elif price < mid:
                bid_vol += vol

    total = ask_vol + bid_vol
    if total <= 0:
        return 50.0
    return _clamp((ask_vol / total) * 100.0, 0.0, 100.0)


def _calc_rule12_book_pct(depth_snapshot: Optional[dict], levels: int = 5) -> float:
    if not isinstance(depth_snapshot, dict):
        return 50.0
    bids = depth_snapshot.get("bids") or []
    asks = depth_snapshot.get("asks") or []
    bid_sum = 0.0
    ask_sum = 0.0
    for row in bids[:max(1, int(levels))]:
        try:
            bid_sum += float(row.get("size") or 0.0)
        except Exception:
            pass
    for row in asks[:max(1, int(levels))]:
        try:
            ask_sum += float(row.get("size") or 0.0)
        except Exception:
            pass
    total = bid_sum + ask_sum
    if total <= 0:
        return 50.0
    return _clamp((bid_sum / total) * 100.0, 0.0, 100.0)


def _calc_rule12_trend_pct(price_history: list, lookback: int = 20) -> float:
    prices = [float(p) for p in (price_history or []) if p is not None]
    if len(prices) < 3:
        return 50.0
    window = prices[-max(3, int(lookback)) :]
    first = window[0]
    last = window[-1]
    hi = max(window)
    lo = min(window)
    rng = hi - lo
    if rng <= 0:
        return 50.0
    trend_score = _clamp((last - first) / rng, -1.0, 1.0)
    return _score_to_pct(trend_score)


def _calc_rule12_momentum_pct(price_volume_history: list, momentum_scale: float = 0.0005) -> float:
    rows = [r for r in price_volume_history if isinstance(r, dict) and r.get("price") is not None]
    if len(rows) < 2:
        return 50.0
    first = rows[0]
    last = rows[-1]
    try:
        first_price = float(first.get("price"))
        last_price = float(last.get("price"))
        first_ts = float(first.get("ts"))
        last_ts = float(last.get("ts"))
    except Exception:
        return 50.0
    dt = last_ts - first_ts
    if dt <= 0:
        return 50.0
    avg_price = (first_price + last_price) / 2.0 if (first_price + last_price) != 0 else 1.0
    rel_speed = ((last_price - first_price) / avg_price) / dt
    scale = float(momentum_scale) if momentum_scale is not None else 0.0005
    if scale <= 0:
        return 50.0
    score = _clamp(rel_speed / scale, -1.0, 1.0)
    return _score_to_pct(score)


def _calc_rule12_volume_pct(price_volume_history: list) -> float:
    rows = [r for r in price_volume_history if isinstance(r, dict)]
    if not rows:
        return 50.0
    trade_rows = [r for r in rows if str(r.get("source") or "").lower() == "trade"]
    if trade_rows:
        rows = trade_rows

    vols = []
    for r in rows:
        try:
            vols.append(float(r.get("volume") or 0.0))
        except Exception:
            vols.append(0.0)
    if len(vols) < 2:
        return 50.0
    split = max(1, len(vols) // 2)
    prev_vol = sum(vols[:split])
    recent_vol = sum(vols[split:])
    total = prev_vol + recent_vol
    if total <= 0:
        return 50.0
    score = _clamp((recent_vol - prev_vol) / total, -1.0, 1.0)
    return _score_to_pct(score)


def _calc_rule12_spread_pct(top_book: Optional[dict], tight_pct: float = 0.001) -> float:
    if not isinstance(top_book, dict):
        return 50.0
    try:
        bid = float(top_book.get("bid")) if top_book.get("bid") is not None else None
        ask = float(top_book.get("ask")) if top_book.get("ask") is not None else None
    except Exception:
        bid, ask = None, None
    if bid is None or ask is None:
        return 50.0
    mid = (bid + ask) / 2.0 if (bid + ask) != 0 else None
    if mid is None or mid <= 0:
        return 50.0
    spread_pct = (ask - bid) / mid
    tight = float(tight_pct) if tight_pct is not None else 0.001
    if tight <= 0:
        return 50.0
    score = 1.0 - min(spread_pct / tight, 2.0)
    return _score_to_pct(_clamp(score, -1.0, 1.0))


def _calc_rule12_pullback_pct(price_history: list, lookback: int = 20) -> float:
    prices = [float(p) for p in (price_history or []) if p is not None]
    if len(prices) < 3:
        return 50.0
    window = prices[-max(3, int(lookback)) :]
    peak = max(window)
    trough = min(window)
    if peak <= trough:
        return 50.0
    last = window[-1]
    pullback_ratio = (peak - last) / (peak - trough)
    score = 1.0 - min(pullback_ratio * 2.0, 2.0)
    return _score_to_pct(_clamp(score, -1.0, 1.0))


def maybe_rule12_trade(
    state: 'TickerState',
    current_price: float,
    price_history: Optional[list],
    price_volume_history: Optional[list],
    top_book: Optional[dict],
    depth_snapshot: Optional[dict],
    buy_threshold: Optional[float] = None,
    sell_threshold: Optional[float] = None,
    min_trades: Optional[int] = None,
    weight_tape: Optional[float] = None,
    weight_book: Optional[float] = None,
    weight_trend: Optional[float] = None,
    weight_momentum: Optional[float] = None,
    weight_volume: Optional[float] = None,
    weight_spread: Optional[float] = None,
    weight_pullback: Optional[float] = None,
    momentum_scale: Optional[float] = None,
    spread_tight_pct: Optional[float] = None,
    buy_callback=None,
    sell_callback=None,
) -> bool:
    """Rule #12: Tape + order book meter for aggressive buy/sell gating."""
    ph = price_history if isinstance(price_history, list) else []
    pv = price_volume_history if isinstance(price_volume_history, list) else []

    min_trades = int(min_trades) if min_trades is not None else 5
    buy_threshold = float(buy_threshold) if buy_threshold is not None else 70.0
    sell_threshold = float(sell_threshold) if sell_threshold is not None else 60.0

    wt_tape = float(weight_tape) if weight_tape is not None else 0.4
    wt_book = float(weight_book) if weight_book is not None else 0.2
    wt_trend = float(weight_trend) if weight_trend is not None else 0.2
    wt_momentum = float(weight_momentum) if weight_momentum is not None else 0.1
    wt_volume = float(weight_volume) if weight_volume is not None else 0.1
    wt_spread = float(weight_spread) if weight_spread is not None else 0.0
    wt_pullback = float(weight_pullback) if weight_pullback is not None else 0.0

    tape_pct = _calc_rule12_tape_pct(pv, top_book, min_trades)
    book_pct = _calc_rule12_book_pct(depth_snapshot, levels=5)
    trend_pct = _calc_rule12_trend_pct(ph, lookback=20)
    momentum_pct = _calc_rule12_momentum_pct(pv, momentum_scale=momentum_scale or 0.0005)
    volume_pct = _calc_rule12_volume_pct(pv)
    spread_pct = _calc_rule12_spread_pct(top_book, tight_pct=spread_tight_pct or 0.001)
    pullback_pct = _calc_rule12_pullback_pct(ph, lookback=20)

    weights = [
        (tape_pct, wt_tape),
        (book_pct, wt_book),
        (trend_pct, wt_trend),
        (momentum_pct, wt_momentum),
        (volume_pct, wt_volume),
        (spread_pct, wt_spread),
        (pullback_pct, wt_pullback),
    ]
    total_w = sum(w for _, w in weights if w > 0)
    if total_w <= 0:
        buyer_pct = 50.0
    else:
        buyer_pct = sum(pct * w for pct, w in weights if w > 0) / total_w
    buyer_pct = _clamp(buyer_pct, 0.0, 100.0)
    seller_pct = 100.0 - buyer_pct

    try:
        state.rule12_last_meter = {
            "buyer_pct": buyer_pct,
            "seller_pct": seller_pct,
            "tape_pct": tape_pct,
            "book_pct": book_pct,
            "trend_pct": trend_pct,
            "momentum_pct": momentum_pct,
            "volume_pct": volume_pct,
            "spread_pct": spread_pct,
            "pullback_pct": pullback_pct,
        }
    except Exception:
        pass

    if state.position is None:
        if buyer_pct >= buy_threshold and buy_callback is not None:
            buy_callback(current_price)
        return True

    if seller_pct >= sell_threshold and sell_callback is not None:
        sell_callback(current_price, win_reason="RULE_12")
    return True
