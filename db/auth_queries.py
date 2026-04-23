"""Authentication-related database queries."""

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .connection import DB_PATH, DB_LOCK


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_user_by_username(username: str) -> Optional[dict]:
    if not username:
        return None
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash, role, is_active, created_at, updated_at FROM users WHERE username = ?",
            (str(username).strip().lower(),),
        )
        row = cur.fetchone()
        conn.close()
    if not row:
        return None
    return {k: row[k] for k in row.keys()}


def upsert_user(username: str, password_hash: str, role: str = "admin", is_active: int = 1) -> dict:
    if not username:
        raise ValueError("username is required")
    uname = str(username).strip().lower()
    now = _now_iso()
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username = ?", (uname,))
        existing = cur.fetchone()
        if existing:
            cur.execute(
                """
                UPDATE users
                SET password_hash = ?, role = ?, is_active = ?, updated_at = ?
                WHERE username = ?
                """,
                (password_hash, role, int(bool(is_active)), now, uname),
            )
        else:
            cur.execute(
                """
                INSERT INTO users (username, password_hash, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (uname, password_hash, role, int(bool(is_active)), now, now),
            )
        conn.commit()
        cur.execute(
            "SELECT id, username, password_hash, role, is_active, created_at, updated_at FROM users WHERE username = ?",
            (uname,),
        )
        row = cur.fetchone()
        conn.close()
    return {k: row[k] for k in row.keys()}


def ensure_default_admin(username: str, password_hash: str) -> None:
    """Create default admin user only if users table is currently empty."""
    if not username or not password_hash:
        return
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        count = int(cur.fetchone()[0])
        conn.close()
    if count == 0:
        upsert_user(username=username, password_hash=password_hash, role="admin", is_active=1)
