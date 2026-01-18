"""ShortV1 Entry Strategy - extracted from ShortV1Task.

Implements IEntryStrategy protocol for short entry in bear markets.
Entry conditions: BEAR_STRONG regime + RSI overbought.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import MarketData, Signal
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

    def check_entry(self, market_data: MarketData) -> Signal | None:
        """Check entry conditions and return signal if criteria met.

        Args:
            market_data: Current market state with indicators.

        Returns:
            Signal with side="sell" to open short if conditions met, None otherwise.
        """
        regime = self._classify_regime(market_data.mfi, market_data.adx)

        if not self._should_enter(regime):
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

    def _should_enter(self, regime: str) -> bool:
        """Check if regime is suitable for short entry.

        Only enters on strong bear regime to maximize profit potential.

        Args:
            regime: Market regime classification.

        Returns:
            True if should enter short position.
        """
        return regime == "BEAR_STRONG"
