"""Application configuration settings database operations."""

import sqlite3
from .connection import DB_PATH, DB_LOCK
from .base import query_records


def get_app_settings() -> dict:
    """Return all app_settings rows as a key→value dict."""
    rows = query_records("SELECT key, value FROM app_settings")
    return {r["key"]: r["value"] for r in rows}


def set_app_setting(key: str, value: str):
    """Upsert a single app_settings row."""
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        conn.commit()
        conn.close()
