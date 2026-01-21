# trading/streams/feed_task.py
"""Price feed task for streaming Binance prices to Redis."""
from __future__ import annotations
import asyncio
import time
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)

# Default publish interval in seconds (only publish to Redis at this rate)
DEFAULT_PUBLISH_INTERVAL = 1.0


class SymbolFeedTask:
    """Async task that streams prices for a single symbol to Redis.

    Uses throttling to reduce Redis traffic - only the most recent price
    is published at configurable intervals (default: once per second).
    """

    # Stream trimming: keep ~1 hour of data at 1 msg/sec per symbol
    # With 3 symbols: 3 * 3600 = 10,800 msgs/hour
    # Set to 50,000 for safety margin (covers multi-hour restarts)
    STREAM_MAX_LENGTH = 50000

    def __init__(
        self,
        symbol: str,
        redis: RedisStreams,
        max_backoff: int = 60,
        publish_interval: float = DEFAULT_PUBLISH_INTERVAL,
    ):
        self.symbol = symbol
        self.redis = redis
        self.max_backoff = max_backoff
        self.publish_interval = publish_interval
        self._running = False
        self._failure_count = 0
        # Throttling state
        self._last_publish_time: float = 0.0
        self._latest_price: dict[str, Any] | None = None

    async def run(self) -> None:
        """Main loop: connect to WebSocket and publish prices."""
        self._running = True

        while self._running:
            try:
                async with self._connect_websocket() as ws:
                    self._failure_count = 0
                    async for msg in ws:
                        if not self._running:
                            break
                        await self._handle_price(msg)
            except Exception as e:
                logger.error(f"Feed {self.symbol} error: {e}")
                self._failure_count += 1
                backoff = self._calculate_backoff(self._failure_count)
                logger.info(f"Feed {self.symbol} reconnecting in {backoff}s")
                await asyncio.sleep(backoff)

    def stop(self) -> None:
        """Signal task to stop."""
        self._running = False

    async def _connect_websocket(self):
        """Connect to Binance WebSocket. Override in subclass."""
        raise NotImplementedError("Subclass must implement _connect_websocket")

    async def _handle_price(self, msg: dict[str, Any]) -> None:
        """Handle incoming price with throttling.

        Always stores the latest price, but only publishes to Redis
        at the configured interval to reduce CPU and network usage.
        """
        # Always store the latest price
        self._latest_price = msg

        # Check if enough time has passed to publish
        current_time = time.time()
        if current_time - self._last_publish_time >= self.publish_interval:
            await self._publish_price(msg)
            self._last_publish_time = current_time

    async def _publish_price(self, msg: dict[str, Any]) -> None:
        """Publish price update to Redis stream with auto-trimming.

        Uses approximate trimming (~) for better performance.
        Stream is trimmed to STREAM_MAX_LENGTH entries.
        """
        await self.redis.publish_event(
            "market:prices",
            {
                "symbol": self.symbol,
                "price": msg["price"],
                "source": "binance",
                "market": msg["market"],
                "timestamp": str(int(time.time() * 1000)),
            },
            maxlen=self.STREAM_MAX_LENGTH,
        )

    def _calculate_backoff(self, failure_count: int) -> int:
        """Calculate exponential backoff with cap."""
        backoff = min(2 ** failure_count, self.max_backoff)
        return max(1, backoff)
