"""WebSocket broadcaster for real-time updates."""

import asyncio
import base64
import json
import os
from datetime import datetime

from .manager import manager


async def broadcaster_loop():
    """
    Background task that broadcasts status updates to all connected WebSocket clients.
    
    This function runs continuously and:
    - Collects status from all capture services
    - Gathers screenshots and encodes them as base64
    - Updates trader signals automatically
    - Broadcasts combined payload to all WebSocket clients
    - Cleans up old screenshots to save disk space
    """
    # Import here to avoid circular imports
    from services.capture_manager import manager_services
    from trading.simulator import trader
    from db.queries import upsert_bot_from_last_result, get_bot_db_entry
    
    while True:
        try:
            # collect per-worker statuses and screenshots
            workers_payload = []
            try:
                for hwnd, svc in manager_services.iter_services():
                    try:
                        st = svc.get_status()
                    except Exception:
                        st = {}
                    last = (st.get('last_result') or {}) if isinstance(st, dict) else {}
                    image_b64 = None
                    img_path = last.get('image_path')
                    if img_path and os.path.exists(img_path):
                        try:
                            with open(img_path, 'rb') as f:
                                image_b64 = base64.b64encode(f.read()).decode('ascii')
                        except Exception:
                            image_b64 = None

                    # pull persisted bot settings and apply Rule #1 override when enabled
                    bot_info = None
                    try:
                        bot_info = get_bot_db_entry(int(hwnd))
                    except Exception:
                        bot_info = None

                    # update trader auto signals if worker produced price/ticker
                    try:
                        trend = last.get('trend') or ''
                        price = last.get('price') or last.get('price_value') or None
                        ticker = last.get('ticker') or None
                        if price is not None and ticker:
                            rule_enabled = False
                            rule2_enabled = False
                            rule3_enabled = False
                            rule4_enabled = True
                            rule5_enabled = False
                            rule6_enabled = False
                            rule7_enabled = False
                            tp_amount = None
                            sl_amount = None
                            rule3_drop = None
                            rule5_down = None
                            rule5_reversal = None
                            rule5_scalp = None
                            rule6_down = None
                            rule6_profit = None
                            rule7_up = None
                            try:
                                if bot_info and isinstance(bot_info, dict):
                                    rule_enabled = bool(bot_info.get('rule_1_enabled'))
                                    rule2_enabled = bool(bot_info.get('rule_2_enabled'))
                                    rule3_enabled = bool(bot_info.get('rule_3_enabled'))
                                    rule4_enabled = bool(bot_info.get('rule_4_enabled', 1))
                                    rule5_enabled = bool(bot_info.get('rule_5_enabled'))
                                    rule6_enabled = bool(bot_info.get('rule_6_enabled'))
                                    rule7_enabled = bool(bot_info.get('rule_7_enabled'))
                                    tp_amount = bot_info.get('take_profit_amount')
                                    sl_amount = bot_info.get('stop_loss_amount')
                                    rule3_drop = bot_info.get('rule_3_drop_count')
                                    rule5_down = bot_info.get('rule_5_down_minutes')
                                    rule5_reversal = bot_info.get('rule_5_reversal_amount')
                                    rule5_scalp = bot_info.get('rule_5_scalp_amount')
                                        rule6_down = bot_info.get('rule_6_down_minutes')
                                        rule6_profit = bot_info.get('rule_6_profit_amount')
                                            rule7_up = bot_info.get('rule_7_up_minutes')
                            except Exception:
                                rule_enabled = False
                                rule2_enabled = False
                                rule3_enabled = False
                                rule4_enabled = True
                                rule5_enabled = False
                                rule6_enabled = False
                                rule7_enabled = False
                                tp_amount = None
                                sl_amount = None
                                rule3_drop = None
                                rule5_down = None
                                rule5_reversal = None
                                rule5_scalp = None
                                rule6_down = None
                                rule6_profit = None
                                rule7_up = None

                            if rule_enabled:
                                # Rule #1 overrides sell logic: sell only on take-profit.
                                # Buys are still allowed so the bot can enter positions.
                                try:
                                    trader.on_signal_take_profit_mode(trend, price, ticker, tp_amount, auto=True, rule_2_enabled=rule2_enabled, stop_loss_amount=sl_amount, rule_3_enabled=rule3_enabled, rule_3_drop_count=rule3_drop, rule_4_enabled=rule4_enabled, rule_5_enabled=rule5_enabled, rule_5_down_minutes=rule5_down, rule_5_reversal_amount=rule5_reversal, rule_5_scalp_amount=rule5_scalp, rule_6_enabled=rule6_enabled, rule_6_down_minutes=rule6_down, rule_6_profit_amount=rule6_profit, rule_7_enabled=rule7_enabled, rule_7_up_minutes=rule7_up)
                                except Exception:
                                    # best-effort; do not break loop
                                    pass
                            else:
                                trader.on_signal(trend, price, ticker, auto=True, rule_2_enabled=rule2_enabled, stop_loss_amount=sl_amount, rule_3_enabled=rule3_enabled, rule_3_drop_count=rule3_drop, rule_4_enabled=rule4_enabled, rule_5_enabled=rule5_enabled, rule_5_down_minutes=rule5_down, rule_5_reversal_amount=rule5_reversal, rule_5_scalp_amount=rule5_scalp, rule_6_enabled=rule6_enabled, rule_6_down_minutes=rule6_down, rule_6_profit_amount=rule6_profit, rule_7_enabled=rule7_enabled, rule_7_up_minutes=rule7_up)
                    except Exception:
                        pass

                    workers_payload.append({
                        'hwnd': int(hwnd),
                        'status': st or {},
                        'screenshot_b64': image_b64,
                        'last_result': last,
                        'bot': bot_info,
                    })

                    # Persist summary info about this worker into bots table
                    try:
                        upsert_bot_from_last_result(hwnd, last or {})
                    except Exception:
                        pass

                    # Keep only the most recent screenshot per-worker to save disk
                    try:
                        if hasattr(svc, 'capture') and hasattr(svc.capture, 'clear_screenshots'):
                            svc.capture.clear_screenshots(keep_last_n=1)
                    except Exception:
                        pass
            except Exception:
                pass
            payload = {
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'workers': workers_payload,
                'trade_summary': trader.summary(),
            }

            await manager.broadcast(json.dumps(payload))
        except Exception as e:
            print("Broadcaster loop error:", e)
        await asyncio.sleep(1)


__all__ = ["broadcaster_loop"]
