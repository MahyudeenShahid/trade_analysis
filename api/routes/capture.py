"""Screen capture and worker management routes."""

import json
import os
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from api.dependencies import require_api_key
from services.capture_manager import manager_services
from services.background_service import service, selector
from db.connection import DB_LOCK, DB_PATH

router = APIRouter(prefix="", tags=["capture"])


@router.post("/start")
def api_start(
    hwnd: int = None,
    interval: float = 1.0,
    bring_to_foreground: Optional[bool] = None
):
    """
    Start background capture for a specific window handle (legacy single-worker mode).
    
    Args:
        hwnd: Window handle to capture
        interval: Capture interval in seconds
        bring_to_foreground: Whether to bring window to foreground before capture
        
    Returns:
        dict: Status of operation
    """
    if hwnd is None:
        raise HTTPException(status_code=400, detail="hwnd is required")
    if not selector.is_window_valid(hwnd):
        raise HTTPException(status_code=400, detail="Window handle invalid")

    # apply bring_to_foreground override if provided
    if bring_to_foreground is not None:
        try:
            service.capture.bring_to_foreground = bool(bring_to_foreground)
        except Exception:
            pass

    service.capture.set_output_folder("screenshots")
    service.set_interval(max(0.5, float(interval)))
    if not service.set_target_window(hwnd):
        raise HTTPException(status_code=500, detail="Failed to set target window")
    started = service.start()
    return {
        "started": started,
        "bring_to_foreground": service.capture.bring_to_foreground
    }


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


@router.post("/stop")
def api_stop():
    """Stop the legacy single-worker capture service."""
    service.stop()
    return {"stopped": True}


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


@router.get("/status")
def api_status():
    """Get status of the legacy single-worker service."""
    return service.get_status()


@router.get("/workers")
def api_workers(_auth: bool = Depends(require_api_key)):
    """
    Return list of active workers with status and last result.
    
    Includes base64 thumbnail when available and bot DB info.
    
    Returns:
        list: Worker status information
    """
    import base64
    from db.queries import get_bot_db_entry
    
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
            # also attach any DB-stored bot info for this hwnd
            bot_info = None
            try:
                bot_info = get_bot_db_entry(int(w.get('hwnd')))
            except Exception:
                bot_info = None
            out.append({
                'hwnd': int(w.get('hwnd')),
                'status': w.get('status') or {},
                'last_result': last,
                'screenshot_b64': img_b64,
                'bot': bot_info,
            })
    except Exception:
        pass
    return out


@router.post("/settings/line_detect")
def api_set_line_detect(enabled: bool, _auth: bool = Depends(require_api_key)):
    """Toggle line detection feature."""
    try:
        service.set_enable_line_detect(bool(enabled))
        return {"enabled": service.enable_line_detect}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/settings/crop_factor")
def api_set_crop_factor(factor: float, _auth: bool = Depends(require_api_key)):
    """
    Set crop factor for all edges (backwards-compatible).
    
    Args:
        factor: Crop factor between 0.0 and 1.0
        
    Returns:
        dict: Current crop settings for all edges
    """
    try:
        if factor < 0.0 or factor > 1.0:
            raise HTTPException(
                status_code=400,
                detail="Crop factor must be between 0.0 and 1.0"
            )
        # Backwards-compatible: set all edges to the provided factor
        try:
            service.capture.left_crop_frac = float(factor)
            service.capture.right_crop_frac = float(factor)
            service.capture.top_crop_frac = float(factor)
            service.capture.bottom_crop_frac = float(factor)
        except Exception:
            # best-effort assignment; ignore if attributes missing
            pass
        return {
            "left": service.capture.left_crop_frac,
            "right": service.capture.right_crop_frac,
            "top": service.capture.top_crop_frac,
            "bottom": service.capture.bottom_crop_frac
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/settings/crop")
def api_set_crop(
    left: Optional[float] = None,
    right: Optional[float] = None,
    top: Optional[float] = None,
    bottom: Optional[float] = None,
    _auth: bool = Depends(require_api_key)
):
    """
    Set per-edge crop fractions (values between 0.0 and 1.0).
    
    Provide any subset of the parameters. Missing values are left unchanged.
    
    Returns:
        dict: Current crop settings
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

        if lf is not None:
            try:
                service.capture.left_crop_frac = lf
            except Exception:
                pass
        if rf is not None:
            try:
                service.capture.right_crop_frac = rf
            except Exception:
                pass
        if tf is not None:
            try:
                service.capture.top_crop_frac = tf
            except Exception:
                pass
        if bf is not None:
            try:
                service.capture.bottom_crop_frac = bf
            except Exception:
                pass

        return {
            "left": getattr(service.capture, 'left_crop_frac', None),
            "right": getattr(service.capture, 'right_crop_frac', None),
            "top": getattr(service.capture, 'top_crop_frac', None),
            "bottom": getattr(service.capture, 'bottom_crop_frac', None)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/settings/bring_to_foreground")
def api_set_bring_to_foreground(
    enabled: bool,
    _auth: bool = Depends(require_api_key)
):
    """Toggle whether capture temporarily brings the target window to foreground."""
    try:
        service.capture.bring_to_foreground = bool(enabled)
        return {"bring_to_foreground": service.capture.bring_to_foreground}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
            # If the worker is not currently running, persist the crop
            # values to the bots table so they can be applied when the
            # worker starts. This helps the UI apply crops even when the
            # capture worker is temporarily stopped.
            try:
                with DB_LOCK:
                    conn = sqlite3.connect(DB_PATH)
                    cur = conn.cursor()
                    # ensure a row exists for this hwnd
                    cur.execute("SELECT hwnd, meta FROM bots WHERE hwnd = ?", (int(hwnd),))
                    row = cur.fetchone()
                    meta = {}
                    if row and row[1]:
                        try:
                            meta = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                        except Exception:
                            meta = {}
                    # attach crop values under meta.crop
                    if 'crop' not in meta or not isinstance(meta.get('crop'), dict):
                        meta['crop'] = {}
                    if lf is not None:
                        meta['crop']['left'] = lf
                    if rf is not None:
                        meta['crop']['right'] = rf
                    if tf is not None:
                        meta['crop']['top'] = tf
                    if bf is not None:
                        meta['crop']['bottom'] = bf

                    if row:
                        cur.execute(
                            "UPDATE bots SET meta = ? WHERE hwnd = ?",
                            (json.dumps(meta), int(hwnd))
                        )
                    else:
                        # insert with empty name/ticker and meta
                        cur.execute(
                            "INSERT INTO bots (hwnd, name, ticker, total_pnl, open_direction, open_price, open_time, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (int(hwnd), None, None, None, None, None, None, json.dumps(meta))
                        )
                    conn.commit()
                    conn.close()
                return {
                    "hwnd": int(hwnd),
                    "left": lf,
                    "right": rf,
                    "top": tf,
                    "bottom": bf,
                    "applied": "persisted"
                }
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to persist crop for inactive worker: {e}"
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
