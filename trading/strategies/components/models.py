"""Data classes for strategy components.

These dataclasses define the data structures passed between entry/exit
strategy components. They are immutable data transfer objects with no
business logic.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass
class MarketData:
    """Current market state with pre-calculated indicators.

    Entry/Exit strategies receive this data - they don't fetch their own.
    """

    symbol: str
    close: float
    mfi: float
    adx: float
    rsi: float
    timestamp: int | str
    # Optional for trailing stop calculations
    high_water_mark: float | None = None


@dataclass
class Signal:
    """Trading signal from entry or exit strategy.

    Used for both entry signals (side="buy" for long, "sell" for short)
    and exit signals (opposite side to close position).
    """

    symbol: str
    side: Literal["buy", "sell"]
    market: Literal["spot", "futures"]
    quantity: float
    reason: str
    # Optional exit-specific fields
    trigger_price: float | None = None


@dataclass
class Position:
    """Current open position state."""

    symbol: str
    entry_price: float
    quantity: float
    strategy: str
    market: Literal["spot", "futures"]
    timestamp: int | str
