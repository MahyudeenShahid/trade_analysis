# Backend Scaling Recommendation

## Bottom Line

For this app, the best path is:

1. Keep the realtime backend on a single Uvicorn worker.
2. Apply targeted performance fixes first.
3. If you still need more headroom, split the read-heavy history API into a second service.
4. Do not move to PostgreSQL or Redis yet unless your deployment model changes.
5. Do not run `uvicorn main:app --workers 4` on the current architecture.

That is the highest-value, lowest-risk path for this repo as it exists today.

---

## What The Current Repo Actually Does

The current backend is not just a stateless FastAPI API. It is a stateful runtime that keeps important data structures in process memory:

- `services/capture_manager.py` keeps active capture workers in `manager_services`
- `services/bot_registry.py` keeps bot/session state in memory
- `trading/simulator.py` keeps the global `trader` instance in memory
- `ws/manager.py` keeps live WebSocket connections in memory
- `main.py` starts a broadcaster loop on startup inside the app process

This matters because many common scaling suggestions only work safely for stateless apps.

---

## What In Your Breakdown Is Correct

Your overall direction is good:

- SQLite is still a real bottleneck under concurrent reads and writes.
- The app does combine realtime capture, trading, history queries, and WebSocket delivery in one process.
- Some blocking synchronous work is happening in places that matter.
- Splitting realtime work from history work is a sensible next architecture if quick wins are not enough.
- PostgreSQL and Redis are possible later, but they are not the first move I would make for this app.

---

## What Needs To Be Corrected For This Repo

### 1. WAL mode is already enabled

`db/migrations.py` already sets:

- `PRAGMA journal_mode=WAL`
- `idx_records_ts ON records(ts DESC)`
- `idx_records_ts_bot ON records(ts DESC, bot_id)`
- `idx_records_ticker ON records(ticker)`

So WAL mode is not missing. It is already part of startup initialization.

### 2. Not every capture tick writes to SQLite

The capture loop mostly writes screenshots and CSV files.

The main SQLite writes are:

- trade persistence in `trading/simulator.py`
- uploaded ingest records in `api/routes/history.py`
- bot persistence/update paths in `db/queries.py`

So the database is important, but the system is not writing one DB row for every raw screenshot capture.

### 3. Not all sync DB calls block the event loop the same way

There is a subtle but important difference here:

- `api/routes/history.py` uses synchronous `def` handlers for `/history` and `/latest`
- FastAPI runs those sync handlers in a threadpool
- that means those routes do not directly block the async event loop thread

However:

- `ingest()` is `async def` and performs blocking file and DB work inline
- `ws/broadcaster.py` is an async loop but performs blocking file I/O and CPU work inline every second

So the repo does have async-blocking problems, but the biggest offender is not simply "all sqlite calls in FastAPI". The bigger issue is blocking work inside async code paths that run continuously.

### 4. Multiple Uvicorn workers are not safe on the current design

This is the most important correction.

Running:

```bash
uvicorn main:app --workers 4
```

would create four independent Python processes. Each process would get its own copy of:

- `manager_services`
- `trader`
- in-memory bot registry
- WebSocket connection manager
- startup broadcaster loop

That means:

- a worker started by one process would not exist in the others
- a bot created in one process would not be visible in the others unless persisted and reloaded everywhere
- WebSocket clients connected to one worker would not see in-memory events from another worker
- trade delta streaming would fragment across processes
- broadcaster loops would run independently in every worker

So `--workers 4` is not a safe quick win for this app. It would make behavior inconsistent unless you first redesign state ownership.

---

## The Real Bottlenecks In This Codebase

### 1. Blocking work inside the broadcaster loop

`ws/broadcaster.py` does a lot of work every second:

- iterates all capture services
- opens screenshot files from disk
- base64-encodes image bytes
- pulls bot state
- runs trading logic
- builds one large payload
- broadcasts to all connected clients

This work happens inside an async loop. That is one of the most likely hotspots in the current backend.

### 2. SQLite write serialization through `DB_LOCK`

`db/connection.py` defines a global `threading.Lock()`.

Write-related paths such as `save_observation()` and bot upserts use that lock. That means writes are serialized inside the process, even before SQLite's own locking behavior is considered.

That is not necessarily wrong, but it does cap write concurrency.

### 3. Current indexes are incomplete for actual history query patterns

The current history API commonly filters like this:

- `WHERE ts >= ? ORDER BY ts DESC`
- `WHERE bot_id = ? AND ts >= ? ORDER BY ts DESC`
- `WHERE ticker = ? AND ts >= ? ORDER BY ts DESC`

Existing indexes help, but `idx_records_ts_bot ON records(ts DESC, bot_id)` is not the best index for `WHERE bot_id = ? ORDER BY ts DESC` because the leading column is `ts`, not `bot_id`.

So index coverage is partially good, but not optimal for the selected-bot history use case.

### 4. Async ingest path still does blocking work inline

`api/routes/history.py::ingest()`:

- copies uploaded files synchronously
- calls `save_observation()` synchronously
- may call trading logic synchronously

That should be treated as a true async-path problem.

### 5. Screenshot payload strategy is expensive

The current broadcaster sends base64 image payloads. That is expensive in CPU, memory, and network terms compared with lighter alternatives such as:

- sending only image URLs
- sending small thumbnails only
- sending a changed-image event instead of full image data every second

For a live dashboard, this can matter as much as database tuning.

---

## Option Review

## Option A: Quick Wins

### Verdict

Recommended, but with one major correction: keep a single app worker.

### What I would do in Option A

1. Add the missing history indexes.

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_records_bot_id_ts ON records(bot_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_records_ticker_ts ON records(ticker, ts DESC);
```

Optional if trend filtering is common:

```sql
CREATE INDEX IF NOT EXISTS idx_records_trend_ts ON records(trend, ts DESC);
```

2. Add connection pragmas that improve SQLite behavior under load.

Recommended per-connection settings:

```sql
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
```

3. Move blocking work off async code paths.

High-value candidates:

- `save_observation()` when called from async handlers
- file copy work inside `ingest()`
- base64 image loading/encoding inside `ws/broadcaster.py`

4. Reduce WebSocket payload size.

Best improvement:

- stop base64-encoding full screenshots every second unless the image changed

Better long-term shape:

- send lightweight metadata over WebSocket
- fetch image by URL separately

5. Keep history pagination strict.

The existing paginated path is good. Make sure the frontend uses paginated requests instead of fetching giant unbounded history ranges.

### Expected benefit

This should give you the best cost-to-benefit ratio with minimal architecture risk.

### What not to do inside Option A

Do not add `--workers 4` yet.

That is the one suggestion in the original breakdown that I would explicitly reject for this repo.

---

## Option B: Split Into Two Services

### Verdict

Recommended as Phase 2 if quick wins are not enough.

### Why this fits your repo well

The current route organization already separates concerns reasonably well:

- capture/realtime logic is concentrated around capture routes, trader state, and WebSocket broadcasting
- history/file-serving logic is concentrated around history routes

So a service split can follow the repo's current boundaries.

### The right split for this app

Do not split into two equivalent app instances that both try to own everything.

Instead split by responsibility:

### Service A: Realtime Engine

Owns:

- capture workers
- trader state
- in-memory bot registry
- WebSocket broadcasting
- trade writes to SQLite
- worker lifecycle routes

Typical routes:

- `/start_multi`
- `/stop_multi`
- `/stop_all_workers`
- `/workers`
- `/ws`
- bot mutation endpoints

### Service B: History API

Owns:

- `/history`
- `/latest`
- `/screenshots`
- `/trade_screenshots/*`
- upload/static file serving related to history browsing

This service is read-heavy and can stay simple.

### Why this split works

- the realtime service remains single-owner for in-memory state
- the history service becomes isolated from live capture load
- both services can share the same SQLite database in WAL mode
- both services can share screenshot directories on disk

### Operational note

If you do this, the cleanest frontend setup is usually:

- one reverse proxy
- two backend upstreams
- frontend still talks to one public origin

That avoids frontend CORS complexity.

---

## Option C: PostgreSQL

### Verdict

Not the next step.

### Use PostgreSQL when one of these becomes true

- you need multiple backend instances safely
- you want remote deployment across machines
- write concurrency is materially higher than a single local SQLite file should handle
- you need stronger operational tooling around backups, analytics, or concurrent access

### Why I would not switch yet

Your bigger bottlenecks right now are:

- stateful single-process design
- blocking work in the broadcaster
- image payload size
- index tuning for history queries

Changing databases before fixing those will increase complexity faster than it increases performance.

---

## Option D: Redis Queue For Capture Jobs

### Verdict

Too early for this app.

Redis + worker queues makes sense when:

- you need job durability
- you need distributed workers
- you want retries and backpressure controls
- you are scheduling many independent jobs across machines

That is not the first scaling problem showing up in this repo.

---

## My Recommendation For Your App

## Best Choice Right Now

Use a corrected Option A first:

1. Stay single-worker.
2. Add the missing composite indexes.
3. Add `busy_timeout` and related connection tuning.
4. Offload blocking work from async paths.
5. Make WebSocket screenshot delivery lighter.

## Best Choice After That

If the app still slows down under real use, do Option B as a targeted split:

- keep one stateful realtime service
- split history into a second read-heavy service

## What I Would Not Recommend Yet

- multiple Uvicorn workers on the current app
- PostgreSQL as the first move
- Redis queue architecture

---

## Recommended Implementation Order

## Phase 1: Low-Risk Changes

Target files:

- `db/migrations.py`
- `db/queries.py`
- `api/routes/history.py`
- `ws/broadcaster.py`

Tasks:

1. Add `idx_records_bot_id_ts` and `idx_records_ticker_ts`.
2. Add `busy_timeout` and `synchronous=NORMAL` on connections.
3. Offload blocking work in `ingest()`.
4. Offload image load/base64 work in `broadcaster_loop()` or reduce image payload frequency.
5. Measure again.

## Phase 2: Service Split If Needed

Possible new entry points:

- `main_realtime.py`
- `main_history.py`

Tasks:

1. Move live worker and WebSocket routes to realtime service.
2. Move history read routes to history service.
3. Keep SQLite shared through WAL mode.
4. Put both behind one reverse proxy.

## Phase 3: Database Migration Only If Requirements Change

Move to PostgreSQL only when you actually need:

- cross-machine scaling
- multi-process shared backend state patterns
- heavier concurrent write workloads

---

## Final Recommendation

For this app, the best answer is not "Option A or B" in the abstract.

The best answer is:

- do Option A first
- but skip multi-worker Uvicorn because the app is stateful
- then do a clean realtime/history split if you still need more headroom

If I were maintaining this repo, that is the exact order I would follow.