#!/usr/bin/env python
"""Manually initialize the database to check for errors."""
import sys
sys.path.insert(0, '.')

from db.migrations import init_db

print("Running init_db()...")
try:
    init_db()
    print("SUCCESS: Database initialized successfully!")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

# Now check what was created
import sqlite3
from db.connection import DB_PATH

print(f"\nDatabase path: {DB_PATH}")
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("\n=== Tables Created ===")
tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
for t in tables:
    print(f"  - {t['name']}")

print("\n=== App Settings (IBKR) ===")
rows = cur.execute("SELECT * FROM app_settings WHERE key LIKE '%ibkr%'").fetchall()
for row in rows:
    print(f"  {row['key']}: {row['value']}")

print("\n=== Bots Table Columns ===")
schema = cur.execute("PRAGMA table_info(bots)").fetchall()
live_cols = [col['name'] for col in schema if 'live' in col['name'] or 'order' in col['name'] or 'retry' in col['name']]
print(f"  Live trading columns: {', '.join(live_cols)}")

conn.close()
print("\nAll checks complete!")
