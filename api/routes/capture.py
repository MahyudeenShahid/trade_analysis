"""Screen capture and worker management routes (multi-worker only)."""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from api.dependencies import require_api_key
from services.capture_manager import manager_services
from services.background_service import selector
from services.bot_registry import list_bots_by_hwnd, set_crop

router = APIRouter(prefix="", tags=["capture"])


@router.post("/start_multi")
def api_start_multi(
    hwnd: int = None,
    interval: float = 1.0,
    bring_to_foreground: Optional[bool] = None
):
    """
    Start a background capture worker for a specific hwnd (multi-worker mode).
    
    This runs a dedicated BackgroundCaptureService instance per hwnd and
    isolates output into a subfolder `screenshots/hwnd_<hwnd>`.
    
    Args:
        hwnd: Window handle to capture
        interval: Capture interval in seconds
        bring_to_foreground: Whether to bring window to foreground
        
    Returns:
        dict: Status with hwnd
    """
    if hwnd is None:
        raise HTTPException(status_code=400, detail="hwnd is required")
    if not selector.is_window_valid(hwnd):
        raise HTTPException(status_code=400, detail="Window handle invalid")

    if manager_services.get_worker(int(hwnd)):
        return {"started": True, "hwnd": int(hwnd), "already_running": True}

    started = manager_services.start_worker(
        int(hwnd),
        interval=float(interval),
        bring_to_foreground=bring_to_foreground
    )
    if not started:
        raise HTTPException(
            status_code=500,
            detail="Failed to start worker (maybe already running or invalid hwnd)"
        )
    return {"started": True, "hwnd": int(hwnd)}


@router.post("/set_capture_interval")
def api_set_capture_interval(hwnd: int = None, interval: float = 1.0):
    """
    Change the capture interval (in seconds) for a running worker.

    Args:
        hwnd: Window handle of the running worker
        interval: New capture interval in seconds (minimum 0.5)

    Returns:
        dict: Confirmed hwnd and interval
    """
    if hwnd is None:
        raise HTTPException(status_code=400, detail="hwnd is required")
    svc = manager_services.get_worker(int(hwnd))
    if not svc:
        raise HTTPException(status_code=404, detail="Worker not found")
    applied = max(0.5, float(interval))
    svc.set_interval(applied)
    return {"hwnd": int(hwnd), "interval": applied}


@router.post("/stop_multi")
def api_stop_multi(hwnd: int = None):
    """
    Stop a multi-worker capture by hwnd.
    
    Args:
        hwnd: Window handle to stop
        
    Returns:
        dict: Status with hwnd
    """
    if hwnd is None:
        raise HTTPException(status_code=400, detail="hwnd is required")
    stopped = manager_services.stop_worker(int(hwnd))
    if not stopped:
        raise HTTPException(status_code=404, detail="Worker not found")
    return {"stopped": True, "hwnd": int(hwnd)}


@router.post("/stop_all_workers")
def api_stop_all_workers(_auth: bool = Depends(require_api_key)):
    """
    Stop all active multi-worker capture services.
    
    Returns:
        dict: List of stopped hwnds and count
    """
    try:
        stopped = []
        # list_workers returns a list of hwnds
        for hw in manager_services.list_workers():
            try:
                ok = manager_services.stop_worker(int(hw))
                if ok:
                    stopped.append(int(hw))
            except Exception:
                # continue stopping others even if one fails
                continue
        return {"stopped": stopped, "count": len(stopped)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workers")
def api_workers(_auth: bool = Depends(require_api_key)):
    """
    Return list of active workers with status and last result.
    
    Includes base64 thumbnail when available and bot DB info.
    
    Returns:
        list: Worker status information
    """
    import base64
    
    out = []
    try:
        for w in manager_services.all_statuses():
            last = w.get('last_result') or {}
            img_b64 = None
            img_path = last.get('image_path')
            if img_path and os.path.exists(img_path):
                try:
                    with open(img_path, 'rb') as f:
                        img_b64 = base64.b64encode(f.read()).decode('ascii')
                except Exception:
                    img_b64 = None
            # attach any session bots for this hwnd
            bot_info = None
            bot_list = []
            try:
                bot_list = list_bots_by_hwnd(int(w.get('hwnd')))
                bot_info = bot_list[0] if bot_list else None
            except Exception:
                bot_info = None
                bot_list = []
            out.append({
                'hwnd': int(w.get('hwnd')),
                'status': w.get('status') or {},
                'last_result': last,
                'screenshot_b64': img_b64,
                'bot': bot_info,
                'bots': bot_list,
            })
    except Exception:
        pass
    return out


@router.post("/workers/{hwnd}/crop")
def api_set_worker_crop(
    hwnd: int,
    left: Optional[float] = None,
    right: Optional[float] = None,
    top: Optional[float] = None,
    bottom: Optional[float] = None,
    _auth: bool = Depends(require_api_key)
):
    """
    Set per-worker crop fractions for a specific worker's capture object.
    
    Values must be between 0.0 and 1.0. Provide any subset of parameters.
    If worker is not running, crop settings are persisted to DB.
    
    Returns:
        dict: Applied crop settings
    """
    try:
        def _validate(v):
            if v is None:
                return None
            try:
                f = float(v)
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail="Crop values must be numeric"
                )
            if f < 0.0 or f > 1.0:
                raise HTTPException(
                    status_code=400,
                    detail="Crop values must be between 0.0 and 1.0"
                )
            return f

        lf = _validate(left)
        rf = _validate(right)
        tf = _validate(top)
        bf = _validate(bottom)

        svc = manager_services.get_worker(int(hwnd))
        if not svc:
            try:
                crop = {}
                if lf is not None:
                    crop['left'] = lf
                if rf is not None:
                    crop['right'] = rf
                if tf is not None:
                    crop['top'] = tf
                if bf is not None:
                    crop['bottom'] = bf
                set_crop(int(hwnd), crop)
                return {
                    "hwnd": int(hwnd),
                    "left": lf,
                    "right": rf,
                    "top": tf,
                    "bottom": bf,
                    "applied": "cached"
                }
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to cache crop for inactive worker: {e}"
                )

        # Apply values if present
        if lf is not None:
            try:
                svc.capture.left_crop_frac = lf
            except Exception:
                pass
        if rf is not None:
            try:
                svc.capture.right_crop_frac = rf
            except Exception:
                pass
        if tf is not None:
            try:
                svc.capture.top_crop_frac = tf
            except Exception:
                pass
        if bf is not None:
            try:
                svc.capture.bottom_crop_frac = bf
            except Exception:
                pass

        return {
            "hwnd": int(hwnd),
            "left": getattr(svc.capture, 'left_crop_frac', None),
            "right": getattr(svc.capture, 'right_crop_frac', None),
            "top": getattr(svc.capture, 'top_crop_frac', None),
            "bottom": getattr(svc.capture, 'bottom_crop_frac', None),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router"]
