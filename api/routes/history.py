"""History, records, and upload management routes."""

import json
import os
import shutil
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from api.dependencies import require_api_key
from config.settings import UPLOADS_DIR
from config.time_utils import (
    capture_filename_timestamp,
    day_bounds_utc,
    get_time_mode,
    history_day_key,
    recent_days_start_ts,
    screenshot_day_key,
)
from db.queries import query_records, get_latest_record, save_observation, query_history_page
from services.bot_registry import list_bots_by_hwnd
from trading.simulator import trader

router = APIRouter(prefix="", tags=["history"])

TRADE_SCREENSHOTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "trade_screenshots")
)

# Cache: trade_id candidate string → absolute directory path (or None).
# Populated lazily; cleared when the process restarts.
_trade_dir_cache: dict = {}


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
    day = screenshot_day_key(trade_id)
    if day:
        return day
    return screenshot_day_key(record.get("ts"))


def _safe_join(base_dir: str, rel_path: str) -> Optional[str]:
    base = os.path.abspath(base_dir)
    target = os.path.abspath(os.path.join(base, rel_path))
    if not target.startswith(base):
        return None
    return target


def _find_trade_record(trade_id: Optional[str]) -> Optional[dict]:
    if not trade_id:
        return None

    seen = set()
    candidates = [str(trade_id)]
    parsed = _parse_iso(trade_id)
    if parsed:
        candidates.extend([
            parsed.isoformat(),
            parsed.isoformat() + 'Z',
        ])

    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            rows = query_records(
                """
                SELECT * FROM records
                WHERE ts = ? OR buy_time = ? OR sell_time = ?
                ORDER BY ts DESC
                LIMIT 1
                """,
                (candidate, candidate, candidate),
            )
            if rows:
                return rows[0]
        except Exception:
            pass

    return None


def _build_history_where(
    days: int = 7,
    ticker: Optional[str] = None,
    bot_id: Optional[str] = None,
    bot_name: Optional[str] = None,
    selected_day: Optional[str] = None,
    start_ts: Optional[str] = None,
    end_ts: Optional[str] = None,
    trend: Optional[str] = None,
    win_reason: Optional[str] = None,
):
    params: List[object] = []
    clauses: List[str] = []

    if selected_day:
        try:
            start_ts, end_ts = day_bounds_utc(selected_day)
        except Exception:
            start_ts = start_ts or None
            end_ts = end_ts or None

    if start_ts:
        clauses.append("ts >= ?")
        params.append(start_ts)
    else:
        clauses.append("ts >= ?")
        params.append(recent_days_start_ts(days))

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
    if win_reason:
        clauses.append("win_reason = ?")
        params.append(win_reason)

    where = " AND ".join(clauses) if clauses else "1=1"
    return where, tuple(params)


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _round_overview_bucket(bucket: dict) -> dict:
    return {
        **bucket,
        "total_profit": round(float(bucket.get("total_profit") or 0), 2),
        "total_loss": round(float(bucket.get("total_loss") or 0), 2),
        "net": round(float(bucket.get("net") or 0), 2),
    }


def _empty_overview_totals() -> dict:
    return {
        "count": 0,
        "wins": 0,
        "losses": 0,
        "total_profit": 0.0,
        "total_loss": 0.0,
        "net": 0.0,
    }


def _aggregate_overview_rows(rows: List[dict], selected_day: Optional[str] = None, profit_filter: str = "all"):
    daily_map = {}
    totals = _empty_overview_totals()

    for row in rows:
        day_key = history_day_key(row.get("ts"))
        pnl = _to_float(row.get("pnl"))

        if day_key:
            bucket = daily_map.setdefault(day_key, {
                "day_key": day_key,
                "count": 0,
                "wins": 0,
                "losses": 0,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "net": 0.0,
            })
            bucket["count"] += 1
            if pnl is not None:
                bucket["net"] += pnl
                if pnl > 0:
                    bucket["wins"] += 1
                    bucket["total_profit"] += pnl
                elif pnl < 0:
                    bucket["losses"] += 1
                    bucket["total_loss"] += abs(pnl)

        include = True
        if selected_day and day_key != selected_day:
            include = False
        if include and profit_filter == "profit":
            include = pnl is not None and pnl > 0
        elif include and profit_filter == "loss":
            include = pnl is not None and pnl < 0

        if not include:
            continue

        totals["count"] += 1
        if pnl is not None:
            totals["net"] += pnl
            if pnl > 0:
                totals["wins"] += 1
                totals["total_profit"] += pnl
            elif pnl < 0:
                totals["losses"] += 1
                totals["total_loss"] += abs(pnl)

    daily_rows = [_round_overview_bucket(bucket) for _, bucket in sorted(daily_map.items())]
    return daily_rows, _round_overview_bucket(totals)


def _collect_trade_screenshots(record: dict) -> List[dict]:
    """Collect trade screenshots with metadata (time, price)."""
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

    # Check cache first — avoids os.walk on repeat calls for the same trade
    cache_key = candidates[0]
    if cache_key in _trade_dir_cache:
        target_dir = _trade_dir_cache[cache_key]
    else:
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
        _trade_dir_cache[cache_key] = target_dir  # cache miss or None

    if not target_dir:
        return []
    

    # Try to load metadata.json if it exists
    metadata_file = os.path.join(target_dir, 'metadata.json')
    saved_metadata = None
    if os.path.exists(metadata_file):
        try:
            with open(metadata_file, 'r') as f:
                saved_metadata = json.load(f)
        except Exception:
            pass
    
    # Get buy_price from record as fallback
    buy_price = record.get('buy_price')
    if buy_price is None:
        buy_price = meta.get('buy_price') or meta.get('entry_price')
    
    # Use metadata buy_price if available
    if saved_metadata and saved_metadata.get('buy_price'):
        buy_price = saved_metadata.get('buy_price')

    last_known_price = buy_price

    # Collect screenshots with metadata
    screenshots = []
    for dirpath, _, filenames in os.walk(target_dir):
        for fname in sorted(filenames):
            if fname == 'metadata.json':
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".png", ".jpg", ".jpeg"):
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, TRADE_SCREENSHOTS_DIR).replace(os.sep, "/")
            
            # Try to extract time from filename
            time_str = None
            screenshot_price = last_known_price
            try:
                # Filename format: capture_YYYYMMDD_HHMMSS_mmm.jpg
                if 'capture_' in fname:
                    parts = fname.split('_')
                    if len(parts) >= 3:
                        date_part = parts[1]
                        time_part = parts[2].split('.')[0]
                        time_str = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}T{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
                
                # Try to find this screenshot in saved metadata
                if saved_metadata and saved_metadata.get('screenshots'):
                    for sm in saved_metadata['screenshots']:
                        if isinstance(sm, dict) and sm.get('path'):
                            if os.path.basename(sm['path']) == fname:
                                if sm.get('price') is not None:
                                    screenshot_price = sm['price']
                                    last_known_price = screenshot_price
                                if sm.get('time') and not time_str:
                                    time_str = sm['time']
                                break
            except Exception:
                pass
            
            screenshots.append({
                'url': f"/trade_screenshots/{rel}",
                'time': time_str,
                'price': screenshot_price
            })
    
    return screenshots


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
    selected_day: Optional[str] = None,
    start_ts: Optional[str] = None,
    end_ts: Optional[str] = None,
    trend: Optional[str] = None,
    win_reason: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    screenshots: bool = False,
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

    # COUNT + paginated SELECT in one connection
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
    """Return 7-day day-bucket counts plus full aggregate totals for the active filters."""
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


@router.get("/screenshots")
def api_trade_screenshots_for_trade(trade_id: Optional[str] = None):
    """
    Return the list of screenshot objects for a specific trade.
    Accepts trade_id (ISO timestamp) and finds the matching trade folder.
    Used by the frontend to lazy-load screenshots for WS-delivered trade records.
    """
    if not trade_id:
        return JSONResponse(status_code=400, content={"detail": "trade_id required"})
    record = _find_trade_record(trade_id) or {"trade_id": trade_id, "ts": trade_id}
    if not record.get("trade_id"):
        record["trade_id"] = trade_id
    shots = _collect_trade_screenshots(record)
    return {"trade_id": trade_id, "screenshots": shots}


@router.get("/trade_screenshots/{filename:path}")
def api_trade_screenshots(filename: str):
    path = _safe_join(TRADE_SCREENSHOTS_DIR, filename)
    if not path or not os.path.exists(path):
        return JSONResponse(status_code=404, content={"detail": "file not found"})
    return FileResponse(path)


__all__ = ["router"]
