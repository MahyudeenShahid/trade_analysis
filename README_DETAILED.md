# Trade Analysis + Marketview Detailed Guide (Layman Friendly)

This file is a simple explanation of what the system does, what changed, and especially everything related to Order Book improvements.

## What This Project Does

Think of this project as two parts:
- `trade_analysis` (backend): the brain that connects to IB Gateway, stores data, and runs trading logic.
- `marketview` (frontend): the screen where you monitor bots, charts, order book, and controls.

If you are a non-technical user, this is the short version:
- The system reads live market data.
- It shows what buyers/sellers are doing.
- It helps you review price movement and order book behavior over time.
- It can run configurable rule-based trading behavior.

---

## Big Recent Improvements (Easy Summary)

1. Live Preview view switch
- You can switch between screenshot mode and detailed IB chart mode.

2. Better chart interaction
- Hovering on chart points now shows exact values.
- A vertical crosshair line tracks the hovered x-position.
- Fullscreen chart now has full controls (same as normal chart).

3. Live mode visibility
- `Live On` and `Live Off` now use clear state colors.

4. Order Book visibility and history
- Total bid/ask views improved.
- Historical Order Book snapshots are recorded and can be reviewed later.

---

## Complete Order Book Changes (All Previous Work)

This section documents the full Order Book evolution from basic display to historical analysis.

### Phase 1: Better totals in Order Book UI
- Added total volume display for bid and ask.
- Support for two total modes:
  - Best price level only
  - All visible depth levels
- Added toggle so user can switch between those modes.

Why this matters:
- Best-level totals help for quick microstructure reading.
- All-level totals help for broader liquidity pressure analysis.

### Phase 2: Backend depth subscription reliability
- Ensured selected ticker is actively subscribed for depth feed.
- Added fallback exchange subscribe attempts when SMART depth is empty.
- Added diagnostics to help detect entitlement/venue issues.

Why this matters:
- Prevents blank order book in common connection/entitlement edge cases.

### Phase 3: Live depth exposure to frontend
- Backend broadcaster includes depth snapshots in websocket payload (`order_books`).
- Frontend reads and renders live bids/asks from those snapshots.

Why this matters:
- Order Book updates in real time while bots run.

### Phase 4: Historical Order Book recording (SQLite)
- Added persistent storage for Order Book snapshots.
- Added background recorder process that samples depth periodically.
- Added retention cleanup policy so old snapshots are pruned.

Storage approach:
- Database: SQLite
- Data: timestamped depth snapshots (bid/ask ladders)
- Retention: configurable (for example one month)
- Sampling interval: configurable
- Depth levels saved: configurable

Why this matters:
- You can inspect what the order book looked like earlier, not just "now".

### Phase 5: Order Book history API endpoints
- Added backend endpoints to:
  - fetch historical order book data for a ticker/time range
  - read/update history settings (interval, levels, retention, enabled)

Why this matters:
- Frontend can request history directly and visualize it.

### Phase 6: Order Book history chart + hover details
- Added order-book history chart in UI.
- Hovering a point shows that exact snapshot context.
- Added deeper hover detail with full L2 rows for that point.

Why this matters:
- You can correlate price movement with liquidity stack changes at specific moments.

### Phase 7: Control Panel settings for Order Book history
- Added dedicated controls for Order Book history capture.
- Reworked controls into accordion/toggle style for easier use.

Typical controls include:
- capture enabled/disabled
- sample interval
- depth levels
- retention window

Why this matters:
- Non-technical users can tune storage vs precision without code changes.

### Phase 8: UX integrations around Order Book workflows
- Order Book now sits in the live workflow together with chart and preview controls.
- Chart and preview improvements make Order Book analysis easier in one place.

Why this matters:
- Faster review loop while troubleshooting strategy behavior.

---

## Trading Rules (High-Level)

The engine supports multiple rules and strategy paths.

Core simple rules:
- Rule #1: take-profit
- Rule #2: stop-loss
- Rule #3: consecutive drops

Extended strategy set includes:
- Rule #4 through Rule #9
- RSI+Bollinger strategy path (treated as Rule #10 in the current guide flow)

If you need full Rule #10 deep explanation, see `README.md` section updates or request a dedicated rule-only guide file.

---

## Developer Run Steps

```powershell
cd trade_analysis
python -m venv .venv
& .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:DEV_ALLOW_ORIGINS = "https://marketview1.netlify.app"
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Frontend env reminder:

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_API_KEY=devkey
```

---

## Quick Troubleshooting

Order Book is empty:
- Confirm IB is connected in UI.
- Confirm depth market data entitlement in IBKR account.
- Try a ticker/exchange with active depth.
- Check backend diagnostics endpoint for the ticker.

History chart has no points:
- Ensure history recording is enabled.
- Wait for recorder to collect samples.
- Check retention/interval settings are not too restrictive.

Live view not updating:
- Check `Live On` state.
- Verify backend API URL and key in frontend env.

---

Maintained for easy onboarding and non-technical understanding.
