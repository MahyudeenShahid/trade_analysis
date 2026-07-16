# Rule 14 (Order Book History Trend Auto-Trader) Documentation

Rule 14 is a high-speed, automated trend-following trading strategy designed to watch order book price changes and place immediate orders via Interactive Brokers (IBKR). Unlike other rules in the system that rely on visual screenshot analysis, Rule 14 operates directly on real-time Order Book History data to ensure maximum speed and accuracy.

---

## 1. Core Concept

Rule 14 monitors the **mid-price of the best bid/ask** snapshots over a rolling window. It calculates the slope of these prices to determine the short-term trend:
* **Uptrend detected** (slope exceeds positive threshold) $\rightarrow$ **BUY** (Long entry)
* **Downtrend detected** (slope drops below negative threshold) $\rightarrow$ **SELL** (Exit position)
* **Stop-Loss Breach** (mid-price drops below configured floor) $\rightarrow$ **SELL** (Stop-loss exit)
* **Long-Only**: Rule 14 does not open short positions; it only buys to open and sells to close.
* **Bypass Rule**: When Rule 14 is enabled on a bot, it overrides all screenshot-based indicators and capture rules for that bot.

---

## 2. How It Works (The Logic)

### A. Mid-Price Extraction
For any point in the order book history, the mid-price is calculated as:
$$\text{Mid Price} = \frac{\text{Best Ask Price} + \text{Best Bid Price}}{2}$$

If only one side of the order book is available, it falls back to the best bid or best ask price.

### B. Trend & Direction Detection (Point-to-Point Scanning)
To make signal decisions robust and trace active movements without lag or artificial delays, Rule 14 evaluates the direction of each segment within the lookback window:
1. **Point-to-Point Classification**: For each adjacent pair of mid-prices, it calculates the percentage change:
   $$\text{Change \%} = \frac{\text{Mid}_{i} - \text{Mid}_{i-1}}{\text{Mid}_{i-1}}$$
2. **Threshold Guard**: The calculated percentage change is compared against the per-interval threshold:
   $$\text{Threshold per interval} = \frac{\text{Slope Threshold}}{\text{Window Length} - 1}$$
   * **UP ($+1$)**: If $\text{Change \%} > \text{Threshold per interval}$
   * **DOWN ($-1$)**: If $\text{Change \%} < -\text{Threshold per interval}$
   * **FLAT ($0$)**: Otherwise
3. **Scan-Back**: The algorithm scans from the rightmost (most recent) interval backward to find the first non-flat direction (`up` or `down`), which determines the active trend.

### C. Signal Rules
1. **Flat (No Position)**:
   * If detected trend is `up` and the bot is **not** in cooldown $\rightarrow$ Fire **BUY** signal.
2. **Holding Position**:
   * **Stop-Loss**: If $\text{Mid}_{\text{current}} \le \text{Entry Price} \times (1.0 - \text{Stop Loss \%}) \rightarrow$ Fire **SELL** (Stop-Loss) signal immediately (bypasses trend check).
   * **Trend Reversal**: If detected trend is `down` $\rightarrow$ Fire **SELL** (Trend Exit) signal.

### D. Cooldown Period
When a position is closed (either by trend exit or stop-loss), the bot enters a cooldown phase of `cooldown_secs`. During this time, new buy signals are blocked to prevent "churning" or immediate re-entry in a volatile market.

---

## 3. Architecture & Implementation

The strategy is split across several modules:

### A. Runtime State Management (`trading/rule14.py`)
Each bot has an in-memory `Rule14State` that tracks:
* Configured parameters: `qty` (shares), `stop_loss_pct`, `cooldown_secs`, and `slope_threshold`.
* Position status: `position_price` (entry price), `entry_fill_status`, and `entry_fill_price`.
* Trade logging and order history events for the UI.

### B. Background Evaluation Loop (`ws/broadcaster_r14.py`)
Rule 14 is evaluated in two places in the backend:
1. **Capture Loop (`evaluate_r14_for_bot`)**: Evaluates Rule 14 whenever a screen capture is processed for a bot.
2. **Standalone Loop (`evaluate_standalone_r14`)**: A background loop running every 0.1 seconds that queries the `order_book_snapshots` database table for the last 60 seconds of order book points and evaluates the slope, independent of screen capture events.

### C. Database Persistence (`db/connection.py`)
The best bid/ask snapshots are recorded to the SQLite `order_book_snapshots` table on every trade event, providing historical data for slope evaluations.

---

## 4. How It Buys and Sells (Order Execution)

Rule 14 supports two execution types configured per bot:

### A. Market Orders
* The order is routed immediately as a `MarketOrder`.
* **Execution**: Fills immediately at the best available market price.
* **Speed**: Instantaneous.

### B. Limit Orders (Marketable Limit)
* To ensure fast fills while avoiding slippage, the system places **marketable limit orders**:
  * **Buy Orders**: Limit price is set to $\text{Mid Price} + \text{Limit Offset}$ (defaulting to \$0.01).
  * **Sell Orders**: Limit price is set to $\text{Mid Price} - \text{Limit Offset}$ (defaulting to \$0.01).
* Placing the buy limit slightly above the mid-price (and sell limit slightly below) ensures the order matches with existing book orders immediately while guaranteeing that the price cannot execute worse than the limit.
* **Timeout**: If a limit order does not fill within `ORDER_FILL_TIMEOUT` (45 seconds), it is automatically cancelled and retried up to `max_retries` times.

---

## 5. Manual Orders (Buy Now / Sell Now Override)

Manual buy/sell orders can be executed immediately for a bot through the REST API `/rule14/manual_order`. 

* **Behavior**: Bypasses all trend checks and cooldowns.
* **Quantity**: Uses the Rule 14 configured position size (`qty`).
* **Order Type**: Respects the bot's configured `buy_order_type` and `sell_order_type` in the database, allowing manual operations to use **Market** or **Limit** orders.
* **Parameter Overrides**: Can accept an `order_type` field in the request payload to explicitly override the bot settings (e.g. force a market order).
