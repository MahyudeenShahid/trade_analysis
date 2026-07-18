"""Rule 12 REST API routes."""

import asyncio
from fastapi import APIRouter, Depends, HTTPException
from api.dependencies import require_api_key

router = APIRouter(prefix="", tags=["ibkr"])


def _persist_r12_config(hwnd: int, config: dict):
    """Save R12 config into the bot's meta field so it survives server restarts."""
    try:
        from db.queries import get_bot_db_entry, upsert_bot_settings
        row = get_bot_db_entry(hwnd) or {}
        existing_meta = row.get('meta') or {}
        if isinstance(existing_meta, str):
            import json
            try:
                existing_meta = json.loads(existing_meta)
            except Exception:
                existing_meta = {}
        if not isinstance(existing_meta, dict):
            existing_meta = {}
        existing_meta['r12_config'] = config
        upsert_bot_settings(hwnd, {'meta': existing_meta})
        
        # Sync to in-memory bot registry to update UI badges immediately
        try:
            from services.bot_registry import list_bots_by_hwnd, update_bot
            for b in list_bots_by_hwnd(hwnd):
                bid = b.get('bot_id') or b.get('id')
                if bid:
                    update_bot(bid, {'meta': existing_meta})
        except Exception:
            pass
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[R12] Failed to persist config for hwnd={hwnd}: {e}")


def load_r12_config_from_db(hwnd: int) -> dict | None:
    """Load R12 config from DB meta for this bot. Returns None if not set."""
    try:
        from db.queries import get_bot_db_entry
        row = get_bot_db_entry(hwnd) or {}
        meta = row.get('meta') or {}
        if isinstance(meta, str):
            import json
            try:
                meta = json.loads(meta)
            except Exception:
                return None
        return meta.get('r12_config') if isinstance(meta, dict) else None
    except Exception:
        return None


@router.post("/rule12/configure")
async def rule12_configure(payload: dict, _auth=Depends(require_api_key)):
    """
    Enable or disable Rule 12 for a bot, and set its parameters.
    """
    from trading.rules_tape_meter import configure_r12, r12_state_for_frontend
    hwnd = int(payload.get('hwnd') or 0)
    if hwnd <= 0:
        raise HTTPException(status_code=400, detail='hwnd required')

    enabled = bool(payload.get('enabled', False))
    stop_loss_pct = float(payload.get('stop_loss_pct') or 0.0)
    always_sell_on_profit = bool(payload.get('always_sell_on_profit', False))

    configure_r12(
        hwnd,
        enabled=enabled,
        stop_loss_pct=stop_loss_pct,
        always_sell_on_profit=always_sell_on_profit,
    )

    # Persist to DB so settings survive server restart
    _persist_r12_config(hwnd, {
        'enabled': enabled,
        'stop_loss_pct': stop_loss_pct,
        'always_sell_on_profit': always_sell_on_profit,
    })

    return {'ok': True, 'state': r12_state_for_frontend(hwnd)}


@router.get("/rule12/state/{hwnd}")
async def rule12_state(hwnd: int, _auth=Depends(require_api_key)):
    """Return current R12 runtime state for a bot (position, trend, P&L, status, etc.)."""
    from trading.rules_tape_meter import r12_state_for_frontend
    return r12_state_for_frontend(hwnd)
