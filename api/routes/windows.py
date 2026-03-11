"""Window enumeration and selection routes."""

from fastapi import APIRouter
from services.background_service import selector
from config.time_utils import current_timestamp

router = APIRouter(prefix="", tags=["windows"])


@router.get("/windows")
def list_windows():
    """
    List all available windows.
    
    Returns:
        list: List of dictionaries with hwnd, title, and process for each window
    """
    wins = selector.enumerate_windows()
    return [{"hwnd": int(h), "title": t, "process": p} for (h, t, p) in wins]


@router.get("/ping")
def api_ping():
    """
    Lightweight health endpoint useful for debugging connectivity.
    
    Returns:
        dict: Status and timestamp
    """
    return {"ok": True, "ts": current_timestamp()}


__all__ = ["router"]
