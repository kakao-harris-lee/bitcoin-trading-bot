# trading/strategies/short_v1_task.py
"""ShortV1 Strategy - ported to stream architecture."""
from __future__ import annotations
import logging
from typing import Any, TYPE_CHECKING

from trading.streams.base_strategy import BaseStrategyTask
from trading.strategies.indicators import get_indicators

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)

# Regime thresholds
MFI_BEAR = 48
ADX_TREND = 20

# RSI threshold for short entry
RSI_OVERBOUGHT = 70

# Exit thresholds (for short positions)
STOP_LOSS_PCT = 2.0      # +2% price rise = stop loss
TAKE_PROFIT_PCT = 3.0    # -3% price drop = take profit
RSI_OVERSOLD = 30        # Cover short when RSI oversold


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
        """Calculate position size for futures."""
        return self.config.get("position_size", 0.01)

    async def evaluate_exit(self, symbol: str, position: dict) -> dict[str, Any] | None:
        """Evaluate exit conditions for short position."""
        indicators = self._calculate_indicators(symbol)
        if indicators is None:
            return None

        entry_price = float(position.get("entry_price", 0))
        quantity = float(position.get("quantity", 0))
        current_price = indicators["close"]

        if entry_price <= 0 or quantity <= 0:
            return None

        # For shorts: profit when price drops, loss when price rises
        # P&L % = (entry - current) / entry * 100
        pnl_pct = ((entry_price - current_price) / entry_price) * 100

        # Exit condition 1: Stop loss (price rose too much)
        if pnl_pct <= -STOP_LOSS_PCT:
            return {
                "symbol": symbol,
                "side": "buy",  # Buy to cover short
                "market": "futures",
                "quantity": str(quantity),
                "reason": f"ShortV1 exit: Stop loss {pnl_pct:.2f}%",
            }

        # Exit condition 2: Take profit (price dropped enough)
        if pnl_pct >= TAKE_PROFIT_PCT:
            return {
                "symbol": symbol,
                "side": "buy",  # Buy to cover short
                "market": "futures",
                "quantity": str(quantity),
                "reason": f"ShortV1 exit: Take profit {pnl_pct:.2f}%",
            }

        # Exit condition 3: RSI oversold (mean reversion complete)
        if indicators["rsi"] <= RSI_OVERSOLD:
            return {
                "symbol": symbol,
                "side": "buy",  # Buy to cover short
                "market": "futures",
                "quantity": str(quantity),
                "reason": f"ShortV1 exit: RSI={indicators['rsi']:.1f} (oversold), P&L={pnl_pct:.2f}%",
            }

        # Exit condition 4: Regime change to bullish
        regime = self._classify_regime(indicators["mfi"], indicators["adx"])
        if regime == "BULL" and pnl_pct > 0:
            return {
                "symbol": symbol,
                "side": "buy",  # Buy to cover short
                "market": "futures",
                "quantity": str(quantity),
                "reason": f"ShortV1 exit: Regime change to {regime}, locking {pnl_pct:.2f}%",
            }

        return None
