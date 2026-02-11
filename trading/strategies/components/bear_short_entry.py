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

        self._update_consecutive_bear(symbol, regime)

        # Gate 1: Regime must be BEAR_STRONG only (strict)
        if regime != "BEAR_STRONG":
            return None

        if not self._passes_macd_gate(market_data):
            return None

        if not self._passes_ema200_gate(market_data):
            return None

        if not self._passes_rsi_gate(market_data):
            return None

        if not self._passes_consecutive_bear_gate(symbol):
            return None

        if not self._passes_volume_gate(symbol, context.volume_ratio):
            return None

        # All conditions met
        reason = self._build_reason(market_data, regime)
        logger.info(f"{symbol}: {reason}")

        return Signal(
            symbol=market_data.symbol,
            side="sell",
            market=self.params.market,
            quantity=self.params.position_size,
            reason=reason,
        )

    def _update_consecutive_bear(self, symbol: str, regime: str) -> None:
        if regime == "BEAR_STRONG":
            self._consecutive_bear[symbol] = self._consecutive_bear.get(symbol, 0) + 1
            return
        self._consecutive_bear[symbol] = 0

    def _passes_macd_gate(self, market_data: MarketData) -> bool:
        if market_data.macd < market_data.macd_signal:
            return True
        logger.debug(
            f"{market_data.symbol}: BearShort skip - MACD={market_data.macd:.2f} "
            f">= Signal={market_data.macd_signal:.2f}"
        )
        return False

    def _passes_ema200_gate(self, market_data: MarketData) -> bool:
        if not self.params.ema200_filter or market_data.ema_200 <= 0:
            return True
        if market_data.close < market_data.ema_200:
            return True
        logger.debug(
            f"{market_data.symbol}: BearShort skip - price {market_data.close:.0f} "
            f">= EMA200 {market_data.ema_200:.0f}"
        )
        return False

    def _passes_rsi_gate(self, market_data: MarketData) -> bool:
        if self.params.rsi_max <= 0:
            return True
        if market_data.rsi < self.params.rsi_max:
            return True
        logger.debug(
            f"{market_data.symbol}: BearShort skip - RSI {market_data.rsi:.1f} "
            f">= max {self.params.rsi_max}"
        )
        return False

    def _passes_consecutive_bear_gate(self, symbol: str) -> bool:
        consec = self._consecutive_bear.get(symbol, 0)
        if consec >= self.params.min_consecutive_bear:
            return True
        logger.debug(
            f"{symbol}: BearShort skip - {consec} consecutive BEAR_STRONG "
            f"< required {self.params.min_consecutive_bear}"
        )
        return False

    def _passes_volume_gate(self, symbol: str, volume_ratio: float) -> bool:
        threshold = self.params.volume_ratio_threshold
        if threshold <= 0:
            return True
        if volume_ratio >= threshold:
            return True
        logger.debug(
            f"{symbol}: BearShort skip - volume_ratio={volume_ratio:.2f} < {threshold}"
        )
        return False

    def _build_reason(self, market_data: MarketData, regime: str) -> str:
        reason = (
            f"BearShort entry: {regime}, "
            f"MACD={market_data.macd:.2f}<Signal={market_data.macd_signal:.2f}"
        )
        if self.params.ema200_filter:
            reason += ", <EMA200"
        if self.params.rsi_max > 0:
            reason += f", RSI={market_data.rsi:.1f}"
        return reason
