# trading/strategies/v35_long_task.py
"""V35 Long Strategy - ported to stream architecture."""
from __future__ import annotations
import logging
from typing import Any, TYPE_CHECKING
import numpy as np

from trading.streams.base_strategy import BaseStrategyTask

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
        """Calculate MFI and ADX from price buffer."""
        try:
            buffer = list(self.price_buffer[symbol])
            closes = np.array([float(p["price"]) for p in buffer])

            # For now, use simplified calculation
            # In production, use talib with full OHLCV data
            # This is a placeholder that returns mock values
            # Real implementation will fetch OHLCV from data source

            # Simplified momentum: price vs SMA
            sma = np.mean(closes[-20:])
            current = closes[-1]
            momentum = (current - sma) / sma * 100

            # Mock MFI based on momentum
            mfi = 50 + momentum * 2
            mfi = max(0, min(100, mfi))

            # Mock ADX (trend strength)
            volatility = np.std(closes[-20:]) / np.mean(closes[-20:])
            adx = volatility * 1000  # Scale to typical ADX range
            adx = max(0, min(50, adx))

            return {
                "mfi": mfi,
                "adx": adx,
                "close": current,
            }
        except Exception as e:
            logger.error(f"Indicator calculation failed: {e}")
            return None

    def _calculate_position_size(self, price: float) -> float:
        """Calculate position size based on config."""
        # Default: 0.01 BTC or configured amount
        return self.config.get("position_size", 0.01)
