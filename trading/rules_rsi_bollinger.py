"""Rule 10: RSI + Bollinger Reversal.

Buy when RSI <= threshold and price touches lower BB.
"""

from typing import TYPE_CHECKING, Optional
import logging
import math
import time
from datetime import datetime

if TYPE_CHECKING:
    from trading.state import TickerState

logger = logging.getLogger(__name__)


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
                              daily_max_loss: Optional[float] = None,
                              max_losses_per_day: Optional[int] = None,
                              size_multiplier: Optional[float] = None,
                              trend_enabled: Optional[bool] = None,
                              trend_ma: Optional[int] = None,
                              liquidity_enabled: Optional[bool] = None,
                              min_avg_volume: Optional[int] = None,
                              avg_volume: Optional[float] = None,
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

    # Minimum re-entry interval
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
