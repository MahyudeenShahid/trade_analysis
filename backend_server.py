import asyncio
import base64
import json
import os
import sqlite3
import threading
import uuid
import shutil
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from background_capture_service import BackgroundCaptureService
from window_selector import WindowSelector
# Use the available simulator implementation. Earlier code referenced
# `trade_simulator_multi` but the repo provides `trade_simulator.py`.
from trade_simulator import TradeSimulator

# Use absolute path for database to ensure consistency across runs
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend_data.db")
UPLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
API_KEY = os.environ.get("BACKEND_API_KEY", "devkey")
DB_LOCK = threading.Lock()

app = FastAPI(title="Local Screenshot Backend")

# Serve uploaded files
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# Serve SPA UI if exists
WEB_UI_DIR = "web_ui"
if os.path.isdir(WEB_UI_DIR):
    app.mount("/static", StaticFiles(directory=WEB_UI_DIR), name="webui_static")

    @app.get("/")
    def serve_index():
        index_path = os.path.join(WEB_UI_DIR, "index.html")
        if not os.path.exists(index_path):
            return JSONResponse(status_code=404, content={"detail": "UI not found"})
        return FileResponse(index_path)


def require_api_key(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    key = authorization.split(" ", 1)[1].strip()
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return True


def _row_to_dict(row: sqlite3.Row):
    return {k: row[k] for k in row.keys()}


def query_records(sql: str, params: tuple = ()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_latest_record():
    rows = query_records("SELECT * FROM records ORDER BY ts DESC LIMIT 1")
    return rows[0] if rows else None


# CORS configuration: allow listing for production, with a DEV override
_dev_allow_all = os.environ.get("DEV_ALLOW_ALL_CORS", "0") in ("1", "true", "True")
# Optional comma-separated origins for dev (e.g. "https://marketview1.netlify.app,http://localhost:5173")
_dev_allow_origins = os.environ.get("DEV_ALLOW_ORIGINS")
if _dev_allow_all:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    if _dev_allow_origins:
        # split and strip
        try:
            origins = [o.strip() for o in _dev_allow_origins.split(",") if o.strip()]
        except Exception:
            origins = []
    else:
        origins = [
            "https://brilliant-lollipop-2620b1.netlify.app",
            "https://electrotropic-uselessly-lashawna.ngrok-free.dev",
            "http://localhost:3000",
            "https://marketview1.netlify.app",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
        ]

    app.add_middleware(
      CORSMiddleware,
      allow_origins=origins,
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
    )


@app.middleware("http")
async def log_requests(request, call_next):
    try:
        print(f"[HTTP] {request.method} {request.url}")
    except Exception:
        pass
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        print(f"[HTTP] handler error: {e}")
        raise


class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket):
        try:
            self.active.remove(websocket)
        except ValueError:
            pass

    async def broadcast(self, message: str):
        to_remove = []
        for ws in list(self.active):
            try:
                await ws.send_text(message)
            except Exception:
                to_remove.append(ws)
        for ws in to_remove:
            self.disconnect(ws)


manager = ConnectionManager()
service = BackgroundCaptureService()
selector = WindowSelector()


class CaptureManager:
    """Manage multiple BackgroundCaptureService instances keyed by hwnd."""

    def __init__(self):
        # map hwnd (int) -> BackgroundCaptureService
        self._services = {}
        self._lock = threading.Lock()

    def start_worker(self, hwnd: int, interval: float = 1.0, bring_to_foreground: Optional[bool] = None):
        with self._lock:
            if hwnd in self._services:
                # already running for this hwnd
                return False
            svc = BackgroundCaptureService()
            # use per-hwnd folder to avoid filename collisions
            out_folder = os.path.join(svc.capture.output_folder, f"hwnd_{hwnd}")
            try:
                os.makedirs(out_folder, exist_ok=True)
                svc.capture.set_output_folder(out_folder)
            except Exception:
                pass
            if bring_to_foreground is not None:
                try:
                    svc.capture.bring_to_foreground = bool(bring_to_foreground)
                except Exception:
                    pass
            svc.set_interval(max(0.5, float(interval)))
            if not svc.set_target_window(hwnd):
                return False
            # Apply any persisted per-bot crop settings from DB before starting
            try:
                bot_row = get_bot_db_entry(hwnd)
                if bot_row and isinstance(bot_row.get('meta'), dict):
                    crop = bot_row.get('meta', {}).get('crop')
                    if isinstance(crop, dict):
                        if 'left' in crop:
                            try: svc.capture.left_crop_frac = float(crop.get('left'))
                            except Exception: pass
                        if 'right' in crop:
                            try: svc.capture.right_crop_frac = float(crop.get('right'))
                            except Exception: pass
                        if 'top' in crop:
                            try: svc.capture.top_crop_frac = float(crop.get('top'))
                            except Exception: pass
                        if 'bottom' in crop:
                            try: svc.capture.bottom_crop_frac = float(crop.get('bottom'))
                            except Exception: pass
            except Exception:
                pass
            started = svc.start()
            if started:
                self._services[hwnd] = svc
            return started

    def stop_worker(self, hwnd: int):
        with self._lock:
            svc = self._services.get(hwnd)
            if not svc:
                return False
            try:
                svc.stop()
            except Exception:
                pass
            try:
                del self._services[hwnd]
            except Exception:
                pass
            return True

    def list_workers(self):
        with self._lock:
            return list(self._services.keys())

    def iter_services(self):
        """Yield (hwnd, service) pairs for all managed services."""
        with self._lock:
            for hwnd, svc in list(self._services.items()):
                yield hwnd, svc

    def get_worker(self, hwnd: int):
        with self._lock:
            return self._services.get(hwnd)

    def all_statuses(self):
        out = []
        with self._lock:
            for hwnd, svc in list(self._services.items()):
                try:
                    st = svc.get_status()
                except Exception:
                    st = {}
                out.append({"hwnd": int(hwnd), "status": st, "last_result": st.get('last_result') if isinstance(st, dict) else None})
        return out


manager_services = CaptureManager()


def _persist_trade_as_record(trade: dict):
    """Persist trade into `records` table."""
    try:
        meta = trade.get("meta") or {}
        try:
            if isinstance(meta, str):
                meta = json.loads(meta)
        except Exception:
            pass

        # Prefer explicit fields if present; otherwise try common meta keys
        buy_price = trade.get("buy_price") or meta.get("entry_price") or None
        sell_price = trade.get("sell_price") or meta.get("exit_price") or None
        buy_time = trade.get("buy_time") or meta.get("entry_time") or None
        sell_time = trade.get("sell_time") or meta.get("exit_time") or None

        # If the trade uses a generic `price` and `ts` fields (common shape),
        # infer buy/sell values from them based on direction when explicit
        # buy/sell fields are missing. Also accept `meta.price` / `meta.ts`.
        try:
            # helper to read common price/time keys
            price_in_trade = trade.get('price')
            time_in_trade = trade.get('ts') or trade.get('time')
            price_in_meta = None
            time_in_meta = None
            if isinstance(meta, dict):
                price_in_meta = meta.get('price') or meta.get('p')
                time_in_meta = meta.get('ts') or meta.get('time') or meta.get('timestamp')

            # if direction explicit, favor it
            direction = (trade.get('direction') or (meta.get('direction') if isinstance(meta, dict) else None) or '').lower()
            if direction == 'buy':
                if buy_price is None:
                    buy_price = price_in_trade if price_in_trade is not None else price_in_meta
                if buy_time is None:
                    buy_time = time_in_trade if time_in_trade is not None else time_in_meta
            elif direction == 'sell':
                if sell_price is None:
                    sell_price = price_in_trade if price_in_trade is not None else price_in_meta
                if sell_time is None:
                    sell_time = time_in_trade if time_in_trade is not None else time_in_meta
            else:
                # no explicit direction: if only price/time exist, consider them as buy by default
                if buy_price is None and (price_in_trade is not None or price_in_meta is not None):
                    buy_price = price_in_trade if price_in_trade is not None else price_in_meta
                if buy_time is None and (time_in_trade is not None or time_in_meta is not None):
                    buy_time = time_in_trade if time_in_trade is not None else time_in_meta
        except Exception:
            pass

        # If this is a sell event and buy info wasn't provided, try to find
        # the matching last buy for the same ticker from the in-memory trader
        # state so we can persist a paired record (buy+sell) for history UI.
        try:
            if (trade.get("direction") == "sell") and (buy_price is None):
                tk = trade.get("ticker")
                if tk and hasattr(trader, 'tickers') and tk in trader.tickers:
                    hist = trader.tickers[tk].get('trade_history', [])
                    # Find last buy before this sell
                    sell_ts = trade.get('ts')
                    candidate = None
                    for t in reversed(hist):
                        if t.get('direction') == 'buy':
                            # If timestamps exist, ensure buy occurred before sell when possible
                            if sell_ts and t.get('ts'):
                                try:
                                    if t.get('ts') <= sell_ts:
                                        candidate = t
                                        break
                                except Exception:
                                    candidate = t
                                    break
                            else:
                                candidate = t
                                break
                    if candidate:
                        buy_price = buy_price or candidate.get('price')
                        buy_time = buy_time or candidate.get('ts')
        except Exception:
            # Non-fatal; proceed without paired info if lookup fails
            pass

        ts = trade.get("ts") or (datetime.utcnow().isoformat() + 'Z')

        # If this is a SELL event, try to find an existing buy record in DB
        # (same ticker, sell_time IS NULL) and update it with sell info so
        # pairing survives restarts. Otherwise insert a record as usual.
        if trade.get("direction") == "sell":
            try:
                with DB_LOCK:
                    conn = sqlite3.connect(DB_PATH)
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT id, meta FROM records WHERE ticker = ? AND (sell_time IS NULL OR sell_time = '') ORDER BY ts DESC LIMIT 1",
                        (trade.get("ticker"),),
                    )
                    row = cur.fetchone()
                    if row:
                        rec_id = row["id"]
                        # merge meta JSONs if possible
                        existing_meta = {}
                        try:
                            existing_meta = json.loads(row["meta"]) if row["meta"] else {}
                        except Exception:
                            existing_meta = {}
                        # merge without overwriting existing buy info when present
                        merged_meta = existing_meta.copy()
                        try:
                            # trade may contain latest sell info
                            merged_meta.update(trade)
                        except Exception:
                            pass

                        # If we have buy info (from candidate lookup or merged_meta), ensure DB buy fields are set
                        try:
                            # prefer values we computed earlier, fall back to merged_meta if present
                            db_buy_price = buy_price or merged_meta.get('buy_price') or merged_meta.get('entry') or merged_meta.get('price') if merged_meta.get('direction') == 'buy' else buy_price or merged_meta.get('buy_price')
                        except Exception:
                            db_buy_price = buy_price
                        try:
                            db_buy_time = buy_time or merged_meta.get('buy_time') or merged_meta.get('entry_time') or merged_meta.get('ts')
                        except Exception:
                            db_buy_time = buy_time

                        # compute profit if possible
                        computed_profit = None
                        try:
                            sp = sell_price if sell_price is not None else merged_meta.get('price') if merged_meta.get('direction') == 'sell' else None
                            bp = db_buy_price
                            if sp is not None and bp is not None:
                                computed_profit = float(sp) - float(bp)
                                # also expose in merged_meta
                                merged_meta['profit'] = computed_profit
                        except Exception:
                            computed_profit = merged_meta.get('profit') if isinstance(merged_meta, dict) else None

                        # Perform update: set buy_price, buy_time, sell_price, sell_time, meta
                        cur.execute(
                            "UPDATE records SET buy_price = ?, buy_time = ?, sell_price = ?, sell_time = ?, meta = ? WHERE id = ?",
                            (
                                db_buy_price,
                                db_buy_time,
                                sell_price,
                                sell_time or ts,
                                json.dumps(merged_meta),
                                rec_id,
                            ),
                        )
                        conn.commit()
                        conn.close()
                        return
                    conn.close()
            except Exception as e:
                print(f"Failed DB-driven pairing update: {e}")

        # Fallback: insert a fresh record (handles buys and unmatched sells)
        obs = {
            "ts": ts,
            "image_path": None,
            "name": trade.get("ticker") or f"trade_{trade.get('direction')}",
            "ticker": trade.get("ticker"),
            "price": str(trade.get("price")) if trade.get("price") is not None else None,
            "trend": trade.get("direction"),
            "buy_price": buy_price,
            "sell_price": sell_price,
            "buy_time": buy_time,
            "sell_time": sell_time,
            "meta": trade,
        }
        # If both buy and sell price are known, compute profit and include in meta
        try:
            b = obs.get('buy_price')
            s = obs.get('sell_price')
            if b is not None and s is not None:
                try:
                    p = float(s) - float(b)
                    if isinstance(obs.get('meta'), dict):
                        obs['meta']['profit'] = p
                    else:
                        # ensure meta is a dict with profit
                        try:
                            m = json.loads(obs['meta']) if isinstance(obs.get('meta'), str) else {}
                        except Exception:
                            m = {}
                        m['profit'] = p
                        obs['meta'] = m
                except Exception:
                    pass
        except Exception:
            pass
        save_observation(obs)
    except Exception as e:
        print(f"Failed to persist trade: {e}")


trader = TradeSimulator(on_trade=_persist_trade_as_record)  # multi-ticker simulator


def init_db():
    print(f"[Database] Initializing database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            image_path TEXT,
            name TEXT,
            ticker TEXT,
            price TEXT,
            trend TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            image_path TEXT,
            name TEXT,
            ticker TEXT,
            price TEXT,
            trend TEXT,
            buy_price REAL,
            sell_price REAL,
            buy_time TEXT,
            sell_time TEXT,
            meta TEXT
        )
        """
    )
    # Migration: ensure new columns exist
    cur.execute("PRAGMA table_info(records)")
    existing = [r[1] for r in cur.fetchall()]
    additions = [
        ("buy_price", "REAL"),
        ("sell_price", "REAL"),
        ("buy_time", "TEXT"),
        ("sell_time", "TEXT"),
    ]
    for col, typ in additions:
        if col not in existing:
            try:
                cur.execute(f"ALTER TABLE records ADD COLUMN {col} {typ}")
            except Exception:
                pass

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            ticker TEXT,
            action TEXT,
            qty REAL,
            price REAL,
            profit REAL,
            meta TEXT
        )
        """
    )
    # Bots table: store per-worker bot metadata (keyed by hwnd)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bots (
            hwnd INTEGER PRIMARY KEY,
            name TEXT,
            ticker TEXT,
            total_pnl REAL,
            open_direction TEXT,
            open_price REAL,
            open_time TEXT,
            meta TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    os.makedirs(UPLOADS_DIR, exist_ok=True)


def upsert_bot_from_last_result(hwnd: int, last: dict):
    """Insert or update a bots table row based on the worker's last_result payload."""
    try:
        if not isinstance(hwnd, int):
            hwnd = int(hwnd)
    except Exception:
        return
    try:
        name = last.get('name') if isinstance(last, dict) else None
    except Exception:
        name = None

    try:
        ticker = last.get('ticker') or (last.get('meta') and isinstance(last.get('meta'), dict) and last.get('meta').get('ticker'))
    except Exception:
        ticker = None

    # total_pnl: prefer meta.profit if present
    total_pnl = None
    try:
        meta = last.get('meta') if isinstance(last, dict) else {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        total_pnl = meta.get('profit') if isinstance(meta, dict) else None
    except Exception:
        total_pnl = None

    open_direction = None
    open_price = None
    open_time = None
    try:
        if isinstance(meta, dict):
            # Normalize common fields
            open_direction = meta.get('direction') or meta.get('trend')
            open_price = meta.get('buy_price') or meta.get('entry_price') or meta.get('price')
            open_time = meta.get('buy_time') or meta.get('entry_time') or meta.get('ts')
    except Exception:
        pass

    # Upsert into DB
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            # Check existing
            cur.execute("SELECT hwnd FROM bots WHERE hwnd = ?", (hwnd,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE bots SET name = ?, ticker = ?, total_pnl = ?, open_direction = ?, open_price = ?, open_time = ?, meta = ? WHERE hwnd = ?",
                    (
                        name,
                        ticker,
                        float(total_pnl) if total_pnl is not None else None,
                        open_direction,
                        float(open_price) if open_price is not None else None,
                        open_time,
                        json.dumps(meta) if isinstance(meta, dict) else json.dumps({}),
                        hwnd,
                    ),
                )
            else:
                cur.execute(
                    "INSERT INTO bots (hwnd, name, ticker, total_pnl, open_direction, open_price, open_time, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        hwnd,
                        name,
                        ticker,
                        float(total_pnl) if total_pnl is not None else None,
                        open_direction,
                        float(open_price) if open_price is not None else None,
                        open_time,
                        json.dumps(meta) if isinstance(meta, dict) else json.dumps({}),
                    ),
                )
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"Failed to upsert bot for hwnd {hwnd}: {e}")


def get_bot_db_entry(hwnd: int):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM bots WHERE hwnd = ?", (int(hwnd),))
            r = cur.fetchone()
            conn.close()
            if not r:
                return None
            out = {k: r[k] for k in r.keys()}
            # parse meta JSON
            try:
                out['meta'] = json.loads(out.get('meta') or '{}')
            except Exception:
                out['meta'] = {}
            return out
    except Exception:
        return None


def save_observation(obs: dict):
    """Persist a record to DB thread-safely and prune older than 7 days."""
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO records (ts, image_path, name, ticker, price, trend, buy_price, sell_price, buy_time, sell_time, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                obs.get("ts"),
                obs.get("image_path"),
                obs.get("name"),
                obs.get("ticker"),
                obs.get("price"),
                obs.get("trend"),
                obs.get("buy_price"),
                obs.get("sell_price"),
                obs.get("buy_time"),
                obs.get("sell_time"),
                json.dumps(obs.get("meta", {})) if obs.get("meta") is not None else None,
            ),
        )
        conn.commit()
        # prune older than 7 days (use UTC 'Z' suffixed ISO strings)
        cutoff = datetime.utcnow() - timedelta(days=7)
        cur.execute("DELETE FROM records WHERE ts < ?", (cutoff.isoformat() + 'Z',))
        conn.commit()
        conn.close()


async def broadcaster_loop():
    while True:
        try:
            # collect single-service status (backwards-compatible)
            status = service.get_status()

            # collect per-worker statuses and screenshots
            workers_payload = []
            try:
                for hwnd, svc in manager_services.iter_services():
                    try:
                        st = svc.get_status()
                    except Exception:
                        st = {}
                    last = (st.get('last_result') or {}) if isinstance(st, dict) else {}
                    image_b64 = None
                    img_path = last.get('image_path')
                    if img_path and os.path.exists(img_path):
                        try:
                            with open(img_path, 'rb') as f:
                                image_b64 = base64.b64encode(f.read()).decode('ascii')
                        except Exception:
                            image_b64 = None

                    # update trader auto signals if worker produced price/ticker
                    try:
                        trend = last.get('trend') or ''
                        price = last.get('price') or last.get('price_value') or None
                        ticker = last.get('ticker') or None
                        if price and ticker:
                            trader.on_signal(trend, price, ticker, auto=True)
                    except Exception:
                        pass

                    workers_payload.append({
                        'hwnd': int(hwnd),
                        'status': st or {},
                        'screenshot_b64': image_b64,
                        'last_result': last,
                    })

                    # Persist summary info about this worker into bots table
                    try:
                        upsert_bot_from_last_result(hwnd, last or {})
                    except Exception:
                        pass

                    # Keep only the most recent screenshot per-worker to save disk
                    try:
                        if hasattr(svc, 'capture') and hasattr(svc.capture, 'clear_screenshots'):
                            svc.capture.clear_screenshots(keep_last_n=1)
                    except Exception:
                        pass
            except Exception:
                pass

            # Also handle the legacy single-service screenshot/status
            image_b64 = None
            try:
                last = status.get('last_result') or {}
                img_path = last.get('image_path')
                if img_path and os.path.exists(img_path):
                    with open(img_path, 'rb') as f:
                        image_b64 = base64.b64encode(f.read()).decode('ascii')
                # update trader auto signals for legacy service
                try:
                    trend = last.get('trend') or ''
                    price = last.get('price') or last.get('price_value') or None
                    ticker = last.get('ticker') or None
                    if price and ticker:
                        trader.on_signal(trend, price, ticker, auto=True)
                except Exception:
                    pass
            except Exception:
                image_b64 = None

            payload = {
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'status': status,
                'workers': workers_payload,
                'trade_summary': trader.summary(),
                'screenshot_b64': image_b64,
            }

            # cleanup screenshots for legacy single service
            try:
                service.capture.clear_screenshots(keep_last_n=1)
            except Exception:
                pass

            await manager.broadcast(json.dumps(payload))
        except Exception as e:
            print("Broadcaster loop error:", e)
        await asyncio.sleep(1)


@app.on_event("startup")
async def startup_event():
    init_db()
    asyncio.create_task(broadcaster_loop())


@app.get("/windows")
def list_windows():
    wins = selector.enumerate_windows()
    return [{"hwnd": int(h), "title": t, "process": p} for (h, t, p) in wins]


@app.get("/ping")
def api_ping():
    """Lightweight health endpoint useful for debugging connectivity."""
    return {"ok": True, "ts": datetime.utcnow().isoformat() + 'Z'}


@app.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    ticker: Optional[str] = Form(None),
    price: Optional[str] = Form(None),
    trend: Optional[str] = Form(None),
    meta: Optional[str] = Form(None),
    _auth: bool = Depends(require_api_key),
):
    """Accepts multipart/form-data and triggers trade automatically."""
    ts = datetime.utcnow().isoformat() + 'Z'
    filename = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}_{os.path.basename(file.filename)}"
    dest = os.path.join(UPLOADS_DIR, filename)
    try:
        with open(dest, "wb") as out:
            shutil.copyfileobj(file.file, out)
    finally:
        try:
            file.file.close()
        except Exception:
            pass

    record = {
        "ts": ts,
        "image_path": dest,
        "name": name,
        "ticker": ticker,
        "price": price,
        "trend": trend,
        "meta": json.loads(meta) if meta else {},
    }

    # Persist in DB
    save_observation(record)

    # Trigger trade automatically for this ticker
    if price and trend and ticker:
        trader.on_signal(trend, price, ticker, auto=True)

    return {"id": uuid.uuid4().hex, "image_url": f"/uploads/{filename}", "ts": ts}


@app.post("/manual_trade")
def api_manual_trade(trade: dict, _auth: bool = Depends(require_api_key)):
    """
    Accept a manual trade JSON payload and persist it to the records table.

    Expected payload: a JSON object representing a trade, e.g.
    { "ticker": "TSLA", "price": 123.45, "direction": "buy", "ts": "...", "meta": {...} }
    """
    try:
        if not isinstance(trade, dict):
            raise HTTPException(status_code=400, detail="trade must be a JSON object")
        # Persist the trade using existing helper
        _persist_trade_as_record(trade)
        # Optionally trigger trader signals if applicable
        try:
            trend = (trade.get('direction') or '').lower()
            price = trade.get('price')
            ticker = trade.get('ticker')
            # If explicit buy/sell direction provided, directly record in simulator
            if trend in ('buy', 'sell') and price is not None and ticker:
                try:
                    if trend == 'buy':
                        trader._buy(ticker, float(price))
                    else:
                        trader._sell(ticker, float(price))
                except Exception:
                    # fallback: try signaling with mapped trend
                    mapped = 'up' if trend == 'buy' else 'down'
                    try:
                        trader.on_signal(mapped, price, ticker, auto=True)
                    except Exception:
                        pass
            else:
                # allow other trend naming (e.g., 'up'/'down') to be handled by simulator
                if trend and price and ticker:
                    try:
                        trader.on_signal(trend, price, ticker, auto=True)
                    except Exception:
                        pass
        except Exception:
            pass
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/latest")
def api_latest():
    rec = get_latest_record()
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "no records"})
    if rec.get("image_path"):
        rec["image_url"] = "/uploads/" + os.path.basename(rec["image_path"])
    return rec


@app.get("/history")
def api_history(
    days: int = 7,
    ticker: Optional[str] = None,
    start_ts: Optional[str] = None,
    end_ts: Optional[str] = None,
    trend: Optional[str] = None,
    limit: Optional[int] = None,
):
    params: List[object] = []
    clauses: List[str] = []

    if start_ts:
        clauses.append("ts >= ?")
        params.append(start_ts)
    else:
        cutoff = datetime.utcnow() - timedelta(days=days)
        clauses.append("ts >= ?")
        params.append(cutoff.isoformat() + 'Z')

    if end_ts:
        clauses.append("ts <= ?")
        params.append(end_ts)

    if ticker:
        clauses.append("ticker = ?")
        params.append(ticker)

    if trend:
        clauses.append("trend = ?")
        params.append(trend)

    where = " AND ".join(clauses) if clauses else "1=1"
    # If `limit` is provided, apply LIMIT clause. Otherwise return all
    # matching records (e.g. all trades from the last `days`). This
    # ensures the API can return all trades for the last 7 days when
    # the caller doesn't specify a limit.
    if limit is None:
        sql = f"SELECT * FROM records WHERE {where} ORDER BY ts DESC"
    else:
        sql = f"SELECT * FROM records WHERE {where} ORDER BY ts DESC LIMIT ?"
        params.append(int(limit))

    rows = query_records(sql, tuple(params))
    for r in rows:
        if r.get("image_path"):
            r["image_url"] = "/uploads/" + os.path.basename(r["image_path"])
    return rows


@app.get("/uploads/{filename:path}")
def api_uploads(filename: str):
    path = os.path.join(UPLOADS_DIR, filename)
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"detail": "file not found"})
    return FileResponse(path)


@app.get("/trades")
def api_trades(_auth: bool = Depends(require_api_key)):
    return trader.summary()


@app.post("/start")
def api_start(hwnd: int = None, interval: float = 1.0, bring_to_foreground: Optional[bool] = None):
    """
    Start background capture for a specific window handle.

    Optional query param `bring_to_foreground` can be provided to temporarily
    set whether the capture should bring the target window to the foreground
    before capturing. If omitted, the existing `service.capture.bring_to_foreground`
    value is used.
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
    return {"started": started, "bring_to_foreground": service.capture.bring_to_foreground}


@app.post("/start_multi")
def api_start_multi(hwnd: int = None, interval: float = 1.0, bring_to_foreground: Optional[bool] = None):
    """Start a background capture worker for a specific hwnd (multi-worker).

    This runs a dedicated BackgroundCaptureService instance per hwnd and
    isolates output into a subfolder `screenshots/hwnd_<hwnd>`.
    """
    if hwnd is None:
        raise HTTPException(status_code=400, detail="hwnd is required")
    if not selector.is_window_valid(hwnd):
        raise HTTPException(status_code=400, detail="Window handle invalid")

    started = manager_services.start_worker(int(hwnd), interval=float(interval), bring_to_foreground=bring_to_foreground)
    if not started:
        raise HTTPException(status_code=500, detail="Failed to start worker (maybe already running or invalid hwnd)")
    return {"started": True, "hwnd": int(hwnd)}


@app.post("/stop_multi")
def api_stop_multi(hwnd: int = None):
    """Stop a multi-worker capture by hwnd."""
    if hwnd is None:
        raise HTTPException(status_code=400, detail="hwnd is required")
    stopped = manager_services.stop_worker(int(hwnd))
    if not stopped:
        raise HTTPException(status_code=404, detail="Worker not found")
    return {"stopped": True, "hwnd": int(hwnd)}


@app.post("/settings/line_detect")
def api_set_line_detect(enabled: bool, _auth: bool = Depends(require_api_key)):
    try:
        service.set_enable_line_detect(bool(enabled))
        return {"enabled": service.enable_line_detect}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/settings/crop_factor")
def api_set_crop_factor(factor: float, _auth: bool = Depends(require_api_key)):
    try:
        if factor < 0.0 or factor > 1.0:
            raise HTTPException(status_code=400, detail="Crop factor must be between 0.0 and 1.0")
        # Backwards-compatible: set all edges to the provided factor
        try:
            service.capture.left_crop_frac = float(factor)
            service.capture.right_crop_frac = float(factor)
            service.capture.top_crop_frac = float(factor)
            service.capture.bottom_crop_frac = float(factor)
        except Exception:
            # best-effort assignment; ignore if attributes missing
            pass
        return {"left": service.capture.left_crop_frac, "right": service.capture.right_crop_frac, "top": service.capture.top_crop_frac, "bottom": service.capture.bottom_crop_frac}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/settings/crop")
def api_set_crop(left: Optional[float] = None, right: Optional[float] = None, top: Optional[float] = None, bottom: Optional[float] = None, _auth: bool = Depends(require_api_key)):
    """Set per-edge crop fractions (values between 0.0 and 1.0).

    Provide any subset of the parameters. Missing values are left unchanged.
    """
    try:
        def _validate(v):
            if v is None:
                return None
            try:
                f = float(v)
            except Exception:
                raise HTTPException(status_code=400, detail="Crop values must be numeric")
            if f < 0.0 or f > 1.0:
                raise HTTPException(status_code=400, detail="Crop values must be between 0.0 and 1.0")
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

        return {"left": getattr(service.capture, 'left_crop_frac', None), "right": getattr(service.capture, 'right_crop_frac', None), "top": getattr(service.capture, 'top_crop_frac', None), "bottom": getattr(service.capture, 'bottom_crop_frac', None)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/settings/bring_to_foreground")
def api_set_bring_to_foreground(enabled: bool, _auth: bool = Depends(require_api_key)):
    """Toggle whether capture temporarily brings the target window to foreground."""
    try:
        service.capture.bring_to_foreground = bool(enabled)
        return {"bring_to_foreground": service.capture.bring_to_foreground}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/stop")
def api_stop():
    service.stop()
    return {"stopped": True}


@app.post("/stop_all_workers")
def api_stop_all_workers(_auth: bool = Depends(require_api_key)):
    """Stop all active multi-worker capture services.

    Returns a list of hwnds that were successfully stopped and a count.
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


@app.get("/status")
def api_status():
    return service.get_status()


@app.get("/workers")
def api_workers(_auth: bool = Depends(require_api_key)):
    """Return list of active workers with status and last result (includes a base64 thumbnail when available)."""
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


@app.get("/bots")
def api_bots(_auth: bool = Depends(require_api_key)):
    """Return all stored bot rows."""
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


@app.delete("/bots/{hwnd}")
def api_delete_bot(hwnd: int, _auth: bool = Depends(require_api_key)):
    """Delete a bot row from DB and remove its screenshots folder.

    Stops the worker if it is currently running, removes the DB row in
    `bots` and deletes the `screenshots/hwnd_<hwnd>` folder (best-effort).
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
            base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
            target = os.path.join(base, f'hwnd_{int(hwnd)}')
            if os.path.exists(target) and os.path.isdir(target):
                shutil.rmtree(target)
        except Exception:
            pass

        return {"deleted": True, "hwnd": int(hwnd)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/workers/{hwnd}/crop")
def api_set_worker_crop(hwnd: int, left: Optional[float] = None, right: Optional[float] = None, top: Optional[float] = None, bottom: Optional[float] = None, _auth: bool = Depends(require_api_key)):
    """Set per-worker crop fractions for a specific worker's capture object.

    Values must be between 0.0 and 1.0. Provide any subset of parameters.
    """
    try:
        def _validate(v):
            if v is None:
                return None
            try:
                f = float(v)
            except Exception:
                raise HTTPException(status_code=400, detail="Crop values must be numeric")
            if f < 0.0 or f > 1.0:
                raise HTTPException(status_code=400, detail="Crop values must be between 0.0 and 1.0")
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
                            cur.execute("UPDATE bots SET meta = ? WHERE hwnd = ?", (json.dumps(meta), int(hwnd)))
                        else:
                            # insert with empty name/ticker and meta
                            cur.execute("INSERT INTO bots (hwnd, name, ticker, total_pnl, open_direction, open_price, open_time, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (int(hwnd), None, None, None, None, None, None, json.dumps(meta)))
                        conn.commit()
                        conn.close()
                    return {"hwnd": int(hwnd), "left": lf, "right": rf, "top": tf, "bottom": bf, "applied": "persisted"}
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Failed to persist crop for inactive worker: {e}")

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


@app.websocket("/")
async def websocket_root(websocket: WebSocket):
    # Accept connections made to the root path (some clients/tunnels connect here)
    try:
        print(f"[WS] incoming connection at / from {websocket.client}")
    except Exception:
        pass
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(10)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    try:
        print(f"[WS] incoming connection at /ws from {websocket.client}")
    except Exception:
        pass
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(10)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# Compatibility: re-export the refactored app
# ---------------------------------------------------------------------------
# The codebase has been refactored into `main.py` with multi-worker capture only.
# Keep `backend_server:app` working by delegating to the canonical app.
try:
    from main import app as _refactored_app
    app = _refactored_app
except Exception:
    # If something is wrong with the refactored app import, fall back to the
    # legacy app defined above so the module can still import for debugging.
    pass
