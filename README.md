.

## Manual setup (for developers)
From a PowerShell prompt in the project root:


```powershell
cd trade_analysis

git pull https://github.com/MahyudeenShahid/trade_analysis.git

python -m venv .venv
& .venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt

$env:DEV_ALLOW_ORIGINS = "https://marketview1.netlify.app"
# Preferred (refactored entrypoint)
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
# Compatibility (kept working)
# python -m uvicorn backend_server:app --host 0.0.0.0 --port 8000 --reload

```

---

## Trading Rules (Detailed)

The trading engine supports three configurable rules. Each rule can be enabled per-bot and persisted in the bots table. Rules are evaluated on every price update and can act on **open positions**.

### Rule #1 — Take Profit (TAKE_PROFIT_RULE_1)
**Goal:** Sell only when a profit target is reached.

**Settings:**
- `rule_1_enabled` (boolean)
- `take_profit_amount` (float)

**Logic:**
- When enabled, the engine **allows buys as normal**, but **sell logic is overridden**.
- A sell is executed only when:

$$current\_price \ge buy\_price + take\_profit\_amount$$

**Example:**
- Buy at $100.00
- `take_profit_amount = 0.50`
- Sell when price reaches $100.50 or higher

**Win reason tag:** `TAKE_PROFIT_RULE_1`

**Notes:**
- Rule #1 does **not** block Rule #2 or Rule #3. If those rules are enabled, they can still trigger a sell even while Rule #1 is active.

---

### Rule #2 — Stop Loss at Buy Price (STOP_LOSS_RULE_2)
**Goal:** Exit quickly when price falls to or below a stop-loss threshold based on the entry price.

**Settings:**
- `rule_2_enabled` (boolean)
- `stop_loss_amount` (float)

**Logic:**
- When enabled, a sell is executed immediately when:

$$current\_price \le buy\_price - stop\_loss\_amount$$

**Example:**
- Buy at $100.00
- `stop_loss_amount = 0.05`
- Sell when price reaches $99.95 or lower

**Win reason tag:** `STOP_LOSS_RULE_2`

**Notes:**
- If `stop_loss_amount = 0`, Rule #2 behaves as **sell at buy price or lower**.

---

### Rule #3 — Consecutive Lower Prices (CONSECUTIVE_DROPS_RULE_3)
**Goal:** Sell after a configurable number of **consecutive lower price ticks** after entry.

**Settings:**
- `rule_3_enabled` (boolean)
- `rule_3_drop_count` (integer, >= 1)

**Logic:**
- Each time the price is **lower than the previous tick**, the drop counter increases.
- Any **uptick** resets the drop counter to 0.
- When the drop counter reaches `rule_3_drop_count`, a sell is triggered.

**Example (rule_3_drop_count = 2):**
- Buy at $100.00
- Price peaks at $100.75 (peak updated)
- Price drops to $100.45 → drop #1
- Price drops to $100.35 → drop #2 → **sell**

**Win reason tag:** `CONSECUTIVE_DROPS_RULE_3`

---

### Rule Priority and Compatibility
- **Rule #2** and **Rule #3** are evaluated **before** Rule #1 take-profit logic when Rule #1 is enabled.
- This means a stop-loss or consecutive-drop sell can occur **even in Rule #1 mode**.
- If multiple rules are enabled, the first rule to trigger a sell ends the position for that tick.

---

### History Filters
Each sell records a `win_reason` tag, which the UI uses for filtering:
- Rule #1: `TAKE_PROFIT_RULE_1`
- Rule #2: `STOP_LOSS_RULE_2`
- Rule #3: `CONSECUTIVE_DROPS_RULE_3`

## ngrok browser warning (how to bypass)

If you use a free ngrok tunnel, new visitors will see a browser warning/interstitial page. This is normal for free tunnels.

- **For API/frontend requests:** Add the header `ngrok-skip-browser-warning: true` to every request. Most frontend frameworks (fetch, axios) allow custom headers.
	- Example (fetch):
		```js
		fetch('https://<your-ngrok-url>/history?ticker=AAPL', {
			headers: {
				'ngrok-skip-browser-warning': 'true',
				'Authorization': 'Bearer <API_KEY>'
			}
		})
		```
	- Example (curl):
		```powershell
		curl -H "ngrok-skip-browser-warning: true" https://electrotropic-uselessly-lashawna.ngrok-free.dev/history?ticker=AAPL
		```

- **For browsers:** The first time you visit the ngrok URL, click "Visit Site" on the warning page. After that, you will be redirected to your backend and the warning will not appear again for a while.

- **For production/no warning:** Upgrade to a paid ngrok account or use cloudflared (Cloudflare Tunnel) to remove the warning for all visitors.

---


---

Developed by [Mahyudeen Shahid](https://mahyudeen.me/) with ❤