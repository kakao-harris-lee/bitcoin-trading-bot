# trading/strategies/v35_long_task.py
"""V35 Long Strategy - ported to stream architecture."""
from __future__ import annotations
import logging
from typing import Any, TYPE_CHECKING

from trading.streams.base_strategy import BaseStrategyTask
from trading.strategies.indicators import get_indicators

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)

# Regime thresholds (from original RegimeRouter)
MFI_BULL = 52
MFI_BEAR = 48
ADX_STRONG = 25
ADX_TREND = 20
ADX_WEAK = 15


class V35LongTask(BaseStrategyTask):
    """V35 Long-only strategy for Binance spot."""

    def __init__(
        self,
        symbols: list[str],
        redis: RedisStreams,
        config: dict | None = None,
    ):
        super().__init__(
            name="v35_long",
            symbols=symbols,
            redis=redis,
            market="spot",
            buffer_size=500,
        )
        self.config = config or {}
        self.min_data_points = 180  # Need enough data for indicators

    async def evaluate(self, symbol: str) -> dict[str, Any] | None:
        """Evaluate entry conditions for symbol."""
        buffer = self.price_buffer.get(symbol, [])

        # Need sufficient data
        if len(buffer) < self.min_data_points:
            return None

        # Calculate indicators
        indicators = self._calculate_indicators(symbol)
        if indicators is None:
            return None

        # Classify regime
        regime = self._classify_regime(indicators["mfi"], indicators["adx"])

        # Check entry
        if self._should_enter(regime):
            quantity = self._calculate_position_size(indicators["close"])
            return {
                "symbol": symbol,
                "side": "buy",
                "market": "spot",
                "quantity": str(quantity),
                "reason": f"V35 entry: {regime}, MFI={indicators['mfi']:.1f}, ADX={indicators['adx']:.1f}",
            }

        return None

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Self-classify market regime (replaces RegimeRouter)."""
        if mfi >= MFI_BULL:
            if adx >= ADX_STRONG:
                return "BULL_STRONG"
            elif adx >= ADX_TREND:
                return "BULL_MODERATE"
            else:
                return "SIDEWAYS_BULL"
        elif mfi <= MFI_BEAR:
            if adx >= ADX_TREND:
                return "BEAR_STRONG"
            elif adx >= ADX_WEAK:
                return "BEAR_MODERATE"
            else:
                return "SIDEWAYS_BEAR"
        else:
            return "SIDEWAYS_NEUTRAL"

    def _should_enter(self, regime: str) -> bool:
        """Check if regime is suitable for entry."""
        return regime in ("BULL_STRONG", "BULL_MODERATE")

    def _calculate_indicators(self, symbol: str) -> dict[str, float] | None:
        """Calculate indicators using OHLCV data from database."""
        try:
            # Get proper indicators from database OHLCV data
            indicators = get_indicators(symbol, periods=100)
            if indicators is None:
                logger.warning(f"Could not load indicators for {symbol}")
                return None

            # Use current price from buffer if available
            buffer = self.price_buffer.get(symbol, [])
            if buffer:
                indicators["close"] = float(buffer[-1]["price"])

            return indicators
        except Exception as e:
            logger.error(f"Indicator calculation failed for {symbol}: {e}")
            return None

    def _calculate_position_size(self, price: float) -> float:
        """Calculate position size based on config."""
        # Default: 0.01 BTC or configured amount
        return self.config.get("position_size", 0.01)
