"""Rule 11: Momentum tick breakout with advanced safety, stops, and tick density filtering."""

from typing import TYPE_CHECKING, Optional
import time
from datetime import datetime

if TYPE_CHECKING:
    from trading.state import TickerState


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

    # 2. Safety overrides
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

    # 4. Trend filter
    try:
        if trend_enabled:
            ma_len = int(trend_ma) if trend_ma is not None else 50
            if ma_len > 1 and isinstance(price_history, list) and len(price_history) >= ma_len:
                ma = sum(price_history[-ma_len:]) / float(ma_len)
                if float(current_price) < ma:
                    return True
    except Exception:
        pass

    # 5. Liquidity filter
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

    # 7. Tick Density Filter
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
