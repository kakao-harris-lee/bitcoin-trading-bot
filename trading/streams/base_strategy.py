# trading/streams/base_strategy.py
"""Base class for strategy tasks."""
from __future__ import annotations
import asyncio
import time
import uuid
import logging
from abc import ABC, abstractmethod
from collections import deque
from trading.streams.data_warmup import DataWarmup
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .redis_streams import RedisStreams

logger = logging.getLogger(__name__)

# Default evaluation interval in seconds (only evaluate entry/exit at this interval)
# For strategies using minute+ candles, 5 seconds is plenty fast for entry/exit checks
DEFAULT_EVALUATION_INTERVAL = 5.0


def get_position_key(symbol: str, market: str) -> str:
    """Get Redis key for position.

    Args:
        symbol: Trading symbol (e.g., "BTC")
        market: Market type ("spot" or "futures")

    Returns:
        Redis key like "positions:BTC:spot" or "positions:BTC:futures"
    """
    return f"positions:{symbol}:{market}"


class BaseStrategyTask(ABC):
    """Base class for autonomous strategy tasks."""

    def __init__(
        self,
        name: str,
        symbols: list[str],
        redis: RedisStreams,
        market: str,
        buffer_size: int = 500,
        use_smart_exit: bool = False,
    ):
        self.name = name
        self.symbols = set(symbols)
        self.redis = redis
        self.market = market
        self.buffer_size = buffer_size
        self.use_smart_exit = use_smart_exit
        self.price_buffer: dict[str, deque] = {}
        self._running = False
        # Track pending entries to avoid duplicate orders
        self._pending_entry: dict[str, bool] = {}
        # Track positions we've notified exit strategy about
        self._notified_positions: set[str] = set()
        # Track pending exits to avoid duplicate exit signals (for smart exit)
        self._pending_exits: set[str] = set()
        # Evaluation throttling to reduce CPU usage
        self._evaluation_interval = DEFAULT_EVALUATION_INTERVAL
        self._last_evaluation_time: dict[str, float] = {}
        self._last_entry_evaluation_time: dict[str, float] = {}
        self._last_exit_evaluation_time: dict[str, float] = {}
        # Cache for position and blocked status to reduce Redis calls
        self._position_cache: dict[str, tuple[float, dict | None]] = {}
        self._blocked_cache: tuple[float, bool] = (0.0, False)
        self._cache_ttl = 1.0  # Cache TTL in seconds

    async def fetch_initial_candles(self, symbol: str, interval: str = "1h", limit: int = 200) -> list[dict]:
        """Fetch historical candles for warm-up."""
        try:
            warmup = DataWarmup()
            candles = await warmup.fetch_recent_candles(
                symbol=symbol,
                limit=limit,
                interval=interval,
                market=self.market
            )
            return candles
        except Exception as e:
            logger.error(f"Failed to fetch initial candles for {symbol}: {e}")
            return []

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

    def _should_evaluate(self, symbol: str) -> bool:
        """Check if enough time has passed to evaluate this symbol.

        Uses time-based throttling to reduce CPU usage from frequent evaluations.

        Args:
            symbol: Trading symbol.

        Returns:
            True if evaluation should proceed, False to skip.
        """
        current_time = time.time()
        last_time = self._last_evaluation_time.get(symbol, 0)

        if current_time - last_time >= self._evaluation_interval:
            self._last_evaluation_time[symbol] = current_time
            return True
        return False

    def _should_evaluate_entry(self, symbol: str, msg: dict[str, Any]) -> bool:
        """Check if entry evaluation should run for this symbol/message."""
        current_time = time.time()
        last_time = self._last_entry_evaluation_time.get(symbol, 0)
        if current_time - last_time >= self._evaluation_interval:
            self._last_entry_evaluation_time[symbol] = current_time
            return True
        return False

    def _should_evaluate_exit(
        self,
        symbol: str,
        msg: dict[str, Any],
        position: dict[str, Any],
    ) -> bool:
        """Check if exit evaluation should run for this symbol/message."""
        current_time = time.time()
        last_time = self._last_exit_evaluation_time.get(symbol, 0)
        if current_time - last_time >= self._evaluation_interval:
            self._last_exit_evaluation_time[symbol] = current_time
            return True
        return False

    async def _get_cached_blocked(self) -> bool:
        """Get blocked status with caching to reduce Redis calls.

        Returns:
            True if blocked, False otherwise.
        """
        current_time = time.time()
        cache_time, cached_value = self._blocked_cache

        if current_time - cache_time < self._cache_ttl:
            return cached_value

        # Cache expired, fetch from Redis
        is_blocked = await self.redis.is_blocked()
        self._blocked_cache = (current_time, is_blocked)
        return is_blocked

    async def _get_cached_position(self, symbol: str) -> dict | None:
        """Get position with caching to reduce Redis calls.

        Args:
            symbol: Trading symbol.

        Returns:
            Position dict or None.
        """
        current_time = time.time()
        cache_key = f"{symbol}:{self.market}"

        if cache_key in self._position_cache:
            cache_time, cached_value = self._position_cache[cache_key]
            if current_time - cache_time < self._cache_ttl:
                return cached_value

        # Cache expired, fetch from Redis
        position = await self.redis.get_position(symbol, self.market)
        self._position_cache[cache_key] = (current_time, position)
        return position

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        """Handle incoming price message with throttling.

        Uses time-based throttling to reduce CPU usage. Price buffer is always
        updated, but entry/exit evaluation only happens at configured intervals.
        """
        symbol = msg.get("symbol")

        # Filter by symbol
        if symbol not in self.symbols:
            return

        # NOTE: Market filter removed for hybrid mode.
        # Engine uses futures price feeds for ALL strategies (spot and futures).
        # Spot and futures prices are nearly identical (~0.1% difference).
        # The strategy's "market" determines WHERE orders execute, not which
        # price data to consume. See engine.py hybrid mode comment.

        # Update buffer (always, for indicator calculation)
        self._update_buffer(symbol, msg)

        # Skip signal evaluation for warm-up data (historical candles)
        # Warm-up data is for populating buffers/indicators, not trading
        if msg.get("warmup") == "true":
            return

        # Check if blocked (cached)
        if await self._get_cached_blocked():
            return

        position = await self._get_cached_position(symbol)
        if position:
            handled = await self._handle_existing_position(symbol, msg, position)
            if handled:
                return
        else:
            await self._handle_position_cleared(symbol)

        # Check if entry is already pending (order published but not yet filled)
        if self._pending_entry.get(symbol):
            return

        if not self._should_evaluate_entry(symbol, msg):
            return

        # Evaluate entry
        signal = await self.evaluate(symbol)
        if signal:
            self._pending_entry[symbol] = True
            await self._publish_order(signal)

    async def _handle_position_cleared(self, symbol: str) -> None:
        """Handle transition from existing position to no position."""
        if symbol not in self._pending_exits:
            return
        self._pending_exits.discard(symbol)
        self._notified_positions.discard(symbol)
        await self.on_position_closed(symbol)
        logger.info(f"Strategy {self.name}: {symbol} position closed, cleared pending exit")

    async def _handle_existing_position(
        self,
        symbol: str,
        msg: dict[str, Any],
        position: dict[str, Any],
    ) -> bool:
        """Handle exit evaluation flow when a position exists.

        Returns:
            True if message processing should stop after this handler.
        """
        position_strategy = position.get("strategy", "")
        if position_strategy != self.name:
            self._pending_entry.pop(symbol, None)
            return True

        self._pending_entry.pop(symbol, None)
        if symbol not in self._notified_positions:
            self._notified_positions.add(symbol)
            await self.on_position_opened(symbol, position)

        if symbol in self._pending_exits:
            return True
        if not self._should_evaluate_exit(symbol, msg, position):
            return True

        exit_signal = await self.evaluate_exit(symbol, position)
        if exit_signal:
            await self._handle_exit_signal(symbol, position, exit_signal)
        return True

    async def _handle_exit_signal(
        self,
        symbol: str,
        position: dict[str, Any],
        exit_signal: dict[str, Any],
    ) -> None:
        """Publish exit signal and update position lifecycle state."""
        if self.use_smart_exit:
            self._pending_exits.add(symbol)
        await self._publish_exit(exit_signal, position)
        if self.use_smart_exit:
            return

        await self.redis.clear_position(symbol, self.market)
        self._notified_positions.discard(symbol)
        await self.on_position_closed(symbol)

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

    async def _publish_exit(self, signal: dict[str, Any], position: dict) -> None:
        """Publish exit signal to appropriate stream."""
        if self.use_smart_exit:
            # Add trigger price if not present
            if "trigger_price" not in signal:
                buffer = self.price_buffer.get(signal["symbol"], [])
                if buffer:
                    signal["trigger_price"] = buffer[-1]["price"]

            exit_signal = {
                "id": str(uuid.uuid4()),
                "strategy": self.name,
                **signal,
            }
            await self.redis.publish("exit_signals", exit_signal)
            logger.info(f"Strategy {self.name} published exit signal: {exit_signal}")
        else:
            await self._publish_order(signal)

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

    async def on_position_opened(self, symbol: str, position: dict) -> None:
        """
        Called when a new position is detected for the first time.

        Override in subclass to initialize exit strategy state (e.g., high water mark).

        Args:
            symbol: Trading symbol.
            position: Position dict from Redis.
        """
        pass

    async def on_position_closed(self, symbol: str) -> None:
        """
        Called when a position is closed.

        Override in subclass to clean up exit strategy state.

        Args:
            symbol: Trading symbol.
        """
        pass

    # Minimum sellable quantities per symbol (2x step_size to survive fee deduction).
    # Buying exactly 1 step leaves post-fee holdings below the sellable minimum.
    _MIN_SELLABLE_QTY = {
        "BTC": 0.00002,   # 2 × 0.00001 step
        "ETH": 0.0002,    # 2 × 0.0001 step
        "SOL": 0.02,      # 2 × 0.01 step
        "BNB": 0.002,     # 2 × 0.001 step
    }

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
        # Use symbol-specific minimum that ensures post-fee sellability
        min_sellable = self._MIN_SELLABLE_QTY.get(symbol, min_size)
        effective_min = max(min_size, min_sellable)

        try:
            # Get balance from Redis (set by executor)
            # Use mode-specific key: account:paper or account:live
            risk = await self.redis._client.hgetall("risk")
            mode = risk.get("mode", "paper") if risk else "paper"
            account_key = f"account:{mode}"

            account = await self.redis._client.hgetall(account_key)

            if not account:
                logger.warning(f"No account balance found in {account_key}, using minimum size")
                return effective_min

            balance = float(account.get("futures_balance", 0))

            if balance <= 0:
                return effective_min

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

            return max(size, effective_min)

        except Exception as e:
            logger.warning(f"Failed to calculate dynamic position size: {e}")
            return effective_min
