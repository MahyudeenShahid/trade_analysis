# Project Structure Overview

## 📁 New Folder Structure

```
trade_analysis/
│
├── main.py ⭐                       # Minimal entry point (120 lines)
│   ├── App initialization
│   ├── CORS middleware
│   ├── Route registration
│   └── Startup events
│
├── config/ 🔧                       # Configuration (35 lines total)
│   ├── __init__.py
│   └── settings.py
│       ├── DB_PATH
│       ├── UPLOADS_DIR
│       ├── API_KEY
│       └── CORS_ORIGINS
│
├── db/ 💾                          # Database layer (215 lines total)
│   ├── __init__.py
│   ├── connection.py              # DB path + lock
│   ├── migrations.py              # Schema & migrations
│   └── queries.py                 # All SQL operations
│       ├── query_records()
│       ├── get_latest_record()
│       ├── save_observation()
│       ├── get_bot_db_entry()
│       └── upsert_bot_from_last_result()
│
├── ws/ 🔌                          # WebSocket layer (170 lines total)
│   ├── __init__.py
│   ├── manager.py                 # ConnectionManager
│   │   ├── connect()
│   │   ├── disconnect()
│   │   └── broadcast()
│   └── broadcaster.py             # Real-time loop
│       └── broadcaster_loop()
│
├── services/ 🛠️                    # Business logic (175 lines total)
│   ├── __init__.py
│   ├── background_service.py      # Legacy instances
│   │   ├── service (BackgroundCaptureService)
│   │   └── selector (WindowSelector)
│   └── capture_manager.py         # Multi-worker manager
│       └── CaptureManager
│           ├── start_worker()
│           ├── stop_worker()
│           ├── list_workers()
│           ├── iter_services()
│           └── all_statuses()
│
├── trading/ 📊                     # Trading logic (230 lines total)
│   ├── __init__.py
│   └── simulator.py
│       ├── persist_trade_as_record()
│       └── trader (TradeSimulator instance)
│
├── api/ 🌐                         # API layer (655 lines total)
│   ├── __init__.py
│   ├── dependencies.py            # require_api_key()
│   └── routes/
│       ├── __init__.py
│       ├── windows.py             # 30 lines - Window enumeration
│       │   ├── GET /windows
│       │   └── GET /ping
│       ├── capture.py             # 340 lines - Capture management
│       │   ├── POST /start
│       │   ├── POST /start_multi
│       │   ├── POST /stop
│       │   ├── POST /stop_multi
│       │   ├── POST /stop_all_workers
│       │   ├── GET /status
│       │   ├── GET /workers
│       │   ├── POST /settings/line_detect
│       │   ├── POST /settings/crop_factor
│       │   ├── POST /settings/crop
│       │   ├── POST /settings/bring_to_foreground
│       │   └── POST /workers/{hwnd}/crop
│       ├── history.py             # 145 lines - Records & uploads
│       │   ├── POST /ingest
│       │   ├── GET /latest
│       │   ├── GET /history
│       │   └── GET /uploads/{filename}
│       ├── trades.py              # 75 lines - Trading operations
│       │   ├── GET /trades
│       │   └── POST /manual_trade
│       ├── bots.py                # 80 lines - Bot management
│       │   ├── GET /bots
│       │   └── DELETE /bots/{hwnd}
│       └── websocket.py           # 45 lines - WebSocket endpoints
│           ├── WS /
│           └── WS /ws
│
└── models/ 📋                      # Data models (placeholder)
    └── __init__.py                # Reserved for Pydantic models
```

## 📊 Comparison

### Before (backend_server.py)
- **1 file**: 1,348 lines
- **Everything mixed**: DB, WS, HTTP, business logic
- **Hard to navigate**: Need to scroll through entire file
- **Testing difficulty**: Hard to test individual components
- **Import chaos**: All globals in one namespace

### After (Modular Structure)
- **30 files**: ~1,500 lines (with documentation)
- **Clear separation**: Each concern in its own module
- **Easy navigation**: Find code by feature/responsibility
- **Testing ready**: Each module independently testable
- **Clean imports**: Explicit dependencies

## 🔄 Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                        HTTP Request                          │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  v
┌─────────────────────────────────────────────────────────────┐
│                      main.py (FastAPI)                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ CORS Middleware → Request Logger → Route Handlers    │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  v
┌─────────────────────────────────────────────────────────────┐
│                    API Routes (api/routes/)                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  windows.py │ capture.py │ history.py │ trades.py    │   │
│  │  bots.py │ websocket.py                              │   │
│  └──────────────┬───────────────────────────────────────┘   │
└─────────────────┼───────────────────────────────────────────┘
                  │
      ┌───────────┼───────────┬────────────┐
      │           │           │            │
      v           v           v            v
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│services/│ │trading/ │ │   db/   │ │   ws/   │
│         │ │         │ │         │ │         │
│ Capture │ │  Trade  │ │Database │ │WebSocket│
│ Manager │ │Simulator│ │ Queries │ │ Manager │
└─────────┘ └─────────┘ └─────────┘ └─────────┘
      │           │           │            │
      └───────────┴───────────┴────────────┘
                  │
                  v
┌─────────────────────────────────────────────────────────────┐
│              External Dependencies & Storage                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ SQLite DB │ Screenshots │ BackgroundCaptureService   │   │
│  │ WindowSelector │ TradeSimulator                      │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 🎯 Key Benefits

### 1. Maintainability ⬆️
- **Before**: Find code by scrolling → 😓
- **After**: Navigate by feature → 😊

### 2. Testability ⬆️
- **Before**: Test entire 1348-line file → 😓
- **After**: Test each 30-150 line module → 😊

### 3. Collaboration ⬆️
- **Before**: Merge conflicts on single file → 😓
- **After**: Work on separate modules → 😊

### 4. Onboarding ⬆️
- **Before**: "Read 1348 lines to understand" → 😓
- **After**: "Check REFACTORING.md + folder structure" → 😊

### 5. Debugging ⬆️
- **Before**: Bug could be anywhere in 1348 lines → 😓
- **After**: Check relevant module (30-340 lines) → 😊

## 🚀 Quick Start

### Running the new version:
```bash
cd trade_analysis
python main.py
```

### Running tests (future):
```bash
pytest tests/db/           # Test database layer
pytest tests/ws/           # Test WebSocket layer
pytest tests/api/          # Test API routes
pytest tests/services/     # Test business logic
```

### Adding a new endpoint:
1. Choose appropriate route file in `api/routes/`
2. Add endpoint function
3. Register router in `main.py` (if new file)
4. Done! ✅

### Adding a new feature:
1. Create module in appropriate folder
2. Import in `__init__.py`
3. Use in routes or services
4. Done! ✅

## 📈 Lines of Code Distribution

```
Total: ~1,500 lines (including docs)

main.py:                120 lines  (8%)
config/:                 35 lines  (2%)
db/:                    215 lines (14%)
ws/:                    170 lines (11%)
services/:              175 lines (12%)
trading/:               230 lines (15%)
api/:                   655 lines (44%)
models/:                  5 lines  (<1%)
Documentation:          200 lines (13%)
```

**Result**: No single file exceeds 340 lines! 🎉
