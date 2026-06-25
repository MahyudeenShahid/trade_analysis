"""
Rule 14 — History Graph Trend Auto-Trader

Logic:
  - Watches the OrderBook History chart (mid-price of best bid/ask snapshots).
  - Slope > +THRESHOLD % over the lookback window  → BUY  (long entry)
  - Slope < -THRESHOLD % over the lookback window  → SELL (close long)
  - Stop-loss % fires independently of trend check.
  - Long-only (no shorting).
  - Overrides all other rules when enabled on a bot.

This rule is designed for fast IBKR execution. It fires marketable limit orders
(ask+offset for buy, bid-offset for sell) to ensure near-instant fills.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum slope magnitude to trigger a signal (in fractional terms).
# 0.0003 == 0.03%.  Prevents firing on micro-noise.
DEFAULT_SLOPE_THRESHOLD = 0.0003


# ─── Per-ticker runtime state ────────────────────────────────────────────────

@dataclass
class Rule14State:
    """Mutable runtime state for R14 on a single bot/ticker."""
    enabled: bool = False

    # Config (set by UI)
    qty: int = 1                      # shares per order
    stop_loss_pct: float = 0.0        # 0 = disabled, e.g. 0.5 = 0.5%
    cooldown_secs: float = 0.0        # 0 = no cooldown
    slope_threshold: float = DEFAULT_SLOPE_THRESHOLD  # min slope to trigger

    # Position tracking
    position_price: Optional[float] = None   # signal price at entry, None = flat
    position_ts: float = 0.0                 # unix time of entry
    entry_limit_price: Optional[float] = None  # limit price sent to IBKR
    entry_fill_price: Optional[float] = None   # actual fill price from IBKR
    entry_fill_status: str = ''               # 'pending' | 'filled' | 'failed'

    # Last signal sent (prevents duplicate orders)
    last_signal: str = ''             # 'buy' | 'sell' | ''
    last_signal_ts: float = 0.0      # unix time of last signal

    # Last sell time (for cooldown)
    last_sell_ts: float = 0.0

    # For broadcast to frontend
    last_trend: str = ''              # 'up' | 'down' | ''
    last_slope_pct: float = 0.0
    last_mid_price: Optional[float] = None

    # Rolling log of executed trades (for UI markers on the blue graph)
    # Each entry: {'direction': 'buy'|'sell', 'price': float, 'ts': float, 'reason': str}
    trade_log: list = field(default_factory=list)
    _trade_log_max: int = 200  # keep last 200 trades

    # ─── Order event log ─────────────────────────────────────────────────────
    # Tracks the full lifecycle of each order:
    # {'event': 'order_placed'|'order_filled'|'order_failed', 'direction': str,
    #  'signal_price': float, 'limit_price': float|None, 'fill_price': float|None,
    #  'slippage': float|None, 'reason': str, 'ts': float}
    order_events: list = field(default_factory=list)
    _order_events_max: int = 100

    # Current status phrase for display
    status_text: str = 'Idle'


# Global registry: hwnd → Rule14State
_r14_states: dict[int, Rule14State] = {}


def get_r14_state(hwnd: int) -> Rule14State:
    """Get or create the R14 state for this bot window handle."""
    if hwnd not in _r14_states:
        _r14_states[hwnd] = Rule14State()
    return _r14_states[hwnd]


def configure_r14(hwnd: int, *, enabled: bool, qty: int = 1,
                  stop_loss_pct: float = 0.0, cooldown_secs: float = 0.0,
                  slope_threshold: float = DEFAULT_SLOPE_THRESHOLD) -> Rule14State:
    """Update config for this bot. Call from API route."""
    s = get_r14_state(hwnd)
    s.enabled = enabled
    s.qty = max(1, int(qty))
    s.stop_loss_pct = max(0.0, float(stop_loss_pct))
    s.cooldown_secs = max(0.0, float(cooldown_secs))
    s.slope_threshold = max(0.0, float(slope_threshold))
    if not enabled:
        s.status_text = 'Disabled'
    return s


def _append_order_event(s: Rule14State, event: dict) -> None:
    """Append to order_events, trimming if over max."""
    s.order_events.append(event)
    if len(s.order_events) > s._order_events_max:
        s.order_events = s.order_events[-s._order_events_max:]


def record_order_placed(hwnd: int, direction: str, signal_price: float,
                        limit_price: Optional[float]) -> None:
    """Called by broadcaster immediately after dispatching the IBKR order."""
    s = get_r14_state(hwnd)
    now = time.time()
    lp_str = f'${limit_price:.2f}' if limit_price is not None else 'MKT'
    _append_order_event(s, {
        'event': 'order_placed',
        'direction': direction,
        'signal_price': signal_price,
        'limit_price': limit_price,
        'fill_price': None,
        'slippage': None,
        'reason': f'Order sent to IBKR — limit {lp_str}',
        'ts': now,
    })
    if direction == 'buy':
        s.entry_limit_price = limit_price
        s.entry_fill_status = 'pending'
        s.status_text = f'⏳ BUY order placed @ {lp_str} — awaiting fill…'
    else:
        s.status_text = f'⏳ SELL order placed @ {lp_str} — awaiting fill…'


def record_order_fill(hwnd: int, direction: str, signal_price: float,
                      limit_price: Optional[float], fill_price: Optional[float],
                      ok: bool, error_msg: str = '') -> None:
    """Called by broadcaster after IBKR order completes (filled or failed)."""
    s = get_r14_state(hwnd)
    now = time.time()
    slippage = None
    if ok and fill_price is not None and signal_price is not None:
        slippage = round(fill_price - signal_price, 4)

    lp_str = f'${limit_price:.2f}' if limit_price is not None else 'MKT'
    fp_str = f'${fill_price:.2f}' if fill_price is not None else '—'

    if ok:
        slip_str = f'{slippage:+.2f}' if slippage is not None else ''
        reason = f'Filled @ {fp_str} (slip {slip_str})'
        _append_order_event(s, {
            'event': 'order_filled',
            'direction': direction,
            'signal_price': signal_price,
            'limit_price': limit_price,
            'fill_price': fill_price,
            'slippage': slippage,
            'reason': reason,
            'ts': now,
        })
        if direction == 'buy':
            s.entry_fill_price = fill_price
            s.entry_fill_status = 'filled'
            s.status_text = f'✅ BOUGHT @ {fp_str} (slip {slip_str}) — holding'
        else:
            s.status_text = f'✅ SOLD @ {fp_str} (slip {slip_str}) — flat'
    else:
        _append_order_event(s, {
            'event': 'order_failed',
            'direction': direction,
            'signal_price': signal_price,
            'limit_price': limit_price,
            'fill_price': None,
            'slippage': None,
            'reason': f'FAILED: {error_msg or "unknown"}',
            'ts': now,
        })
        if direction == 'buy':
            s.entry_fill_status = 'failed'
            s.status_text = f'❌ BUY FAILED — {error_msg or "unknown"}'
        else:
            s.status_text = f'❌ SELL FAILED — {error_msg or "unknown"}'


def r14_state_for_frontend(hwnd: int) -> dict:
    """Return a JSON-serialisable snapshot for the WS broadcast."""
    s = get_r14_state(hwnd)
    pnl = None
    pnl_pct = None
    ref_price = s.entry_fill_price or s.position_price
    if ref_price is not None and s.last_mid_price is not None:
        pnl = round((s.last_mid_price - ref_price) * s.qty, 4)
        pnl_pct = round(((s.last_mid_price - ref_price) / ref_price) * 100, 4) if ref_price > 0 else None
    return {
        'enabled': s.enabled,
        'qty': s.qty,
        'stop_loss_pct': s.stop_loss_pct,
        'cooldown_secs': s.cooldown_secs,
        'slope_threshold': round(s.slope_threshold * 100, 4),  # in % for display
        'position_price': s.position_price,
        'entry_fill_price': s.entry_fill_price,
        'entry_fill_status': s.entry_fill_status,
        'pnl': pnl,
        'pnl_pct': pnl_pct,
        'last_trend': s.last_trend,
        'last_slope_pct': round(s.last_slope_pct * 100, 4),  # in % for display
        'last_mid_price': s.last_mid_price,
        'last_signal': s.last_signal,
        'last_signal_ts': s.last_signal_ts,
        'status_text': s.status_text,
        # Send last 50 trade events so the UI can place markers on the blue graph
        'trade_log': s.trade_log[-50:],
        # Send last 30 order events for the status log panel
        'order_events': s.order_events[-30:],
    }


# ─── Slope computation ────────────────────────────────────────────────────────

def _slope_pct(mids: list[float]) -> Optional[float]:
    """
    Fraction change from first to last point.
    Returns None if insufficient data.
    """
    vals = [v for v in mids if isinstance(v, (int, float)) and v > 0]
    if len(vals) < 2:
        return None
    first, last = vals[0], vals[-1]
    return (last - first) / first


def _mid_from_point(point: dict) -> Optional[float]:
    """Extract mid price from an order-book-history point dict."""
    try:
        bids = point.get('bids') or []
        asks = point.get('asks') or []
        best_bid = float(bids[0]['price']) if bids else None
        best_ask = float(asks[0]['price']) if asks else None
        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) / 2.0
        return best_bid or best_ask
    except Exception:
        return None


# ─── Main signal function ─────────────────────────────────────────────────────

def maybe_rule14_signal(
    hwnd: int,
    history_points: list[dict],   # raw order-book history [{bids,asks,ts}...]
    lookback: int = 10,
) -> Optional[str]:
    """
    Evaluate R14 logic for one tick.

    Returns 'buy', 'sell', or None.
    Updates state in-place.
    """
    s = get_r14_state(hwnd)
    if not s.enabled:
        return None

    # Build mid-price series from the history points
    recent = history_points[-max(2, lookback):]
    mids = [_mid_from_point(p) for p in recent]
    mids = [m for m in mids if m is not None]

    if not mids:
        return None

    cur_mid = mids[-1]
    s.last_mid_price = cur_mid

    slope = _slope_pct(mids)
    if slope is None:
        return None

    s.last_slope_pct = slope

    threshold = s.slope_threshold  # minimum slope magnitude to act on
    # Determine trend direction with threshold guard
    if slope > threshold:
        trend = 'up'
    elif slope < -threshold:
        trend = 'down'
    else:
        trend = ''  # flat / noise — do nothing

    s.last_trend = trend

    now = time.time()

    # ── EXIT logic ────────────────────────────────────────────────────────────
    if s.position_price is not None:
        entry = s.position_price

        # Stop-loss check (fires before trend check)
        if s.stop_loss_pct > 0:
            stop_floor = entry * (1.0 - s.stop_loss_pct / 100.0)
            if cur_mid <= stop_floor:
                reason = f'stop-loss @ floor ${stop_floor:.4f}'
                logger.info(
                    f"[R14] hwnd={hwnd} STOP-LOSS triggered at {cur_mid:.4f} "
                    f"(entry={entry:.4f}, floor={stop_floor:.4f})"
                )
                s.position_price = None
                s.entry_fill_price = None
                s.entry_fill_status = ''
                s.last_sell_ts = now
                s.last_signal = 'sell'
                s.last_signal_ts = now
                s.status_text = f'🛑 STOP-LOSS triggered @ ${cur_mid:.2f}'
                s.trade_log.append({'direction': 'sell', 'price': cur_mid, 'ts': now, 'reason': reason})
                if len(s.trade_log) > s._trade_log_max:
                    s.trade_log = s.trade_log[-s._trade_log_max:]
                return 'sell'

        # Trend reversed to DOWN → close position
        if trend == 'down':
            reason = f'trend DOWN slope={slope*100:.4f}%'
            logger.info(
                f"[R14] hwnd={hwnd} SELL (trend DOWN) at {cur_mid:.4f} "
                f"(slope={slope*100:.4f}%)"
            )
            s.position_price = None
            s.entry_fill_price = None
            s.entry_fill_status = ''
            s.last_sell_ts = now
            s.last_signal = 'sell'
            s.last_signal_ts = now
            s.trade_log.append({'direction': 'sell', 'price': cur_mid, 'ts': now, 'reason': reason})
            if len(s.trade_log) > s._trade_log_max:
                s.trade_log = s.trade_log[-s._trade_log_max:]
            return 'sell'

        # Still holding, show live P&L in status
        ref = s.entry_fill_price or entry
        live_pnl = (cur_mid - ref) * s.qty
        s.status_text = (
            f'📈 Holding {s.qty}sh @ ${ref:.2f} — '
            f'P&L: {"+" if live_pnl >= 0 else ""}{live_pnl:.2f} (cur ${cur_mid:.2f})'
        )
        return None  # holding, trend still UP

    # ── ENTRY logic ───────────────────────────────────────────────────────────
    # Cooldown guard
    if s.cooldown_secs > 0 and s.last_sell_ts > 0:
        elapsed = now - s.last_sell_ts
        if elapsed < s.cooldown_secs:
            remaining = s.cooldown_secs - elapsed
            s.status_text = f'⏱ Cooldown — {remaining:.0f}s remaining'
            return None

    if trend == 'up':
        reason = f'trend UP slope={slope*100:.4f}%'
        logger.info(
            f"[R14] hwnd={hwnd} BUY (trend UP) at {cur_mid:.4f} "
            f"(slope={slope*100:.4f}%)"
        )
        s.position_price = cur_mid
        s.position_ts = now
        s.entry_fill_price = None
        s.entry_fill_status = ''
        s.last_signal = 'buy'
        s.last_signal_ts = now
        s.status_text = f'🟡 BUY signal @ ${cur_mid:.2f} — sending order…'
        s.trade_log.append({'direction': 'buy', 'price': cur_mid, 'ts': now, 'reason': reason})
        if len(s.trade_log) > s._trade_log_max:
            s.trade_log = s.trade_log[-s._trade_log_max:]
        return 'buy'

    if trend == '':
        s.status_text = (
            f'💤 Waiting — slope {slope*100:+.4f}% '
            f'(need ±{threshold*100:.3f}%)'
        )
    elif trend == 'down':
        s.status_text = f'⬇ Trend down — flat, no position'

    return None


__all__ = [
    'Rule14State',
    'get_r14_state',
    'configure_r14',
    'r14_state_for_frontend',
    'record_order_placed',
    'record_order_fill',
    'maybe_rule14_signal',
]
