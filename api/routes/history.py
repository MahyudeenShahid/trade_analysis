"""History, records, and upload management routes."""

import json
import os
import shutil
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, Depends
from fastapi.responses import FileResponse, JSONResponse

from api.dependencies import require_api_key
from config.settings import UPLOADS_DIR
from config.time_utils import (
    capture_filename_timestamp,
    get_time_mode,
)
from db.queries import get_latest_record, save_observation, query_history_page, query_records
from services.bot_registry import list_bots_by_hwnd
from trading.simulator import trader

from .history_helpers import (
    TRADE_SCREENSHOTS_DIR,
    _extract_trade_id,
    _safe_join,
    _find_trade_record,
    _build_history_where,
    _aggregate_overview_rows,
    _collect_trade_screenshots,
)

router = APIRouter(prefix="", tags=["history"])


@router.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    hwnd: Optional[int] = Form(None),
    name: Optional[str] = Form(None),
    ticker: Optional[str] = Form(None),
    price: Optional[str] = Form(None),
    trend: Optional[str] = Form(None),
    meta: Optional[str] = Form(None),
    _auth: bool = Depends(require_api_key),
):
    """
    Accept multipart/form-data and trigger trade automatically.

    Saves uploaded file and creates a database record, then triggers
    trading signals if ticker/price/trend are provided.
    """
    ts = datetime.utcnow().isoformat() + 'Z'
    filename = f"{capture_filename_timestamp()}_{uuid.uuid4().hex[:8]}_{os.path.basename(file.filename)}"
    dest = os.path.join(UPLOADS_DIR, filename)
    try:
        with open(dest, "wb") as out:
            shutil.copyfileobj(file.file, out)
    finally:
        try:
            file.file.close()
        except Exception:
            pass

    record = {
        "ts": ts,
        "image_path": dest,
        "name": name,
        "ticker": ticker,
        "price": price,
        "trend": trend,
        "meta": json.loads(meta) if meta else {},
    }

    # Persist in DB
    save_observation(record)

    # Trigger trade automatically for this ticker
    if price is not None and ticker:
        try:
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
            bot_list = []
            if hwnd is not None:
                try:
                    bot_list = list_bots_by_hwnd(int(hwnd))
                except Exception:
                    bot_list = []

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

                if rule_enabled:
                    try:
                        trader.on_signal_take_profit_mode(
                            trend, price, ticker, tp_amount, auto=True,
                            rule_2_enabled=rule2_enabled, stop_loss_amount=sl_amount,
                            rule_3_enabled=rule3_enabled, rule_3_drop_count=rule3_drop,
                            rule_4_enabled=rule4_enabled, rule_5_enabled=rule5_enabled,
                            rule_5_down_minutes=rule5_down, rule_5_reversal_amount=rule5_reversal,
                            rule_5_scalp_amount=rule5_scalp, rule_6_enabled=rule6_enabled,
                            rule_6_down_minutes=rule6_down, rule_6_profit_amount=rule6_profit,
                            rule_7_enabled=rule7_enabled, rule_7_up_minutes=rule7_up,
                            rule_8_enabled=rule8_enabled, rule_8_buy_offset=rule8_buy,
                            rule_8_sell_offset=rule8_sell, rule_9_enabled=rule9_enabled,
                            rule_9_amount=rule9_amount, rule_9_flips=rule9_flips,
                            rule_9_window_minutes=rule9_window, bot_id=bot_id, bot_name=bot_name,
                        )
                    except Exception:
                        pass
                else:
                    trader.on_signal(
                        trend, price, ticker, auto=True,
                        rule_2_enabled=rule2_enabled, stop_loss_amount=sl_amount,
                        rule_3_enabled=rule3_enabled, rule_3_drop_count=rule3_drop,
                        rule_4_enabled=rule4_enabled, rule_5_enabled=rule5_enabled,
                        rule_5_down_minutes=rule5_down, rule_5_reversal_amount=rule5_reversal,
                        rule_5_scalp_amount=rule5_scalp, rule_6_enabled=rule6_enabled,
                        rule_6_down_minutes=rule6_down, rule_6_profit_amount=rule6_profit,
                        rule_7_enabled=rule7_enabled, rule_7_up_minutes=rule7_up,
                        rule_8_enabled=rule8_enabled, rule_8_buy_offset=rule8_buy,
                        rule_8_sell_offset=rule8_sell, rule_9_enabled=rule9_enabled,
                        rule_9_amount=rule9_amount, rule_9_flips=rule9_flips,
                        rule_9_window_minutes=rule9_window, bot_id=bot_id, bot_name=bot_name,
                    )
        except Exception:
            pass

    return {"id": uuid.uuid4().hex, "image_url": f"/uploads/{filename}", "ts": ts}


@router.get("/latest")
def api_latest():
    """Get the most recent record from the database."""
    rec = get_latest_record()
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "no records"})
    if rec.get("image_path"):
        rec["image_url"] = "/uploads/" + os.path.basename(rec["image_path"])
    return rec


@router.get("/history")
def api_history(
    days: int = 7,
    ticker: Optional[str] = None,
    bot_id: Optional[str] = None,
    bot_name: Optional[str] = None,
    selected_day: Optional[str] = None,
    start_ts: Optional[str] = None,
    end_ts: Optional[str] = None,
    trend: Optional[str] = None,
    win_reason: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    screenshots: bool = False,
):
    """Get historical records with optional filtering."""
    where, params = _build_history_where(
        days=days,
        ticker=ticker,
        bot_id=bot_id,
        bot_name=bot_name,
        selected_day=selected_day,
        start_ts=start_ts,
        end_ts=end_ts,
        trend=trend,
        win_reason=win_reason,
    )

    if limit is None:
        count_rows = query_records(f"SELECT COUNT(*) as count FROM records WHERE {where}", tuple(params))
        total_count = count_rows[0]['count'] if count_rows else 0
        rows = query_records(f"SELECT * FROM records WHERE {where} ORDER BY ts DESC", tuple(params))
    else:
        total_count, rows = query_history_page(where, tuple(params), int(limit), int(offset))
    for r in rows:
        if r.get("image_path"):
            r["image_url"] = "/uploads/" + os.path.basename(r["image_path"])
        try:
            r["trade_id"] = _extract_trade_id(r)
            if screenshots:
                r["screenshots"] = _collect_trade_screenshots(r)
            else:
                r["screenshots"] = []
        except Exception as e:
            print(f"[History API] Error processing record: {e}")
            r["trade_id"] = _extract_trade_id(r)
            r["screenshots"] = []
    return JSONResponse(content=rows, headers={"X-Total-Count": str(total_count)})


@router.get("/history_overview")
def api_history_overview(
    days: int = 7,
    ticker: Optional[str] = None,
    bot_id: Optional[str] = None,
    bot_name: Optional[str] = None,
    start_ts: Optional[str] = None,
    end_ts: Optional[str] = None,
    trend: Optional[str] = None,
    win_reason: Optional[str] = None,
    selected_day: Optional[str] = None,
    profit_filter: str = "all",
):
    """Return day-bucket counts plus full aggregate totals for the active filters."""
    where, params = _build_history_where(
        days=days,
        ticker=ticker,
        bot_id=bot_id,
        bot_name=bot_name,
        selected_day=None,
        start_ts=start_ts,
        end_ts=end_ts,
        trend=trend,
        win_reason=win_reason,
    )

    pnl_expr = (
        "CASE WHEN buy_price IS NOT NULL AND sell_price IS NOT NULL "
        "THEN CAST(sell_price AS REAL) - CAST(buy_price AS REAL) ELSE NULL END"
    )
    base_rows = query_records(
        f"SELECT ts, {pnl_expr} AS pnl FROM records WHERE {where} ORDER BY ts ASC",
        tuple(params),
    )
    daily_rows, totals = _aggregate_overview_rows(
        base_rows,
        selected_day=selected_day,
        profit_filter=profit_filter,
    )

    return {
        "daily": daily_rows,
        "totals": totals,
        "selected_day": selected_day,
        "profit_filter": profit_filter,
        "time_mode": get_time_mode(),
    }


@router.get("/uploads/{filename:path}")
def api_uploads(filename: str):
    """Serve uploaded files."""
    path = _safe_join(UPLOADS_DIR, filename)
    if not path or not os.path.exists(path):
        return JSONResponse(status_code=404, content={"detail": "file not found"})
    return FileResponse(path)


@router.get("/screenshots")
def api_trade_screenshots_for_trade(trade_id: Optional[str] = None):
    """Return the list of screenshot objects for a specific trade."""
    if not trade_id:
        return JSONResponse(status_code=400, content={"detail": "trade_id required"})
    record = _find_trade_record(trade_id) or {"trade_id": trade_id, "ts": trade_id}
    if not record.get("trade_id"):
        record["trade_id"] = trade_id
    shots = _collect_trade_screenshots(record)
    return {"trade_id": trade_id, "screenshots": shots}


@router.get("/trade_screenshots/{filename:path}")
def api_trade_screenshots(filename: str):
    """Serve trade screenshots."""
    path = _safe_join(TRADE_SCREENSHOTS_DIR, filename)
    if not path or not os.path.exists(path):
        return JSONResponse(status_code=404, content={"detail": "file not found"})
    return FileResponse(path)


__all__ = ["router"]
