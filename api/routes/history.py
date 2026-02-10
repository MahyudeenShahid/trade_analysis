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
from services.bot_registry import list_bots_by_hwnd
from trading.simulator import trader

router = APIRouter(prefix="", tags=["history"])

TRADE_SCREENSHOTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "trade_screenshots")
)


def _parse_iso(ts: Optional[str]):
    if not ts:
        return None
    try:
        raw = str(ts)
        if raw.endswith("Z"):
            raw = raw[:-1]
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _extract_meta(record: dict) -> dict:
    meta = record.get("meta") if isinstance(record, dict) else None
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta


def _extract_trade_id(record: dict) -> Optional[str]:
    meta = _extract_meta(record)
    trade_id = record.get("trade_id") or meta.get("trade_id")
    if trade_id:
        return str(trade_id)
    for key in ("buy_time", "entry_time", "ts", "time"):
        if meta.get(key):
            return str(meta.get(key))
    for key in ("buy_time", "ts", "time"):
        if record.get(key):
            return str(record.get(key))
    return None


def _trade_day(record: dict) -> Optional[str]:
    trade_id = _extract_trade_id(record)
    dt = _parse_iso(trade_id)
    if not dt:
        dt = _parse_iso(record.get("ts"))
    if not dt:
        return None
    return dt.strftime("%Y%m%d")


def _safe_join(base_dir: str, rel_path: str) -> Optional[str]:
    base = os.path.abspath(base_dir)
    target = os.path.abspath(os.path.join(base, rel_path))
    if not target.startswith(base):
        return None
    return target


def _collect_trade_screenshots(record: dict) -> List[str]:
    meta = _extract_meta(record)
    candidates = []
    trade_id = _extract_trade_id(record)
    if trade_id:
        candidates.append(str(trade_id))
    for key in ("ts", "buy_time", "time"):
        if record.get(key):
            candidates.append(str(record.get(key)))
    for key in ("ts", "buy_time", "time", "entry_time"):
        if meta.get(key):
            candidates.append(str(meta.get(key)))

    candidates = [c.replace(":", "-") for c in candidates if c]
    if not candidates:
        return []

    day = _trade_day(record)

    search_roots = []
    if day:
        search_roots.append(os.path.join(TRADE_SCREENSHOTS_DIR, day))
    search_roots.append(TRADE_SCREENSHOTS_DIR)

    target_dir = None
    for root in search_roots:
        if not os.path.exists(root):
            continue
        for dirpath, dirnames, _ in os.walk(root):
            base = os.path.basename(dirpath)
            if not base.startswith("trade_"):
                continue
            for cand in candidates:
                if base == f"trade_{cand}":
                    target_dir = dirpath
                    break
            if target_dir:
                break
        if target_dir:
            break

    if not target_dir:
        return []

    images = []
    for dirpath, _, filenames in os.walk(target_dir):
        for fname in sorted(filenames):
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".png", ".jpg", ".jpeg"):
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, TRADE_SCREENSHOTS_DIR).replace(os.sep, "/")
            images.append(f"/trade_screenshots/{rel}")
    return images


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
                        trader.on_signal_take_profit_mode(trend, price, ticker, tp_amount, auto=True, rule_2_enabled=rule2_enabled, stop_loss_amount=sl_amount, rule_3_enabled=rule3_enabled, rule_3_drop_count=rule3_drop, rule_4_enabled=rule4_enabled, rule_5_enabled=rule5_enabled, rule_5_down_minutes=rule5_down, rule_5_reversal_amount=rule5_reversal, rule_5_scalp_amount=rule5_scalp, rule_6_enabled=rule6_enabled, rule_6_down_minutes=rule6_down, rule_6_profit_amount=rule6_profit, rule_7_enabled=rule7_enabled, rule_7_up_minutes=rule7_up, rule_8_enabled=rule8_enabled, rule_8_buy_offset=rule8_buy, rule_8_sell_offset=rule8_sell, rule_9_enabled=rule9_enabled, rule_9_amount=rule9_amount, rule_9_flips=rule9_flips, rule_9_window_minutes=rule9_window, bot_id=bot_id, bot_name=bot_name)
                    except Exception:
                        pass
                else:
                    trader.on_signal(trend, price, ticker, auto=True, rule_2_enabled=rule2_enabled, stop_loss_amount=sl_amount, rule_3_enabled=rule3_enabled, rule_3_drop_count=rule3_drop, rule_4_enabled=rule4_enabled, rule_5_enabled=rule5_enabled, rule_5_down_minutes=rule5_down, rule_5_reversal_amount=rule5_reversal, rule_5_scalp_amount=rule5_scalp, rule_6_enabled=rule6_enabled, rule_6_down_minutes=rule6_down, rule_6_profit_amount=rule6_profit, rule_7_enabled=rule7_enabled, rule_7_up_minutes=rule7_up, rule_8_enabled=rule8_enabled, rule_8_buy_offset=rule8_buy, rule_8_sell_offset=rule8_sell, rule_9_enabled=rule9_enabled, rule_9_amount=rule9_amount, rule_9_flips=rule9_flips, rule_9_window_minutes=rule9_window, bot_id=bot_id, bot_name=bot_name)
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
    bot_id: Optional[str] = None,
    bot_name: Optional[str] = None,
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
    if bot_id:
        clauses.append("bot_id = ?")
        params.append(bot_id)
    if bot_name:
        clauses.append("bot_name LIKE ?")
        params.append(f"%{bot_name}%")

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
        try:
            r["trade_id"] = _extract_trade_id(r)
            r["screenshots"] = _collect_trade_screenshots(r)
        except Exception:
            r["trade_id"] = _extract_trade_id(r)
            r["screenshots"] = []
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


@router.get("/trade_screenshots/{filename:path}")
def api_trade_screenshots(filename: str):
    path = _safe_join(TRADE_SCREENSHOTS_DIR, filename)
    if not path or not os.path.exists(path):
        return JSONResponse(status_code=404, content={"detail": "file not found"})
    return FileResponse(path)


__all__ = ["router"]
