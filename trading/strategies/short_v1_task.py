# trading/strategies/short_v1_task.py
"""ShortV1 Strategy - ported to stream architecture."""
from __future__ import annotations
import logging
from typing import Any, TYPE_CHECKING
import numpy as np

from trading.streams.base_strategy import BaseStrategyTask

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)

# Regime thresholds
MFI_BEAR = 48
ADX_TREND = 20

# RSI threshold for short entry
RSI_OVERBOUGHT = 70


class ShortV1Task(BaseStrategyTask):
    """Short strategy for Binance futures in bear markets."""

    def __init__(
        self,
        symbols: list[str],
        redis: RedisStreams,
        config: dict | None = None,
    ):
        super().__init__(
            name="short_v1",
            symbols=symbols,
            redis=redis,
            market="futures",  # Shorts on futures
            buffer_size=500,
        )
        self.config = config or {}
        self.min_data_points = 180

    async def evaluate(self, symbol: str) -> dict[str, Any] | None:
        """Evaluate short entry conditions."""
        buffer = self.price_buffer.get(symbol, [])

        if len(buffer) < self.min_data_points:
            return None

        indicators = self._calculate_indicators(symbol)
        if indicators is None:
            return None

        regime = self._classify_regime(indicators["mfi"], indicators["adx"])

        if not self._should_enter(regime):
            return None

        # Short when RSI is overbought in bear market
        if indicators["rsi"] > RSI_OVERBOUGHT:
            quantity = self._calculate_position_size(indicators["close"])
            return {
                "symbol": symbol,
                "side": "sell",
                "market": "futures",
                "quantity": str(quantity),
                "reason": f"ShortV1 entry: {regime}, RSI={indicators['rsi']:.1f} (overbought)",
            }

        return None

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Self-classify market regime."""
        if mfi <= MFI_BEAR:
            if adx >= ADX_TREND:
                return "BEAR_STRONG"
            else:
                return "BEAR_MODERATE"
        elif mfi >= 52:
            return "BULL"
        else:
            return "SIDEWAYS"

    def _should_enter(self, regime: str) -> bool:
        """Only enter on strong bear regime."""
        return regime == "BEAR_STRONG"

    def _calculate_indicators(self, symbol: str) -> dict[str, float] | None:
        """Calculate indicators from price buffer."""
        try:
            buffer = list(self.price_buffer[symbol])
            closes = np.array([float(p["price"]) for p in buffer])

            sma = np.mean(closes[-20:])
            current = closes[-1]
            momentum = (current - sma) / sma * 100

            mfi = 50 + momentum * 2
            mfi = max(0, min(100, mfi))

            volatility = np.std(closes[-20:]) / np.mean(closes[-20:])
            adx = volatility * 1000
            adx = max(0, min(50, adx))

            # RSI calculation with edge case handling
            deltas = np.diff(closes[-15:])
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_gain = np.mean(gains)
            avg_loss = np.mean(losses)

            # Minimum movement threshold (0.01% of price) to avoid false signals
            min_movement = np.mean(closes[-15:]) * 0.0001
            if avg_gain < min_movement and avg_loss < min_movement:
                rsi = 50.0  # No significant movement, neutral RSI
            elif avg_loss < min_movement:
                rsi = 100.0  # Only significant gains
            else:
                rs = avg_gain / max(avg_loss, min_movement)
                rsi = 100 - (100 / (1 + rs))

            return {
                "mfi": mfi,
                "adx": adx,
                "close": current,
                "rsi": rsi,
            }
        except Exception as e:
            logger.error(f"Indicator calculation failed: {e}")
            return None

    def _calculate_position_size(self, price: float) -> float:
        """Calculate position size for futures."""
        return self.config.get("position_size", 0.01)
