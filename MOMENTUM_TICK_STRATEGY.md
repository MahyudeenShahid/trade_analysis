# The 5-Second Momentum Breakout (Tape Reading)

What you are describing is a classic **"Tape Reading"** or **"Micro-Momentum"** strategy. It is exactly how professional human scalpers trade. 

You wait for three things to align perfectly:
1. **High Volume:** Big money is stepping in.
2. **Immediate Price Action:** Over 2-5 seconds, the price goes up (e.g., $10.01 -> $10.03 -> $10.05).
3. **Bid/Ask Pressure:** Buyers are aggressively paying the Ask price, pushing the whole order book higher.

When all three flash green: **BUY.**

## The Good News
- This is a highly logical, proven way to trade. 
- It captures the exact moment of a breakout.
- The trades are over very quickly (you win or lose in under a minute).

## The Danger (Why automated bots struggle with this)
When a stock moves from $10.01 to $10.05 in 3 seconds, that means **liquidity is vanishing**. 
If you send a "Market Buy" when you see $10.05, by the time your order reaches the exchange (100 milliseconds later), the price might be $10.08. 
You get filled at $10.08. Then the breakout pauses, the stock rests at $10.05, and you are instantly losing money. **This is slippage.**

## How We Can Build This Safely for You
To make this work without getting destroyed by slippage, we have to build it with strict rules:

1. **The Data Feed:** We must tell IBKR to send us **Tick-by-Tick Data** (every single trade and volume update instantly). Your current bot doesn't track 1-minute volume, so we will need to add a volume tracker to `trade_analysis/ibkr/order_book.py`.
2. **The "Speed Limit" Trigger:** The code will measure the speed: *"Did the Ask price move up 3 cents in under 5 seconds?"*
3. **The Volume Trigger:** *"Were 5,000+ shares traded in the last 60 seconds?"*
4. **The Order Type (Crucial):** If the trigger fires at $10.05, we DO NOT send a Market Order. We send a **Limit Order at $10.06**. 
   - If we get filled at 10.05 or 10.06, great. 
   - If the price instantly jumps to 10.10, our order just sits at 10.06 and doesn't fill. We safely miss the trade instead of buying the absolute top.

## What I Will Need To Code To Make This Work:
1. Update your IBKR connection to ask for **Live Volume Data** (to check for the 5,000+ shares).
2. Create a "Rolling 5-Second Memory" in Python that tracks the last 5 seconds of the Ask price to detect the fast jump ($10.01 -> $10.05).
3. Write the strategy logic in `trading/rules.py` to combine Volume + 5-Second Speed.
4. Set up the Limit order router to never pay more than `+1 cent` above the signal price.

### Should We Build This?
This strategy is exciting and mimics real human trading. The coding involves getting real-time volume from IBKR and creating a 5-second speed tracker. 

Do you want me to start writing the code to pull live volume and track 5-second price speed for this strategy?