"""V35 Classic Entry Strategy - Original simple regime-based approach.

Restored from initial implementation (c96dad8f) with minimal modifications.
Entry logic: MFI + ADX regime classification only.
No complex filters (MACD, RSI, breakout, stress).

Philosophy: Simple rules that work across market conditions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import Signal, TradingContext
from .registry import entry_strategy

logger = logging.getLogger(__name__)


@dataclass
class V35ClassicEntryParams:
    """Parameters for V35 Classic entry strategy.

    Minimal parameters - only what's needed for regime classification.
    """

    # MFI thresholds for regime classification
    mfi_bull: float = 52.0
    mfi_bear: float = 48.0

    # ADX thresholds for trend strength
    adx_strong: float = 25.0
    adx_trend: float = 20.0

    # Entry regimes (configurable)
    allowed_regimes: list[str] | None = None  # Default: BULL_STRONG, BULL_MODERATE

    # Position sizing
    position_size: float = 0.30

    # EMA200 filter (optional safety)
    use_ema200_filter: bool = True

    market: Literal["spot", "futures"] = "spot"


@entry_strategy(params_class=V35ClassicEntryParams)
class V35ClassicEntryStrategy:
    """V35 Classic entry strategy - simple regime-based entry.

    Entry conditions:
    1. Market regime is BULL_STRONG or BULL_MODERATE
    2. (Optional) Price above EMA200

    No MACD, RSI, breakout, or other complex filters.
    Simplicity is the key.
    """

    def __init__(self, params: V35ClassicEntryParams | None = None):
        self.params = params or V35ClassicEntryParams()
        if self.params.allowed_regimes is None:
            self.params.allowed_regimes = ["BULL_STRONG", "BULL_MODERATE"]

    def check_entry(self, ctx: TradingContext) -> Signal | None:
        """Check entry conditions.

        Args:
            ctx: Trading context with market data.

        Returns:
            Signal if entry conditions met, None otherwise.
        """
        market_data = ctx.market
        p = self.params

        # EMA200 filter (optional but recommended)
        if p.use_ema200_filter and market_data.ema_200 > 0:
            if market_data.close < market_data.ema_200:
                logger.debug(
                    f"{market_data.symbol}: Skip - below EMA200 "
                    f"({market_data.close:.0f} < {market_data.ema_200:.0f})"
                )
                return None

        # Classify regime using MFI and ADX
        regime = self._classify_regime(market_data.mfi, market_data.adx)

        # Check if regime is in allowed list
        if regime in p.allowed_regimes:
            reason = (
                f"V35Classic entry: {regime}, "
                f"MFI={market_data.mfi:.1f}, ADX={market_data.adx:.1f}"
            )
            if p.use_ema200_filter:
                reason += f", above EMA200"

            logger.info(f"{market_data.symbol}: {reason}")

            return Signal(
                symbol=market_data.symbol,
                side="buy",
                market=p.market,
                quantity=p.position_size,
                reason=reason,
            )

        return None

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Classify market regime based on MFI and ADX.

        Simple regime classification:
        - BULL_STRONG: MFI >= mfi_bull and ADX >= adx_strong
        - BULL_MODERATE: MFI >= mfi_bull and ADX >= adx_trend
        - SIDEWAYS: MFI between bear and bull
        - BEAR: MFI <= mfi_bear
        """
        p = self.params

        if mfi >= p.mfi_bull:
            if adx >= p.adx_strong:
                return "BULL_STRONG"
            elif adx >= p.adx_trend:
                return "BULL_MODERATE"
            else:
                return "SIDEWAYS_UP"
        elif mfi <= p.mfi_bear:
            return "BEAR"
        else:
            return "SIDEWAYS"
