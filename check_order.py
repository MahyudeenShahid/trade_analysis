import sqlite3
conn = sqlite3.connect('backend_data.db')
conn.row_factory = sqlite3.Row
# Check order 494
r = conn.execute('SELECT id,ts,ticker,direction,order_type,qty,price,limit_price,status,error_msg,fill_price,retries FROM live_orders WHERE id=494').fetchone()
print("ORDER 494:", dict(r) if r else 'NOT FOUND')
# Also check last 5 orders to see pattern
rows = conn.execute('SELECT id,ts,ticker,direction,order_type,qty,price,limit_price,status,error_msg,fill_price,retries FROM live_orders ORDER BY id DESC LIMIT 5').fetchall()
print("\nLAST 5 ORDERS:")
for row in rows:
    d = dict(row)
    print(f"  ID={d['id']} {d['direction']} {d['qty']} {d['ticker']} @ limit={d['limit_price']} status={d['status']} err={d['error_msg']} fill={d['fill_price']} retries={d['retries']}")
conn.close()
