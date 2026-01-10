# Refactored Backend Structure

## Overview

This FastAPI backend has been refactored from a single 1348-line file into a clean, modular, production-ready structure following best practices.

## Project Structure

```
trade_analysis/
├── main.py                          # Application entry point (minimal)
├── backend_server.py                # Original file (kept for reference)
│
├── config/                          # Configuration & Settings
│   ├── __init__.py
│   └── settings.py                  # Environment variables, CORS, paths
│
├── db/                              # Database Layer
│   ├── __init__.py
│   ├── connection.py                # DB path and thread lock
│   ├── migrations.py                # Schema initialization & migrations
│   └── queries.py                   # All database queries
│
├── ws/                              # WebSocket Layer
│   ├── __init__.py
│   ├── manager.py                   # ConnectionManager class
│   └── broadcaster.py               # Real-time broadcast loop
│
├── services/                        # Business Logic Services
│   ├── __init__.py
│   ├── background_service.py        # Legacy service & window selector
│   └── capture_manager.py           # Multi-worker capture manager
│
├── trading/                         # Trading Logic
│   ├── __init__.py
│   └── simulator.py                 # Trade simulator & persistence
│
├── api/                             # API Layer
│   ├── __init__.py
│   ├── dependencies.py              # Auth & validation dependencies
│   └── routes/                      # Feature-based route modules
│       ├── __init__.py
│       ├── windows.py               # Window enumeration, health check
│       ├── capture.py               # Capture workers, settings
│       ├── history.py               # Records, uploads, ingest
│       ├── trades.py                # Trade summary, manual trades
│       ├── bots.py                  # Bot CRUD operations
│       └── websocket.py             # WebSocket endpoints
│
└── models/                          # Data Models (placeholder)
    └── __init__.py                  # Reserved for Pydantic models
```

## Module Responsibilities

### 🔧 **config/** - Configuration Management
- **settings.py**: Centralized configuration
  - Database path (`DB_PATH`)
  - Uploads directory (`UPLOADS_DIR`)
  - API key authentication (`API_KEY`)
  - CORS origins and development overrides
  - Environment variable parsing

### 💾 **db/** - Database Layer
- **connection.py**: Database connection utilities
  - Thread-safe DB lock (`DB_LOCK`)
  - Database path constant
  
- **migrations.py**: Schema management
  - `init_db()`: Creates all tables
  - Handles schema migrations (ALTER TABLE)
  - Creates `observations`, `records`, `trades`, `bots` tables
  
- **queries.py**: Data access layer
  - `query_records()`: Execute SQL queries
  - `get_latest_record()`: Fetch most recent record
  - `save_observation()`: Persist records with auto-pruning
  - `get_bot_db_entry()`: Retrieve bot by hwnd
  - `upsert_bot_from_last_result()`: Update bot state

### 🔌 **ws/** - WebSocket Layer
- **manager.py**: Connection management
  - `ConnectionManager`: Handle WebSocket lifecycle
  - `connect()`, `disconnect()`, `broadcast()` methods
  - Automatic cleanup of dead connections
  
- **broadcaster.py**: Real-time updates
  - `broadcaster_loop()`: Background task
  - Collects worker statuses and screenshots
  - Encodes images as base64
  - Broadcasts JSON payloads every second
  - Auto-cleans old screenshots

### 🛠️ **services/** - Business Logic
- **background_service.py**: Legacy service instances
  - Single `BackgroundCaptureService` instance
  - `WindowSelector` instance
  
- **capture_manager.py**: Multi-worker management
  - `CaptureManager`: Manages multiple capture workers
  - Per-window isolation (separate folders)
  - Thread-safe worker registry
  - Crop settings persistence from DB

### 📊 **trading/** - Trading Logic
- **simulator.py**: Trade simulation
  - `persist_trade_as_record()`: Complex trade persistence
  - Buy/sell pairing logic (in-memory + DB)
  - Profit calculation
  - `trader`: Global TradeSimulator instance

### 🌐 **api/** - API Endpoints
- **dependencies.py**: Reusable dependencies
  - `require_api_key()`: Bearer token authentication
  
- **routes/windows.py**: Window management
  - `GET /windows`: List available windows
  - `GET /ping`: Health check
  
- **routes/capture.py**: Capture operations
  - `POST /start`: Start legacy single capture
  - `POST /start_multi`: Start multi-worker
  - `POST /stop_multi`: Stop specific worker
  - `POST /stop_all_workers`: Stop all workers
  - `GET /workers`: Get all worker statuses
  - `POST /settings/*`: Various capture settings
  - `POST /workers/{hwnd}/crop`: Per-worker crop
  
- **routes/history.py**: Data management
  - `POST /ingest`: Upload & auto-trade
  - `GET /latest`: Most recent record
  - `GET /history`: Filtered historical records
  - `GET /uploads/{filename}`: Serve uploaded files
  
- **routes/trades.py**: Trading operations
  - `GET /trades`: Trade summary
  - `POST /manual_trade`: Manual trade entry
  
- **routes/bots.py**: Bot management
  - `GET /bots`: List all bots
  - `DELETE /bots/{hwnd}`: Remove bot & cleanup
  
- **routes/websocket.py**: Real-time connections
  - `WS /`: Root WebSocket endpoint
  - `WS /ws`: Primary WebSocket endpoint

## Key Design Patterns

### 1. **Separation of Concerns**
Each module has a single, well-defined responsibility:
- Config → Settings
- DB → Data persistence
- WS → Real-time communication
- Services → Business logic
- Trading → Domain logic
- API → HTTP interface

### 2. **Dependency Injection**
- FastAPI's `Depends()` for auth and validation
- Services are imported where needed
- Global instances managed at module level

### 3. **Thread Safety**
- `DB_LOCK` for SQLite operations
- `_lock` in `CaptureManager` for worker registry

### 4. **Feature-Based Routing**
Routes organized by feature area, not by HTTP method:
- Easier to locate and maintain
- Better code organization
- Clear boundaries

### 5. **Error Handling**
- Consistent HTTPException usage
- Try-except blocks for critical operations
- Graceful degradation

## Migration from Original File

### What Changed
✅ **Zero breaking changes** - All functionality preserved  
✅ **Same API endpoints** - All routes work identically  
✅ **Same behavior** - Database, WebSocket, capture logic unchanged  
✅ **Better organization** - Code split into logical modules  
✅ **Easier testing** - Each module can be tested independently  
✅ **Better maintainability** - Changes are isolated to specific files  

### Import Updates
The refactoring uses relative imports within the new structure:
```python
from config.settings import API_KEY
from db.queries import save_observation
from ws.manager import manager
from services.capture_manager import manager_services
from trading.simulator import trader
```

## Running the Application

### Using the new main.py
```bash
# Development
python main.py

# Production with uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# With workers
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Environment Variables
```bash
# API Key (default: devkey)
export BACKEND_API_KEY="your-secret-key"

# Allow all CORS origins (dev only)
export DEV_ALLOW_ALL_CORS="1"

# Custom CORS origins
export DEV_ALLOW_ORIGINS="http://localhost:3000,http://localhost:5173"
```

## Testing Endpoints

```bash
# Health check
curl http://localhost:8000/ping

# List windows
curl http://localhost:8000/windows

# Get workers (requires auth)
curl -H "Authorization: Bearer devkey" http://localhost:8000/workers

# Get trade summary
curl -H "Authorization: Bearer devkey" http://localhost:8000/trades

# WebSocket connection
wscat -c ws://localhost:8000/ws
```

## Future Enhancements

### Immediate Next Steps
1. **Add Pydantic models** in `models/` for request/response validation
2. **Add unit tests** for each module
3. **Add logging** with proper log levels
4. **Add metrics** (Prometheus/OpenTelemetry)

### Long-term Improvements
1. **Async database** operations (aiosqlite)
2. **Connection pooling** for database
3. **Redis** for WebSocket pub/sub in multi-worker deployments
4. **Background tasks** using Celery or similar
5. **API versioning** (e.g., `/api/v1/`)
6. **OpenAPI tags** and better documentation

## Benefits of Refactoring

### For Development
- **Faster onboarding**: New developers understand structure immediately
- **Parallel work**: Multiple developers can work on different modules
- **Clear ownership**: Each module has a specific purpose
- **Better IDE support**: Better autocomplete and navigation

### For Maintenance
- **Easier debugging**: Issues isolated to specific modules
- **Simpler updates**: Changes don't ripple across entire codebase
- **Clear dependencies**: Import statements show relationships
- **Refactoring safety**: Changes are localized

### For Production
- **Better testing**: Unit test each module independently
- **Better monitoring**: Log and monitor specific components
- **Better scaling**: Identify performance bottlenecks per module
- **Better deployment**: Deploy specific modules if architecture evolves

## Backwards Compatibility

The original `backend_server.py` is preserved. You can still run it if needed:
```bash
python backend_server.py
```

However, **use `main.py` going forward** for the refactored version with all the same functionality.

## Questions or Issues?

The refactored code maintains 100% functional compatibility with the original. If you encounter any differences in behavior, please review the module that handles that feature using the structure guide above.
