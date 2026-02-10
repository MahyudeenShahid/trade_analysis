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
    from services.bot_registry import list_bots_by_hwnd
    from trading.simulator import trader
    
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

                    # pull session bot settings for this hwnd
                    bot_info = None
                    bot_list = []
                    try:
                        bot_list = list_bots_by_hwnd(int(hwnd))
                        bot_info = bot_list[0] if bot_list else None
                    except Exception:
                        bot_info = None
                        bot_list = []

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
                            rule8_enabled = False
                            rule9_enabled = False
                            tp_amount = None
                            sl_amount = None
                            rule3_drop = None
                            rule5_down = None
                            rule5_reversal = None
                            rule5_scalp = None
                            rule6_down = None
                            rule6_profit = None
                            rule7_up = None
                            rule8_buy = None
                            rule8_sell = None
                            rule9_amount = None
                            rule9_flips = None
                            rule9_window = None
                            for bot in bot_list:
                                try:
                                    rule_enabled = bool(bot.get('rule_1_enabled'))
                                    rule2_enabled = bool(bot.get('rule_2_enabled'))
                                    rule3_enabled = bool(bot.get('rule_3_enabled'))
                                    rule4_enabled = bool(bot.get('rule_4_enabled', 1))
                                    rule5_enabled = bool(bot.get('rule_5_enabled'))
                                    rule6_enabled = bool(bot.get('rule_6_enabled'))
                                    rule7_enabled = bool(bot.get('rule_7_enabled'))
                                    rule8_enabled = bool(bot.get('rule_8_enabled'))
                                    rule9_enabled = bool(bot.get('rule_9_enabled'))
                                    tp_amount = bot.get('take_profit_amount')
                                    sl_amount = bot.get('stop_loss_amount')
                                    rule3_drop = bot.get('rule_3_drop_count')
                                    rule5_down = bot.get('rule_5_down_minutes')
                                    rule5_reversal = bot.get('rule_5_reversal_amount')
                                    rule5_scalp = bot.get('rule_5_scalp_amount')
                                    rule6_down = bot.get('rule_6_down_minutes')
                                    rule6_profit = bot.get('rule_6_profit_amount')
                                    rule7_up = bot.get('rule_7_up_minutes')
                                    rule8_buy = bot.get('rule_8_buy_offset')
                                    rule8_sell = bot.get('rule_8_sell_offset')
                                    rule9_amount = bot.get('rule_9_amount')
                                    rule9_flips = bot.get('rule_9_flips')
                                    rule9_window = bot.get('rule_9_window_minutes')
                                    bot_id = bot.get('bot_id') or bot.get('id')
                                    bot_name = bot.get('name')
                                except Exception:
                                    continue

                                # Always call on_signal - Rule 1 now works alongside default logic
                                try:
                                    before_count = len(trader.trade_history)
                                    trader.on_signal(trend, price, ticker, auto=True, rule_1_enabled=rule_enabled, take_profit_amount=tp_amount, rule_2_enabled=rule2_enabled, stop_loss_amount=sl_amount, rule_3_enabled=rule3_enabled, rule_3_drop_count=rule3_drop, rule_4_enabled=rule4_enabled, rule_5_enabled=rule5_enabled, rule_5_down_minutes=rule5_down, rule_5_reversal_amount=rule5_reversal, rule_5_scalp_amount=rule5_scalp, rule_6_enabled=rule6_enabled, rule_6_down_minutes=rule6_down, rule_6_profit_amount=rule6_profit, rule_7_enabled=rule7_enabled, rule_7_up_minutes=rule7_up, rule_8_enabled=rule8_enabled, rule_8_buy_offset=rule8_buy, rule_8_sell_offset=rule8_sell, rule_9_enabled=rule9_enabled, rule_9_amount=rule9_amount, rule_9_flips=rule9_flips, rule_9_window_minutes=rule9_window, bot_id=bot_id, bot_name=bot_name)
                                    after_count = len(trader.trade_history)
                                    if after_count > before_count and hasattr(svc, 'handle_trade_event'):
                                        try:
                                            for ev in trader.trade_history[before_count:after_count]:
                                                if bot_id and ev.get('bot_id') != bot_id:
                                                    continue
                                                svc.handle_trade_event(ev.get('direction'), ev.get('ticker'), ev.get('trade_id') or ev.get('ts'), ev.get('price'))
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
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
                    })

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
