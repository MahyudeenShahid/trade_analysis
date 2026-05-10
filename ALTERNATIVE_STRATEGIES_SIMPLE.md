# Alternative Strategies — Simple Explanation

Here are easier descriptions of the alternative trading ideas and what they do. Pick one to try first.

1) Passive Limit-Capture
- What it does: Put a limit order inside the bid/ask spread and wait to be filled. You don't cross the market.
- Why try it: If it works, you pay almost no slippage.
- Things to watch: Many orders will not fill when the market moves fast.

2) Hybrid Passive → Aggressive
- What it does: Try the passive limit first. If it doesn't fill in N seconds, switch to a small aggressive order so you get filled.
- Why try it: More fills than passive-only, but some trades will have slippage.

3) VWAP Reversion Scalper
- What it does: If price is a little below VWAP, buy expecting it to revert to VWAP; sell for a small profit.
- Why try it: Good for stocks that bounce back to average price.

4) Small Mean-Revert (RSI + Bands)
- What it does: Buy when short-term indicators say price is oversold; take a small profit quickly.
- Why try it: Works in choppy markets where price often bounces.

5) Momentum Breakout + Volume Filter
- What it does: Buy when price breaks a short-term high and volume is higher than normal.
- Why try it: Captures trending moves, but can have bigger slippage.

6) Order-Book Imbalance
- What it does: If the order book shows many more bids than asks (or vice versa), trade in that direction.
- Why try it: Fast reaction to where liquidity is concentrated — best on very liquid stocks.

7) ADX Trend-Follow
- What it does: Only trade when trend strength (ADX) is high, enter on small pullbacks.
- Why try it: Reduces whipsaw in sideways markets.

8) TWAP/VWAP Slicing
- What it does: Break a big order into many small ones over time to avoid moving the market.
- Why try it: Execution improvement, not a trading signal.

9) Pairs Trading (advanced)
- What it does: Trade two related stocks when their prices diverge and expect them to come back together.
- Why try it: Direction-neutral, but needs more engineering and testing.

Quick recommendation: Start with "Passive Limit-Capture" or the "Hybrid" version — they are easiest to build and reduce slippage risk.

Next steps I can do for you:
- Add a simple `post-only` + TTL order path in the backend and record signal vs fill price for slippage.
- Or, implement UI toggles so you can turn the strategy on/off and set TTL.

Tell me which next step you'd like.
