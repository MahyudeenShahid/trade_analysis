"""Trade simulator integration and persistence logic."""

import json
from datetime import datetime

from trade_simulator import TradeSimulator
from db.queries import save_observation
from db.connection import DB_LOCK, DB_PATH
import sqlite3


def persist_trade_as_record(trade: dict):
    """
    Persist trade into `records` table.
    
    This function handles:
    - Extracting buy/sell price and time from various trade payload formats
    - Pairing sell events with previous buy events (in-memory and DB-backed)
    - Computing profit when both buy and sell prices are available
    - Updating existing records when sell events complete a trade pair
    
    Args:
        trade: Dictionary containing trade information (ticker, price, direction, etc.)
    """
    try:
        meta = trade.get("meta") or {}
        try:
            if isinstance(meta, str):
                meta = json.loads(meta)
        except Exception:
            pass

        # Prefer explicit fields if present; otherwise try common meta keys
        buy_price = trade.get("buy_price") or meta.get("entry_price") or None
        sell_price = trade.get("sell_price") or meta.get("exit_price") or None
        buy_time = trade.get("buy_time") or meta.get("entry_time") or None
        sell_time = trade.get("sell_time") or meta.get("exit_time") or None
        win_reason = trade.get("win_reason") or (meta.get("win_reason") if isinstance(meta, dict) else None)

        # If the trade uses a generic `price` and `ts` fields (common shape),
        # infer buy/sell values from them based on direction when explicit
        # buy/sell fields are missing. Also accept `meta.price` / `meta.ts`.
        try:
            # helper to read common price/time keys
            price_in_trade = trade.get('price')
            time_in_trade = trade.get('ts') or trade.get('time')
            price_in_meta = None
            time_in_meta = None
            if isinstance(meta, dict):
                price_in_meta = meta.get('price') or meta.get('p')
                time_in_meta = meta.get('ts') or meta.get('time') or meta.get('timestamp')

            # if direction explicit, favor it
            direction = (trade.get('direction') or (meta.get('direction') if isinstance(meta, dict) else None) or '').lower()
            if direction == 'buy':
                if buy_price is None:
                    buy_price = price_in_trade if price_in_trade is not None else price_in_meta
                if buy_time is None:
                    buy_time = time_in_trade if time_in_trade is not None else time_in_meta
            elif direction == 'sell':
                if sell_price is None:
                    sell_price = price_in_trade if price_in_trade is not None else price_in_meta
                if sell_time is None:
                    sell_time = time_in_trade if time_in_trade is not None else time_in_meta
            else:
                # no explicit direction: if only price/time exist, consider them as buy by default
                if buy_price is None and (price_in_trade is not None or price_in_meta is not None):
                    buy_price = price_in_trade if price_in_trade is not None else price_in_meta
                if buy_time is None and (time_in_trade is not None or time_in_meta is not None):
                    buy_time = time_in_trade if time_in_trade is not None else time_in_meta
        except Exception:
            pass

        # If this is a sell event and buy info wasn't provided, try to find
        # the matching last buy for the same ticker from the in-memory trader
        # state so we can persist a paired record (buy+sell) for history UI.
        try:
            if (trade.get("direction") == "sell") and (buy_price is None):
                tk = trade.get("ticker")
                if tk and hasattr(trader, 'tickers') and tk in trader.tickers:
                    hist = trader.tickers[tk].get('trade_history', [])
                    # Find last buy before this sell
                    sell_ts = trade.get('ts')
                    candidate = None
                    for t in reversed(hist):
                        if t.get('direction') == 'buy':
                            # If timestamps exist, ensure buy occurred before sell when possible
                            if sell_ts and t.get('ts'):
                                try:
                                    if t.get('ts') <= sell_ts:
                                        candidate = t
                                        break
                                except Exception:
                                    candidate = t
                                    break
                            else:
                                candidate = t
                                break
                    if candidate:
                        buy_price = buy_price or candidate.get('price')
                        buy_time = buy_time or candidate.get('ts')
        except Exception:
            # Non-fatal; proceed without paired info if lookup fails
            pass

        ts = trade.get("ts") or (datetime.utcnow().isoformat() + 'Z')

        # If this is a SELL event, try to find an existing buy record in DB
        # (same ticker, sell_time IS NULL) and update it with sell info so
        # pairing survives restarts. Otherwise insert a record as usual.
        if trade.get("direction") == "sell":
            try:
                with DB_LOCK:
                    conn = sqlite3.connect(DB_PATH)
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT id, meta FROM records WHERE ticker = ? AND (sell_time IS NULL OR sell_time = '') ORDER BY ts DESC LIMIT 1",
                        (trade.get("ticker"),),
                    )
                    row = cur.fetchone()
                    if row:
                        rec_id = row["id"]
                        # merge meta JSONs if possible
                        existing_meta = {}
                        try:
                            existing_meta = json.loads(row["meta"]) if row["meta"] else {}
                        except Exception:
                            existing_meta = {}
                        # merge without overwriting existing buy info when present
                        merged_meta = existing_meta.copy()
                        try:
                            # trade may contain latest sell info
                            merged_meta.update(trade)
                        except Exception:
                            pass

                        # If we have buy info (from candidate lookup or merged_meta), ensure DB buy fields are set
                        try:
                            # prefer values we computed earlier, fall back to merged_meta if present
                            db_buy_price = buy_price or merged_meta.get('buy_price') or merged_meta.get('entry') or merged_meta.get('price') if merged_meta.get('direction') == 'buy' else buy_price or merged_meta.get('buy_price')
                        except Exception:
                            db_buy_price = buy_price
                        try:
                            db_buy_time = buy_time or merged_meta.get('buy_time') or merged_meta.get('entry_time') or merged_meta.get('ts')
                        except Exception:
                            db_buy_time = buy_time

                        # compute profit if possible
                        computed_profit = None
                        try:
                            sp = sell_price if sell_price is not None else merged_meta.get('price') if merged_meta.get('direction') == 'sell' else None
                            bp = db_buy_price
                            if sp is not None and bp is not None:
                                computed_profit = float(sp) - float(bp)
                                # also expose in merged_meta
                                merged_meta['profit'] = computed_profit
                        except Exception:
                            computed_profit = merged_meta.get('profit') if isinstance(merged_meta, dict) else None

                        # Perform update: set buy_price, buy_time, sell_price, sell_time, meta
                        cur.execute(
                            "UPDATE records SET buy_price = ?, buy_time = ?, sell_price = ?, sell_time = ?, win_reason = ?, meta = ? WHERE id = ?",
                            (
                                db_buy_price,
                                db_buy_time,
                                sell_price,
                                sell_time or ts,
                                win_reason,
                                json.dumps(merged_meta),
                                rec_id,
                            ),
                        )
                        conn.commit()
                        conn.close()
                        return
                    conn.close()
            except Exception as e:
                print(f"Failed DB-driven pairing update: {e}")

        # Fallback: insert a fresh record (handles buys and unmatched sells)
        obs = {
            "ts": ts,
            "image_path": None,
            "name": trade.get("ticker") or f"trade_{trade.get('direction')}",
            "ticker": trade.get("ticker"),
            "price": str(trade.get("price")) if trade.get("price") is not None else None,
            "trend": trade.get("direction"),
            "buy_price": buy_price,
            "sell_price": sell_price,
            "buy_time": buy_time,
            "sell_time": sell_time,
            "win_reason": win_reason,
            "meta": trade,
        }
        # If both buy and sell price are known, compute profit and include in meta
        try:
            b = obs.get('buy_price')
            s = obs.get('sell_price')
            if b is not None and s is not None:
                try:
                    p = float(s) - float(b)
                    if isinstance(obs.get('meta'), dict):
                        obs['meta']['profit'] = p
                    else:
                        # ensure meta is a dict with profit
                        try:
                            m = json.loads(obs['meta']) if isinstance(obs.get('meta'), str) else {}
                        except Exception:
                            m = {}
                        m['profit'] = p
                        obs['meta'] = m
                except Exception:
                    pass
        except Exception:
            pass
        save_observation(obs)
    except Exception as e:
        print(f"Failed to persist trade: {e}")


# Initialize the global trader instance with persistence callback
trader = TradeSimulator(on_trade=persist_trade_as_record)

__all__ = ["trader", "persist_trade_as_record"]
