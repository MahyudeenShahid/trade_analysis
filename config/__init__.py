"""Configuration module for application settings."""

from .settings import (
    API_KEY,
    DB_PATH,
    UPLOADS_DIR,
    WEB_UI_DIR,
    CORS_ORIGINS,
    DEV_ALLOW_ALL_CORS,
)

__all__ = [
    "API_KEY",
    "DB_PATH",
    "UPLOADS_DIR",
    "WEB_UI_DIR",
    "CORS_ORIGINS",
    "DEV_ALLOW_ALL_CORS",
]
