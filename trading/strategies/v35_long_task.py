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

# Exit thresholds (from legacy v35_long.py)
STOP_LOSS_PCT = 1.5      # -1.5% stop loss
TAKE_PROFIT_PCT = 3.0    # +3.0% take profit
TRAILING_ACTIVATION = 2.0  # Activate trailing at +2%
TRAILING_DISTANCE = 1.5    # Trail by 1.5%


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
        # Track high water mark for trailing stop per symbol
        self.high_water_mark: dict[str, float] = {}

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
            quantity = await self._calculate_position_size(symbol, indicators["close"])
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

    async def _calculate_position_size(self, symbol: str, price: float) -> float:
        """Calculate position size (dynamic or fixed based on config)."""
        use_dynamic = self.config.get("dynamic_sizing", False)

        if use_dynamic:
            position_pct = self.config.get("position_pct", 0.02)  # 2% of balance
            return await self.get_dynamic_position_size(symbol, price, position_pct)
        else:
            return self.config.get("position_size", 0.01)

    async def evaluate_exit(self, symbol: str, position: dict) -> dict[str, Any] | None:
        """Evaluate exit conditions for long position."""
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

        # Update high water mark
        if symbol not in self.high_water_mark:
            self.high_water_mark[symbol] = current_price
        else:
            self.high_water_mark[symbol] = max(self.high_water_mark[symbol], current_price)

        hwm = self.high_water_mark[symbol]
        hwm_pnl = ((hwm - entry_price) / entry_price) * 100

        # Exit condition 1: Stop loss
        if pnl_pct <= -STOP_LOSS_PCT:
            self.high_water_mark.pop(symbol, None)
            return {
                "symbol": symbol,
                "side": "sell",
                "market": "spot",
                "quantity": str(quantity),
                "reason": f"V35 exit: Stop loss {pnl_pct:.2f}%",
            }

        # Exit condition 2: Take profit
        if pnl_pct >= TAKE_PROFIT_PCT:
            self.high_water_mark.pop(symbol, None)
            return {
                "symbol": symbol,
                "side": "sell",
                "market": "spot",
                "quantity": str(quantity),
                "reason": f"V35 exit: Take profit {pnl_pct:.2f}%",
            }

        # Exit condition 3: Trailing stop (activated after +2%, trails by 1.5%)
        if hwm_pnl >= TRAILING_ACTIVATION:
            trailing_stop_price = hwm * (1 - TRAILING_DISTANCE / 100)
            if current_price <= trailing_stop_price:
                locked_pnl = ((trailing_stop_price - entry_price) / entry_price) * 100
                self.high_water_mark.pop(symbol, None)
                return {
                    "symbol": symbol,
                    "side": "sell",
                    "market": "spot",
                    "quantity": str(quantity),
                    "reason": f"V35 exit: Trailing stop {locked_pnl:.2f}% (HWM={hwm_pnl:.2f}%)",
                }

        # Exit condition 4: Regime change to bearish
        regime = self._classify_regime(indicators["mfi"], indicators["adx"])
        if regime in ("BEAR_STRONG", "BEAR_MODERATE") and pnl_pct > 0:
            self.high_water_mark.pop(symbol, None)
            return {
                "symbol": symbol,
                "side": "sell",
                "market": "spot",
                "quantity": str(quantity),
                "reason": f"V35 exit: Regime change to {regime}, locking {pnl_pct:.2f}%",
            }

        return None
