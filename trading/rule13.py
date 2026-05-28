"""
Rule 13 — Blue Graph Direction (Slope-Based Auto-Trade)

Logic:
  - Compute slope of recent price history over a configurable lookback window.
  - slope > +threshold_pct  → BUY  (graph pointing up)
  - slope < -threshold_pct  → SELL / close position (graph pointing down)
  - flat zone               → no action

This rule is intentionally pure and stateless beyond the TickerState position —
it reads price_history directly from the state and acts on slope alone.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable, List, Optional

if TYPE_CHECKING:
    from .state import TickerState


def _compute_slope_pct(prices: List[float], lookback: int) -> Optional[float]:
    """
    Return the percentage change from the oldest to newest point in the
    lookback window, expressed as a signed fraction (e.g. 0.003 = +0.3%).
    Returns None if insufficient data.
    """
    if not prices or len(prices) < 2:
        return None
    window = prices[-max(2, int(lookback)):]
    first = window[0]
    last = window[-1]
    if first == 0:
        return None
    return (last - first) / abs(first)


def maybe_rule13_trade(
    state: "TickerState",
    current_price: float,
    price_history: Optional[List[float]] = None,
    *,
    lookback: int = 5,
    slope_threshold_pct: float = 0.0005,
    profit_pct: float = 0.2,
    stop_pct: float = 0.4,
    stop_enabled: bool = True,
    only_profit: bool = False,
    cooldown_minutes: float = 0.0,
    buy_callback: Optional[Callable[[float], None]] = None,
    sell_callback: Optional[Callable[[float, str], None]] = None,
) -> bool:
    """
    Rule #13: Blue Graph Direction — slope-based buy/sell.

    Returns True if this rule acted (buy or sell triggered) so the caller
    can short-circuit other rules.

    Parameters
    ----------
    state               TickerState for the current bot/ticker
    current_price       Latest price tick
    price_history       Explicit price list; falls back to state.price_history
    lookback            Number of ticks to include in slope calculation (default 5)
    slope_threshold_pct Minimum |slope| to trigger (default 0.05% = 0.0005)
    profit_pct          Take-profit percentage above entry (default 0.2 %)
    stop_pct            Stop-loss percentage below entry (default 0.4 %)
    stop_enabled        Whether the stop-loss fires at all
    only_profit         When True, stop-loss is ignored (sell only on profit)
    cooldown_minutes    Minutes to wait after a sell before buying again
    buy_callback        Called with the buy price when a BUY is triggered
    sell_callback       Called with (sell_price, win_reason) when a SELL fires
    """
    prices = price_history if isinstance(price_history, list) and price_history else (
        state.price_history if hasattr(state, "price_history") else []
    )

    slope = _compute_slope_pct(prices, lookback)
    if slope is None:
        # Not enough data — let the rule pass through silently
        return False

    # ── EXIT logic (position open) ──────────────────────────────────────────
    if state.position is not None:
        entry = float(state.position.get("price") or current_price)

        # Take-profit
        if profit_pct and profit_pct > 0:
            target = entry * (1 + profit_pct / 100)
            if current_price >= target:
                if sell_callback:
                    sell_callback(current_price, "RULE_13_PROFIT")
                return True

        # Stop-loss (only if not in only_profit mode)
        if stop_enabled and not only_profit and stop_pct and stop_pct > 0:
            stop_floor = entry * (1 - stop_pct / 100)
            if current_price <= stop_floor:
                if sell_callback:
                    sell_callback(current_price, "RULE_13_STOP")
                return True

        # Slope turned DOWN — close the position
        if slope < -abs(float(slope_threshold_pct)):
            if only_profit and current_price <= entry:
                return False  # honour only_profit — do not close at a loss
            if sell_callback:
                sell_callback(current_price, "RULE_13_SLOPE_DOWN")
            return True

        return False  # holding, no exit condition met

    # ── ENTRY logic (no position) ────────────────────────────────────────────
    # Cooldown: check time since last sell
    if cooldown_minutes and cooldown_minutes > 0:
        last_sell = getattr(state, "rule13_last_sell_time", None)
        if last_sell is not None:
            try:
                elapsed = (datetime.utcnow() - last_sell).total_seconds() / 60.0
                if elapsed < cooldown_minutes:
                    return False
            except Exception:
                pass

    if slope > abs(float(slope_threshold_pct)):
        if buy_callback:
            buy_callback(current_price)
        return True

    return False


__all__ = ["maybe_rule13_trade", "_compute_slope_pct"]
