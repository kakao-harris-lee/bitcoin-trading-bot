"""ShortV1 Entry Strategy - extracted from ShortV1Task.

Implements IEntryStrategy protocol for short entry in bear markets.
Entry conditions: BEAR_STRONG regime + RSI overbought.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import (
    MarketContext,
    MarketData,
    Signal,
    BULLISH_NO_SHORT_REGIMES,
    SIDEWAYS_VOLATILE_REGIMES,
    BEAR_REGIMES,
)
from .registry import entry_strategy

logger = logging.getLogger(__name__)


@dataclass
class ShortEntryParams:
    """Parameters for Short entry strategy."""

    # MFI threshold for bear regime
    mfi_bear: float = 48.0
    mfi_bull: float = 52.0

    # ADX threshold for trend strength
    adx_trend: float = 20.0

    # RSI threshold for short entry (overbought)
    rsi_overbought: float = 70.0

    # Position sizing
    position_size: float = 0.01
    market: Literal["spot", "futures"] = "futures"


@entry_strategy(params_class=ShortEntryParams)
class ShortEntryStrategy:
    """Short entry strategy for bear markets.

    Enters short positions when:
    - Market regime is BEAR_STRONG (MFI <= mfi_bear and ADX >= adx_trend)
    - RSI is overbought (> rsi_overbought threshold)

    Note: Returns Signal with side="sell" to open a short position.

    Implements IEntryStrategy protocol (structural subtyping).
    """

    def __init__(self, params: ShortEntryParams | None = None):
        """Initialize with entry parameters.

        Args:
            params: Entry parameters. Uses defaults if not provided.
        """
        self.params = params or ShortEntryParams()

    def check_entry(
        self,
        market_data: MarketData,
        context: MarketContext,
    ) -> Signal | None:
        """Check entry conditions and return signal if criteria met.

        Safety filters (Binance Futures):
        - Skip if BULL regime (never short in bull market)
        - Allow BEAR regimes (BEAR_STRONG, BEAR_MODERATE)
        - Allow SIDEWAYS_FLAT/DOWN only with extreme volatility

        Args:
            market_data: Current market state with indicators.
            context: Pre-analyzed market context (trend, volatility).

        Returns:
            Signal with side="sell" to open short if conditions met, None otherwise.
        """
        regime = context.regime

        # === SAFETY FILTER 1: Never short in BULL ===
        # BULL_STRONG, BULL_MODERATE, SIDEWAYS_UP are all bullish - don't short
        if regime in BULLISH_NO_SHORT_REGIMES:
            logger.debug(
                f"{market_data.symbol}: Skipping short entry - bullish regime "
                f"({regime})"
            )
            return None

        # === SAFETY FILTER 2: SIDEWAYS requires extreme volatility ===
        # Only short in SIDEWAYS_FLAT/DOWN if market is volatile
        if regime in SIDEWAYS_VOLATILE_REGIMES:
            if not context.is_extreme_volatility:
                logger.debug(
                    f"{market_data.symbol}: Skipping short entry - SIDEWAYS without "
                    f"extreme volatility ({context.volatility_score*100:.2f}%)"
                )
                return None

        # === Regime check ===
        # BEAR_STRONG, BEAR_MODERATE: Always allow
        # SIDEWAYS_FLAT, SIDEWAYS_DOWN: Only if extreme volatility (checked above)
        if not self._should_enter(regime, context.is_extreme_volatility):
            return None

        # Short when RSI is overbought in bear market
        if market_data.rsi > self.params.rsi_overbought:
            reason = (
                f"ShortV1 entry: {regime}, "
                f"RSI={market_data.rsi:.1f} (overbought)"
            )
            logger.info(f"{market_data.symbol}: {reason}")

            return Signal(
                symbol=market_data.symbol,
                side="sell",  # Short entry
                market=self.params.market,
                quantity=self.params.position_size,
                reason=reason,
            )

        return None

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Classify market regime based on MFI and ADX.

        Args:
            mfi: Money Flow Index value (0-100)
            adx: Average Directional Index value

        Returns:
            Regime classification string.
        """
        p = self.params

        if mfi <= p.mfi_bear:
            if adx >= p.adx_trend:
                return "BEAR_STRONG"
            else:
                return "BEAR_MODERATE"
        elif mfi >= p.mfi_bull:
            return "BULL"
        else:
            return "SIDEWAYS"

    def _should_enter(self, regime: str, is_extreme_volatility: bool = False) -> bool:
        """Check if regime is suitable for short entry.

        Allowed regimes:
        - BEAR_STRONG: Always allowed (strong bearish trend)
        - BEAR_MODERATE: Always allowed (moderate bearish trend)
        - SIDEWAYS_FLAT/DOWN: Only with extreme volatility

        Args:
            regime: Market regime classification.
            is_extreme_volatility: Whether volatility exceeds threshold.

        Returns:
            True if should enter short position.
        """
        # BEAR regimes: Always allow shorting
        if regime in BEAR_REGIMES:
            return True

        # SIDEWAYS_FLAT/DOWN: Only with extreme volatility
        if regime in SIDEWAYS_VOLATILE_REGIMES:
            return is_extreme_volatility

        # BULL regimes and SIDEWAYS_UP: Never short
        return False
