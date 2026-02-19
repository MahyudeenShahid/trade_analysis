"""
FastAPI Backend Server - Main Application Entry Point

This is a refactored, production-ready FastAPI application for screenshot capture,
trade simulation, and real-time WebSocket updates.

Architecture:
- config/: Environment variables, CORS settings, paths
- db/: SQLite database operations and migrations
- ws/: WebSocket connection management and broadcasting
- services/: Background capture workers and window selection
- trading/: Trade simulator and persistence logic
- api/routes/: REST API endpoints organized by feature
"""

import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from config.settings import (
    CORS_ORIGINS,
    DEV_ALLOW_ALL_CORS,
    UPLOADS_DIR,
    WEB_UI_DIR,
)
from db.migrations import init_db
from ws.broadcaster import broadcaster_loop
from api.routes import windows, capture, history, trades, bots, websocket, chart


# Create FastAPI application
app = FastAPI(title="Local Screenshot Backend")


# ============================================================================
# Static File Serving
# ============================================================================

# Serve uploaded files
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# Serve SPA UI if exists
if os.path.isdir(WEB_UI_DIR):
    app.mount("/static", StaticFiles(directory=WEB_UI_DIR), name="webui_static")

    @app.get("/")
    def serve_index():
        """Serve the web UI index page."""
        index_path = os.path.join(WEB_UI_DIR, "index.html")
        if not os.path.exists(index_path):
            return JSONResponse(
                status_code=404,
                content={"detail": "UI not found"}
            )
        return FileResponse(index_path)


# ============================================================================
# CORS Middleware
# ============================================================================

if DEV_ALLOW_ALL_CORS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ============================================================================
# Request Logging Middleware
# ============================================================================

@app.middleware("http")
async def log_requests(request, call_next):
    """Log all HTTP requests for debugging."""
    try:
        print(f"[HTTP] {request.method} {request.url}")
    except Exception:
        pass
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        print(f"[HTTP] handler error: {e}")
        raise


# ============================================================================
# Startup Event
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """
    Initialize application on startup.
    
    - Initializes database schema
    - Starts WebSocket broadcaster loop for real-time updates
    """
    init_db()
    asyncio.create_task(broadcaster_loop())


# ============================================================================
# API Routes Registration
# ============================================================================

# Register all route modules
app.include_router(windows.router)
app.include_router(capture.router)
app.include_router(history.router)
app.include_router(trades.router)
app.include_router(bots.router)
app.include_router(websocket.router)
app.include_router(chart.router)


# ============================================================================
# Application Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
