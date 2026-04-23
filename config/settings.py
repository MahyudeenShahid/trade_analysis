"""Application settings and environment configuration."""

import os


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv_file(path: str) -> None:
    """Load KEY=VALUE pairs from a local .env file without overriding real env vars."""
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.lower().startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key:
                    continue

                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]

                if key not in os.environ:
                    os.environ[key] = value
    except Exception:
        # Fail open: app can still run with process-level environment vars.
        pass


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _as_int(value: str, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


    # Load local .env once at import time.
    _load_dotenv_file(os.path.join(PROJECT_ROOT, ".env"))

# Use absolute path for database to ensure consistency across runs
    DB_PATH = os.path.join(PROJECT_ROOT, "backend_data.db")
    UPLOADS_DIR = os.path.join(PROJECT_ROOT, "uploads")
WEB_UI_DIR = "web_ui"

# API Key for authentication
API_KEY = os.environ.get("BACKEND_API_KEY", "devkey")

# Authentication settings
AUTH_ENABLED = _as_bool(os.environ.get("BACKEND_AUTH_ENABLED", "1"), default=True)
AUTH_ALLOW_LEGACY_API_KEY = _as_bool(os.environ.get("BACKEND_AUTH_ALLOW_LEGACY_API_KEY", "1"), default=True)
AUTH_SECRET_KEY = os.environ.get("BACKEND_AUTH_SECRET", f"{API_KEY}-jwt-secret")
AUTH_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = _as_int(os.environ.get("BACKEND_AUTH_TOKEN_EXPIRE_MINUTES", "480"), 480)

# Default admin bootstrap user for first login.
# By default, password falls back to BACKEND_API_KEY to avoid introducing a second hardcoded secret.
AUTH_ADMIN_USERNAME = os.environ.get("BACKEND_ADMIN_USERNAME", "admin")
AUTH_ADMIN_PASSWORD = os.environ.get("BACKEND_ADMIN_PASSWORD", API_KEY)

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
