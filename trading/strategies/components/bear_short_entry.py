"""Bear Short Entry Strategy - conservative futures short during BEAR_STRONG regimes.

Enters short positions when all three conditions are met:
1. Regime is BEAR_STRONG (strict - not BEAR_MODERATE)
2. MACD bearish momentum (MACD < Signal line)
3. Volume confirmation (volume_ratio >= threshold)

Based on hybrid analysis (4H indicators + 1H SL/TP) showing 57.3% win rate
and +989% total P&L across BTC/ETH/SOL over ~6 years.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import MarketData, Signal, TradingContext
from .registry import entry_strategy

logger = logging.getLogger(__name__)


@dataclass
class BearShortEntryParams:
    """Parameters for Bear Short entry strategy."""

    # Volume ratio threshold for confirmation
    volume_ratio_threshold: float = 1.5

    # Position sizing
    position_size: float = 0.01
    market: Literal["futures"] = "futures"


@entry_strategy(params_class=BearShortEntryParams)
class BearShortEntryStrategy:
    """Conservative short entry for confirmed bear markets.

    Entry conditions (all must be true):
    1. Regime == BEAR_STRONG (strict gate)
    2. MACD < MACD Signal (bearish momentum)
    3. volume_ratio >= threshold (volume confirmation)

    Returns Signal with side="sell" to open a short position.
    Implements IEntryStrategy protocol (structural subtyping).
    """

    def __init__(self, params: BearShortEntryParams | None = None):
        self.params = params or BearShortEntryParams()

    def check_entry(self, ctx: TradingContext) -> Signal | None:
        """Check entry conditions for bear short.

        Args:
            ctx: Trading context with market data and regime.

        Returns:
            Signal with side="sell" if all conditions met, None otherwise.
        """
        market_data = ctx.market
        context = ctx.regime
        regime = context.regime

        # Gate 1: Regime must be BEAR_STRONG only (strict)
        if regime != "BEAR_STRONG":
            logger.debug(
                f"{market_data.symbol}: BearShort skip - regime {regime} "
                f"(need BEAR_STRONG)"
            )
            return None

        # Gate 2: MACD bearish momentum (MACD < Signal)
        if market_data.macd >= market_data.macd_signal:
            logger.debug(
                f"{market_data.symbol}: BearShort skip - MACD={market_data.macd:.2f} "
                f">= Signal={market_data.macd_signal:.2f}"
            )
            return None

        # Gate 3: Volume confirmation
        if context.volume_ratio < self.params.volume_ratio_threshold:
            logger.debug(
                f"{market_data.symbol}: BearShort skip - volume_ratio="
                f"{context.volume_ratio:.2f} < {self.params.volume_ratio_threshold}"
            )
            return None

        # All conditions met
        reason = (
            f"BearShort entry: {regime}, "
            f"MACD={market_data.macd:.2f}<Signal={market_data.macd_signal:.2f}, "
            f"vol_ratio={context.volume_ratio:.2f}"
        )
        logger.info(f"{market_data.symbol}: {reason}")

        return Signal(
            symbol=market_data.symbol,
            side="sell",
            market=self.params.market,
            quantity=self.params.position_size,
            reason=reason,
        )
