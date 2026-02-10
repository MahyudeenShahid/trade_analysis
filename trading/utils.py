"""
Trading utilities: price parsing, normalization, and helper functions.
"""

from typing import Optional


def parse_price(price_str: Optional[str]) -> Optional[float]:
    """Convert price string to float, handling $, commas, and spaces."""
    if not price_str:
        return None
    try:
        clean = str(price_str).strip().replace("$", "").replace(",", "").replace(" ", "")
        return float(clean)
    except ValueError:
        return None


def normalize_ticker(ticker: str) -> str:
    """Normalize ticker symbol to uppercase."""
    try:
        return str(ticker or '').strip().upper()
    except Exception:
        return ''


def normalize_bot_id(bot_id: Optional[str]) -> str:
    """Normalize bot ID."""
    try:
        return str(bot_id or '').strip()
    except Exception:
        return ''


def make_state_key(bot_id: Optional[str], ticker: str) -> str:
    """Create a unique state key for bot + ticker combination."""
    b = normalize_bot_id(bot_id)
    t = normalize_ticker(ticker)
    if not t:
        return ''
    if b:
        return f"{b}:{t}"
    return t
