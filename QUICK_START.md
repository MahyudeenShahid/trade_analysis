# 🚀 Quick Start Guide

## Simple One-Command Startup

### Backend (Auto-initializes everything):

```bash
cd trade_analysis
python start.py
```

**Or use uvicorn directly:**
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### What Happens Automatically:

✅ **Step 1: Database Initialization**
- Creates all tables (bots, live_orders, app_settings, etc.)
- No manual `run_init_db.py` needed!

✅ **Step 2: IBKR Auto-Enable**
- Sets `ibkr_enabled = 1` automatically
- No manual `enable_ibkr_trading.py` needed!

✅ **Step 3: Background Tasks Start**
- WebSocket broadcaster (1s loop)
- IBKR keepalive (30s loop, connects when enabled)

✅ **Step 4: Server Ready**
- Backend running on http://0.0.0.0:8000
- Swagger docs at http://localhost:8000/docs

---

## Startup Logs You'll See:

```
[Startup] Initializing database...
[Database] Initializing database at: e:\client\client\trade_analysis\backend_data.db
[Startup] Database initialized ✓
[Startup] Auto-enabling IBKR...
[Startup] IBKR enabled ✓
[Startup] IBKR will connect to 127.0.0.1:4002
[Startup] Starting background tasks...
[Startup] All systems ready ✓
INFO:     Uvicorn running on http://0.0.0.0:8000
[IBKR] Keepalive: attempting reconnect …
[IBKR] Connected to 127.0.0.1:4002 clientId=1
```

---

## Frontend (Separate Terminal):

```bash
cd marketview
npm install  # First time only
npm run dev
```

Open: http://localhost:5173

---

## Full Fresh Start (New Folder):

```bash
# 1. Copy or clone repo
cp -r /path/to/old/client /path/to/new/location

# 2. Install backend dependencies
cd /path/to/new/location/trade_analysis
pip install -r requirements.txt

# 3. Install frontend dependencies
cd ../marketview
npm install

# 4. Start backend (auto-initializes!)
cd ../trade_analysis
python start.py

# 5. Start frontend (new terminal)
cd ../marketview
npm run dev
```

---

## What's Automated vs Manual:

| Task | Before | Now |
|------|--------|-----|
| Init database | ❌ Manual `run_init_db.py` | ✅ Automatic on startup |
| Enable IBKR | ❌ Manual `enable_ibkr_trading.py` | ✅ Automatic on startup |
| Start WebSocket | ✅ Already automatic | ✅ Still automatic |
| Start IBKR loop | ✅ Already automatic | ✅ Still automatic |

---

## Configuration (After First Start):

Once running, configure through the UI:

1. Open http://localhost:5173
2. Add a bot (window + ticker)
3. Enable "Live Trading" toggle
4. Set order size
5. Bot starts trading!

---

## Manual Scripts (Still Available):

If you need them:

```bash
# Check IBKR status
python diagnose_ibkr.py

# Force re-init database
python run_init_db.py

# Enable IBKR manually
python enable_ibkr_trading.py

# Check settings
python check_settings.py
```

---

## IBKR Connection Settings:

Default (auto-configured):
- `ibkr_enabled`: 1
- `ibkr_host`: 127.0.0.1
- `ibkr_port`: 4002 (paper trading)
- `ibkr_client_id`: 1

Change via API or database if needed.

---

## Troubleshooting:

**Issue:** Database errors on startup
**Fix:** Delete `backend_data.db` and restart (will recreate)

**Issue:** IBKR connection failed
**Fix:** Make sure IB Gateway is running on port 4002

**Issue:** Port 8000 already in use
**Fix:** Kill old process or change port:
```bash
python start.py --port 8001
```

---

## That's It! 🎉

Just run `python start.py` and everything happens automatically!
