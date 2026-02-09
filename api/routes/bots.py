"""Session-scoped bot management routes (in-memory only)."""

from fastapi import APIRouter, Depends, HTTPException
from api.dependencies import require_api_key
from services.bot_registry import (
    register_bot,
    update_bot,
    remove_bot,
    list_bots,
    get_bot,
    clear_all,
)
from trading.simulator import clear_bot_state, clear_all_state

router = APIRouter(prefix="", tags=["bots"])


@router.get("/bots")
def api_bots(_auth: bool = Depends(require_api_key)):
    """Return all session bots (in-memory)."""
    try:
        return list_bots()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bots/{bot_id}")
def api_bot(bot_id: str, _auth: bool = Depends(require_api_key)):
    """Get a single bot by bot_id (session-only)."""
    try:
        row = get_bot(bot_id)
        if not row:
            raise HTTPException(status_code=404, detail="bot not found")
        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bots/upsert")
def api_bot_upsert(payload: dict, _auth: bool = Depends(require_api_key)):
    """Create/update a session bot (no DB persistence)."""
    try:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be an object")
        bot_id = payload.get('bot_id') or payload.get('id')
        if not bot_id:
            raise HTTPException(status_code=400, detail="bot_id is required")

        existing = get_bot(bot_id)
        if existing:
            row = update_bot(bot_id, payload)
        else:
            row = register_bot(payload)
        if not row:
            raise HTTPException(status_code=400, detail="failed to register bot")
        return {"ok": True, "bot": row}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/bots/{bot_id}")
def api_delete_bot(bot_id: str, _auth: bool = Depends(require_api_key)):
    """Remove a session bot by bot_id (no DB side-effects)."""
    try:
        removed = remove_bot(bot_id)
        if not removed:
            raise HTTPException(status_code=404, detail="bot not found")
        try:
            clear_bot_state(bot_id)
        except Exception:
            pass
        return {"deleted": True, "bot_id": bot_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bots/clear")
def api_clear_bots(_auth: bool = Depends(require_api_key)):
    """Clear all session bots."""
    try:
        clear_all()
        try:
            clear_all_state()
        except Exception:
            pass
        return {"cleared": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router"]
