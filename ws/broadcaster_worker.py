"""Worker payload compilation for WebSocket broadcaster."""

import base64
import os
from services.capture_manager import manager_services
from services.bot_registry import list_bots_by_hwnd
from db.queries import get_bot_db_entry


def build_workers_payload() -> list:
    """Collect per-worker status, base64 encoded screenshots, and active bot profiles."""
    workers_payload = []
    try:
        for hwnd, svc in manager_services.iter_services():
            try:
                st = svc.get_status()
            except Exception:
                st = {}
            last = (st.get('last_result') or {}) if isinstance(st, dict) else {}
            image_b64 = None
            image_mime = None
            img_path = last.get('image_path')
            if img_path and os.path.exists(img_path):
                try:
                    with open(img_path, 'rb') as f:
                        image_b64 = base64.b64encode(f.read()).decode('ascii')
                    if str(img_path).lower().endswith(('.jpg', '.jpeg')):
                        image_mime = 'image/jpeg'
                    else:
                        image_mime = 'image/png'
                except Exception:
                    image_b64 = None

            # Pull session bot settings for this hwnd (fallback to DB when empty)
            bot_info = None
            bot_list = []
            try:
                bot_list = list_bots_by_hwnd(int(hwnd))
                bot_info = bot_list[0] if bot_list else None
            except Exception:
                bot_info = None
                bot_list = []
            if not bot_list:
                try:
                    bot_db_row = get_bot_db_entry(int(hwnd))
                    if isinstance(bot_db_row, dict) and bot_db_row:
                        bot_info = bot_db_row
                        bot_list = [bot_db_row]
                except Exception:
                    pass

            workers_payload.append({
                'hwnd': int(hwnd),
                'status': st or {},
                'screenshot_b64': image_b64,
                'screenshot_mime': image_mime,
                'last_result': last,
                'bot': bot_info,
                'bots': bot_list,
                'svc': svc,  # Retain service reference for signal overrides
            })
    except Exception:
        pass
    return workers_payload
