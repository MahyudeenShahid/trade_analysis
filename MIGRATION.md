# Quick Migration Guide

## ✅ What You Need to Know

### The Good News
- **Zero breaking changes** - All functionality works exactly the same
- **Same endpoints** - All API routes unchanged
- **Same database** - Uses the same `backend_data.db`
- **Same dependencies** - No new packages required
- **Backward compatible** - Old `backend_server.py` still works

### What Changed
- Code split into modules (config, db, ws, services, trading, api)
- Entry point is now `main.py` instead of `backend_server.py`
- Cleaner organization for easier maintenance

---

## 🚀 How to Switch

### Option 1: Direct Switch (Recommended)
```bash
# Stop the old server
# Ctrl+C if running

# Start the new server
python main.py

# Or with uvicorn
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Option 2: Test in Parallel
```bash
# Run old server on port 8000
python backend_server.py

# Run new server on port 8001 (in another terminal)
uvicorn main:app --port 8001

# Compare behavior
curl http://localhost:8000/ping
curl http://localhost:8001/ping
```

### Option 3: Gradual Migration
```bash
# Keep using backend_server.py for now
python backend_server.py

# When ready, switch to main.py
python main.py
```

---

## 📝 Code Changes Required

### If you import from backend_server.py
**Before:**
```python
from backend_server import trader, manager, service
```

**After:**
```python
from trading.simulator import trader
from ws.manager import manager
from services.background_service import service
```

### If you have tests
**Before:**
```python
import backend_server
# Test everything in one file
```

**After:**
```python
from db.queries import get_latest_record
from ws.manager import ConnectionManager
# Test specific modules
```

---

## 🔍 Finding Your Code

### "Where did X go?"

| Original backend_server.py | New Location |
|---------------------------|--------------|
| `API_KEY`, `DB_PATH`, `UPLOADS_DIR` | `config/settings.py` |
| `init_db()` | `db/migrations.py` |
| `query_records()`, `save_observation()` | `db/queries.py` |
| `ConnectionManager` | `ws/manager.py` |
| `broadcaster_loop()` | `ws/broadcaster.py` |
| `CaptureManager` | `services/capture_manager.py` |
| `service`, `selector` | `services/background_service.py` |
| `trader`, `persist_trade_as_record()` | `trading/simulator.py` |
| `require_api_key()` | `api/dependencies.py` |
| `@app.get("/windows")` | `api/routes/windows.py` |
| `@app.post("/start")` | `api/routes/capture.py` |
| `@app.get("/history")` | `api/routes/history.py` |
| `@app.get("/trades")` | `api/routes/trades.py` |
| `@app.get("/bots")` | `api/routes/bots.py` |
| `@app.websocket("/ws")` | `api/routes/websocket.py` |

---

## 🧪 Testing Checklist

After switching to `main.py`, verify:

- [ ] Server starts without errors
- [ ] `GET /ping` returns `{"ok": true, ...}`
- [ ] `GET /windows` lists windows
- [ ] `POST /start_multi` starts capture workers
- [ ] WebSocket connects at `ws://localhost:8000/ws`
- [ ] Database file `backend_data.db` is created/used
- [ ] Uploaded files appear in `uploads/`
- [ ] Screenshots saved correctly
- [ ] Trade simulator works
- [ ] CORS works for your frontend

---

## ⚠️ Common Issues

### Issue: ModuleNotFoundError
```python
ModuleNotFoundError: No module named 'config'
```

**Solution**: Make sure you're running from the `trade_analysis/` directory:
```bash
cd trade_analysis
python main.py
```

### Issue: Import errors
```python
ImportError: cannot import name 'X' from 'Y'
```

**Solution**: Check that all `__init__.py` files exist in each folder

### Issue: Old behavior in new code
**Solution**: Make sure you stopped the old `backend_server.py` process

---

## 🔄 Rollback Plan

If you need to revert:

1. **Stop the new server** (Ctrl+C)
2. **Start the old server**:
   ```bash
   python backend_server.py
   ```
3. Everything works as before!

The original `backend_server.py` is **not modified** and remains fully functional.

---

## 📞 Need Help?

### Quick Diagnostics
```bash
# Check if main.py exists
ls -la main.py

# Check folder structure
tree -L 2  # or: ls -R

# Test imports
python -c "from config import settings; print(settings.DB_PATH)"

# Start with verbose output
python main.py
```

### Debug Mode
```bash
# Run with debug logging
uvicorn main:app --reload --log-level debug
```

---

## 🎯 Next Steps

Once you're comfortable with the new structure:

1. **Update your deployment scripts** to use `main.py`
2. **Update documentation** to reference new structure
3. **Add tests** for individual modules
4. **Explore the new structure** - easier to understand!
5. **Start using module organization** for new features

---

## 📚 Additional Resources

- **REFACTORING.md** - Detailed explanation of changes
- **STRUCTURE.md** - Visual guide to new structure
- **README.md** - Original project documentation

---

## ✨ Benefits You'll Notice

### Day 1
- Cleaner imports
- Easier to find code

### Week 1
- Faster development
- Less merge conflicts

### Month 1
- Better code quality
- Easier onboarding
- More confident refactoring

---

## 🎉 Welcome to the New Structure!

The refactored codebase maintains 100% compatibility while being **significantly easier to work with**. Happy coding! 🚀
