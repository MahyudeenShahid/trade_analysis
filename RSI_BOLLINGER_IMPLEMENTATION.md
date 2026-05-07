# How to Implement RSI + Bollinger Reversal in Your System

Your current system reads the screen to decide when to buy (the chart lines go up/down). 
To make the **RSI + Bollinger Reversal** profitable and perfectly accurate, we should calculate the RSI and Bollinger Bands directly from the real price data coming from Interactive Brokers (IBKR), *not* by trying to guess it from a screenshot.

Here is the exact step-by-step roadmap of how we will change your code:

## Step 1: Get the Real Price History (Backend)
Right now, you stream live prices in `trade_analysis/ibkr/order_book.py` (the BBO fallback we added). 
We need to keep a rolling list of the last 20 minutes of prices (1-minute candles) so we can do math on them.
- **Action:** Open `order_book.py` and have it save a small list of the last 20 close prices for the active ticker.

## Step 2: Add the Math (Backend)
We need a tiny math function to calculate RSI and Bollinger Bands.
- **Action:** Create a new file `trade_analysis/trading/indicators.py`.
- Write a 10-line Python function that takes our list of 20 prices and spits out:
  1. The Current RSI (0-100)
  2. The Lower Bollinger Band Price (e.g., $150.25)

## Step 3: Create the New Rule (Backend)
Your current rules are in `trade_analysis/trading/rules.py` (like `check_rule_6`, `check_rule_5`).
- **Action:** We add a new function called `check_rsi_bollinger_rule(state, prices)`.
- If `RSI < 30` and the `Current Price <= Lower Bollinger Band`, this function returns a **Signal to BUY**.
- Crucially, it will also tell the router *exactly what price to buy at* (the Lower Band price).

## Step 4: The Limit Order Router (Backend)
Currently, `trade_analysis/ibkr/order_router.py` sends an order based on the `buy_order_type` setting. 
- **Action:** We update the router to place a `LIMIT` order exactly at the calculated Lower Bollinger Band price.
- Once that buy fills, the router immediately queues the `SELL` order at a +0.2% profit target.

## Step 5: The Settings UI (Frontend)
You need a way to turn this on and off from your React dashboard.
- **Action:** Edit `marketview/src/components/RuleSettings.jsx`.
- Add toggles:
  - `Enable RSI/Bollinger Strategy: [ON/OFF]`
  - `RSI Target: [30]`
  - `Profit Target %: [0.2]`
  - `Stop Loss %: [0.4]`

---

## What I Should Do Next

This takes about 4 code edits. 
I can start right now by writing **Step 1 and Step 2** (Saving the prices and doing the RSI/Bollinger math in python). 

Should I make these math and data changes directly to your code now?