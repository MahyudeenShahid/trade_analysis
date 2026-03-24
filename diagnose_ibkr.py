#!/usr/bin/env python
"""Complete diagnostic for IBKR live trading setup."""
import sys
sys.path.insert(0, '.')

import sqlite3
from db.connection import DB_PATH

print("="*60)
print("IBKR LIVE TRADING DIAGNOSTIC")
print("="*60)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# 1. Check IBKR global settings
print("\n1. IBKR GLOBAL SETTINGS:")
print("-" * 40)
rows = conn.execute("SELECT * FROM app_settings WHERE key LIKE '%ibkr%'").fetchall()
for row in rows:
    status = "OK" if (row['key'] == 'ibkr_enabled' and row['value'] == '1') else "INFO"
    print(f"   [{status}] {row['key']}: {row['value']}")

enabled = conn.execute("SELECT value FROM app_settings WHERE key = 'ibkr_enabled'").fetchone()
if enabled and enabled['value'] != '1':
    print("\n   *** ERROR: ibkr_enabled must be '1' ***")
    print("   Run: python enable_ibkr_trading.py")

# 2. Check bots table
print("\n2. BOTS CONFIGURATION:")
print("-" * 40)
bots = conn.execute("SELECT * FROM bots").fetchall()

if not bots:
    print("   [ERROR] No bots found!")
    print("\n   SOLUTION: Create a bot through your UI:")
    print("   1. Start your backend server")
    print("   2. Open the frontend")
    print("   3. Add a bot (hwnd, ticker, etc.)")
    print("   4. Enable 'Live Trading' toggle in bot settings")
else:
    for bot in bots:
        print(f"\n   Bot: {bot['name']} (hwnd={bot['hwnd']})")
        print(f"   - Ticker: {bot['ticker']}")
        print(f"   - Live Trading: {'ENABLED' if bot['live_trading_enabled'] else 'DISABLED'}")
        print(f"   - Order Size: {bot['order_size_value']} ({bot['order_size_type']})")
        print(f"   - Order Types: BUY={bot['buy_order_type']}, SELL={bot['sell_order_type']}")

        if not bot['live_trading_enabled']:
            print(f"   [WARNING] Live trading is DISABLED for this bot")
            print(f"   Enable it in the UI or run: python enable_ibkr_trading.py")

# 3. Check recent trades (paper trading)
print("\n3. RECENT PAPER TRADES (last 10):")
print("-" * 40)
trades = conn.execute("SELECT ts, ticker, action, price FROM trades ORDER BY ts DESC LIMIT 10").fetchall()
if not trades:
    print("   [WARNING] No paper trades found!")
    print("   This means your bot rules are NOT triggering buy/sell signals.")
    print("\n   CHECK:")
    print("   - Is screenshot capture working?")
    print("   - Are price/trend being detected?")
    print("   - Are trading rules configured correctly?")
    print("   - Is the bot outside trading hours?")
else:
    for t in trades:
        print(f"   {t['ts']}: {t['action'].upper()} {t['ticker']} @ {t['price']}")

# 4. Check live orders
print("\n4. LIVE ORDERS (IBKR):")
print("-" * 40)
live = conn.execute("SELECT * FROM live_orders ORDER BY ts DESC LIMIT 5").fetchall()
if not live:
    print("   [INFO] No live orders yet")
    print("   This is expected if you just enabled IBKR")
else:
    for order in live:
        status_icon = "OK" if order['status'] == 'filled' else "FAIL" if order['status'] == 'failed' else "PENDING"
        print(f"   [{status_icon}] {order['ts']}: {order['direction'].upper()} {order['qty']} {order['ticker']}")
        print(f"        Status: {order['status']}, Price: {order['price']}")
        if order['error_msg']:
            print(f"        Error: {order['error_msg']}")

# 5. Check order book snapshots
print("\n5. ORDER BOOK SNAPSHOTS:")
print("-" * 40)
snapshots = conn.execute("SELECT COUNT(*) as count FROM order_book_snapshots").fetchone()
print(f"   Total snapshots: {snapshots['count']}")

conn.close()

print("\n" + "="*60)
print("SUMMARY:")
print("="*60)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
enabled = conn.execute("SELECT value FROM app_settings WHERE key = 'ibkr_enabled'").fetchone()
bots_count = conn.execute("SELECT COUNT(*) as count FROM bots WHERE live_trading_enabled = 1").fetchone()
conn.close()

ibkr_on = enabled and enabled['value'] == '1'
bots_ready = bots_count and bots_count['count'] > 0

print(f"   IBKR Enabled:       {'YES' if ibkr_on else 'NO'}")
print(f"   Live Bots Ready:    {bots_count['count'] if bots_count else 0}")
print(f"   Can Place Orders:   {'YES' if ibkr_on and bots_ready else 'NO'}")

if not ibkr_on:
    print("\n   ACTION: Run 'python enable_ibkr_trading.py'")
if not bots_ready:
    print("\n   ACTION: Create a bot in the UI and enable live trading")

print("\n" + "="*60)
