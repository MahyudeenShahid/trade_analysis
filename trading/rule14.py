"""
Rule 14 — History Graph Trend Auto-Trader

Logic:
  - Watches the OrderBook History chart (mid-price of best bid/ask snapshots).
  - Any upward slope  → BUY  (long entry)
  - Any downward slope → SELL (close long)
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


# ─── Per-ticker runtime state ────────────────────────────────────────────────

@dataclass
class Rule14State:
    """Mutable runtime state for R14 on a single bot/ticker."""
    enabled: bool = False

    # Config (set by UI)
    qty: int = 1                      # shares per order
    stop_loss_pct: float = 0.0        # 0 = disabled, e.g. 0.5 = 0.5%
    cooldown_secs: float = 0.0        # 0 = no cooldown

    # Position tracking
    position_price: Optional[float] = None   # entry price, None = flat
    position_ts: float = 0.0                 # unix time of entry

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


# Global registry: hwnd → Rule14State
_r14_states: dict[int, Rule14State] = {}


def get_r14_state(hwnd: int) -> Rule14State:
    """Get or create the R14 state for this bot window handle."""
    if hwnd not in _r14_states:
        _r14_states[hwnd] = Rule14State()
    return _r14_states[hwnd]


def configure_r14(hwnd: int, *, enabled: bool, qty: int = 1,
                  stop_loss_pct: float = 0.0, cooldown_secs: float = 0.0) -> Rule14State:
    """Update config for this bot. Call from API route."""
    s = get_r14_state(hwnd)
    s.enabled = enabled
    s.qty = max(1, int(qty))
    s.stop_loss_pct = max(0.0, float(stop_loss_pct))
    s.cooldown_secs = max(0.0, float(cooldown_secs))
    return s


def r14_state_for_frontend(hwnd: int) -> dict:
    """Return a JSON-serialisable snapshot for the WS broadcast."""
    s = get_r14_state(hwnd)
    pnl = None
    if s.position_price is not None and s.last_mid_price is not None:
        pnl = round((s.last_mid_price - s.position_price) * s.qty, 4)
    return {
        'enabled': s.enabled,
        'qty': s.qty,
        'stop_loss_pct': s.stop_loss_pct,
        'cooldown_secs': s.cooldown_secs,
        'position_price': s.position_price,
        'pnl': pnl,
        'last_trend': s.last_trend,
        'last_slope_pct': round(s.last_slope_pct * 100, 4),  # in % for display
        'last_mid_price': s.last_mid_price,
        'last_signal': s.last_signal,
        'last_signal_ts': s.last_signal_ts,
        # Send last 50 trade events so the UI can place markers on the blue graph
        'trade_log': s.trade_log[-50:],
    }


# ─── Slope computation ────────────────────────────────────────────────────────

def _slope_pct(mids: list[float]) -> Optional[float]:
    """
    Fraction change from first to last point.
    Any slope — no threshold. Returns None if insufficient data.
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

    # Determine raw trend direction (any slope)
    trend = 'up' if slope > 0 else 'down'
    s.last_trend = trend

    now = time.time()

    # ── EXIT logic ────────────────────────────────────────────────────────────
    if s.position_price is not None:
        entry = s.position_price

        # Stop-loss check (fires before trend check)
        if s.stop_loss_pct > 0:
            stop_floor = entry * (1.0 - s.stop_loss_pct / 100.0)
            if cur_mid <= stop_floor:
                reason = f'stop-loss @ floor {stop_floor:.4f}'
                logger.info(
                    f"[R14] hwnd={hwnd} STOP-LOSS triggered at {cur_mid:.4f} "
                    f"(entry={entry:.4f}, floor={stop_floor:.4f})"
                )
                s.position_price = None
                s.last_sell_ts = now
                s.last_signal = 'sell'
                s.last_signal_ts = now
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
            s.last_sell_ts = now
            s.last_signal = 'sell'
            s.last_signal_ts = now
            s.trade_log.append({'direction': 'sell', 'price': cur_mid, 'ts': now, 'reason': reason})
            if len(s.trade_log) > s._trade_log_max:
                s.trade_log = s.trade_log[-s._trade_log_max:]
            return 'sell'

        return None  # holding, trend still UP

    # ── ENTRY logic ───────────────────────────────────────────────────────────
    # Cooldown guard
    if s.cooldown_secs > 0 and s.last_sell_ts > 0:
        elapsed = now - s.last_sell_ts
        if elapsed < s.cooldown_secs:
            return None

    if trend == 'up':
        reason = f'trend UP slope={slope*100:.4f}%'
        logger.info(
            f"[R14] hwnd={hwnd} BUY (trend UP) at {cur_mid:.4f} "
            f"(slope={slope*100:.4f}%)"
        )
        s.position_price = cur_mid
        s.position_ts = now
        s.last_signal = 'buy'
        s.last_signal_ts = now
        s.trade_log.append({'direction': 'buy', 'price': cur_mid, 'ts': now, 'reason': reason})
        if len(s.trade_log) > s._trade_log_max:
            s.trade_log = s.trade_log[-s._trade_log_max:]
        return 'buy'

    return None


__all__ = [
    'Rule14State',
    'get_r14_state',
    'configure_r14',
    'r14_state_for_frontend',
    'maybe_rule14_signal',
]
