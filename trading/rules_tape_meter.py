"""
Rule 12: Main Chart Bot Trend Scalper

A from-scratch implementation of Rule 12 trend-following execution.
- Evaluates the screenshot-detected trend ('up', 'down', '').
- Pulls live price from the IBKR connection.
- Manages order states: buy first, wait for fill, track P&L, then sell when trend changes or stop-loss hits.
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

class Rule12State:
    def __init__(self):
        self.enabled = False
        self.stop_loss_pct = 0.0
        self.always_sell_on_profit = False

        # Position tracking
        self.position_price = None  # None when flat
        self.entry_fill_status = ''  # '', 'pending', 'filled', 'failed'
        self.entry_limit_price = None

        # Telemetry
        self.last_trend = ''
        self.last_mid_price = None
        self.status_text = 'Disabled'
        self.trade_log = []  # Log statements for display

_r12_states = {}

def get_r12_state(hwnd: int) -> Rule12State:
    if hwnd not in _r12_states:
        _r12_states[hwnd] = Rule12State()
    return _r12_states[hwnd]

def configure_r12(hwnd: int, enabled: bool, stop_loss_pct: float = 0.0, always_sell_on_profit: bool = False) -> Rule12State:
    s = get_r12_state(hwnd)
    s.enabled = enabled
    s.stop_loss_pct = max(0.0, float(stop_loss_pct))
    s.always_sell_on_profit = bool(always_sell_on_profit)
    if not enabled:
        s.status_text = 'Disabled'
    return s

def record_order_placed(hwnd: int, direction: str, price: float):
    s = get_r12_state(hwnd)
    s.entry_fill_status = 'pending'
    s.entry_limit_price = price
    
    log_msg = f"Order placed to {direction} at {price:.2f}"
    s.trade_log.append(log_msg)
    s.status_text = f"Order placed {direction} at {price:.2f}"

def record_order_fill(hwnd: int, direction: str, price: float, ok: bool, error_msg: str = ''):
    s = get_r12_state(hwnd)
    if ok:
        log_msg = f"Order executed {direction} at {price:.2f}"
        s.trade_log.append(log_msg)
        if direction == 'buy':
            s.position_price = price
            s.entry_fill_status = 'filled'
            s.status_text = "Waiting to sell"
        else:
            s.position_price = None
            s.entry_fill_status = ''
            s.status_text = "Waiting to buy"
    else:
        log_msg = f"Order executed {direction} at {price:.2f} failed: {error_msg or 'unknown'}"
        s.trade_log.append(log_msg)
        s.entry_fill_status = 'failed'
        s.status_text = f"{direction.upper()} failed"

def r12_state_for_frontend(hwnd: int) -> dict:
    s = get_r12_state(hwnd)
    pnl = None
    pnl_pct = None
    if s.position_price is not None and s.last_mid_price is not None:
        pnl = s.last_mid_price - s.position_price
        pnl_pct = (pnl / s.position_price) * 100.0 if s.position_price > 0 else 0.0

    return {
        'enabled': s.enabled,
        'stop_loss_pct': s.stop_loss_pct,
        'always_sell_on_profit': s.always_sell_on_profit,
        'position_price': s.position_price,
        'entry_fill_status': s.entry_fill_status,
        'last_trend': s.last_trend,
        'last_mid_price': s.last_mid_price,
        'status_text': s.status_text,
        'trade_log': s.trade_log,
        'pnl': round(pnl, 2) if pnl is not None else None,
        'pnl_pct': round(pnl_pct, 2) if pnl_pct is not None else None,
    }

def maybe_rule12_signal(hwnd: int, bot_trend: str, ibkr_price: float) -> Optional[str]:
    s = get_r12_state(hwnd)
    if not s.enabled:
        return None

    s.last_mid_price = ibkr_price
    trend = str(bot_trend).strip().lower()
    s.last_trend = trend

    # Wait for pending orders to complete
    if s.entry_fill_status == 'pending':
        return None

    # FLAT/Waiting status when not in position
    if s.position_price is None:
        if trend == 'up':
            return 'buy'
        s.status_text = "Waiting to buy"
        return None

    # EXIT LOGIC (In Position)
    # 1. Stop Loss Check
    if s.stop_loss_pct > 0:
        stop_level = s.position_price * (1.0 - s.stop_loss_pct / 100.0)
        if ibkr_price <= stop_level:
            return 'sell'

    # 2. Trend Change Exit Check
    if trend == 'down':
        if s.always_sell_on_profit:
            if ibkr_price > s.position_price:
                return 'sell'
            else:
                pnl = ibkr_price - s.position_price
                s.status_text = f"Holding: waiting for profit (Current: {ibkr_price:.2f}, Bought: {s.position_price:.2f})"
                return None
        else:
            return 'sell'

    # 3. Live P&L Updates
    pnl = ibkr_price - s.position_price
    sign = '+' if pnl >= 0 else ''
    s.status_text = f"Waiting to sell | Current P&L: {sign}{pnl:.2f} (Bought: {s.position_price:.2f}, Current: {ibkr_price:.2f})"
    return None

def maybe_rule12_trade(*args, **kwargs):
    return False
