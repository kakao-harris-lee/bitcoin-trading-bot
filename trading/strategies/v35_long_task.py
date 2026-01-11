# trading/strategies/v35_long_task.py
"""V35 Long Strategy - ported to stream architecture."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from trading.streams.base_strategy import BaseStrategyTask
from trading.strategies.indicators import get_indicators

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)

# Default regime thresholds (used if no optimized config)
DEFAULT_PARAMS = {
    "mfi_bull": 52,
    "mfi_bear": 48,
    "adx_strong": 25,
    "adx_trend": 20,
    "adx_weak": 15,
    "stop_loss_pct": 1.5,
    "take_profit_pct": 3.0,
    "trailing_activation": 2.0,
    "trailing_distance": 1.5,
}


def load_optimized_params(symbol: str) -> dict:
    """Load optimized parameters from config file if available."""
    config_path = Path(f"config/strategies/v35_{symbol.lower()}_binance.json")
    if not config_path.exists():
        logger.info(f"No optimized config for {symbol}, using defaults")
        return DEFAULT_PARAMS.copy()

    try:
        with open(config_path) as f:
            opt_config = json.load(f)

        mc = opt_config.get("market_classifier", {})
        ec = opt_config.get("exit_conditions", {})

        params = {
            "mfi_bull": mc.get("mfi_bull_moderate", DEFAULT_PARAMS["mfi_bull"]),
            "mfi_bear": 48,  # Keep default for bear threshold
            "adx_strong": mc.get("adx_strong", DEFAULT_PARAMS["adx_strong"]),
            "adx_trend": mc.get("adx_moderate", DEFAULT_PARAMS["adx_trend"]),
            "adx_weak": 15,
            "stop_loss_pct": abs(ec.get("stop_loss", -DEFAULT_PARAMS["stop_loss_pct"] / 100)) * 100,
            "take_profit_pct": ec.get("tp_bull_moderate_1", DEFAULT_PARAMS["take_profit_pct"] / 100) * 100,
            "trailing_activation": ec.get("trailing_activation", DEFAULT_PARAMS["trailing_activation"] / 100) * 100,
            "trailing_distance": ec.get("trailing_distance", DEFAULT_PARAMS["trailing_distance"] / 100) * 100,
            "trailing_enabled": ec.get("trailing_enabled", True),
        }
        logger.info(f"Loaded optimized params for {symbol}: SL={params['stop_loss_pct']:.1f}%, TP={params['take_profit_pct']:.1f}%")
        return params
    except Exception as e:
        logger.warning(f"Failed to load optimized config for {symbol}: {e}")
        return DEFAULT_PARAMS.copy()


class V35LongTask(BaseStrategyTask):
    """V35 Long-only strategy for Binance spot."""

    def __init__(
        self,
        symbols: list[str],
        redis: RedisStreams,
        config: dict | None = None,
    ):
        config = config or {}
        super().__init__(
            name="v35_long",
            symbols=symbols,
            redis=redis,
            market="spot",
            buffer_size=500,
            use_smart_exit=config.get("use_smart_exit", False),
        )
        self.config = config
        self.min_data_points = 180  # Need enough data for indicators
        # Track high water mark for trailing stop per symbol
        self.high_water_mark: dict[str, float] = {}
        # Load optimized parameters per symbol
        self.params: dict[str, dict] = {s: load_optimized_params(s) for s in symbols}

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

        # Classify regime using per-symbol params
        regime = self._classify_regime(symbol, indicators["mfi"], indicators["adx"])

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

    def _classify_regime(self, symbol: str, mfi: float, adx: float) -> str:
        """Self-classify market regime using optimized params."""
        p = self.params.get(symbol, DEFAULT_PARAMS)
        mfi_bull = p["mfi_bull"]
        mfi_bear = p["mfi_bear"]
        adx_strong = p["adx_strong"]
        adx_trend = p["adx_trend"]
        adx_weak = p["adx_weak"]

        if mfi >= mfi_bull:
            if adx >= adx_strong:
                return "BULL_STRONG"
            elif adx >= adx_trend:
                return "BULL_MODERATE"
            else:
                return "SIDEWAYS_BULL"
        elif mfi <= mfi_bear:
            if adx >= adx_trend:
                return "BEAR_STRONG"
            elif adx >= adx_weak:
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

        # Get per-symbol parameters
        p = self.params.get(symbol, DEFAULT_PARAMS)
        stop_loss_pct = p["stop_loss_pct"]
        take_profit_pct = p["take_profit_pct"]
        trailing_activation = p["trailing_activation"]
        trailing_distance = p["trailing_distance"]
        trailing_enabled = p.get("trailing_enabled", True)

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
        if pnl_pct <= -stop_loss_pct:
            self.high_water_mark.pop(symbol, None)
            return {
                "symbol": symbol,
                "side": "sell",
                "market": "spot",
                "quantity": str(quantity),
                "reason": f"V35 exit: Stop loss {pnl_pct:.2f}%",
            }

        # Exit condition 2: Take profit
        if pnl_pct >= take_profit_pct:
            self.high_water_mark.pop(symbol, None)
            return {
                "symbol": symbol,
                "side": "sell",
                "market": "spot",
                "quantity": str(quantity),
                "reason": f"V35 exit: Take profit {pnl_pct:.2f}%",
            }

        # Exit condition 3: Trailing stop
        if trailing_enabled and hwm_pnl >= trailing_activation:
            trailing_stop_price = hwm * (1 - trailing_distance / 100)
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
        regime = self._classify_regime(symbol, indicators["mfi"], indicators["adx"])
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
