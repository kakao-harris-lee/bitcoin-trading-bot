"""SidewaysV2 Entry Strategy - extracted from SidewaysV2Task.

Implements IEntryStrategy protocol for sideways/range-bound market entry.
Entry conditions: SIDEWAYS regime + RSI oversold (mean reversion buy).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import MarketContext, MarketData, Signal, SIDEWAYS_REGIMES
from .registry import entry_strategy

logger = logging.getLogger(__name__)


@dataclass
class SidewaysEntryParams:
    """Parameters for Sideways entry strategy."""

    # MFI thresholds for regime classification
    mfi_bull: float = 52.0
    mfi_bear: float = 48.0

    # ADX thresholds
    adx_trend: float = 20.0
    adx_weak: float = 15.0

    # RSI threshold for mean reversion entry
    rsi_oversold: float = 35.0

    # Position sizing
    position_size: float = 0.01
    market: Literal["futures"] = "futures"


@entry_strategy(params_class=SidewaysEntryParams)
class SidewaysEntryStrategy:
    """Sideways/range-bound entry strategy.

    Enters long positions on mean reversion when:
    - Market regime is SIDEWAYS (neutral MFI or low ADX)
    - RSI is oversold (<= rsi_oversold threshold)

    Implements IEntryStrategy protocol (structural subtyping).
    """

    def __init__(self, params: SidewaysEntryParams | None = None):
        """Initialize with entry parameters.

        Args:
            params: Entry parameters. Uses defaults if not provided.
        """
        self.params = params or SidewaysEntryParams()

    def check_entry(
        self,
        market_data: MarketData,
        context: MarketContext,
    ) -> Signal | None:
        """Check entry conditions and return signal if criteria met.

        Safety filters (Binance Futures):
        - Skip if high volume (breakout potential kills mean reversion)
        - Skip if regime is not SIDEWAYS (only trade range-bound markets)
        - Skip if extreme volatility (avoid wild swings)

        Args:
            market_data: Current market state with indicators.
            context: Pre-analyzed market context (trend, volatility).

        Returns:
            Signal with side="buy" if entry conditions met, None otherwise.
        """
        # === SAFETY FILTER 1: High volume ===
        # High volume often precedes breakout/trend start, killing mean reversion
        if context.is_high_volume:
            logger.debug(
                f"{market_data.symbol}: Skipping sideways entry - high volume "
                f"(ratio={context.volume_ratio:.2f}x) - potential breakout"
            )
            return None

        # === SAFETY FILTER 2: Non-SIDEWAYS regime ===
        # Only trade mean reversion in range-bound markets
        regime = context.regime
        if not self._should_enter(regime):
            logger.debug(
                f"{market_data.symbol}: Skipping sideways entry - not SIDEWAYS regime "
                f"({regime})"
            )
            return None

        # === SAFETY FILTER 3: Extreme volatility ===
        if context.is_extreme_volatility:
            logger.debug(
                f"{market_data.symbol}: Skipping sideways entry - extreme volatility "
                f"({context.volatility_score*100:.2f}%)"
            )
            return None

        # Mean reversion: buy when oversold
        if market_data.rsi <= self.params.rsi_oversold:
            reason = (
                f"SidewaysV2 entry: {regime}, "
                f"RSI={market_data.rsi:.1f} (oversold)"
            )
            logger.info(f"{market_data.symbol}: {reason}")

            return Signal(
                symbol=market_data.symbol,
                side="buy",
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

        if mfi >= p.mfi_bull:
            if adx >= p.adx_trend:
                return "BULL_MODERATE"
            else:
                return "SIDEWAYS_BULL"
        elif mfi <= p.mfi_bear:
            if adx >= p.adx_trend:
                return "BEAR_MODERATE"
            else:
                return "SIDEWAYS_BEAR"
        else:
            return "SIDEWAYS_NEUTRAL"

    def _should_enter(self, regime: str) -> bool:
        """Check if regime is suitable for sideways entry.

        Args:
            regime: Market regime classification.

        Returns:
            True if regime is sideways (suitable for mean reversion).
        """
        return regime in SIDEWAYS_REGIMES
