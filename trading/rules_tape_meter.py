"""Rule 12: Tape + Order Book Meter."""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from trading.state import TickerState


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
            ask = float(top_book.get("ask")) if top_book.get("ask") is not None else None
            if bid is not None and ask is not None:
                mid = (bid + ask) / 2.0
        except Exception:
            pass

    if mid is None:
        try:
            mid = sum(float(r["price"]) for r in rows) / len(rows)
        except Exception:
            return 50.0

    up_volume = 0.0
    down_volume = 0.0
    for r in rows:
        try:
            price = float(r["price"])
            vol = float(r.get("volume") or 1.0)
            if price > mid:
                up_volume += vol
            elif price < mid:
                down_volume += vol
            else:
                up_volume += vol * 0.5
                down_volume += vol * 0.5
        except Exception:
            pass

    total = up_volume + down_volume
    if total <= 0:
        return 50.0
    return _clamp((up_volume / total) * 100.0, 0.0, 100.0)


def _calc_rule12_book_pct(depth_snapshot: Optional[dict]) -> float:
    if not isinstance(depth_snapshot, dict):
        return 50.0
    bids = depth_snapshot.get("bids") or []
    asks = depth_snapshot.get("asks") or []
    if not bids and not asks:
        return 50.0

    bid_power = 0.0
    for r in bids:
        try:
            bid_power += float(r.get("price") or 0.0) * float(r.get("size") or 0.0)
        except Exception:
            pass

    ask_power = 0.0
    for r in asks:
        try:
            ask_power += float(r.get("price") or 0.0) * float(r.get("size") or 0.0)
        except Exception:
            pass

    total = bid_power + ask_power
    if total <= 0:
        return 50.0
    return _clamp((bid_power / total) * 100.0, 0.0, 100.0)


def maybe_rule12_trade(
    state: 'TickerState',
    current_price: float,
    price_history: list,
    price_volume_history: Optional[list],
    top_book: Optional[dict],
    depth_snapshot: Optional[dict],
    buy_threshold: Optional[float] = 70.0,
    sell_threshold: Optional[float] = 60.0,
    min_trades: Optional[int] = 5,
    weight_tape: Optional[float] = 0.4,
    weight_book: Optional[float] = 0.2,
    weight_trend: Optional[float] = 0.2,
    weight_momentum: Optional[float] = 0.1,
    weight_volume: Optional[float] = 0.1,
    weight_spread: Optional[float] = 0.0,
    weight_pullback: Optional[float] = 0.0,
    momentum_scale: Optional[float] = 0.0005,
    spread_tight_pct: Optional[float] = 0.001,
    buy_callback=None,
    sell_callback=None,
) -> bool:
    """
    Rule #12: Tape + Order Book Meter.
    Aggregates Tape + DOM imbalances, micro-momentum, and spreads into a 0-100 score.
    - Buy if score >= buy_threshold
    - Sell if score <= sell_threshold (while in position)
    Always returns True (blocks default logic).
    """
    wt = float(weight_tape if weight_tape is not None else 0.4)
    wb = float(weight_book if weight_book is not None else 0.2)
    w_trend = float(weight_trend if weight_trend is not None else 0.2)
    w_mom = float(weight_momentum if weight_momentum is not None else 0.1)
    w_vol = float(weight_volume if weight_volume is not None else 0.1)
    w_spr = float(weight_spread if weight_spread is not None else 0.0)
    w_pb = float(weight_pullback if weight_pullback is not None else 0.0)

    # Normalize weights so they sum to 1.0
    total_w = wt + wb + w_trend + w_mom + w_vol + w_spr + w_pb
    if total_w <= 0:
        wt, wb, w_trend, w_mom, w_vol = 0.4, 0.2, 0.2, 0.1, 0.1
        total_w = 1.0
    wt /= total_w
    wb /= total_w
    w_trend /= total_w
    w_mom /= total_w
    w_vol /= total_w
    w_spr /= total_w
    w_pb /= total_w

    # Component 1: Tape Volume Imbalance
    pvh = price_volume_history or []
    min_t = int(min_trades if min_trades is not None else 5)
    tape_pct = _calc_rule12_tape_pct(pvh, top_book, min_t)

    # Component 2: Order Book DOM Imbalance
    book_pct = _calc_rule12_book_pct(depth_snapshot)

    # Component 3: Sparkline Trend
    try:
        from trading.rule13 import _compute_slope_pct
        slope = _compute_slope_pct(price_history, 5)
        trend_score = _score_to_pct(slope / 0.0003) if slope is not None else 50.0
    except Exception:
        trend_score = 50.0

    # Component 4: Micro Momentum (1-tick change)
    mom_score = 50.0
    if len(price_history) >= 2:
        try:
            delta = float(current_price) - float(price_history[-2])
            scale = float(momentum_scale if momentum_scale is not None else 0.0005)
            if scale > 0:
                mom_score = _score_to_pct(delta / (float(current_price) * scale))
        except Exception:
            pass

    # Component 5: Volume Surge
    vol_score = 50.0
    if pvh:
        try:
            recent_vols = [float(x.get("volume") or 0.0) for x in pvh[-5:]]
            older_vols = [float(x.get("volume") or 0.0) for x in pvh[:-5]]
            avg_recent = sum(recent_vols) / len(recent_vols) if recent_vols else 0.0
            avg_older = sum(older_vols) / len(older_vols) if older_vols else 0.0
            if avg_older > 0:
                surge = avg_recent / avg_older
                vol_score = _clamp(surge * 25.0, 0.0, 100.0)
        except Exception:
            pass

    # Component 6: Spread Tightness
    spr_score = 50.0
    if isinstance(top_book, dict):
        try:
            bid = float(top_book.get("bid"))
            ask = float(top_book.get("ask"))
            spread = ask - bid
            tight_pct = float(spread_tight_pct if spread_tight_pct is not None else 0.001)
            target_spread = bid * tight_pct
            if spread <= target_spread:
                spr_score = 100.0
            else:
                spr_score = _clamp((target_spread / spread) * 100.0, 0.0, 100.0)
        except Exception:
            pass

    # Component 7: Pullback Detection
    pb_score = 50.0
    if len(price_history) >= 5:
        try:
            recent_window = price_history[-5:]
            peak = max(recent_window)
            trough = min(recent_window)
            if peak > trough:
                pb = (peak - float(current_price)) / (peak - trough)
                pb_score = _clamp(pb * 100.0, 0.0, 100.0)
        except Exception:
            pass

    # Aggregate final score
    score = (
        tape_pct * wt
        + book_pct * wb
        + trend_score * w_trend
        + mom_score * w_mom
        + vol_score * w_vol
        + spr_score * w_spr
        + pb_score * w_pb
    )

    buy_th = float(buy_threshold if buy_threshold is not None else 70.0)
    sell_th = float(sell_threshold if sell_threshold is not None else 60.0)

    # Position evaluation
    if state.position is None:
        if score >= buy_th:
            buy_callback(current_price)
    else:
        if score <= sell_th:
            sell_callback(current_price, win_reason="RULE_12")

    return True
