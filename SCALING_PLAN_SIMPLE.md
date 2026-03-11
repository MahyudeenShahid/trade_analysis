# Simple Scaling Plan For This Project

## 1. Short Answer

Yes, this project can be made faster.

The best next step is not to create many identical backend copies.
The best next step is:

1. Keep one live backend for screenshot capture, bot logic, trade decisions, and WebSocket updates.
2. Move history reading and screenshot browsing into a separate history service.
3. Make the live updates lighter so the backend sends less image data every second.

In simple words:

- one part should think and react in real time
- one part should answer history questions

That split matches how this project already works.

---

## 2. What I Checked

I reviewed both sides of the project:

- Backend in `trade_analysis`
- Frontend in `marketview`

Important backend areas I checked:

- `background_capture_service.py`
- `ws/broadcaster.py`
- `api/routes/history.py`
- `api/routes/capture.py`
- `services/capture_manager.py`
- `services/bot_registry.py`
- `db/migrations.py`
- `db/queries.py`
- `trading/simulator.py`

Important frontend areas I checked:

- `marketview/src/App.jsx`
- `marketview/src/components/HistoryPanel.jsx`
- `marketview/src/components/LivePreview.jsx`

---

## 3. How The System Works Today

### Backend (`trade_analysis`)

Today the backend is doing many jobs inside one running app:

1. It starts capture workers for each bot/window.
2. Each worker takes screenshots again and again.
3. It reads price/ticker/trend information from the window.
4. It decides whether to buy or sell.
5. It saves trade history into SQLite.
6. It serves history requests.
7. It serves screenshot files.
8. It sends live updates to the frontend through WebSocket.

So one backend process is trying to be:

- a camera
- a trader
- a history server
- a file server
- a live update server

That is why it starts becoming heavy.

### Frontend (`marketview`)

The frontend does three main things:

1. It connects to the backend WebSocket for live updates.
2. It asks for history pages from `/history`.
3. It loads trade screenshots later, only when needed.

This is good news because the frontend already has some smart behavior:

- history is paginated
- screenshots are lazy-loaded
- live trades are received through WebSocket instead of refreshing the whole page every second

So the frontend is not the main problem.
The heavier problem is what the backend has to do every second.

---

## 4. Your Expected Load In Simple Numbers

You mentioned:

- 10 separate bots
- each bot captures every 1 second
- 3000 trades per day
- each trade has around 30 to 40 screenshots

### Live capture load

10 bots x 1 screenshot per second = 10 screenshots every second

That means:

- 600 screenshots per minute
- 36,000 screenshots per hour
- 864,000 capture actions per day

Important note:

The project does clean up many temporary live screenshots, so it may not keep all of them forever on disk.
But the machine still has to do the work of capturing, saving, checking, and often reopening those images.

### Trade screenshot load

3000 trades x 30 to 40 screenshots each = 90,000 to 120,000 trade screenshots per day

This is a big amount of file work.

### What this means in normal language

The pressure is not only "API requests per second".
The bigger pressure is:

- screenshot creation
- disk read/write work
- image encoding
- repeating the same work for live preview and trade history

---

## 5. Where The Current Backend Gets Slow

### Problem 1: One app is doing too many jobs

Right now the same backend process is handling:

- live bots
- history
- screenshots
- live WebSocket updates
- trading logic

Simple example:

If one user opens the history page while 10 bots are running, the same backend is forced to answer history requests while also trying to keep live trading fast.

### Problem 2: The live broadcaster does heavy work every second

The broadcaster loop runs every second and does things like:

- check all workers
- open screenshot files from disk
- convert image bytes to base64 text
- gather bot state
- gather new trades
- send everything to connected clients

Simple example:

The image is already saved once, but then the backend opens it again, converts it again, and sends it again.
That repeated work becomes expensive.

### Problem 3: Full images over WebSocket are costly

Sending full screenshot data every second is heavy because:

- CPU is used to encode the image
- memory is used to hold the image text
- network bandwidth is used to send it
- the browser must decode it again

Simple example:

Instead of saying "the new image is at this address", the backend is trying to push the whole image again and again.

### Problem 4: History requests and screenshot browsing are mixed with live trading

The history side is read-heavy.
It needs to:

- query SQLite
- count records for pagination
- search screenshot folders
- return screenshot file paths

Simple example:

History is like asking a librarian to search old files.
Live trading is like a person making fast buy/sell decisions every second.
Those should not compete for attention in the same place.

### Problem 5: Current app state lives in memory

The running bots, WebSocket connections, and some session bot state are stored in memory inside the current Python process.

That means if you start many identical backend workers, they do not automatically share the same brain.

Simple example:

If you start 4 backend workers, it is not one smart manager with 4 helpers.
It is 4 separate managers, each with different memory.

That can create confusing behavior.

---

## 6. Important Warning: Do Not Scale This By Just Adding Many App Workers

It may look easy to run something like:

```bash
uvicorn main:app --workers 4
```

For this project, that is not the right first step.

Why?

Because the project keeps live state in memory:

- active capture workers
- WebSocket clients
- session bot registry
- live trade state

If you create many identical workers, each worker gets its own separate memory.

That can lead to problems like:

- bot started in one worker is invisible to another worker
- WebSocket client connected to worker A does not see events from worker B
- multiple broadcaster loops run separately
- live state becomes inconsistent

So yes, you want more capacity, but not in that form.

---

## 7. Best Scaling Design For This Project

## Recommended split: 2 services

### Service 1: Live Engine

This service should own all real-time work:

- screenshot capture
- price/trend reading
- trade decisions
- bot runtime state
- WebSocket live updates
- writing trade results

Think of this as the "fast reaction" part.

### Service 2: History Service

This service should own all read-heavy work:

- `/history`
- `/screenshots`
- `/trade_screenshots/*`
- `/uploads/*`
- screenshot browsing and history pagination

Think of this as the "library" part.

### Why this split is good

Because it separates two very different jobs:

- live trading needs speed and steady timing
- history browsing needs database reads and file lookups

This is the cleanest split for your current architecture.

---

## 8. Simple Example Of How The Split Would Work

### Before split

One backend is trying to do this at the same time:

1. Bot captures screenshot.
2. Backend decides trade action.
3. Backend sends live preview.
4. User opens history.
5. Same backend searches old trade screenshots.

Result:

The live side and the history side slow each other down.

### After split

#### Live Engine

1. Bot captures screenshot.
2. Live Engine checks the market data.
3. Live Engine decides buy or sell.
4. Live Engine writes the result.
5. Live Engine sends a small live update.

#### History Service

1. User opens the history page.
2. History Service reads SQLite.
3. History Service loads screenshot file paths.
4. History Service returns the correct history page.

Result:

History browsing no longer steals time from live capture and trading.

---

## 9. What Should Stay In The Live Engine

These parts should stay together in one process first:

- `background_capture_service.py`
- `services/capture_manager.py`
- `trading/simulator.py`
- `ws/broadcaster.py`
- WebSocket routes
- start/stop worker routes

Reason:

They all depend on shared live state.
Keeping them together avoids synchronization problems.

---

## 10. What Should Move To The History Service

These parts are good candidates for the separate history service:

- `/history`
- `/latest`
- `/screenshots`
- `/trade_screenshots/*`
- `/uploads/*`

Main file today:

- `api/routes/history.py`

Reason:

This side is mostly about reading stored data, not running live logic.

---

## 11. What The Frontend Should Do After The Split

The frontend can stay simple.

### Good news

The frontend is already doing some efficient things:

- `App.jsx` uses WebSocket for live changes
- `App.jsx` fetches history page by page
- `HistoryPanel.jsx` lazy-loads screenshots only when needed

That means the frontend does not need a full rewrite.

### Recommended frontend behavior after the split

1. Keep live WebSocket and live worker calls pointed to the Live Engine.
2. Keep history and screenshot requests pointed to the History Service.
3. Use one public domain through a reverse proxy if possible.

Simple explanation of reverse proxy:

It is one front door.
The user still sees one address, but inside, the requests are sent to the correct backend.

### Example

- `/ws` -> Live Engine
- `/workers` -> Live Engine
- `/start_multi` -> Live Engine
- `/history` -> History Service
- `/screenshots` -> History Service
- `/trade_screenshots/...` -> History Service

This is the cleanest frontend setup.

---

## 12. Biggest Quick Wins Before A Full Split

Even before making 2 services, you can get speed improvements.

### Quick win 1: Send lighter WebSocket messages

Best improvement:

- do not send full base64 images every second unless really needed

Better approach:

- send image URL or small thumbnail only
- send the full image only when the user opens preview

Why this helps:

- less CPU
- less memory
- less network traffic
- faster browser rendering

### Quick win 2: Improve database indexes for real history filters

The current database already has WAL mode and some indexes.
That is good.

But the history filters would benefit from better composite indexes such as:

- `(bot_id, ts DESC)`
- `(ticker, ts DESC)`

Why this helps:

When the user filters history by bot or ticker, SQLite finds the rows faster.

### Quick win 3: Add better SQLite connection settings

Useful settings include:

- `busy_timeout`
- `synchronous = NORMAL`

Simple explanation:

This helps SQLite wait more gracefully and work more smoothly under pressure.

### Quick win 4: Move blocking work out of hot async paths

The heaviest candidates are:

- file copy work in upload/ingest
- repeated image read + base64 encode in broadcaster
- expensive disk operations during live updates

Why this helps:

The live loop becomes more stable and less likely to stall.

---

## 13. Is SQLite Still Okay?

For the next step: yes, probably.

Why?

- the bigger problem today is not only the database
- the bigger problem is mixed responsibilities and image-heavy live work
- the project already uses WAL mode, which is the correct direction for SQLite

So the order should be:

1. reduce live workload
2. split live and history
3. then re-measure

Move to PostgreSQL later only if:

- you need multiple backend machines
- you need much heavier concurrent writes
- you need cloud-style scaling across several app instances

---

## 14. Is Redis Or A Queue Needed Right Now?

Not as the first move.

Redis or a queue becomes useful when you need:

- distributed workers
- retry systems
- job scheduling across machines
- backpressure control for many background jobs

Right now the cleaner high-value step is the 2-service split.

---

## 15. Best Plan In Order

## Phase 1: Improve The Current Single Live Backend

Do these first:

1. Reduce WebSocket image weight.
2. Add better history indexes.
3. Add SQLite connection tuning.
4. Move blocking file/image work out of the hottest live paths.

Expected result:

The current system becomes noticeably faster without a risky redesign.

## Phase 2: Split Into Two Services

Create:

1. Live Engine
2. History Service

Expected result:

History load stops interfering with live bots.

## Phase 3: Upgrade Only If Needed

Only after measuring again, consider:

1. PostgreSQL
2. Redis/queue workers
3. separate capture-processing service

---

## 16. If You Want An Even Bigger Future Design

Later, if your load keeps growing, you can move from 2 parts to 3 parts:

1. Capture Service
2. Trading Decision Service
3. History Service

But this is not the first step I would recommend.

Why not first?

Because it adds more complexity:

- more communication between services
- more failure points
- harder debugging

For your current project, 2 parts is the better balance.

---

## 17. Final Recommendation

### Best answer to your question

Yes, you should divide responsibilities.

But do it in the right way:

- keep one live backend for bots, capture, trading, and WebSocket
- create one separate backend for history and screenshot browsing
- do not try to scale this first by running many identical app workers

### In one sentence

Make the live side small and fast, and move the history side into its own service.

---

## 18. Very Simple Business-Level Explanation

If a non-technical person asks what this means, you can explain it like this:

"Right now one worker is trying to watch the market, make trade decisions, send live previews, and answer old history questions at the same time. We should split it into two teams: one team handles live work, and the other team handles old records and screenshots. That will make the system faster and more stable as the number of bots and trades grows." 

---

## 19. Short Decision Summary

### Do this

- keep one live stateful backend
- split history into its own service
- reduce live image payload size
- keep SQLite for now, then measure again

### Do not do this first

- do not simply add many Uvicorn workers
- do not jump to Redis first
- do not move to PostgreSQL before fixing the live workload
