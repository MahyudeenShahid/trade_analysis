"""Trading module for trade simulation and persistence."""

from .simulator import trader, persist_trade_as_record

__all__ = [
    "trader",
    "persist_trade_as_record",
]
