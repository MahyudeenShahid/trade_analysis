"""Runtime-selectable time mode helpers for backend day grouping and display."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from db.connection import DB_LOCK, DB_PATH

TIME_MODE_LOCAL = "local"
TIME_MODE_UTC = "utc"
VALID_TIME_MODES = {TIME_MODE_LOCAL, TIME_MODE_UTC}
DEFAULT_TIME_MODE = TIME_MODE_LOCAL

_time_mode_cache: Optional[str] = None


def normalize_time_mode(value: Optional[str]) -> str:
    raw = str(value or DEFAULT_TIME_MODE).strip().lower()
    return TIME_MODE_UTC if raw == TIME_MODE_UTC else TIME_MODE_LOCAL


def _local_timezone():
    try:
        return datetime.now().astimezone().tzinfo or timezone.utc
    except Exception:
        return timezone.utc


def _ensure_settings_table(conn: sqlite3.Connection):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )


def get_time_mode(refresh: bool = False) -> str:
    global _time_mode_cache

    if _time_mode_cache is not None and not refresh:
        return _time_mode_cache

    fallback = normalize_time_mode(os.environ.get("APP_TIME_MODE", DEFAULT_TIME_MODE))
    try:
        conn = sqlite3.connect(DB_PATH)
        _ensure_settings_table(conn)
        cur = conn.cursor()
        cur.execute("SELECT value FROM app_settings WHERE key = ? LIMIT 1", ("time_mode",))
        row = cur.fetchone()
        conn.close()
        _time_mode_cache = normalize_time_mode(row[0] if row and row[0] else fallback)
    except Exception:
        _time_mode_cache = fallback

    return _time_mode_cache


def set_time_mode(mode: Optional[str]) -> str:
    global _time_mode_cache

    normalized = normalize_time_mode(mode)
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DB_PATH)
            _ensure_settings_table(conn)
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("time_mode", normalized),
            )
            conn.commit()
            conn.close()
    except Exception:
        pass

    _time_mode_cache = normalized
    return normalized


def is_utc_mode(mode: Optional[str] = None) -> bool:
    return normalize_time_mode(mode or get_time_mode()) == TIME_MODE_UTC


def current_wall_datetime(mode: Optional[str] = None) -> datetime:
    return datetime.utcnow() if is_utc_mode(mode) else datetime.now()


def current_timestamp(mode: Optional[str] = None) -> str:
    if is_utc_mode(mode):
        return datetime.utcnow().isoformat() + "Z"
    return datetime.now().astimezone().isoformat()


def current_folder_day(mode: Optional[str] = None) -> str:
    return current_wall_datetime(mode).strftime("%Y%m%d")


def folder_day_from_offset(days_back: int, mode: Optional[str] = None) -> str:
    base = current_wall_datetime(mode) - timedelta(days=max(0, int(days_back)))
    return base.strftime("%Y%m%d")


def capture_filename_timestamp(mode: Optional[str] = None) -> str:
    return current_wall_datetime(mode).strftime("%Y%m%d_%H%M%S_%f")[:-3]


def _format_utc_z(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat() + "Z"


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    raw = str(value).strip()
    try:
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw[:-1]).replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            # Historical record timestamps in this app are stored as UTC when no
            # explicit offset is present.
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def _to_mode_datetime(parsed: datetime, mode: Optional[str] = None) -> datetime:
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if is_utc_mode(mode):
        return parsed.astimezone(timezone.utc)
    return parsed.astimezone(_local_timezone())


def history_day_key(ts: Optional[str], mode: Optional[str] = None) -> Optional[str]:
    parsed = parse_timestamp(ts)
    if not parsed:
        return None
    return _to_mode_datetime(parsed, mode).strftime("%Y-%m-%d")


def screenshot_day_key(ts: Optional[str], mode: Optional[str] = None) -> Optional[str]:
    day_key = history_day_key(ts, mode)
    return day_key.replace("-", "") if day_key else None


def recent_days_start_ts(days: int = 7, mode: Optional[str] = None) -> str:
    span = max(1, int(days)) - 1
    if is_utc_mode(mode):
        now = datetime.utcnow()
        start = datetime(now.year, now.month, now.day) - timedelta(days=span)
        return _format_utc_z(start)

    local_now = datetime.now().astimezone()
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=span)
    return _format_utc_z(start_local.astimezone(timezone.utc))


def day_bounds_utc(day_key: str, mode: Optional[str] = None) -> Tuple[str, str]:
    parsed_day = datetime.strptime(day_key, "%Y-%m-%d")
    if is_utc_mode(mode):
        start = parsed_day.replace(tzinfo=timezone.utc)
        end = start + timedelta(days=1) - timedelta(microseconds=1)
        return _format_utc_z(start), _format_utc_z(end)

    local_tz = _local_timezone()
    start_local = parsed_day.replace(tzinfo=local_tz)
    end_local = start_local + timedelta(days=1) - timedelta(microseconds=1)
    return _format_utc_z(start_local.astimezone(timezone.utc)), _format_utc_z(end_local.astimezone(timezone.utc))


__all__ = [
    "TIME_MODE_LOCAL",
    "TIME_MODE_UTC",
    "VALID_TIME_MODES",
    "capture_filename_timestamp",
    "current_folder_day",
    "current_timestamp",
    "current_wall_datetime",
    "day_bounds_utc",
    "folder_day_from_offset",
    "get_time_mode",
    "history_day_key",
    "is_utc_mode",
    "normalize_time_mode",
    "recent_days_start_ts",
    "screenshot_day_key",
    "set_time_mode",
]