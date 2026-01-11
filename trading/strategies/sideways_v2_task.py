# trading/strategies/sideways_v2_task.py
"""SidewaysV2 Strategy - ported to stream architecture."""
from __future__ import annotations
import logging
from typing import Any, TYPE_CHECKING

from trading.streams.base_strategy import BaseStrategyTask
from trading.strategies.indicators import get_indicators

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)

# Regime thresholds
MFI_BULL = 52
MFI_BEAR = 48
ADX_TREND = 20
ADX_WEAK = 15

# RSI thresholds for mean reversion
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
RSI_MEAN = 50

# Exit thresholds
TAKE_PROFIT_PCT = 1.5  # 1.5% profit target
STOP_LOSS_PCT = 1.0    # 1.0% stop loss


class SidewaysV2Task(BaseStrategyTask):
    """Sideways/range-bound strategy for Binance spot."""

    def __init__(
        self,
        symbols: list[str],
        redis: RedisStreams,
        config: dict | None = None,
    ):
        super().__init__(
            name="sideways_v2",
            symbols=symbols,
            redis=redis,
            market="spot",
            buffer_size=500,
        )
        self.config = config or {}
        self.min_data_points = 180

    async def evaluate(self, symbol: str) -> dict[str, Any] | None:
        """Evaluate entry conditions for sideways market."""
        buffer = self.price_buffer.get(symbol, [])

        if len(buffer) < self.min_data_points:
            return None

        indicators = self._calculate_indicators(symbol)
        if indicators is None:
            return None

        regime = self._classify_regime(indicators["mfi"], indicators["adx"])

        if not self._should_enter(regime):
            return None

        # Mean reversion: buy when oversold
        if indicators["rsi"] <= RSI_OVERSOLD:
            quantity = await self._calculate_position_size(symbol, indicators["close"])
            return {
                "symbol": symbol,
                "side": "buy",
                "market": "spot",
                "quantity": str(quantity),
                "reason": f"SidewaysV2 entry: {regime}, RSI={indicators['rsi']:.1f} (oversold)",
            }

        return None

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Self-classify market regime."""
        if mfi >= MFI_BULL:
            if adx >= ADX_TREND:
                return "BULL_MODERATE"
            else:
                return "SIDEWAYS_BULL"
        elif mfi <= MFI_BEAR:
            if adx >= ADX_TREND:
                return "BEAR_MODERATE"
            elif adx >= ADX_WEAK:
                return "SIDEWAYS_BEAR"
            else:
                return "SIDEWAYS_BEAR"
        else:
            return "SIDEWAYS_NEUTRAL"

    def _should_enter(self, regime: str) -> bool:
        """Check if regime is suitable for entry."""
        return regime.startswith("SIDEWAYS")

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

    async def _calculate_position_size(self, symbol: str, price: float) -> float:
        """Calculate position size (dynamic or fixed based on config)."""
        # Use dynamic sizing if enabled, otherwise fall back to fixed
        use_dynamic = self.config.get("dynamic_sizing", False)

        if use_dynamic:
            position_pct = self.config.get("position_pct", 0.02)  # 2% of balance
            return await self.get_dynamic_position_size(symbol, price, position_pct)
        else:
            return self.config.get("position_size", 0.01)

    async def evaluate_exit(self, symbol: str, position: dict) -> dict[str, Any] | None:
        """Evaluate exit conditions for mean-reversion strategy."""
        indicators = self._calculate_indicators(symbol)
        if indicators is None:
            return None

        entry_price = float(position.get("entry_price", 0))
        quantity = float(position.get("quantity", 0))
        current_price = indicators["close"]

        if entry_price <= 0 or quantity <= 0:
            return None

        # Calculate P&L percentage
        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        # Exit condition 1: Take profit on price target
        if pnl_pct >= TAKE_PROFIT_PCT:
            return {
                "symbol": symbol,
                "side": "sell",
                "market": "spot",
                "quantity": str(quantity),
                "reason": f"SidewaysV2 exit: Take profit {pnl_pct:.2f}%",
            }

        # Exit condition 2: Stop loss
        if pnl_pct <= -STOP_LOSS_PCT:
            return {
                "symbol": symbol,
                "side": "sell",
                "market": "spot",
                "quantity": str(quantity),
                "reason": f"SidewaysV2 exit: Stop loss {pnl_pct:.2f}%",
            }

        # Exit condition 3: RSI mean reversion complete
        if indicators["rsi"] >= RSI_MEAN:
            return {
                "symbol": symbol,
                "side": "sell",
                "market": "spot",
                "quantity": str(quantity),
                "reason": f"SidewaysV2 exit: RSI={indicators['rsi']:.1f} (mean reversion)",
            }

        return None
