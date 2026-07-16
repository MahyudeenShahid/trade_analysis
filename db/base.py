"""Core database execution wrappers."""

import sqlite3
from .connection import DB_PATH


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert SQLite row to dictionary."""
    return {k: row[k] for k in row.keys()}


def query_records(sql: str, params: tuple = ()) -> list:
    """Execute a query and return results as list of dictionaries."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def query_history_page(where: str, params: tuple, limit: int, offset: int) -> tuple:
    """Run COUNT and paginated SELECT in a single connection — avoids opening DB twice."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) as count FROM records WHERE {where}", params)
    total = cur.fetchone()["count"]
    cur.execute(
        f"SELECT * FROM records WHERE {where} ORDER BY ts DESC LIMIT ? OFFSET ?",
        params + (limit, offset),
    )
    rows = [_row_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return total, rows
