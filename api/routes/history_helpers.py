"""Helpers for filtering, aggregating, and collecting history details/screenshots."""

import json
import os
from datetime import datetime
from typing import List, Optional

from config.time_utils import (
    capture_filename_timestamp,
    day_bounds_utc,
    get_time_mode,
    history_day_key,
    recent_days_start_ts,
    screenshot_day_key,
)
from db.queries import query_records

TRADE_SCREENSHOTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "trade_screenshots")
)

# Cache: trade_id candidate string → absolute directory path (or None).
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

    # Check cache first
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
        _trade_dir_cache[cache_key] = target_dir

    if not target_dir or not os.path.exists(target_dir):
        return []

    found = []
    for f in os.listdir(target_dir):
        if not f.lower().endswith(('.png', '.jpg', '.jpeg')):
            continue
        full_path = os.path.join(target_dir, f)
        ts_val = capture_filename_timestamp(f) or record.get("ts")
        # Estimate price from screenshot filename or record
        price_val = record.get("price")
        if "buy" in f.lower():
            price_val = record.get("buy_price") or record.get("price")
        elif "sell" in f.lower():
            price_val = record.get("sell_price") or record.get("price")

        found.append({
            "filename": f,
            "path": os.path.relpath(full_path, TRADE_SCREENSHOTS_DIR).replace(os.sep, '/'),
            "ts": ts_val,
            "price": price_val,
            "type": "buy" if "buy" in f.lower() else "sell" if "sell" in f.lower() else "unknown",
        })
    # Sort chronological
    found.sort(key=lambda x: str(x.get("ts") or ""))
    return found
