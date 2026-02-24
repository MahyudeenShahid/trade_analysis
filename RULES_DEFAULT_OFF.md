# What Happens to Each Rule When Default Trade is OFF

## First, What is "Default Trade"?

Default Trade is the most basic behaviour:
- Chart goes **UP** → bot **buys**
- Chart goes **DOWN** → bot **sells**

When you turn Default Trade **OFF**, that automatic buy/sell stops. The bot will only act when one of the specific rules (Rule 1–9) tells it to.

---

## Quick Answer — Which Rules Still Work Alone?

| Rule | What It Does | Works When Default is OFF? |
|---|---|---|
| Rule 1 – Take Profit | Sells when profit target is reached | ⚠️ Only if something else buys first |
| Rule 2 – Stop Loss | Sells when loss limit is hit | ⚠️ Only if something else buys first |
| Rule 3 – Consecutive Drops | Sells after N drops in a row | ⚠️ Only if something else buys first |
| Rule 5 – Reversal + Scalp | Buys on reversal, sells at scalp target | ✅ Fully works on its own |
| Rule 6 – Long Wait | Waits for long downtrend, buys reversal, sells at profit | ✅ Fully works on its own |
| Rule 7 – Strong Momentum | Buys on strong uptrend... but **no sell logic of its own** | ❌ Will buy but NEVER sell |
| Rule 8 – Offset Orders | Buys/sells at price offsets | ✅ Fully works on its own |
| Rule 9 – Up/Down Cycles | Buys/sells on rapid flip pattern | ✅ Fully works on its own |

---

## Rule by Rule Explanation

### Rule 1 – Take Profit ⚠️
> "Sell when the price is $X above where I bought"

This rule only **sells**. It cannot buy on its own.

- If Default Trade is ON → Default Trade buys, Rule 1 sells when profit is hit ✓
- If Default Trade is OFF → Nothing buys, so Rule 1 never has a chance to sell

**Fix:** Pair it with Rule 5, 6, 7, 8, or 9 so that one of them opens the position.

---

### Rule 2 – Stop Loss ⚠️
> "Sell if the price drops $X below where I bought"

Same situation as Rule 1. This rule only **sells**.

- Needs another rule (or Default) to open a buy position first.

---

### Rule 3 – Consecutive Drops ⚠️
> "Sell if price drops N times in a row from the peak"

Same situation. This rule only **sells**.

- Needs another rule to open a buy position first.

---

### Rule 5 – Reversal + Scalp ✅
> "Wait for a downtrend, then buy when it reverses, then sell quickly for a small profit"

This rule handles both the **buy** and the **sell** itself.

1. Watches for a downtrend lasting X minutes
2. When price turns back up → buys
3. When price rises by the scalp amount → sells

Works perfectly without Default Trade.

---

### Rule 6 – Long Wait ✅
> "Wait for a long downtrend, buy when it reverses, sell at profit target"

Similar to Rule 5. Fully self-contained.

1. Waits for a long downtrend
2. Buys on the first upward tick
3. Sells when profit target is reached

Works perfectly without Default Trade.

---

### Rule 7 – Strong Momentum ❌ BUG WHEN DEFAULT IS OFF
> "Buy when the market has been going up strongly for X minutes"

This rule only handles the **buy side**. The sell was always handled by the Default Trade block:

```
Default block:
  if trend is DOWN and position is open → sell
```

When Default Trade is OFF, that sell block never runs.

**Result:** Rule 7 opens a buy position and then **holds it forever**. The bot gets stuck.

**How to avoid this for now:** If you use Rule 7 with Default Trade OFF, also enable Rule 1 (Take Profit) and/or Rule 2 (Stop Loss) so that eventually it exits.

---

### Rule 8 – Offset Limit Orders ✅
> "Buy when price drops X from last known price, sell when it rises X"

Fully self-contained. Manages both buy and sell based on price offset from reference.

Works perfectly without Default Trade.

---

### Rule 9 – Up/Down Cycles ✅
> "If the price flips direction N times within M minutes, do a quick scalp trade"

Fully self-contained. Detects the pattern, buys, then sells after a small gain.

Works perfectly without Default Trade.

---

## Recommended Combinations When Default Trade is OFF

| Goal | Rules to Enable |
|---|---|
| Safe, slow trades | Rule 6 only |
| Quick scalps | Rule 5 only, or Rule 9 only |
| Protected trading | Rule 5 + Rule 1 (exit at profit) + Rule 2 (stop loss) |
| Momentum trading | Rule 7 + Rule 1 + Rule 2 *(Rule 7 needs help to exit)* |
| Aggressive multi-rule | Rule 5 + Rule 6 + Rule 9 |

---

## Summary

- Rules **1, 2, 3** are **exit-only** — they never open a position. They need a buy to come from somewhere else.
- Rules **5, 6, 8, 9** are **fully independent** — buy + sell logic is inside the rule itself.
- Rule **7 has a bug** — it buys but never sells when Default is OFF. Always pair it with Rule 1 or Rule 2 as a safety exit.
