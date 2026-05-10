"""Lightweight technical indicators for RSI and Bollinger Bands."""

from typing import Iterable, Optional, Tuple
import statistics


def _as_floats(values: Iterable[float]) -> list:
    out = []
    for v in values or []:
        try:
            out.append(float(v))
        except Exception:
            continue
    return out


def calculate_rsi(prices: Iterable[float], length: int = 14) -> Optional[float]:
    series = _as_floats(prices)
    if len(series) < length + 1:
        return None

    window = series[-(length + 1):]
    deltas = [window[i] - window[i - 1] for i in range(1, len(window))]
    gains = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]

    avg_gain = sum(gains) / float(length)
    avg_loss = sum(losses) / float(length)

    if avg_loss == 0 and avg_gain == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_bollinger_bands(
    prices: Iterable[float],
    length: int = 20,
    stdev_multiplier: float = 2.0,
) -> Optional[Tuple[float, float, float]]:
    series = _as_floats(prices)
    if len(series) < length:
        return None

    window = series[-length:]
    mean = sum(window) / float(length)

    try:
        stdev = statistics.pstdev(window)
    except Exception:
        stdev = 0.0

    upper = mean + stdev * stdev_multiplier
    lower = mean - stdev * stdev_multiplier
    return mean, upper, lower


def calculate_rsi_bollinger(
    prices: Iterable[float],
    rsi_length: int = 14,
    bb_length: int = 20,
    bb_stdev_multiplier: float = 2.0,
) -> Optional[dict]:
    series = _as_floats(prices)
    rsi = calculate_rsi(series, length=rsi_length)
    bands = calculate_bollinger_bands(series, length=bb_length, stdev_multiplier=bb_stdev_multiplier)
    if rsi is None or bands is None:
        return None

    mean, upper, lower = bands
    return {
        "rsi": rsi,
        "bb_mean": mean,
        "bb_upper": upper,
        "bb_lower": lower,
    }
