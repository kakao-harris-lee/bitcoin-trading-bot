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
    # OHLCV data for calculations
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    # MACD indicators for momentum entry/exit
    macd: float = 0.0
    macd_signal: float = 0.0
    # Stochastic for conservative entry
    stoch_k: float = 50.0
    stoch_d: float = 50.0
    # Bollinger Bands
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_middle: float = 0.0
    # Historical reference points for breakout/range detection
    prev_high_20: float = 0.0  # 20-period high for resistance
    prev_low_20: float = 0.0   # 20-period low for support
    avg_volume_20: float = 0.0  # 20-period average volume
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
