"""Order book history capture + query helpers."""

import asyncio
import json
import math
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config.time_utils import parse_timestamp
from db.connection import DB_PATH, DB_LOCK
from db.queries import get_app_settings, set_app_setting
from ibkr.client import is_connected
from ibkr.order_book import get_all_snapshots

DEFAULT_HISTORY_ENABLED = True
DEFAULT_INTERVAL_MS = 1000
DEFAULT_LEVELS = 5
DEFAULT_RETENTION_DAYS = 30
ALLOWED_INTERVALS_MS = (200, 500, 1000, 2000, 5000)
ALLOWED_LEVELS = (5, 10, 20)
MAX_RETENTION_DAYS = 365


def _format_utc_z(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat() + "Z"


def _normalize_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def _normalize_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalize_interval(value: Any) -> int:
    interval = _normalize_int(value, DEFAULT_INTERVAL_MS)
    if interval in ALLOWED_INTERVALS_MS:
        return interval
    return min(ALLOWED_INTERVALS_MS, key=lambda v: abs(v - interval))


def _normalize_levels(value: Any) -> int:
    levels = _normalize_int(value, DEFAULT_LEVELS)
    if levels in ALLOWED_LEVELS:
        return levels
    return min(ALLOWED_LEVELS, key=lambda v: abs(v - levels))


def _normalize_retention(value: Any) -> int:
    days = _normalize_int(value, DEFAULT_RETENTION_DAYS)
    if days < 1:
        return DEFAULT_RETENTION_DAYS
    return min(days, MAX_RETENTION_DAYS)


def get_history_settings() -> Dict[str, Any]:
    cfg = get_app_settings()
    enabled = _normalize_bool(cfg.get("order_book_history_enabled"), DEFAULT_HISTORY_ENABLED)
    interval_ms = _normalize_interval(cfg.get("order_book_history_interval_ms"))
    levels = _normalize_levels(cfg.get("order_book_history_levels"))
    retention_days = _normalize_retention(cfg.get("order_book_history_retention_days"))

    return {
        "enabled": enabled,
        "interval_ms": interval_ms,
        "levels": levels,
        "retention_days": retention_days,
        "available_intervals_ms": list(ALLOWED_INTERVALS_MS),
        "available_levels": list(ALLOWED_LEVELS),
    }


def update_history_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return get_history_settings()

    if "enabled" in payload:
        enabled = _normalize_bool(payload.get("enabled"), DEFAULT_HISTORY_ENABLED)
        set_app_setting("order_book_history_enabled", "1" if enabled else "0")

    if "interval_ms" in payload:
        interval_ms = _normalize_interval(payload.get("interval_ms"))
        set_app_setting("order_book_history_interval_ms", str(interval_ms))

    if "levels" in payload:
        levels = _normalize_levels(payload.get("levels"))
        set_app_setting("order_book_history_levels", str(levels))

    if "retention_days" in payload:
        retention_days = _normalize_retention(payload.get("retention_days"))
        set_app_setting("order_book_history_retention_days", str(retention_days))

    return get_history_settings()


def _resolve_range(start: Optional[str], end: Optional[str]) -> tuple[str, str]:
    end_dt = parse_timestamp(end) or datetime.now(timezone.utc)
    start_dt = parse_timestamp(start) or (end_dt - timedelta(hours=1))
    return _format_utc_z(start_dt), _format_utc_z(end_dt)


def prune_order_book_history(retention_days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))
    cutoff_ts = _format_utc_z(cutoff)
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM order_book_history WHERE ts < ?", (cutoff_ts,))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
    return deleted or 0


def save_order_book_history_rows(rows: List[tuple]) -> int:
    if not rows:
        return 0
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.executemany(
            "INSERT INTO order_book_history (ts, ticker, source, levels, bids, asks) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        conn.close()
    return len(rows)


def get_order_book_history(
    ticker: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    max_points: int = 1000,
) -> Dict[str, Any]:
    ticker_u = str(ticker or "").strip().upper()
    start_ts, end_ts = _resolve_range(start, end)
    max_points = max(1, min(int(max_points or 1000), 10000))

    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) as count FROM order_book_history WHERE ticker = ? AND ts BETWEEN ? AND ?",
            (ticker_u, start_ts, end_ts),
        )
        total = int(cur.fetchone()["count"])

        step = 1
        if total > max_points:
            step = max(1, int(math.ceil(total / max_points)))

        if step > 1:
            cur.execute(
                """
                SELECT ts, source, levels, bids, asks
                FROM order_book_history
                WHERE ticker = ? AND ts BETWEEN ? AND ? AND (id % ?) = 0
                ORDER BY ts ASC
                """,
                (ticker_u, start_ts, end_ts, step),
            )
        else:
            cur.execute(
                """
                SELECT ts, source, levels, bids, asks
                FROM order_book_history
                WHERE ticker = ? AND ts BETWEEN ? AND ?
                ORDER BY ts ASC
                """,
                (ticker_u, start_ts, end_ts),
            )

        rows = cur.fetchall()
        conn.close()

    points = []
    for row in rows:
        try:
            bids = json.loads(row["bids"]) if row["bids"] else []
        except Exception:
            bids = []
        try:
            asks = json.loads(row["asks"]) if row["asks"] else []
        except Exception:
            asks = []
        points.append(
            {
                "ts": row["ts"],
                "source": row["source"],
                "levels": row["levels"],
                "bids": bids,
                "asks": asks,
            }
        )

    return {
        "ticker": ticker_u,
        "start": start_ts,
        "end": end_ts,
        "total": total,
        "sampled": step > 1,
        "step": step,
        "points": points,
    }


async def order_book_history_loop() -> None:
    """Background loop: persist depth snapshots at configured intervals."""
    last_prune = 0.0
    last_settings_check = 0.0
    settings_cache: Optional[Dict[str, Any]] = None

    while True:
        try:
            now = time.time()
            if settings_cache is None or (now - last_settings_check) > 2.0:
                settings_cache = get_history_settings()
                last_settings_check = now

            enabled = bool(settings_cache.get("enabled")) if settings_cache else False
            interval_ms = int(settings_cache.get("interval_ms", DEFAULT_INTERVAL_MS)) if settings_cache else DEFAULT_INTERVAL_MS
            levels = int(settings_cache.get("levels", DEFAULT_LEVELS)) if settings_cache else DEFAULT_LEVELS
            retention_days = int(settings_cache.get("retention_days", DEFAULT_RETENTION_DAYS)) if settings_cache else DEFAULT_RETENTION_DAYS

            if not enabled or not is_connected():
                await asyncio.sleep(1.0)
                continue

            snapshots = get_all_snapshots()
            if snapshots:
                now_ts = _format_utc_z(datetime.now(timezone.utc))
                rows = []
                for ticker, snap in snapshots.items():
                    if not isinstance(snap, dict):
                        continue
                    bids = (snap.get("bids") or [])[:levels]
                    asks = (snap.get("asks") or [])[:levels]
                    if not bids and not asks:
                        continue
                    source = snap.get("source")
                    rows.append(
                        (
                            now_ts,
                            str(ticker or "").upper(),
                            source,
                            levels,
                            json.dumps(bids),
                            json.dumps(asks),
                        )
                    )

                if rows:
                    save_order_book_history_rows(rows)

            if now - last_prune > 1800:
                try:
                    prune_order_book_history(retention_days)
                except Exception:
                    pass
                last_prune = now

            await asyncio.sleep(max(0.2, interval_ms / 1000.0))
        except Exception:
            await asyncio.sleep(1.0)
