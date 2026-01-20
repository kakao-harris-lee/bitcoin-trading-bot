"""Data classes for strategy components.

These dataclasses define the data structures passed between entry/exit
strategy components. They are immutable data transfer objects with no
business logic.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

# Type-safe regime classification (7-level V35 style)
# Using Literal provides IDE autocomplete and compile-time validation
Regime = Literal[
    "BULL_STRONG",
    "BULL_MODERATE",
    "SIDEWAYS_UP",
    "SIDEWAYS_FLAT",
    "SIDEWAYS_DOWN",
    "BEAR_MODERATE",
    "BEAR_STRONG",
]

# Regime classification constants (7-level V35 style)
# Use frozensets for O(1) membership testing in hot paths
BULL_REGIMES: frozenset[Regime] = frozenset({"BULL_STRONG", "BULL_MODERATE"})
BEAR_REGIMES: frozenset[Regime] = frozenset({"BEAR_STRONG", "BEAR_MODERATE"})
SIDEWAYS_REGIMES: frozenset[Regime] = frozenset({"SIDEWAYS_UP", "SIDEWAYS_FLAT", "SIDEWAYS_DOWN"})
ALL_REGIMES: frozenset[Regime] = BULL_REGIMES | BEAR_REGIMES | SIDEWAYS_REGIMES

# Bullish regimes where shorting should be avoided
BULLISH_NO_SHORT_REGIMES: frozenset[Regime] = frozenset({"BULL_STRONG", "BULL_MODERATE", "SIDEWAYS_UP"})

# Sideways regimes that may allow shorting with extreme volatility
SIDEWAYS_VOLATILE_REGIMES: frozenset[Regime] = frozenset({"SIDEWAYS_FLAT", "SIDEWAYS_DOWN"})


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

    # Generic indicators map for flexible strategies (EMA, BB, etc)
    indicators: dict[str, float] = None
    high_water_mark: float | None = None  # Track HWM for trailing stops
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
    market: Literal["futures"]
    quantity: float
    reason: str
    # Optional exit-specific fields
    trigger_price: float | None = None


@dataclass(frozen=True)
class MarketContext:
    """Pre-analyzed market state for strategy filtering.

    Provides simplified trend/volatility classification that entry strategies
    can use to filter out unsuitable conditions early.

    Regime classification (V35 style, 7 levels):
    - BULL_STRONG: Strong bullish trend (MFI >= 54 + ADX >= 25)
    - BULL_MODERATE: Moderate bullish (MFI >= 54 + ADX >= 18)
    - SIDEWAYS_UP: Weak bullish (MFI >= 49)
    - SIDEWAYS_FLAT: Neutral (MFI >= 41)
    - SIDEWAYS_DOWN: Weak bearish (MFI >= 34)
    - BEAR_MODERATE: Moderate bearish (ADX < 25)
    - BEAR_STRONG: Strong bearish (ADX >= 25)

    Volume classification:
    - is_high_volume: True if current volume > 1.5x average (breakout potential)
    - volume_ratio: current_volume / avg_volume_20
    """

    trend: Literal["BULL", "BEAR", "NEUTRAL"]  # Simplified trend direction
    regime: Regime  # Detailed 7-level regime (V35 style, type-safe)
    volatility_score: float  # ATR / close price (normalized)
    is_extreme_volatility: bool  # volatility_score > threshold (0.03 = 3%)
    adx: float  # Trend strength
    # Volume analysis for breakout detection
    volume_ratio: float = 1.0  # current_volume / avg_volume_20
    is_high_volume: bool = False  # volume_ratio > 1.5 (potential breakout)


def build_market_context(
    mfi: float,
    adx: float,
    atr: float,
    close: float,
    volatility_threshold: float = 0.03,  # 3% ATR/price
    volume: float = 0.0,
    avg_volume: float = 0.0,
    high_volume_threshold: float = 1.5,  # 1.5x average = high volume
) -> MarketContext:
    """Build MarketContext from indicators.

    Trend classification (simple 3-level):
    - BULL: MFI >= 52 (bullish money flow)
    - BEAR: MFI <= 48 (bearish money flow)
    - NEUTRAL: 48 < MFI < 52 (sideways)

    Regime classification (V35 style, 7-level):
    - BULL_STRONG: MFI >= 54 + ADX >= 25 (strong bullish trend)
    - BULL_MODERATE: MFI >= 54 + ADX >= 18 (moderate bullish)
    - SIDEWAYS_UP: MFI >= 49 (weak bullish)
    - SIDEWAYS_FLAT: MFI >= 41 (neutral)
    - SIDEWAYS_DOWN: MFI >= 34 (weak bearish)
    - BEAR_MODERATE: MFI < 34 + ADX < 25 (moderate bearish)
    - BEAR_STRONG: MFI < 34 + ADX >= 25 (strong bearish)

    Volume classification:
    - is_high_volume: volume > avg_volume * threshold (potential breakout)

    Args:
        mfi: Money Flow Index value (0-100)
        adx: Average Directional Index value
        atr: Average True Range value
        close: Current close price
        volatility_threshold: Threshold for extreme volatility (default 3%)
        volume: Current period volume
        avg_volume: Average volume (20-period)
        high_volume_threshold: Multiplier for high volume detection (default 1.5x)

    Returns:
        MarketContext with trend, regime, volatility, and volume analysis.
    """
    # Trend classification based on MFI (simple 3-level)
    if mfi >= 52:
        trend: Literal["BULL", "BEAR", "NEUTRAL"] = "BULL"
    elif mfi <= 48:
        trend = "BEAR"
    else:
        trend = "NEUTRAL"

    # Regime classification (V35 style, 7-level)
    regime = _classify_regime(mfi, adx)

    # Volatility classification
    volatility_score = atr / close if close > 0 else 0.0
    is_extreme_volatility = volatility_score > volatility_threshold

    # Volume classification (for breakout/mean-reversion filtering)
    volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0
    is_high_volume = volume_ratio > high_volume_threshold

    return MarketContext(
        trend=trend,
        regime=regime,
        volatility_score=volatility_score,
        is_extreme_volatility=is_extreme_volatility,
        adx=adx,
        volume_ratio=volume_ratio,
        is_high_volume=is_high_volume,
    )


@lru_cache(maxsize=1024)
def _classify_regime_cached(
    mfi_rounded: float,
    adx_rounded: float,
    mfi_bull_strong: float,
    mfi_bull_moderate: float,
    mfi_sideways_up: float,
    mfi_bear_moderate: float,
    mfi_bear_strong: float,
    adx_strong_trend: float,
    adx_moderate_trend: float,
) -> Regime:
    """Cached regime classification (internal).

    Values are rounded to 1 decimal place for effective caching.
    Cache hit rates are high because MFI/ADX values cluster.
    """
    # ADX for trend strength
    is_strong_trend = adx_rounded >= adx_strong_trend
    is_moderate_trend = adx_rounded >= adx_moderate_trend

    # MFI for direction (check from highest to lowest)
    if mfi_rounded >= mfi_bull_strong and is_strong_trend:
        return "BULL_STRONG"
    elif mfi_rounded >= mfi_bull_moderate and is_moderate_trend:
        return "BULL_MODERATE"
    elif mfi_rounded >= mfi_sideways_up:
        return "SIDEWAYS_UP"
    elif mfi_rounded >= mfi_bear_moderate:
        return "SIDEWAYS_FLAT"
    elif mfi_rounded >= mfi_bear_strong:
        return "SIDEWAYS_DOWN"
    elif is_strong_trend:
        return "BEAR_STRONG"
    else:
        return "BEAR_MODERATE"


def _classify_regime(
    mfi: float,
    adx: float,
    # V35 default thresholds (from v35_long.json)
    mfi_bull_strong: float = 54.0,
    mfi_bull_moderate: float = 54.0,
    mfi_sideways_up: float = 49.0,
    mfi_bear_moderate: float = 41.0,
    mfi_bear_strong: float = 34.0,
    adx_strong_trend: float = 25.0,
    adx_moderate_trend: float = 18.0,
) -> Regime:
    """Classify market regime based on MFI and ADX (V35 style).

    Uses LRU cache for performance in backtesting hot loops.
    MFI and ADX are rounded to 1 decimal place for effective caching.

    7-level classification:
    - BULL_STRONG: Strong bullish trend (high MFI + strong ADX)
    - BULL_MODERATE: Moderate bullish trend (high MFI + moderate ADX)
    - SIDEWAYS_UP: Weak bullish (moderate MFI, any ADX)
    - SIDEWAYS_FLAT: Neutral (moderate MFI, any ADX)
    - SIDEWAYS_DOWN: Weak bearish (low-moderate MFI, any ADX)
    - BEAR_MODERATE: Moderate bearish (low MFI, moderate ADX)
    - BEAR_STRONG: Strong bearish (very low MFI, strong ADX)

    Args:
        mfi: Money Flow Index value (0-100)
        adx: Average Directional Index value
        mfi_*: MFI thresholds for each level
        adx_*: ADX thresholds for trend strength

    Returns:
        Regime classification (type-safe Literal).
    """
    # Round to 1 decimal for effective caching (e.g., 54.123 -> 54.1)
    # This maintains accuracy while dramatically improving cache hits
    return _classify_regime_cached(
        round(mfi, 1),
        round(adx, 1),
        mfi_bull_strong,
        mfi_bull_moderate,
        mfi_sideways_up,
        mfi_bear_moderate,
        mfi_bear_strong,
        adx_strong_trend,
        adx_moderate_trend,
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
    market: Literal["futures"]
    timestamp: int  # Unix timestamp in milliseconds
    side: str = "buy"  # "buy" for long, "sell" for short
    leverage: int = 1  # leverage multiplier
    liquidation_price: float = 0.0  # for futures
