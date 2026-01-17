"""Composite Strategy Task - assembles Entry/Exit components into a runnable task.

This is the bridge between the component-based strategy architecture and the
stream-based task system. It extends BaseStrategyTask and delegates entry/exit
logic to IEntryStrategy and IExitStrategy components.

Usage:
    entry = V35EntryStrategy(params)
    exit_strat = V35TrailingExitStrategy(params)

    task = CompositeStrategyTask(
        name="v35_long",
        symbols=["BTC", "ETH"],
        redis=redis,
        entry_strategy=entry,
        exit_strategy=exit_strat,
    )

    await task.run()
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from trading.streams.base_strategy import BaseStrategyTask
from trading.strategies.indicators import get_indicators

from .interfaces import IEntryStrategy, IExitStrategy
from .models import MarketData, Position, Signal

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)


class CompositeStrategyTask(BaseStrategyTask):
    """Strategy task that delegates to Entry/Exit components.

    Bridges the component-based architecture with the stream-based task system.
    Entry and exit logic are fully delegated to the injected components.
    """

    def __init__(
        self,
        name: str,
        symbols: list[str],
        redis: RedisStreams,
        entry_strategy: IEntryStrategy,
        exit_strategy: IExitStrategy,
        market: str = "spot",
        buffer_size: int = 500,
        use_smart_exit: bool = False,
        config: dict | None = None,
    ):
        """Initialize composite strategy task.

        Args:
            name: Strategy name (e.g., "v35_long").
            symbols: List of symbols to trade.
            redis: Redis streams client.
            entry_strategy: Entry component implementing IEntryStrategy.
            exit_strategy: Exit component implementing IExitStrategy.
            market: Market type ("spot" or "futures").
            buffer_size: Price buffer size.
            use_smart_exit: Use smart exit stream.
            config: Additional configuration.
        """
        super().__init__(
            name=name,
            symbols=symbols,
            redis=redis,
            market=market,
            buffer_size=buffer_size,
            use_smart_exit=use_smart_exit,
        )
        self.entry_strategy = entry_strategy
        self.exit_strategy = exit_strategy
        self.config = config or {}
        self.min_data_points = 180

    async def evaluate(self, symbol: str) -> dict[str, Any] | None:
        """Evaluate entry conditions by delegating to entry component.

        Args:
            symbol: Trading symbol.

        Returns:
            Order intent dict or None.
        """
        buffer = self.price_buffer.get(symbol, [])

        if len(buffer) < self.min_data_points:
            return None

        # Build MarketData from indicators
        market_data = self._build_market_data(symbol)
        if market_data is None:
            return None

        # Delegate to entry component
        signal = self.entry_strategy.check_entry(market_data)

        if signal:
            # Apply dynamic sizing if configured
            quantity = await self._get_quantity(symbol, market_data.close, signal.quantity)
            return self._signal_to_dict(signal, quantity)

        return None

    async def evaluate_exit(self, symbol: str, position_dict: dict) -> dict[str, Any] | None:
        """Evaluate exit conditions by delegating to exit component.

        Args:
            symbol: Trading symbol.
            position_dict: Position dict from Redis.

        Returns:
            Order intent dict or None.
        """
        # Build MarketData from indicators
        market_data = self._build_market_data(symbol)
        if market_data is None:
            return None

        # Build Position model from dict
        position = self._dict_to_position(position_dict)

        # Delegate to exit component
        # Handle both sync and async exit strategies
        if hasattr(self.exit_strategy, '__class__') and 'Persistent' in self.exit_strategy.__class__.__name__:
            # Async persistent strategy
            signal = await self.exit_strategy.check_exit(position, market_data)
        else:
            # Sync strategy
            signal = self.exit_strategy.check_exit(position, market_data)

        if signal:
            return self._signal_to_dict(signal, signal.quantity)

        return None

    async def on_position_opened(self, symbol: str, position_dict: dict) -> None:
        """Notify exit strategy when position is opened.

        Called by _handle_message after entry order is filled.

        Args:
            symbol: Trading symbol.
            position_dict: Position dict from Redis.
        """
        position = self._dict_to_position(position_dict)

        # Notify exit strategy (for state initialization)
        if hasattr(self.exit_strategy, '__class__') and 'Persistent' in self.exit_strategy.__class__.__name__:
            await self.exit_strategy.on_position_opened(position)
        else:
            self.exit_strategy.on_position_opened(position)

        logger.debug(f"{symbol}: Notified exit strategy of position open")

    async def on_position_closed(self, symbol: str) -> None:
        """Notify exit strategy when position is closed.

        Args:
            symbol: Trading symbol.
        """
        if hasattr(self.exit_strategy, '__class__') and 'Persistent' in self.exit_strategy.__class__.__name__:
            await self.exit_strategy.on_position_closed(symbol)
        else:
            self.exit_strategy.on_position_closed(symbol)

        logger.debug(f"{symbol}: Notified exit strategy of position close")

    def _build_market_data(self, symbol: str) -> MarketData | None:
        """Build MarketData from current indicators.

        Args:
            symbol: Trading symbol.

        Returns:
            MarketData instance or None if indicators unavailable.
        """
        try:
            indicators = get_indicators(symbol, periods=100)
            if indicators is None:
                logger.warning(f"Could not load indicators for {symbol}")
                return None

            # Use current price from buffer if available
            buffer = self.price_buffer.get(symbol, [])
            close = float(buffer[-1]["price"]) if buffer else indicators["close"]

            return MarketData(
                symbol=symbol,
                close=close,
                mfi=indicators["mfi"],
                adx=indicators["adx"],
                rsi=indicators["rsi"],
                timestamp=buffer[-1].get("timestamp", 0) if buffer else 0,
            )
        except Exception as e:
            logger.error(f"Failed to build MarketData for {symbol}: {e}")
            return None

    def _dict_to_position(self, position_dict: dict) -> Position:
        """Convert position dict to Position model.

        Args:
            position_dict: Position dict from Redis.

        Returns:
            Position instance.
        """
        return Position(
            symbol=position_dict.get("symbol", ""),
            entry_price=float(position_dict.get("entry_price", 0)),
            quantity=float(position_dict.get("quantity", 0)),
            strategy=position_dict.get("strategy", self.name),
            market=position_dict.get("market", self.market),
            timestamp=position_dict.get("timestamp", 0),
        )

    def _signal_to_dict(self, signal: Signal, quantity: float) -> dict[str, Any]:
        """Convert Signal model to order intent dict.

        Args:
            signal: Signal from component.
            quantity: Final quantity (may be adjusted).

        Returns:
            Order intent dict.
        """
        result = {
            "symbol": signal.symbol,
            "side": signal.side,
            "market": signal.market,
            "quantity": str(quantity),
            "reason": signal.reason,
        }

        if signal.trigger_price is not None:
            result["trigger_price"] = signal.trigger_price

        return result

    async def _get_quantity(
        self,
        symbol: str,
        price: float,
        default_quantity: float,
    ) -> float:
        """Get position quantity, using dynamic sizing if configured.

        Args:
            symbol: Trading symbol.
            price: Current price.
            default_quantity: Default quantity from signal.

        Returns:
            Final quantity.
        """
        use_dynamic = self.config.get("dynamic_sizing", False)

        if use_dynamic:
            position_pct = self.config.get("position_pct", 0.02)
            return await self.get_dynamic_position_size(symbol, price, position_pct)
        else:
            return self.config.get("position_size", default_quantity)


async def create_composite_task(
    name: str,
    symbols: list[str],
    redis: RedisStreams,
    entry_strategy: IEntryStrategy,
    exit_strategy: IExitStrategy,
    config: dict | None = None,
    market: str = "spot",
    use_smart_exit: bool = False,
) -> CompositeStrategyTask:
    """Create a CompositeStrategyTask.

    Convenience function that also initializes persistent exit strategies.

    Args:
        name: Strategy name.
        symbols: List of symbols.
        redis: Redis streams client.
        entry_strategy: Entry component.
        exit_strategy: Exit component.
        config: Configuration.
        market: Market type.
        use_smart_exit: Use smart exit.

    Returns:
        Initialized CompositeStrategyTask.
    """
    task = CompositeStrategyTask(
        name=name,
        symbols=symbols,
        redis=redis,
        entry_strategy=entry_strategy,
        exit_strategy=exit_strategy,
        market=market,
        config=config,
        use_smart_exit=use_smart_exit,
    )

    # Initialize persistent exit strategy state
    if hasattr(exit_strategy, 'load_state'):
        await exit_strategy.load_state(symbols)
        logger.info(f"{name}: Loaded persistent state for {symbols}")

    return task
