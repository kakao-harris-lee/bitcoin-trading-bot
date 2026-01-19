"""Data classes for strategy components.

These dataclasses define the data structures passed between entry/exit
strategy components. They are immutable data transfer objects with no
business logic.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class MarketData:
    """Current market state with pre-calculated indicators.

    Entry/Exit strategies receive this data - they don't fetch their own.
    This is an immutable data transfer object.
    """

    symbol: str
    close: float
    mfi: float
    adx: float
    rsi: float
    timestamp: int  # Unix timestamp in milliseconds
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
    # ATR for volatility measurement
    atr: float = 0.0
    # Historical reference points for breakout/range detection
    prev_high_20: float = 0.0  # 20-period high for resistance
    prev_low_20: float = 0.0   # 20-period low for support
    avg_volume_20: float = 0.0  # 20-period average volume
    # Optional for trailing stop calculations
    high_water_mark: float | None = None


@dataclass(frozen=True)
class Signal:
    """Trading signal from entry or exit strategy.

    Used for both entry signals (side="buy" for long, "sell" for short)
    and exit signals (opposite side to close position).
    This is an immutable data transfer object.
    """

    symbol: str
    side: Literal["buy", "sell"]
    market: Literal["spot", "futures"]
    quantity: float
    reason: str
    # Optional exit-specific fields
    trigger_price: float | None = None


@dataclass(frozen=True)
class MarketContext:
    """Pre-analyzed market state for strategy filtering.

    Provides simplified trend/volatility classification that entry strategies
    can use to filter out unsuitable conditions early.
    """

    trend: Literal["BULL", "BEAR", "NEUTRAL"]  # Simplified trend direction
    volatility_score: float  # ATR / close price (normalized)
    is_extreme_volatility: bool  # volatility_score > threshold (0.03 = 3%)
    adx: float  # Trend strength


def build_market_context(
    mfi: float,
    adx: float,
    atr: float,
    close: float,
    volatility_threshold: float = 0.03,  # 3% ATR/price
) -> MarketContext:
    """Build MarketContext from indicators.

    Trend classification uses V35's MFI rules:
    - BULL: MFI >= 52 (bullish money flow)
    - BEAR: MFI <= 48 (bearish money flow)
    - NEUTRAL: 48 < MFI < 52 (sideways)

    Args:
        mfi: Money Flow Index value (0-100)
        adx: Average Directional Index value
        atr: Average True Range value
        close: Current close price
        volatility_threshold: Threshold for extreme volatility (default 3%)

    Returns:
        MarketContext with trend and volatility analysis.
    """
    # Trend classification based on MFI (V35's rules)
    if mfi >= 52:
        trend: Literal["BULL", "BEAR", "NEUTRAL"] = "BULL"
    elif mfi <= 48:
        trend = "BEAR"
    else:
        trend = "NEUTRAL"

    # Volatility classification
    volatility_score = atr / close if close > 0 else 0.0
    is_extreme_volatility = volatility_score > volatility_threshold

    return MarketContext(
        trend=trend,
        volatility_score=volatility_score,
        is_extreme_volatility=is_extreme_volatility,
        adx=adx,
    )


@dataclass(frozen=True)
class Position:
    """Current open position state.

    This is an immutable data transfer object.
    """

    symbol: str
    entry_price: float
    quantity: float
    strategy: str
    market: Literal["spot", "futures"]
    timestamp: int  # Unix timestamp in milliseconds
    side: str = "buy"  # "buy" for long, "sell" for short
    leverage: int = 1  # leverage multiplier
    liquidation_price: float = 0.0  # for futures
