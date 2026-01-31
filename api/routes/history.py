"""History, records, and upload management routes."""

import json
import os
import shutil
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from api.dependencies import require_api_key
from config.settings import UPLOADS_DIR
from db.queries import query_records, get_latest_record, save_observation
from trading.simulator import trader

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
    
    Returns:
        dict: Upload result with image URL and timestamp
    """
    ts = datetime.utcnow().isoformat() + 'Z'
    filename = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}_{os.path.basename(file.filename)}"
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

    # Trigger trade automatically for this ticker (Rule #1/2 override when hwnd is known)
    if price is not None and ticker:
        try:
            rule_enabled = False
            rule2_enabled = False
            rule3_enabled = False
            tp_amount = None
            sl_amount = None
            rule3_drop = None
            if hwnd is not None:
                try:
                    from db.queries import get_bot_db_entry
                    bot = get_bot_db_entry(int(hwnd))
                    if bot and isinstance(bot, dict):
                        rule_enabled = bool(bot.get('rule_1_enabled'))
                        rule2_enabled = bool(bot.get('rule_2_enabled'))
                        rule3_enabled = bool(bot.get('rule_3_enabled'))
                        tp_amount = bot.get('take_profit_amount')
                        sl_amount = bot.get('stop_loss_amount')
                        rule3_drop = bot.get('rule_3_drop_count')
                except Exception:
                    rule_enabled = False
                    rule2_enabled = False
                    rule3_enabled = False
                    tp_amount = None
                    sl_amount = None
                    rule3_drop = None

            if rule_enabled:
                try:
                    # Rule #1: sell only on take-profit; buys still allowed.
                    trader.on_signal_take_profit_mode(trend, price, ticker, tp_amount, auto=True, rule_2_enabled=rule2_enabled, stop_loss_amount=sl_amount, rule_3_enabled=rule3_enabled, rule_3_drop_count=rule3_drop)
                except Exception:
                    pass
            else:
                trader.on_signal(trend, price, ticker, auto=True, rule_2_enabled=rule2_enabled, stop_loss_amount=sl_amount, rule_3_enabled=rule3_enabled, rule_3_drop_count=rule3_drop)
        except Exception:
            # best-effort; ingest should still succeed
            pass

    return {"id": uuid.uuid4().hex, "image_url": f"/uploads/{filename}", "ts": ts}


@router.get("/latest")
def api_latest():
    """
    Get the most recent record from the database.
    
    Returns:
        dict: Latest record with image_url if available
    """
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
    start_ts: Optional[str] = None,
    end_ts: Optional[str] = None,
    trend: Optional[str] = None,
    limit: Optional[int] = None,
):
    """
    Get historical records with optional filtering.
    
    Args:
        days: Number of days to look back (default 7)
        ticker: Filter by ticker symbol
        start_ts: Filter by start timestamp
        end_ts: Filter by end timestamp
        trend: Filter by trend/direction
        limit: Maximum number of records to return
        
    Returns:
        list: Filtered records with image URLs
    """
    params: List[object] = []
    clauses: List[str] = []

    if start_ts:
        clauses.append("ts >= ?")
        params.append(start_ts)
    else:
        cutoff = datetime.utcnow() - timedelta(days=days)
        clauses.append("ts >= ?")
        params.append(cutoff.isoformat() + 'Z')

    if end_ts:
        clauses.append("ts <= ?")
        params.append(end_ts)

    if ticker:
        clauses.append("ticker = ?")
        params.append(ticker)

    if trend:
        clauses.append("trend = ?")
        params.append(trend)

    where = " AND ".join(clauses) if clauses else "1=1"
    # If `limit` is provided, apply LIMIT clause. Otherwise return all
    # matching records (e.g. all trades from the last `days`). This
    # ensures the API can return all trades for the last 7 days when
    # the caller doesn't specify a limit.
    if limit is None:
        sql = f"SELECT * FROM records WHERE {where} ORDER BY ts DESC"
    else:
        sql = f"SELECT * FROM records WHERE {where} ORDER BY ts DESC LIMIT ?"
        params.append(int(limit))

    rows = query_records(sql, tuple(params))
    for r in rows:
        if r.get("image_path"):
            r["image_url"] = "/uploads/" + os.path.basename(r["image_path"])
    return rows


@router.get("/uploads/{filename:path}")
def api_uploads(filename: str):
    """
    Serve uploaded files.
    
    Args:
        filename: File name to retrieve
        
    Returns:
        FileResponse: The requested file
    """
    path = os.path.join(UPLOADS_DIR, filename)
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"detail": "file not found"})
    return FileResponse(path)


__all__ = ["router"]
