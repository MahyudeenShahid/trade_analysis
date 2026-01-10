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
    from services.background_service import service
    from trading.simulator import trader
    from db.queries import upsert_bot_from_last_result
    
    while True:
        try:
            # collect single-service status (backwards-compatible)
            status = service.get_status()

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

                    # update trader auto signals if worker produced price/ticker
                    try:
                        trend = last.get('trend') or ''
                        price = last.get('price') or last.get('price_value') or None
                        ticker = last.get('ticker') or None
                        if price and ticker:
                            trader.on_signal(trend, price, ticker, auto=True)
                    except Exception:
                        pass

                    workers_payload.append({
                        'hwnd': int(hwnd),
                        'status': st or {},
                        'screenshot_b64': image_b64,
                        'last_result': last,
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

            # Also handle the legacy single-service screenshot/status
            image_b64 = None
            try:
                last = status.get('last_result') or {}
                img_path = last.get('image_path')
                if img_path and os.path.exists(img_path):
                    with open(img_path, 'rb') as f:
                        image_b64 = base64.b64encode(f.read()).decode('ascii')
                # update trader auto signals for legacy service
                try:
                    trend = last.get('trend') or ''
                    price = last.get('price') or last.get('price_value') or None
                    ticker = last.get('ticker') or None
                    if price and ticker:
                        trader.on_signal(trend, price, ticker, auto=True)
                except Exception:
                    pass
            except Exception:
                image_b64 = None

            payload = {
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'status': status,
                'workers': workers_payload,
                'trade_summary': trader.summary(),
                'screenshot_b64': image_b64,
            }

            # cleanup screenshots for legacy single service
            try:
                service.capture.clear_screenshots(keep_last_n=1)
            except Exception:
                pass

            await manager.broadcast(json.dumps(payload))
        except Exception as e:
            print("Broadcaster loop error:", e)
        await asyncio.sleep(1)


__all__ = ["broadcaster_loop"]
