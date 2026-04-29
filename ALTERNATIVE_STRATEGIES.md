# Alternative Trading Strategies — Summary & Implementation Notes

This document lists alternative rules and systems you can try instead of (or alongside) the current rule set. Each entry includes a short description, pros/cons, implementation notes, and risk-control suggestions tailored to your live constraints (small size, slippage-sensitive, single-ticker exposure).

---

## 1) Passive Limit-Capture

- Description: place `post-only` limit orders inside the spread aiming to capture the spread without crossing the book.
- Pros: minimal slippage when filled; simple to measure; low implementation risk.
- Cons: low fill probability in fast-moving markets; can be picked off on aggressive moves.
- Implementation notes:
  - Config flags: `entry_type=post-only`, `limit_offset_pct`, `ttl_seconds` (time-to-live before cancel).
  - Order flow: place `post-only` limit; if not filled within `ttl_seconds`, cancel and optionally fallback to hybrid aggressive logic.
  - Files to touch: `trade_analysis/ibkr/order_router.py` (post-only order handling + TTL), `marketview/RuleSettings.jsx` (new UI toggles).
- Risk controls: limit active exposure to 1 ticker, min trade dollars, per-trade stop-loss.
- Metrics to track: fill rate, average slippage when filled, canceled order rate.

## 2) Hybrid Passive → Aggressive

- Description: start with `post-only` limit; if not filled by TTL, convert to a marketable limit or small market order to ensure execution.
- Pros: balances low-slippage attempts with the need to get filled; improves realized trade count.
- Cons: introduces some slippage on the fallback leg; more complex state handling.
- Implementation notes:
  - Config: `ttl_seconds`, `fallback_type` (`marketable-limit` / `market`), `max_fallback_slippage`.
  - Order state machine: `POSTED` → on TTL expiry `FALLBACK` → execute fallback order.
  - Persist signal price for slippage calc in `live_orders`.

## 3) VWAP / Reversion Scalper

- Description: enter when price deviates from VWAP by a small threshold and there is short-term mean reversion.
- Pros: better for mean-reverting instruments; naturally limits exposure to momentum moves.
- Cons: fails in sustained trends; needs reliable VWAP computation and volume data.
- Implementation notes:
  - Data: compute intraday VWAP in `trade_analysis` (or in frontend if preferred).
  - Config: `vwap_deviation_pct`, `profit_target`, `stop_loss_pct`.

## 4) Micro Mean-Revert (RSI + Bollinger)

- Description: combine short-term RSI and Bollinger band touches for entries; tight profit and stop.
- Pros: effective in choppy, mean-reverting names.
- Cons: noisy; requires filtering by liquidity and spread.

## 5) Momentum Breakout + Volume Filter

- Description: enter on breakouts of short-term highs with higher-than-average volume.
- Pros: captures directional moves; clear volume-based filter reduces false breakouts.
- Cons: higher slippage risk; requires volume history.

## 6) Order-Book Imbalance Execution

- Description: trigger when L2 shows strong imbalance (e.g., bidQty/(bid+ask) > 0.7). Use small marketable limit to take liquidity.
- Pros: fast reaction to immediate supply/demand; good for liquid tickers.
- Cons: requires robust L2 and low-latency execution; sensitive to spoofing.

## 7) ADX Trend-Follow (low churn)

- Description: require ADX above threshold plus moving-average confirmation; enter on pullbacks using limit orders.
- Pros: reduces whipsaw in choppy markets.

## 8) TWAP / VWAP Slicing (execution only)

- Description: split larger sends into smaller child orders over time to reduce market impact.
- Use case: execution optimization, not a signal generator.

## 9) Pairs / Statistical Arbitrage (advanced)

- Description: trade mean reversion between cointegrated tickers.
- Pros: direction-neutral; can be lower volatility.
- Cons: high engineering cost; needs rigorous backtesting and monitoring.

---

## Recommended First Prototypes (order of effort & impact)

1. `Passive Limit-Capture` (lowest risk & fastest to prototype)
2. `Hybrid Passive→Aggressive` (adds execution robustness)
3. `Order-Book Imbalance` (requires L2 reliability but good for liquid names)

Why these: they prioritize minimizing slippage (your main live loss driver) and are implementable by adjusting the order routing + a few config toggles.

## Short Implementation Checklist

- Add `slippage_signal_price` and `slippage_fill_price` fields to `live_orders` and record them on order fill. (See `DAILY_5_10_USD_PLAN.md` step 1.)
- Implement `post-only` order path and TTL fallback in `trade_analysis/ibkr/order_router.py`.
- Add UI toggles in `marketview` `RuleSettings` to enable `post-only`, `ttl_seconds`, and `fallback_type`.
- Add dashboard metrics: daily realized PnL, fill vs signal slippage histogram, fill-rate.

## Suggested Config Keys (example)

- `strategy.type`: `passive-limit` | `hybrid` | `vwap-scalper` | ...
- `passive.limit_offset_pct`: e.g. `0.05` (0.05%)
- `passive.ttl_seconds`: e.g. `10`
- `hybrid.fallback_type`: `market` | `marketable-limit`

## Risk Controls (always enable in live)

- `max_active_tickers = 1`
- `daily_loss_stop = -10` (see `DAILY_5_10_USD_PLAN.md`)
- `max_consecutive_losses = 3`
- `min_trade_dollars` to avoid noise trades

---

If you want, I can now implement a small prototype of the `passive-limit` strategy and add slippage tracking in `live_orders`. Confirm and I will create the code changes and unit checks next.
