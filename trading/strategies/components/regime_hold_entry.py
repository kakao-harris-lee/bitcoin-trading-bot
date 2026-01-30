"""Regime-hold entry strategy: stay long in allowed regimes."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from .models import Signal, TradingContext
from .registry import entry_strategy

logger = logging.getLogger(__name__)


@dataclass
class RegimeHoldEntryParams:
    """Parameters for regime-hold entry strategy."""

    allowed_regimes: list[str] = field(
        default_factory=lambda: [
            "BULL_STRONG",
            "BULL_MODERATE",
            "SIDEWAYS_UP",
        ]
    )
    min_adx: float = 0.0
    allow_extreme_volatility: bool = False
    position_size: float = 0.01
    market: Literal["futures"] = "futures"


@entry_strategy(params_class=RegimeHoldEntryParams)
class RegimeHoldEntryStrategy:
    """Enter long when regime is in allowed set; hold otherwise."""

    def __init__(self, params: RegimeHoldEntryParams | None = None):
        self.params = params or RegimeHoldEntryParams()

    def check_entry(self, ctx: TradingContext) -> Signal | None:
        market_data = ctx.market
        context = ctx.regime
        p = self.params

        if not p.allow_extreme_volatility and context.is_extreme_volatility:
            logger.debug(
                f"{market_data.symbol}: RegimeHold entry blocked - extreme volatility"
            )
            return None

        if context.adx < p.min_adx:
            logger.debug(
                f"{market_data.symbol}: RegimeHold entry blocked - ADX {context.adx:.1f} < {p.min_adx:.1f}"
            )
            return None

        if context.regime in p.allowed_regimes:
            reason = f"RegimeHold entry: {context.regime}"
            logger.info(f"{market_data.symbol}: {reason}")
            return Signal(
                symbol=market_data.symbol,
                side="buy",
                market=p.market,
                quantity=p.position_size,
                reason=reason,
            )

        return None
