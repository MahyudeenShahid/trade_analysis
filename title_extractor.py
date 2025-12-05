import re
from dataclasses import dataclass
from typing import Optional
 

@dataclass
class TitleResult:
    name: Optional[str] = None
    ticker: Optional[str] = None
    price_text: Optional[str] = None
    price_value: Optional[float] = None
    change_text: Optional[str] = None


_RE_PRICE = re.compile(r"\$?\s*([0-9]{1,3}(?:[0-9,]*)(?:\.[0-9]+)?)")
_RE_TICKER = re.compile(r"\b[A-Z]{3,5}\b")
_FORBIDDEN_TICKERS = {"YTD", "MAX"}


def extract_from_title(title: str) -> TitleResult:
    """Parse a window title for a name, ticker and price (fast, no OCR).

    This is a heuristic parser intended for titles that include the instrument
    and optionally its price (examples: "AAPL 175.23 - MyApp", "Bitcoin $42000 - Feed").
    """
    if not title:
        return TitleResult()

    s = title.strip()
    price_text = None
    price_value = None

    m = _RE_PRICE.search(s)
    if m:
        raw = m.group(1).replace(',', '')
        try:
            val = float(raw)
            price_value = val
            price_text = f"${val:.2f}"
        except Exception:
            price_value = None

    ticker = None
    for tk in _RE_TICKER.findall(s.upper()):
        if tk not in _FORBIDDEN_TICKERS:
            ticker = tk
            break

    name = s
    try:
        if ticker:
            name = re.sub(r"\b" + re.escape(ticker) + r"\b", '', name, flags=re.IGNORECASE)
        if m:
            name = name.replace(m.group(0), '')
        name = re.sub(r'[-–—|:()\[\]]', ' ', name)
        name = re.sub(r'\s+[-–—]\s+.*$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        if not name:
            name = None
    except Exception:
        name = None

    return TitleResult(name=name, ticker=ticker, price_text=price_text, price_value=price_value)
