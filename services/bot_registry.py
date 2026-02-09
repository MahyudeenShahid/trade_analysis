"""In-memory bot registry for session-scoped bots and settings."""

from threading import RLock


_LOCK = RLock()
_BOTS_BY_ID = {}
_HWND_INDEX = {}
_CROP_BY_HWND = {}


def _normalize_bot_id(bot_id):
    if bot_id is None:
        return None
    try:
        return str(bot_id).strip()
    except Exception:
        return None


def register_bot(bot):
    if not isinstance(bot, dict):
        return None
    bot_id = _normalize_bot_id(bot.get("bot_id") or bot.get("id"))
    if not bot_id:
        return None
    try:
        hwnd = int(bot.get("hwnd")) if bot.get("hwnd") is not None else None
    except Exception:
        hwnd = None
    with _LOCK:
        existing = _BOTS_BY_ID.get(bot_id, {})
        merged = {**existing, **bot}
        merged["bot_id"] = bot_id
        if hwnd is not None:
            merged["hwnd"] = hwnd
        _BOTS_BY_ID[bot_id] = merged
        if hwnd is not None:
            ids = _HWND_INDEX.get(hwnd, set())
            ids.add(bot_id)
            _HWND_INDEX[hwnd] = ids
        return merged


def update_bot(bot_id, changes):
    bot_id = _normalize_bot_id(bot_id)
    if not bot_id:
        return None
    if not isinstance(changes, dict):
        changes = {}
    with _LOCK:
        existing = _BOTS_BY_ID.get(bot_id)
        if not existing:
            merged = {**changes, "bot_id": bot_id}
        else:
            merged = {**existing, **changes, "bot_id": bot_id}
        if merged.get("hwnd") is not None:
            try:
                hwnd = int(merged.get("hwnd"))
                merged["hwnd"] = hwnd
                ids = _HWND_INDEX.get(hwnd, set())
                ids.add(bot_id)
                _HWND_INDEX[hwnd] = ids
            except Exception:
                pass
        _BOTS_BY_ID[bot_id] = merged
        return merged


def remove_bot(bot_id):
    bot_id = _normalize_bot_id(bot_id)
    if not bot_id:
        return False
    with _LOCK:
        bot = _BOTS_BY_ID.pop(bot_id, None)
        if bot and bot.get("hwnd") is not None:
            try:
                hwnd = int(bot.get("hwnd"))
                ids = _HWND_INDEX.get(hwnd, set())
                if bot_id in ids:
                    ids.remove(bot_id)
                if ids:
                    _HWND_INDEX[hwnd] = ids
                else:
                    _HWND_INDEX.pop(hwnd, None)
            except Exception:
                pass
        return True


def list_bots():
    with _LOCK:
        return list(_BOTS_BY_ID.values())


def get_bot(bot_id):
    bot_id = _normalize_bot_id(bot_id)
    if not bot_id:
        return None
    with _LOCK:
        return _BOTS_BY_ID.get(bot_id)


def list_bots_by_hwnd(hwnd):
    try:
        hwnd = int(hwnd)
    except Exception:
        return []
    with _LOCK:
        ids = _HWND_INDEX.get(hwnd, set())
        return [b for b in (_BOTS_BY_ID.get(i) for i in ids) if b]


def set_crop(hwnd, crop):
    try:
        hwnd = int(hwnd)
    except Exception:
        return None
    if not isinstance(crop, dict):
        return None
    with _LOCK:
        existing = _CROP_BY_HWND.get(hwnd, {})
        merged = {**existing, **crop}
        _CROP_BY_HWND[hwnd] = merged
        return merged


def get_crop(hwnd):
    try:
        hwnd = int(hwnd)
    except Exception:
        return None
    with _LOCK:
        return _CROP_BY_HWND.get(hwnd)


def clear_all():
    with _LOCK:
        _BOTS_BY_ID.clear()
        _HWND_INDEX.clear()
        _CROP_BY_HWND.clear()
