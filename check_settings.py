#!/usr/bin/env python
import sqlite3
import sys

db_path = 'backend_data.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=== Available Tables ===")
tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
for t in tables:
    print(f"  - {t['name']}")

print("\n=== Bots Table Schema ===")
schema = cur.execute("PRAGMA table_info(bots)").fetchall()
for col in schema:
    print(f"  {col['name']}: {col['type']}")

print("\n=== Bot Live Trading Settings ===")
rows = cur.execute("SELECT * FROM bots LIMIT 3").fetchall()
for row in rows:
    print(f"\nhwnd={row['hwnd']}")
    for key in row.keys():
        print(f"  {key}: {row[key]}")

conn.close()
