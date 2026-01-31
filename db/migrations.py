"""Database schema migrations and initialization."""

import os
import sqlite3
from .connection import DB_PATH, DB_LOCK
from config.settings import UPLOADS_DIR


def init_db():
    """Initialize database schema and create tables."""
    print(f"[Database] Initializing database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Create observations table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            image_path TEXT,
            name TEXT,
            ticker TEXT,
            price TEXT,
            trend TEXT
        )
        """
    )
    
    # Create records table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            image_path TEXT,
            name TEXT,
            ticker TEXT,
            price TEXT,
            trend TEXT,
            buy_price REAL,
            sell_price REAL,
            buy_time TEXT,
            sell_time TEXT,
            win_reason TEXT,
            meta TEXT
        )
        """
    )
    
    # Migration: ensure new columns exist
    cur.execute("PRAGMA table_info(records)")
    existing = [r[1] for r in cur.fetchall()]
    additions = [
        ("buy_price", "REAL"),
        ("sell_price", "REAL"),
        ("buy_time", "TEXT"),
        ("sell_time", "TEXT"),
        ("win_reason", "TEXT"),
    ]
    for col, typ in additions:
        if col not in existing:
            try:
                cur.execute(f"ALTER TABLE records ADD COLUMN {col} {typ}")
            except Exception:
                pass

    # Create trades table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            ticker TEXT,
            action TEXT,
            qty REAL,
            price REAL,
            profit REAL,
            meta TEXT
        )
        """
    )
    
    # Bots table: store per-worker bot metadata (keyed by hwnd)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bots (
            hwnd INTEGER PRIMARY KEY,
            name TEXT,
            ticker TEXT,
            total_pnl REAL,
            open_direction TEXT,
            open_price REAL,
            open_time TEXT,
            rule_1_enabled INTEGER,
            rule_2_enabled INTEGER,
            rule_3_enabled INTEGER,
            take_profit_amount REAL,
            stop_loss_amount REAL,
            rule_3_drop_count INTEGER,
            meta TEXT
        )
        """
    )

    # Migration: ensure new columns exist in bots
    try:
        cur.execute("PRAGMA table_info(bots)")
        existing_bots = [r[1] for r in cur.fetchall()]
        bot_additions = [
            ("rule_1_enabled", "INTEGER"),
            ("rule_2_enabled", "INTEGER"),
            ("rule_3_enabled", "INTEGER"),
            ("take_profit_amount", "REAL"),
            ("stop_loss_amount", "REAL"),
            ("rule_3_drop_count", "INTEGER"),
        ]
        for col, typ in bot_additions:
            if col not in existing_bots:
                try:
                    cur.execute(f"ALTER TABLE bots ADD COLUMN {col} {typ}")
                except Exception:
                    pass
    except Exception:
        pass
    
    conn.commit()
    conn.close()
    os.makedirs(UPLOADS_DIR, exist_ok=True)


__all__ = ["init_db"]
