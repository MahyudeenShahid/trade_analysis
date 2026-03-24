#!/usr/bin/env python
"""Enable IBKR live trading and configure bot settings."""
import sys
sys.path.insert(0, '.')

import sqlite3
from db.connection import DB_PATH, DB_LOCK

print("=== Enabling IBKR Live Trading ===\n")

with DB_LOCK:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Enable IBKR globally
    print("1. Setting ibkr_enabled = 1 ...")
    cur.execute("UPDATE app_settings SET value = '1' WHERE key = 'ibkr_enabled'")

    # 2. Check current bot settings
    print("\n2. Current bots:")
    bots = cur.execute("SELECT hwnd, name, ticker, live_trading_enabled, order_size_type, order_size_value FROM bots").fetchall()

    if not bots:
        print("   WARNING: No bots found in database!")
        print("   You need to create a bot first through the UI.")
    else:
        for bot in bots:
            print(f"   hwnd={bot['hwnd']}, name={bot['name']}, ticker={bot['ticker']}, live_enabled={bot['live_trading_enabled']}")

        # 3. Enable live trading for ALL bots (or you can do it selectively)
        print("\n3. Enabling live_trading_enabled for all bots...")
        cur.execute("""
            UPDATE bots
            SET
                live_trading_enabled = 1,
                order_size_type = COALESCE(order_size_type, 'fixed'),
                order_size_value = COALESCE(order_size_value, 1.0),
                buy_order_type = COALESCE(buy_order_type, 'market'),
                sell_order_type = COALESCE(sell_order_type, 'market'),
                retry_delay_secs = COALESCE(retry_delay_secs, 5.0),
                max_retries = COALESCE(max_retries, 3)
        """)
        print(f"   Updated {cur.rowcount} bot(s)")

    conn.commit()

    # 4. Verify changes
    print("\n4. Final settings:")
    row = cur.execute("SELECT value FROM app_settings WHERE key = 'ibkr_enabled'").fetchone()
    print(f"   ibkr_enabled: {row['value']}")

    bots = cur.execute("SELECT hwnd, name, ticker, live_trading_enabled, order_size_type, order_size_value, buy_order_type FROM bots").fetchall()
    for bot in bots:
        print(f"   Bot {bot['hwnd']} ({bot['name']}): live_enabled={bot['live_trading_enabled']}, size={bot['order_size_value']} {bot['order_size_type']}, buy_type={bot['buy_order_type']}")

    conn.close()

print("\n=== SUCCESS! ===")
print("\nNext steps:")
print("1. Make sure IB Gateway or TWS is running on port 4002 (paper trading)")
print("2. Restart your backend server")
print("3. Your bot should now place live orders!")
