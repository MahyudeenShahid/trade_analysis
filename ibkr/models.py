"""Data models for IBKR order requests and results."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IBKROrderRequest:
    ticker: str
    direction: str          # 'buy' | 'sell'
    order_type: str         # 'market' | 'limit'
    qty: float
    limit_price: Optional[float] = None
    bot_id: Optional[str] = None
    hwnd: Optional[int] = None
    trade_ref_id: Optional[str] = None   # links to records.ts / trade_id


@dataclass
class IBKROrderResult:
    ok: bool
    ibkr_order_id: Optional[int] = None
    fill_price: Optional[float] = None
    fill_ts: Optional[str] = None
    error_msg: Optional[str] = None
    retries: int = 0
