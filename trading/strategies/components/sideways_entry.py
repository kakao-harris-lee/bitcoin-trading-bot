"""SidewaysV2 Entry Strategy - extracted from SidewaysV2Task.

Implements IEntryStrategy protocol for sideways/range-bound market entry.
Entry conditions: SIDEWAYS regime + RSI oversold (mean reversion buy).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import MarketData, Signal
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
    market: Literal["spot", "futures"] = "spot"


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

    def check_entry(self, market_data: MarketData) -> Signal | None:
        """Check entry conditions and return signal if criteria met.

        Args:
            market_data: Current market state with indicators.

        Returns:
            Signal with side="buy" if entry conditions met, None otherwise.
        """
        regime = self._classify_regime(market_data.mfi, market_data.adx)

        if not self._should_enter(regime):
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
        return regime.startswith("SIDEWAYS")
