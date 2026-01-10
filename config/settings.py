"""Application settings and environment configuration."""

import os

# Use absolute path for database to ensure consistency across runs
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend_data.db")
UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
WEB_UI_DIR = "web_ui"

# API Key for authentication
API_KEY = os.environ.get("BACKEND_API_KEY", "devkey")

# CORS configuration: allow listing for production, with a DEV override
DEV_ALLOW_ALL_CORS = os.environ.get("DEV_ALLOW_ALL_CORS", "0") in ("1", "true", "True")

# Optional comma-separated origins for dev (e.g. "https://marketview1.netlify.app,http://localhost:5173")
_dev_allow_origins = os.environ.get("DEV_ALLOW_ORIGINS")

if _dev_allow_origins:
    # split and strip
    try:
        CORS_ORIGINS = [o.strip() for o in _dev_allow_origins.split(",") if o.strip()]
    except Exception:
        CORS_ORIGINS = []
else:
    CORS_ORIGINS = [
        "https://brilliant-lollipop-2620b1.netlify.app",
        "https://electrotropic-uselessly-lashawna.ngrok-free.dev",
        "http://localhost:3000",
        "https://marketview1.netlify.app",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]
