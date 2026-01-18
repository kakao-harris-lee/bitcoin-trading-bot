"""V35 Entry Strategy - extracted from V35LongTask.

Implements IEntryStrategy protocol for V35 long-only entry logic.
Entry conditions: BULL_STRONG or BULL_MODERATE regime classification.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import MarketData, Signal
from .registry import entry_strategy

logger = logging.getLogger(__name__)


@dataclass
class V35EntryParams:
    """Parameters for V35 entry strategy."""

    # MFI thresholds for regime classification
    mfi_bull: float = 52.0
    mfi_bear: float = 48.0

    # ADX thresholds for trend strength
    adx_strong: float = 25.0
    adx_trend: float = 20.0
    adx_weak: float = 15.0

    # Position sizing
    position_size: float = 0.01
    market: Literal["spot", "futures"] = "spot"


@entry_strategy(params_class=V35EntryParams)
class V35EntryStrategy:
    """V35 Long entry strategy.

    Enters long positions when market regime is bullish:
    - BULL_STRONG: MFI >= mfi_bull and ADX >= adx_strong
    - BULL_MODERATE: MFI >= mfi_bull and ADX >= adx_trend

    Implements IEntryStrategy protocol (structural subtyping).
    """

    def __init__(self, params: V35EntryParams | None = None):
        """Initialize with entry parameters.

        Args:
            params: Entry parameters. Uses defaults if not provided.
        """
        self.params = params or V35EntryParams()

    def check_entry(self, market_data: MarketData) -> Signal | None:
        """Check entry conditions and return signal if entry criteria met.

        Args:
            market_data: Current market state with indicators.

        Returns:
            Signal with side="buy" if entry conditions met, None otherwise.
        """
        regime = self._classify_regime(market_data.mfi, market_data.adx)

        if self._should_enter(regime):
            reason = (
                f"V35 entry: {regime}, "
                f"MFI={market_data.mfi:.1f}, "
                f"ADX={market_data.adx:.1f}"
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

        Regimes:
        - BULL_STRONG: Strong bullish trend (high MFI + high ADX)
        - BULL_MODERATE: Moderate bullish trend (high MFI + moderate ADX)
        - SIDEWAYS_BULL: Weak bullish (high MFI + low ADX)
        - BEAR_STRONG: Strong bearish trend
        - BEAR_MODERATE: Moderate bearish trend
        - SIDEWAYS_BEAR: Weak bearish
        - SIDEWAYS_NEUTRAL: No clear direction

        Args:
            mfi: Money Flow Index value (0-100)
            adx: Average Directional Index value

        Returns:
            Regime classification string.
        """
        p = self.params

        if mfi >= p.mfi_bull:
            if adx >= p.adx_strong:
                return "BULL_STRONG"
            elif adx >= p.adx_trend:
                return "BULL_MODERATE"
            else:
                return "SIDEWAYS_BULL"
        elif mfi <= p.mfi_bear:
            if adx >= p.adx_trend:
                return "BEAR_STRONG"
            elif adx >= p.adx_weak:
                return "BEAR_MODERATE"
            else:
                return "SIDEWAYS_BEAR"
        else:
            return "SIDEWAYS_NEUTRAL"

    def _should_enter(self, regime: str) -> bool:
        """Check if regime is suitable for long entry.

        Args:
            regime: Market regime classification.

        Returns:
            True if should enter long position.
        """
        return regime in ("BULL_STRONG", "BULL_MODERATE")
