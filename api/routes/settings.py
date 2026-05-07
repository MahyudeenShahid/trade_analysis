"""Runtime application settings routes."""

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_api_key
from config.time_utils import TIME_MODE_LOCAL, TIME_MODE_UTC, get_time_mode, set_time_mode
from db.queries import get_app_settings, set_app_setting

router = APIRouter(prefix="", tags=["settings"])


class TimeModeUpdate(BaseModel):
    mode: str


SIGNAL_SOURCE_SCREENSHOT = "screenshot"
SIGNAL_SOURCE_IBKR = "ibkr"
SIGNAL_SOURCE_ALLOWED = [SIGNAL_SOURCE_SCREENSHOT, SIGNAL_SOURCE_IBKR]


class SignalSourceUpdate(BaseModel):
    source: str


@router.get("/time_mode")
def api_get_time_mode(_auth: bool = Depends(require_api_key)):
    mode = get_time_mode()
    return {
        "mode": mode,
        "default": TIME_MODE_LOCAL,
        "available": [TIME_MODE_LOCAL, TIME_MODE_UTC],
    }


@router.post("/time_mode")
def api_set_time_mode(payload: TimeModeUpdate, _auth: bool = Depends(require_api_key)):
    mode = set_time_mode(payload.mode)
    return {
        "ok": True,
        "mode": mode,
        "default": TIME_MODE_LOCAL,
        "available": [TIME_MODE_LOCAL, TIME_MODE_UTC],
    }


@router.get("/signal_source")
def api_get_signal_source(_auth: bool = Depends(require_api_key)):
    cfg = get_app_settings()
    source = str(cfg.get("signal_source") or SIGNAL_SOURCE_SCREENSHOT).strip().lower()
    if source not in SIGNAL_SOURCE_ALLOWED:
        source = SIGNAL_SOURCE_SCREENSHOT
    return {
        "source": source,
        "default": SIGNAL_SOURCE_SCREENSHOT,
        "available": SIGNAL_SOURCE_ALLOWED,
    }


@router.post("/signal_source")
def api_set_signal_source(payload: SignalSourceUpdate, _auth: bool = Depends(require_api_key)):
    source = str(payload.source or "").strip().lower()
    if source not in SIGNAL_SOURCE_ALLOWED:
        raise HTTPException(status_code=400, detail="source must be 'screenshot' or 'ibkr'")
    set_app_setting("signal_source", source)
    return {
        "ok": True,
        "source": source,
        "default": SIGNAL_SOURCE_SCREENSHOT,
        "available": SIGNAL_SOURCE_ALLOWED,
    }


__all__ = ["router"]