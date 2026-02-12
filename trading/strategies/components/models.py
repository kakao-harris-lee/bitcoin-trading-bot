"""Data classes for strategy components.

These dataclasses define the data structures passed between entry/exit
strategy components. They are immutable data transfer objects with no
business logic.
"""

from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Literal, Mapping

# Type-safe regime classification (7-level)
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

# Regime classification constants (7-level)
# Use frozensets for O(1) membership testing in hot paths
BULL_REGIMES: frozenset[Regime] = frozenset({"BULL_STRONG", "BULL_MODERATE"})
BEAR_REGIMES: frozenset[Regime] = frozenset({"BEAR_STRONG", "BEAR_MODERATE"})
SIDEWAYS_REGIMES: frozenset[Regime] = frozenset({"SIDEWAYS_UP", "SIDEWAYS_FLAT", "SIDEWAYS_DOWN"})
ALL_REGIMES: frozenset[Regime] = BULL_REGIMES | BEAR_REGIMES | SIDEWAYS_REGIMES

# Bullish regimes where shorting should be avoided
BULLISH_NO_SHORT_REGIMES: frozenset[Regime] = frozenset({"BULL_STRONG", "BULL_MODERATE", "SIDEWAYS_UP"})

# Sideways regimes that may allow shorting with extreme volatility
SIDEWAYS_VOLATILE_REGIMES: frozenset[Regime] = frozenset({"SIDEWAYS_FLAT", "SIDEWAYS_DOWN"})

# MLP Direction Classifier label constants (Parente & Rizzuti 2025)
# 3-class classification: Hold(0), Buy(1), Sell(2)
MLP_LABEL_HOLD: int = 0
MLP_LABEL_BUY: int = 1
MLP_LABEL_SELL: int = 2


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
    open: float = 0.0
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
    # Note: Optional dict - callers should use `market_data.indicators or {}` for safe access
    indicators: dict[str, float] | None = None
    high_water_mark: float | None = None  # Track HWM for trailing stops
    # ATR for volatility measurement
    atr: float = 0.0
    # Historical reference points for breakout/range detection
    prev_high_20: float = 0.0  # 20-period high for resistance
    prev_low_20: float = 0.0   # 20-period low for support
    avg_volume_20: float = 0.0  # 20-period average volume
    # 30-day high for drawdown-based BEAR detection (720 periods for hourly data)
    high_30d: float = 0.0  # 30-day rolling high for drawdown calculation
    # EMA for trend filtering
    ema_120: float = 0.0  # 120-period EMA for MA120 panic sell
    ema_200: float = 0.0  # 200-period EMA for bear market filter
    # Market stress indicator (0-100, higher = more stress)
    market_stress: float = 0.0  # Composite stress score for pause trading
    # Volatility breakout (Larry Williams strategy)
    breakout_signal: int = 0  # 1 if close > target_price (prev_day_range * k)
    target_price: float = 0.0  # open + (prev_day_range * k)


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

    Regime classification (7-level):
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
    regime: Regime  # Detailed 7-level regime (type-safe)
    volatility_score: float  # ATR / close price (normalized)
    is_extreme_volatility: bool  # volatility_score > threshold (0.03 = 3%)
    adx: float  # Trend strength
    # Volume analysis for breakout detection
    volume_ratio: float = 1.0  # current_volume / avg_volume_20
    is_high_volume: bool = False  # volume_ratio > 1.5 (potential breakout)
    # Drawdown analysis for BEAR detection
    drawdown: float = 0.0  # Current drawdown from recent high (0.0 to 1.0)
    is_drawdown_bear: bool = False  # True if regime was overridden to BEAR due to drawdown
    # RF probability from HybridPredictor (LSTM + RandomForest)
    rf_confidence: float = 0.0  # RF confidence score (0-1), 0 = not available
    rf_direction: str = "SIDEWAYS"  # RF predicted direction (UP/DOWN/SIDEWAYS)
    rf_signal: str = "HOLD"  # RF trading signal (BUY/SELL/HOLD)


def build_market_context(
    mfi: float,
    adx: float,
    atr: float,
    close: float,
    volatility_threshold: float = 0.03,  # 3% ATR/price
    volume: float = 0.0,
    avg_volume: float = 0.0,
    high_volume_threshold: float = 1.5,  # 1.5x average = high volume
    recent_high: float = 0.0,  # Recent high for drawdown calculation
    drawdown_bear_threshold: float = 0.15,  # 15% drawdown = BEAR override
    # RF probability from HybridPredictor (optional)
    rf_confidence: float = 0.0,  # RF confidence score (0-1)
    rf_direction: str = "SIDEWAYS",  # RF predicted direction
    rf_signal: str = "HOLD",  # RF trading signal
    # Regime classification thresholds (externalised for optimisation)
    mfi_bull_strong: float = 54.0,
    mfi_bull_moderate: float = 54.0,
    mfi_sideways_up: float = 49.0,
    mfi_bear_moderate: float = 41.0,
    mfi_bear_strong: float = 34.0,
    adx_strong_trend: float = 25.0,
    adx_moderate_trend: float = 18.0,
) -> MarketContext:
    """Build MarketContext from indicators.

    Trend classification (simple 3-level):
    - BULL: MFI >= 52 (bullish money flow)
    - BEAR: MFI <= 48 (bearish money flow) OR drawdown > threshold
    - NEUTRAL: 48 < MFI < 52 (sideways)

    Regime classification (7-level):
    - BULL_STRONG: MFI >= 54 + ADX >= 25 (strong bullish trend)
    - BULL_MODERATE: MFI >= 54 + ADX >= 18 (moderate bullish)
    - SIDEWAYS_UP: MFI >= 49 (weak bullish)
    - SIDEWAYS_FLAT: MFI >= 41 (neutral)
    - SIDEWAYS_DOWN: MFI >= 34 (weak bearish)
    - BEAR_MODERATE: MFI < 34 + ADX < 25 (moderate bearish) OR drawdown > threshold
    - BEAR_STRONG: MFI < 34 + ADX >= 25 (strong bearish) OR drawdown > threshold + strong ADX

    Volume classification:
    - is_high_volume: volume > avg_volume * threshold (potential breakout)

    Drawdown-based BEAR detection:
    - If price drops > 15% from recent high, override to BEAR regime
    - This catches crashes that MFI misses (e.g., 2021 May crash)

    Args:
        mfi: Money Flow Index value (0-100)
        adx: Average Directional Index value
        atr: Average True Range value
        close: Current close price
        volatility_threshold: Threshold for extreme volatility (default 3%)
        volume: Current period volume
        avg_volume: Average volume (20-period)
        high_volume_threshold: Multiplier for high volume detection (default 1.5x)
        recent_high: Recent high price for drawdown calculation (20-period high)
        drawdown_bear_threshold: Drawdown threshold to override regime to BEAR (default 15%)

    Returns:
        MarketContext with trend, regime, volatility, and volume analysis.
    """
    regime_kwargs = dict(
        mfi_bull_strong=mfi_bull_strong,
        mfi_bull_moderate=mfi_bull_moderate,
        mfi_sideways_up=mfi_sideways_up,
        mfi_bear_moderate=mfi_bear_moderate,
        mfi_bear_strong=mfi_bear_strong,
        adx_strong_trend=adx_strong_trend,
        adx_moderate_trend=adx_moderate_trend,
    )
    drawdown = _compute_drawdown(recent_high, close)
    is_drawdown_bear = drawdown >= drawdown_bear_threshold
    trend = _classify_trend(mfi, is_drawdown_bear)
    regime = _resolve_regime(mfi, adx, is_drawdown_bear, **regime_kwargs)
    volatility_score, is_extreme_volatility = _compute_volatility(atr, close, volatility_threshold)
    volume_ratio, is_high_volume = _compute_volume(volume, avg_volume, high_volume_threshold)

    return MarketContext(
        trend=trend,
        regime=regime,
        volatility_score=volatility_score,
        is_extreme_volatility=is_extreme_volatility,
        adx=adx,
        volume_ratio=volume_ratio,
        is_high_volume=is_high_volume,
        drawdown=drawdown,
        is_drawdown_bear=is_drawdown_bear,
        rf_confidence=rf_confidence,
        rf_direction=rf_direction,
        rf_signal=rf_signal,
    )


def _compute_drawdown(recent_high: float, close: float) -> float:
    if recent_high > 0 and close > 0:
        return (recent_high - close) / recent_high
    return 0.0


def _classify_trend(mfi: float, is_drawdown_bear: bool) -> Literal["BULL", "BEAR", "NEUTRAL"]:
    if is_drawdown_bear:
        return "BEAR"
    if mfi >= 52:
        return "BULL"
    if mfi <= 48:
        return "BEAR"
    return "NEUTRAL"


def _resolve_regime(mfi: float, adx: float, is_drawdown_bear: bool, **regime_kwargs) -> Regime:
    regime = _classify_regime(mfi, adx, **regime_kwargs)
    if not is_drawdown_bear or regime in BEAR_REGIMES:
        return regime
    adx_strong = regime_kwargs.get("adx_strong_trend", 25.0)
    return "BEAR_STRONG" if adx >= adx_strong else "BEAR_MODERATE"


def _compute_volatility(
    atr: float, close: float, volatility_threshold: float
) -> tuple[float, bool]:
    volatility_score = atr / close if close > 0 else 0.0
    return volatility_score, volatility_score > volatility_threshold


def _compute_volume(
    volume: float, avg_volume: float, high_volume_threshold: float
) -> tuple[float, bool]:
    volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0
    return volume_ratio, volume_ratio > high_volume_threshold


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
    # Default thresholds (allocation defaults)
    mfi_bull_strong: float = 54.0,
    mfi_bull_moderate: float = 54.0,
    mfi_sideways_up: float = 49.0,
    mfi_bear_moderate: float = 41.0,
    mfi_bear_strong: float = 34.0,
    adx_strong_trend: float = 25.0,
    adx_moderate_trend: float = 18.0,
) -> Regime:
    """Classify market regime based on MFI and ADX (7-level).

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
    entry_time: int | None = None  # Entry bar timestamp for FWin exit (milliseconds)


@dataclass(frozen=True)
class TradingContext:
    """Centralized trading decision context.

    Computed once per symbol per tick, shared across all strategies.
    Contains market data, regime analysis, and cross-strategy position info.

    Note: positions is typed as Mapping (read-only view) to enforce immutability.
    Pass MappingProxyType(dict) when constructing to prevent mutation.
    """

    symbol: str
    timestamp: int  # Unix ms

    # Market data (indicators computed once)
    market: MarketData

    # Pre-analyzed regime (computed once)
    regime: MarketContext

    # All open positions for this symbol across strategies (read-only)
    # Key: strategy_name, Value: Position
    # Use Mapping type to signal immutability intent
    positions: Mapping[str, Position]

    # MLP Direction predictions (optional, for mlp_direction strategy)
    # Pre-computed by ComponentStrategyAdapter.precompute_mlp_predictions()
    mlp_prediction: int | None = None  # 0=HOLD, 1=BUY, 2=SELL
    mlp_confidence: float | None = None  # Confidence score (0.0-1.0)

    def has_position(self, strategy: str) -> bool:
        """Check if a strategy has an open position."""
        return strategy in self.positions

    def get_position(self, strategy: str) -> Position | None:
        """Get position for a strategy, or None if not positioned."""
        return self.positions.get(strategy)

    def other_strategies_positioned(self, exclude: str) -> list[str]:
        """Get strategy names holding positions, excluding specified strategy."""
        return [s for s in self.positions if s != exclude]

    @property
    def is_bull_regime(self) -> bool:
        """Check if current regime is bullish (BULL_STRONG or BULL_MODERATE)."""
        return self.regime.regime in BULL_REGIMES

    @property
    def is_bear_regime(self) -> bool:
        """Check if current regime is bearish (BEAR_STRONG or BEAR_MODERATE)."""
        return self.regime.regime in BEAR_REGIMES

    @property
    def is_sideways_regime(self) -> bool:
        """Check if current regime is sideways."""
        return self.regime.regime in SIDEWAYS_REGIMES
