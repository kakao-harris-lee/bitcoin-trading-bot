"""Market regime classification for live/paper trading.

Classifies market conditions using MFI (Money Flow Index) and ADX (Average
Directional Index) indicators into 7 market states:

Market States:
    BULL_STRONG:      MFI >= 52, ADX >= 25 (strong uptrend)
    BULL_MODERATE:    MFI >= 52, ADX >= 20 (moderate uptrend)
    SIDEWAYS_BULL:    MFI >= 52, ADX < 20  (bullish but weak trend)
    SIDEWAYS_NEUTRAL: 48 < MFI < 52        (no clear direction)
    SIDEWAYS_BEAR:    MFI <= 48, ADX < 15  (bearish but weak trend)
    BEAR_MODERATE:    MFI <= 48, 15 <= ADX < 20 (moderate downtrend)
    BEAR_STRONG:      MFI <= 48, ADX >= 20 (strong downtrend)

Base Regimes:
    BULL:     All BULL_* states
    SIDEWAYS: All SIDEWAYS_* states
    BEAR:     All BEAR_* states

Usage:
    from trading.strategy.regime_router import RegimeRouter, RegimeContext

    router = RegimeRouter()
    context: RegimeContext = router.recommend(df_daily)

    # Access classification
    print(context.market_state)  # e.g., "BEAR_STRONG"
    print(context.regime)        # e.g., "BEAR"

    # Access raw indicators for custom logic
    print(context.mfi)           # e.g., 42.5
    print(context.adx)           # e.g., 28.3

    # Strategy decides whether to trade based on context
    if context.regime == "BEAR" and context.adx >= 25:
        # Strong bear trend - consider short position
        pass

Note:
    Strategy selection is NOT handled by RegimeRouter. Consumers (e.g.,
    MultiAssetAlphaManager, RegimeRouterLiveAdapter) are responsible for
    deciding which strategy to run based on the RegimeContext.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional, TYPE_CHECKING

import pandas as pd

from core.data_loader import DataLoader
from trading.indicators import technical as ta

if TYPE_CHECKING:
    from trading.data.data_cache import DataCache

MarketState = Literal[
    "BULL_STRONG",
    "BULL_MODERATE",
    "SIDEWAYS_BULL",
    "SIDEWAYS_NEUTRAL",
    "SIDEWAYS_BEAR",
    "BEAR_MODERATE",
    "BEAR_STRONG",
]

Regime = Literal["BULL", "SIDEWAYS", "BEAR"]


@dataclass(frozen=True)
class RegimeContext:
    """Market regime classification with raw indicator values.

    Attributes:
        market_state: Detailed market state (e.g., "BEAR_STRONG", "SIDEWAYS_NEUTRAL")
        regime: Base regime category ("BULL", "SIDEWAYS", or "BEAR")
        mfi: Money Flow Index value (0-100). Higher = more buying pressure
        adx: Average Directional Index value. Higher = stronger trend
    """
    market_state: MarketState
    regime: Regime
    mfi: float
    adx: float


# Backward compatibility alias
RegimeDecision = RegimeContext


class RegimeRouter:
    """Market regime classifier using MFI and ADX indicators.

    Provides market state classification and raw indicator values.
    Strategy selection is handled by consumers (e.g., AlphaManager).
    """

    def __init__(
        self,
        lookback_days: int = 180,
        mfi_period: int = 14,
        adx_period: int = 14,
        # Classification thresholds
        mfi_bull: float = 52.0,
        mfi_bear: float = 48.0,
        adx_strong: float = 25.0,
        adx_trend: float = 20.0,
        adx_weak: float = 15.0,
        # Data cache for efficient data loading
        data_cache: Optional["DataCache"] = None,
        # Deprecated parameters (ignored, kept for backward compatibility)
        **_deprecated_kwargs,
    ):
        self.lookback_days = int(lookback_days)
        self.mfi_period = int(mfi_period)
        self.adx_period = int(adx_period)

        self.mfi_bull = float(mfi_bull)
        self.mfi_bear = float(mfi_bear)
        self.adx_strong = float(adx_strong)
        self.adx_trend = float(adx_trend)
        self.adx_weak = float(adx_weak)

        # Data cache
        self.data_cache = data_cache

    def get_recent_daily_df(self, end_dt: datetime | None = None) -> pd.DataFrame:
        """Load daily candles for lookback window.

        Uses DataCache if available, otherwise falls back to direct DataLoader.
        Returns a DataFrame with columns: timestamp, open, high, low, close, volume
        """
        # Try cache first
        if self.data_cache:
            df = self.data_cache.get('day', periods=self.lookback_days)
            if df is not None and len(df) > 0:
                return df

        # Fallback to direct DataLoader
        if end_dt is None:
            end_dt = datetime.utcnow()

        start_date = (end_dt - timedelta(days=self.lookback_days)).strftime("%Y-%m-%d")
        end_date = end_dt.strftime("%Y-%m-%d")

        with DataLoader() as loader:
            df = loader.load_timeframe(
                "day",
                start_date=start_date,
                end_date=end_date,
            )

        return df

    @staticmethod
    def market_state_to_regime(market_state: MarketState) -> Regime:
        """Convert market state to base regime."""
        if market_state.startswith("BULL"):
            return "BULL"
        elif market_state.startswith("SIDEWAYS"):
            return "SIDEWAYS"
        return "BEAR"

    def classify_from_values(self, mfi: float, adx: float) -> MarketState:
        """Deterministic mapping for unit tests and for low-dependency routing."""
        if pd.isna(mfi) or pd.isna(adx):
            # Conservative default (avoid entering) when indicators are not ready.
            return "SIDEWAYS_NEUTRAL"

        if mfi >= self.mfi_bull:
            if adx >= self.adx_strong:
                return "BULL_STRONG"
            if adx >= self.adx_trend:
                return "BULL_MODERATE"
            return "SIDEWAYS_BULL"

        if mfi <= self.mfi_bear:
            if adx >= self.adx_trend:
                return "BEAR_STRONG"
            if adx >= self.adx_weak:
                return "BEAR_MODERATE"
            return "SIDEWAYS_BEAR"

        return "SIDEWAYS_NEUTRAL"

    def classify_market_state(self, df_day: pd.DataFrame) -> MarketState:
        """Classify market state from daily OHLCV data."""
        context = self.recommend(df_day)
        return context.market_state

    def recommend(self, df_day: pd.DataFrame) -> RegimeContext:
        """Get full regime context with market state and raw indicator values.

        Args:
            df_day: Daily OHLCV DataFrame with columns: high, low, close, volume

        Returns:
            RegimeContext with market_state, regime, mfi, adx
        """
        df = df_day.copy()

        # Default values when insufficient data
        if len(df) < max(self.mfi_period, self.adx_period) + 5:
            return RegimeContext(
                market_state="SIDEWAYS_NEUTRAL",
                regime="SIDEWAYS",
                mfi=50.0,
                adx=0.0,
            )

        df["mfi"] = _calc_mfi(df, period=self.mfi_period)
        df["adx"] = _calc_adx(df, period=self.adx_period)

        mfi = float(df["mfi"].iloc[-1])
        adx = float(df["adx"].iloc[-1])
        market_state = self.classify_from_values(mfi=mfi, adx=adx)
        regime = self.market_state_to_regime(market_state)

        return RegimeContext(
            market_state=market_state,
            regime=regime,
            mfi=mfi,
            adx=adx,
        )


def _calc_mfi(df: pd.DataFrame, period: int) -> pd.Series:
    """Calculate MFI using talib."""
    return ta.mfi(df["high"], df["low"], df["close"], df["volume"], period=period)


def _calc_adx(df: pd.DataFrame, period: int) -> pd.Series:
    """Calculate ADX using talib.

    Note: talib uses EMA smoothing (more accurate) vs the previous
    rolling mean implementation. This may result in slightly different
    values but is the industry-standard calculation.
    """
    adx_val, _, _ = ta.adx(df["high"], df["low"], df["close"], period=period)
    return adx_val.fillna(0.0)
