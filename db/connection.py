"""Database connection and locking utilities."""

import threading
from config.settings import DB_PATH

# Thread-safe database lock
DB_LOCK = threading.Lock()

__all__ = ["DB_PATH", "DB_LOCK"]
