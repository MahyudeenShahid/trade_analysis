"""Database query operations (Compatibility Hub)."""

from .base import query_records, query_history_page
from .observations import get_latest_record, save_observation
from .bots import get_bot_db_entry, upsert_bot_from_last_result, upsert_bot_settings
from .settings import get_app_settings, set_app_setting
from .orders import (
    save_live_order,
    update_live_order_status,
    get_live_orders,
    count_live_orders,
    get_last_buy_order,
    get_last_order_for_hwnd_ticker,
)

__all__ = [
    "query_records",
    "query_history_page",
    "get_latest_record",
    "save_observation",
    "get_bot_db_entry",
    "upsert_bot_from_last_result",
    "upsert_bot_settings",
    "get_app_settings",
    "set_app_setting",
    "save_live_order",
    "update_live_order_status",
    "get_live_orders",
    "count_live_orders",
    "get_last_buy_order",
    "get_last_order_for_hwnd_ticker",
]
