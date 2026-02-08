"""Bear Short Entry Strategy - conservative futures short during BEAR_STRONG regimes.

Entry conditions (all must be true):
1. Regime is BEAR_STRONG (strict - not BEAR_MODERATE)
2. MACD bearish momentum (MACD < Signal line)

Optional filters (per-asset, configured in allocation.json):
3. EMA200 filter: price < EMA200 (blocks shorts during bull pullbacks)
4. RSI ceiling: RSI < threshold (confirms sustained bearish pressure)
5. Consecutive regime: N consecutive BEAR_STRONG candles (regime stability)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from .models import MarketData, Signal, TradingContext
from .registry import entry_strategy

logger = logging.getLogger(__name__)


@dataclass
class BearShortEntryParams:
    """Parameters for Bear Short entry strategy."""

    # Volume ratio threshold (0 = disabled, kept for backward compat)
    volume_ratio_threshold: float = 0.0

    # EMA200 filter: only short when price < EMA200 (0 = disabled)
    ema200_filter: bool = False

    # RSI ceiling: only short when RSI < this value (0 = disabled)
    rsi_max: float = 0.0

    # Consecutive BEAR_STRONG candles required (1 = no extra requirement)
    min_consecutive_bear: int = 1

    # Position sizing
    position_size: float = 0.01
    market: Literal["futures"] = "futures"


@entry_strategy(params_class=BearShortEntryParams)
class BearShortEntryStrategy:
    """Conservative short entry for confirmed bear markets.

    Entry conditions (all must be true):
    1. Regime == BEAR_STRONG (strict gate)
    2. MACD < MACD Signal (bearish momentum)
    3. price < EMA200 (if ema200_filter enabled)
    4. RSI < rsi_max (if rsi_max > 0)
    5. N consecutive BEAR_STRONG candles (if min_consecutive_bear > 1)

    Returns Signal with side="sell" to open a short position.
    Implements IEntryStrategy protocol (structural subtyping).
    """

    def __init__(self, params: BearShortEntryParams | None = None):
        self.params = params or BearShortEntryParams()
        self._consecutive_bear: dict[str, int] = {}

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
        symbol = market_data.symbol
        p = self.params

        # Track consecutive BEAR_STRONG candles
        if regime == "BEAR_STRONG":
            self._consecutive_bear[symbol] = self._consecutive_bear.get(symbol, 0) + 1
        else:
            self._consecutive_bear[symbol] = 0

        # Gate 1: Regime must be BEAR_STRONG only (strict)
        if regime != "BEAR_STRONG":
            return None

        # Gate 2: MACD bearish momentum (MACD < Signal)
        if market_data.macd >= market_data.macd_signal:
            logger.debug(
                f"{symbol}: BearShort skip - MACD={market_data.macd:.2f} "
                f">= Signal={market_data.macd_signal:.2f}"
            )
            return None

        # Gate 3: EMA200 filter (price must be below 200-EMA)
        if p.ema200_filter and market_data.ema_200 > 0:
            if market_data.close >= market_data.ema_200:
                logger.debug(
                    f"{symbol}: BearShort skip - price {market_data.close:.0f} "
                    f">= EMA200 {market_data.ema_200:.0f}"
                )
                return None

        # Gate 4: RSI ceiling
        if p.rsi_max > 0 and market_data.rsi >= p.rsi_max:
            logger.debug(
                f"{symbol}: BearShort skip - RSI {market_data.rsi:.1f} "
                f">= max {p.rsi_max}"
            )
            return None

        # Gate 5: Consecutive BEAR_STRONG candles
        consec = self._consecutive_bear.get(symbol, 0)
        if consec < p.min_consecutive_bear:
            logger.debug(
                f"{symbol}: BearShort skip - {consec} consecutive BEAR_STRONG "
                f"< required {p.min_consecutive_bear}"
            )
            return None

        # Gate 6: Volume confirmation (optional, disabled by default)
        if p.volume_ratio_threshold > 0 and context.volume_ratio < p.volume_ratio_threshold:
            logger.debug(
                f"{symbol}: BearShort skip - volume_ratio="
                f"{context.volume_ratio:.2f} < {p.volume_ratio_threshold}"
            )
            return None

        # All conditions met
        reason = (
            f"BearShort entry: {regime}, "
            f"MACD={market_data.macd:.2f}<Signal={market_data.macd_signal:.2f}"
        )
        if p.ema200_filter:
            reason += f", <EMA200"
        if p.rsi_max > 0:
            reason += f", RSI={market_data.rsi:.1f}"
        logger.info(f"{symbol}: {reason}")

        return Signal(
            symbol=market_data.symbol,
            side="sell",
            market=self.params.market,
            quantity=self.params.position_size,
            reason=reason,
        )
