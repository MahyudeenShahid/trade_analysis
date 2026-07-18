"""
Rule 15 — Main Chart (IBKR Price History) Auto-Trader

Logic:
  - Watches the IBKR live price history (same data that feeds IBKRChart).
  - Slope / Scan detection on the rolling price list — same two modes as Rule 14.
  - Slope > +THRESHOLD % over the lookback window  → BUY  (long entry)
  - Slope < -THRESHOLD % over the lookback window  → SELL (close long)
  - FLAT (between ±threshold) while holding        → hold (no sell)
  - Stop-loss % fires independently of trend check.
  - Long-only (no shorting).
  - Blocks all other rules (1–12) when it fires, just like Rule 14.

All trades are labelled rule: 'R15' in the order history.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_SLOPE_THRESHOLD = 0.0003   # 0.03 %


# ─── Per-bot runtime state ────────────────────────────────────────────────────

@dataclass
class Rule15State:
    """Mutable runtime state for R15 on a single bot/ticker."""
    enabled: bool = False

    # Config (set by UI)
    qty: int = 1
    stop_loss_pct: float = 0.0
    cooldown_secs: float = 0.0
    slope_threshold: float = DEFAULT_SLOPE_THRESHOLD
    strategy_mode: str = 'scan'       # 'scan' | 'slope'
    lookback_seconds: float = 300.0   # default 5 minutes lookback
    use_bot_trend: bool = False
    always_sell_on_profit: bool = False

    # Position tracking
    position_price: Optional[float] = None
    position_ts: float = 0.0
    entry_limit_price: Optional[float] = None
    entry_fill_price: Optional[float] = None
    entry_fill_status: str = ''        # 'pending' | 'filled' | 'failed'

    # Last signal
    last_signal: str = ''
    last_signal_ts: float = 0.0

    # Cooldown
    last_sell_ts: float = 0.0

    # For broadcast / display
    last_trend: str = ''
    last_slope_pct: float = 0.0
    last_mid_price: Optional[float] = None

    # Rolling trade log (for UI markers)
    trade_log: list = field(default_factory=list)
    _trade_log_max: int = 200

    # Full order lifecycle events
    order_events: list = field(default_factory=list)
    _order_events_max: int = 100

    # Status display string
    status_text: str = 'Idle'


# Global registry: hwnd → Rule15State
_r15_states: dict[int, Rule15State] = {}


def get_r15_state(hwnd: int) -> Rule15State:
    """Get or create the R15 state for this bot window handle."""
    if hwnd not in _r15_states:
        _r15_states[hwnd] = Rule15State()
    return _r15_states[hwnd]


def configure_r15(hwnd: int, *, enabled: bool, qty: int = 1,
                  stop_loss_pct: float = 0.0, cooldown_secs: float = 0.0,
                  slope_threshold: float = DEFAULT_SLOPE_THRESHOLD,
                  strategy_mode: str = 'scan',
                  lookback_seconds: float = 300.0,
                  use_bot_trend: bool = False,
                  always_sell_on_profit: bool = False) -> Rule15State:
    """Update config for this bot. Called from the API route."""
    s = get_r15_state(hwnd)
    s.enabled = enabled
    s.qty = max(1, int(qty))
    s.stop_loss_pct = max(0.0, float(stop_loss_pct))
    s.cooldown_secs = max(0.0, float(cooldown_secs))
    s.slope_threshold = max(0.0, float(slope_threshold))
    s.strategy_mode = str(strategy_mode).strip().lower()
    s.lookback_seconds = max(10.0, float(lookback_seconds))
    s.use_bot_trend = bool(use_bot_trend)
    s.always_sell_on_profit = bool(always_sell_on_profit)
    if s.strategy_mode not in ('scan', 'slope'):
        s.strategy_mode = 'scan'
    if not enabled:
        s.status_text = 'Disabled'
    return s


# ─── Order event recording ────────────────────────────────────────────────────

def _append_order_event(s: Rule15State, event: dict) -> None:
    s.order_events.append(event)
    if len(s.order_events) > s._order_events_max:
        s.order_events = s.order_events[-s._order_events_max:]


def record_order_placed(hwnd: int, direction: str, signal_price: float,
                        limit_price: Optional[float]) -> None:
    """Called immediately after the IBKR order is dispatched."""
    s = get_r15_state(hwnd)
    now = time.time()
    lp_str = f'${limit_price:.2f}' if limit_price is not None else 'MKT'
    
    # User requested log format: detailed logs with time and price
    log_msg = f"{direction.upper()} order requested @ {lp_str}"
    
    _append_order_event(s, {
        'event': 'order_placed',
        'direction': direction,
        'signal_price': signal_price,
        'limit_price': limit_price,
        'fill_price': None,
        'slippage': None,
        'reason': log_msg,
        'ts': now,
    })
    
    s.trade_log.append({
        'direction': direction,
        'price': limit_price or signal_price,
        'ts': now,
        'reason': f"Order requested: {log_msg}"
    })
    if len(s.trade_log) > s._trade_log_max:
        s.trade_log = s.trade_log[-s._trade_log_max:]

    if direction == 'buy':
        s.entry_limit_price = limit_price
        s.entry_fill_status = 'pending'
        s.status_text = f'⏳ BUY order requested @ {lp_str} — awaiting fill…'
    else:
        s.status_text = f'⏳ SELL on the way (requested) @ {lp_str} — awaiting fill…'


def record_order_fill(hwnd: int, direction: str, signal_price: float,
                      limit_price: Optional[float], fill_price: Optional[float],
                      ok: bool, error_msg: str = '') -> None:
    """Called after IBKR order completes (filled or failed)."""
    s = get_r15_state(hwnd)
    now = time.time()
    slippage = None
    if ok and fill_price is not None and signal_price is not None:
        slippage = round(fill_price - signal_price, 4)

    lp_str = f'${limit_price:.2f}' if limit_price is not None else 'MKT'
    fp_str = f'${fill_price:.2f}' if fill_price is not None else '\u2014'

    if ok:
        slip_str = f'{slippage:+.2f}' if slippage is not None else ''
        log_msg = f"BUY filled successfully @ {fp_str}" if direction == 'buy' else f"SOLD successfully @ {fp_str}"
        
        _append_order_event(s, {
            'event': 'order_filled',
            'direction': direction,
            'signal_price': signal_price,
            'limit_price': limit_price,
            'fill_price': fill_price,
            'slippage': slippage,
            'reason': log_msg,
            'ts': now,
        })
        
        s.trade_log.append({
            'direction': direction,
            'price': fill_price or signal_price,
            'ts': now,
            'reason': log_msg
        })
        if len(s.trade_log) > s._trade_log_max:
            s.trade_log = s.trade_log[-s._trade_log_max:]

        if direction == 'buy':
            s.entry_fill_price = fill_price
            s.position_price = fill_price
            s.entry_fill_status = 'filled'
            s.status_text = f'✅ BOUGHT successfully @ {fp_str} — holding'
        else:
            # Reset immediately so it is flat and can buy again instantly (CD permitting)
            s.position_price = None
            s.entry_fill_price = None
            s.entry_fill_status = ''
            s.status_text = f'✅ SOLD successfully @ {fp_str} — flat'
    else:
        log_msg = f"{direction.upper()} FAILED: {error_msg or 'unknown'}"
        _append_order_event(s, {
            'event': 'order_failed',
            'direction': direction,
            'signal_price': signal_price,
            'limit_price': limit_price,
            'fill_price': None,
            'slippage': None,
            'reason': log_msg,
            'ts': now,
        })
        s.trade_log.append({
            'direction': direction,
            'price': limit_price or signal_price,
            'ts': now,
            'reason': log_msg
        })
        if len(s.trade_log) > s._trade_log_max:
            s.trade_log = s.trade_log[-s._trade_log_max:]

        if direction == 'buy':
            s.entry_fill_status = 'failed'
            s.status_text = f'❌ BUY FAILED — {error_msg or "unknown"}'
        else:
            s.status_text = f'❌ SELL FAILED — {error_msg or "unknown"}'


def r15_state_for_frontend(hwnd: int) -> dict:
    """Return a JSON-serialisable snapshot for the WS broadcast."""
    s = get_r15_state(hwnd)
    pnl = None
    pnl_pct = None
    ref_price = s.entry_fill_price or s.position_price
    if ref_price is not None and s.last_mid_price is not None:
        pnl = round((s.last_mid_price - ref_price) * s.qty, 4)
        pnl_pct = round(
            ((s.last_mid_price - ref_price) / ref_price) * 100, 4
        ) if ref_price > 0 else None
    slope_pct = round(s.last_slope_pct * 100, 4)
    slope_thresh_pct = round(s.slope_threshold * 100, 4)
    return {
        'enabled': s.enabled,
        'qty': s.qty,
        'stop_loss_pct': s.stop_loss_pct,
        'cooldown_secs': s.cooldown_secs,
        'slope_threshold': slope_thresh_pct,
        'slope_threshold_pct': slope_thresh_pct,
        'strategy_mode': s.strategy_mode,
        'lookback_seconds': s.lookback_seconds,
        'use_bot_trend': s.use_bot_trend,
        'always_sell_on_profit': s.always_sell_on_profit,
        'position_price': s.position_price,
        'entry_fill_price': s.entry_fill_price,
        'entry_fill_status': s.entry_fill_status,
        'pnl': pnl,
        'pnl_pct': pnl_pct,
        'last_trend': s.last_trend,
        'last_slope_pct': slope_pct,
        'last_mid_price': s.last_mid_price,
        'last_signal': s.last_signal,
        'last_signal_ts': s.last_signal_ts,
        'status_text': s.status_text,
        'trade_log': s.trade_log[-50:],
        'order_events': s.order_events[-30:],
    }


# ─── Main signal function ─────────────────────────────────────────────────────

def maybe_rule15_signal(
    hwnd: int,
    price_history: list,   # list[float] or list[dict]
    lookback: int = 15,
    bot_trend: Optional[str] = None,
) -> Optional[str]:
    """
    Evaluate R15 logic for one tick using the IBKR main chart price history or captured bot trend.

    price_history: rolling list of floats or dicts.
    Returns 'buy', 'sell', or None.  Updates state in-place.
    """
    s = get_r15_state(hwnd)
    if not s.enabled:
        return None

    # Parse inputs to raw (timestamp, price) tuples
    parsed = []
    for p in (price_history or []):
        if isinstance(p, dict):
            ts = p.get('ts')
            price = p.get('price')
            if ts is not None and price is not None:
                parsed.append((float(ts), float(price)))
        elif isinstance(p, (int, float)):
            parsed.append((len(parsed) * 0.25, float(p)))

    parsed.sort(key=lambda x: x[0])
    if len(parsed) < 2:
        return None

    now_ts, cur_price = parsed[-1]
    s.last_mid_price = cur_price

    if s.use_bot_trend:
        if bot_trend is not None:
            trend = str(bot_trend).strip().lower()
        else:
            trend = s.last_trend
        # Fallback slope calculation for displays
        first_p = parsed[0][1]
        s.last_slope_pct = (cur_price - first_p) / first_p if first_p > 0 else 0.0
    else:
        lookback_secs = getattr(s, 'lookback_seconds', 300.0)
        threshold = s.slope_threshold

        # Down-sample to N=15 points evenly spaced over the lookback duration
        target_times = [now_ts - lookback_secs + (i * (lookback_secs / 14)) for i in range(15)]
        recent = []
        for t in target_times:
            closest = min(parsed, key=lambda x: abs(x[0] - t))
            if not recent or recent[-1] != closest:
                recent.append(closest)

        if len(recent) < 2:
            return None

        recent_prices = [pt[1] for pt in recent]
        first_val = recent_prices[0]
        
        # ── Trend detection ────────────────────────────────────────────────────────
        if s.strategy_mode == 'slope':
            if first_val <= 0:
                trend = ''
            else:
                slope = (cur_price - first_val) / first_val
                if slope > threshold:
                    trend = 'up'
                elif slope < -threshold:
                    trend = 'down'
                else:
                    trend = ''
        else:
            # Scan-back: classify each consecutive step, scan right-to-left for last non-flat
            interval_threshold = threshold / max(1, len(recent_prices) - 1)
            dirs = []
            for i in range(1, len(recent_prices)):
                prev = recent_prices[i - 1]
                if prev <= 0:
                    dirs.append(0)
                    continue
                change_pct = (recent_prices[i] - prev) / prev
                if change_pct > interval_threshold:
                    dirs.append(1)
                elif change_pct < -interval_threshold:
                    dirs.append(-1)
                else:
                    dirs.append(0)

            end_dir = 0
            for d in reversed(dirs):
                if d != 0:
                    end_dir = d
                    break

            trend = 'up' if end_dir == 1 else ('down' if end_dir == -1 else '')

        first_p = recent_prices[0]
        s.last_slope_pct = (recent_prices[-1] - first_p) / first_p if first_p > 0 else 0.0

    try:
        if not s.use_bot_trend:
            print(
                f'[R15 Debug] hwnd={hwnd} mode={s.strategy_mode} '
                f'prices={recent[-5:]} threshold={threshold:.6f} trend={trend}'
            )
    except Exception:
        pass

    s.last_trend = trend

    now = time.time()

    # ── EXIT logic ─────────────────────────────────────────────────────────────
    if s.position_price is not None:
        entry = s.position_price

        # Stop-loss check (fires before trend check - always exits regardless of always_sell_on_profit)
        if s.stop_loss_pct > 0:
            stop_floor = entry * (1.0 - s.stop_loss_pct / 100.0)
            if cur_price <= stop_floor:
                reason = f'stop-loss @ floor ${stop_floor:.2f}'
                logger.info(f'[R15] hwnd={hwnd} STOP-LOSS triggered at {cur_price:.4f}')
                s.position_price = None
                s.entry_fill_price = None
                s.entry_fill_status = ''
                s.last_sell_ts = now
                s.last_signal = 'sell'
                s.last_signal_ts = now
                log_msg = f"STOP-LOSS triggered @ ${cur_price:.2f} — selling"
                s.status_text = f'🛑 {log_msg}'
                s.trade_log.append({'direction': 'sell', 'price': cur_price, 'ts': now, 'reason': log_msg})
                if len(s.trade_log) > s._trade_log_max:
                    s.trade_log = s.trade_log[-s._trade_log_max:]
                return 'sell'

        # Sell ONLY on DOWN — hold through FLAT
        if trend == 'down':
            ref = s.entry_fill_price or entry
            # Check always_sell_on_profit condition if enabled
            if s.always_sell_on_profit and cur_price < ref:
                # Do not trigger exit since position is negative
                s.status_text = f'📈 Trend is DOWN, but holding because position is negative (${cur_price:.2f} < ${ref:.2f})'
                return None

            reason = 'trend DOWN'
            logger.info(f'[R15] hwnd={hwnd} SELL (trend DOWN) at {cur_price:.4f}')
            s.position_price = None
            s.entry_fill_price = None
            s.entry_fill_status = ''
            s.last_sell_ts = now
            s.last_signal = 'sell'
            s.last_signal_ts = now
            log_msg = f"SELL on the way (requested) @ ${cur_price:.2f}"
            s.trade_log.append({'direction': 'sell', 'price': cur_price, 'ts': now, 'reason': log_msg})
            if len(s.trade_log) > s._trade_log_max:
                s.trade_log = s.trade_log[-s._trade_log_max:]
            return 'sell'

        # Still holding — show live P&L
        ref = s.entry_fill_price or entry
        live_pnl = (cur_price - ref) * s.qty
        sign = '+' if live_pnl >= 0 else ''
        s.status_text = (
            f'📈 Holding {s.qty}sh @ ${ref:.2f} — '
            f'Profit: {sign}{live_pnl:.2f} (cur ${cur_price:.2f}, Trend: {trend or "flat"})'
        )
        return None

    # ── ENTRY logic ────────────────────────────────────────────────────────────
    if s.cooldown_secs > 0 and s.last_sell_ts > 0:
        elapsed = now - s.last_sell_ts
        if elapsed < s.cooldown_secs:
            remaining = s.cooldown_secs - elapsed
            s.status_text = f'\u23f1 Cooldown \u2014 {remaining:.0f}s remaining'
            return None

    if trend == 'up':
        logger.info(f'[R15] hwnd={hwnd} BUY (trend UP) at {cur_price:.4f}')
        s.position_price = cur_price
        s.position_ts = now
        s.entry_fill_price = None
        s.entry_fill_status = ''
        s.last_signal = 'buy'
        s.last_signal_ts = now
        s.status_text = f'\U0001f7e1 BUY signal @ ${cur_price:.2f} \u2014 sending order\u2026'
        s.trade_log.append({'direction': 'buy', 'price': cur_price, 'ts': now, 'reason': 'trend UP'})
        if len(s.trade_log) > s._trade_log_max:
            s.trade_log = s.trade_log[-s._trade_log_max:]
        return 'buy'

    # No action — update status
    slope_disp = s.last_slope_pct * 100
    if trend == '':
        s.status_text = (
            f'\U0001f4a4 Waiting \u2014 slope {slope_disp:+.4f}% '
            f'(need \u00b1{threshold * 100:.3f}%)'
        )
    elif trend == 'down':
        s.status_text = '\u2b07 Trend down \u2014 flat, no position'

    return None


__all__ = [
    'Rule15State',
    'DEFAULT_SLOPE_THRESHOLD',
    'get_r15_state',
    'configure_r15',
    'r15_state_for_frontend',
    'record_order_placed',
    'record_order_fill',
    'maybe_rule15_signal',
    '_r15_states',
]
