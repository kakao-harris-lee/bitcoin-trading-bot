# trading/streams/base_strategy.py
"""Base class for strategy tasks."""
from __future__ import annotations
import asyncio
import uuid
import logging
from abc import ABC, abstractmethod
from collections import deque
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .redis_streams import RedisStreams

logger = logging.getLogger(__name__)


class BaseStrategyTask(ABC):
    """Base class for autonomous strategy tasks."""

    def __init__(
        self,
        name: str,
        symbols: list[str],
        redis: RedisStreams,
        market: str,
        buffer_size: int = 500,
    ):
        self.name = name
        self.symbols = set(symbols)
        self.redis = redis
        self.market = market
        self.buffer_size = buffer_size
        self.price_buffer: dict[str, deque] = {}
        self._running = False

    async def run(self) -> None:
        """Main loop: consume prices, evaluate, publish orders."""
        self._running = True
        group = f"strategy-{self.name}"
        consumer = f"{self.name}-{uuid.uuid4().hex[:8]}"

        # Ensure consumer group exists
        await self.redis.create_consumer_group("market:prices", group)

        logger.info(f"Strategy {self.name} started, watching {self.symbols}")

        while self._running:
            try:
                messages = await self.redis.consume(
                    "market:prices", group, consumer, count=10, block_ms=1000
                )

                for msg in messages:
                    await self._handle_message(msg)
                    await self.redis.ack("market:prices", group, msg["_id"])

            except Exception as e:
                logger.error(f"Strategy {self.name} error: {e}")
                await asyncio.sleep(1)

    def stop(self) -> None:
        """Signal task to stop."""
        self._running = False

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        """Handle incoming price message."""
        symbol = msg.get("symbol")

        # Filter by symbol
        if symbol not in self.symbols:
            return

        # Filter by market
        if msg.get("market") != self.market:
            return

        # Update buffer
        self._update_buffer(symbol, msg)

        # Check if blocked
        if await self.redis.is_blocked():
            return

        # Check if already has position - evaluate exit only for own positions
        position = await self.redis.get_position(symbol, self.market)
        if position:
            # Only evaluate exit if this strategy owns the position
            if position.get("strategy") == self.name:
                exit_signal = await self.evaluate_exit(symbol, position)
                if exit_signal:
                    await self._publish_order(exit_signal)
                    await self.redis.clear_position(symbol, self.market)
            return

        # Evaluate entry
        signal = await self.evaluate(symbol)
        if signal:
            await self._publish_order(signal)

    def _update_buffer(self, symbol: str, msg: dict[str, Any]) -> None:
        """Update price buffer for symbol."""
        if symbol not in self.price_buffer:
            self.price_buffer[symbol] = deque(maxlen=self.buffer_size)
        self.price_buffer[symbol].append(msg)

    async def _publish_order(self, signal: dict[str, Any]) -> None:
        """Publish order intent to orders stream."""
        order = {
            "id": str(uuid.uuid4()),
            "strategy": self.name,
            **signal,
        }
        await self.redis.publish("orders", order)
        logger.info(f"Strategy {self.name} published order: {order}")

    @abstractmethod
    async def evaluate(self, symbol: str) -> dict[str, Any] | None:
        """
        Evaluate current market state for symbol.

        Returns order intent dict or None.
        Order intent: {"symbol", "side", "market", "quantity", "reason"}
        """
        pass

    async def evaluate_exit(self, symbol: str, position: dict) -> dict[str, Any] | None:
        """
        Evaluate exit conditions for existing position.

        Override in subclass to implement exit logic.
        Returns order intent dict or None.
        """
        return None

    async def get_dynamic_position_size(
        self,
        symbol: str,
        price: float,
        position_pct: float = 0.02,
        min_size: float = 0.001,
    ) -> float:
        """
        Calculate position size based on account balance.

        Args:
            symbol: Trading symbol (BTC, ETH, SOL)
            price: Current price of the asset
            position_pct: Percentage of balance to use (default 2%)
            min_size: Minimum position size

        Returns:
            Position size in asset units
        """
        try:
            # Get balance from Redis (set by AsyncExecutor)
            balance_key = "spot_balance" if self.market == "spot" else "futures_balance"
            account = await self.redis.client.hgetall("account")

            if not account:
                logger.warning("No account balance found, using minimum size")
                return min_size

            balance = float(account.get(balance_key, 0))

            if balance <= 0:
                return min_size

            # Calculate position size
            position_value = balance * position_pct
            size = position_value / price

            # Round to appropriate precision
            if symbol == "BTC":
                size = round(size, 5)  # 0.00001 BTC precision
            elif symbol == "ETH":
                size = round(size, 4)  # 0.0001 ETH precision
            else:
                size = round(size, 3)  # 0.001 for others

            return max(size, min_size)

        except Exception as e:
            logger.warning(f"Failed to calculate dynamic position size: {e}")
            return min_size
