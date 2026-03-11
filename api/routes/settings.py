"""Runtime application settings routes."""

from pydantic import BaseModel
from fastapi import APIRouter, Depends

from api.dependencies import require_api_key
from config.time_utils import TIME_MODE_LOCAL, TIME_MODE_UTC, get_time_mode, set_time_mode

router = APIRouter(prefix="", tags=["settings"])


class TimeModeUpdate(BaseModel):
    mode: str


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


__all__ = ["router"]