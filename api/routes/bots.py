"""Bot management and persistence routes."""

import json
import os
import shutil
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from api.dependencies import require_api_key
from db.queries import query_records
from db.connection import DB_LOCK, DB_PATH
from services.capture_manager import manager_services

router = APIRouter(prefix="", tags=["bots"])


@router.get("/bots")
def api_bots(_auth: bool = Depends(require_api_key)):
    """
    Return all stored bot rows from the database.
    
    Returns:
        list: Bot records with parsed meta JSON
    """
    try:
        rows = query_records("SELECT * FROM bots ORDER BY hwnd")
        for r in rows:
            try:
                if r.get('meta'):
                    r['meta'] = json.loads(r['meta'])
                else:
                    r['meta'] = {}
            except Exception:
                r['meta'] = {}
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/bots/{hwnd}")
def api_delete_bot(hwnd: int, _auth: bool = Depends(require_api_key)):
    """
    Delete a bot row from DB and remove its screenshots folder.
    
    Stops the worker if it is currently running, removes the DB row in
    `bots` and deletes the `screenshots/hwnd_<hwnd>` folder (best-effort).
    
    Args:
        hwnd: Window handle to delete
        
    Returns:
        dict: Deletion status
    """
    try:
        # Stop worker if running
        try:
            manager_services.stop_worker(int(hwnd))
        except Exception:
            pass

        with DB_LOCK:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("DELETE FROM bots WHERE hwnd = ?", (int(hwnd),))
            conn.commit()
            conn.close()

        # Best-effort remove screenshots folder for this hwnd
        try:
            # typical worker folder: screenshots/hwnd_<hwnd>
            base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'screenshots')
            target = os.path.join(base, f'hwnd_{int(hwnd)}')
            if os.path.exists(target) and os.path.isdir(target):
                shutil.rmtree(target)
        except Exception:
            pass

        return {"deleted": True, "hwnd": int(hwnd)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router"]
