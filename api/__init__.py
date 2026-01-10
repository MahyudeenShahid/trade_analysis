"""API routes module."""

from fastapi import APIRouter
from .routes import windows, capture, history, trades, bots, websocket

__all__ = [
    "windows",
    "capture",
    "history",
    "trades",
    "bots",
    "websocket",
]
