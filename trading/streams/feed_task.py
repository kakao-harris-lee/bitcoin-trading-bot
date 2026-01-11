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


class SymbolFeedTask:
    """Async task that streams prices for a single symbol to Redis."""

    def __init__(
        self,
        symbol: str,
        redis: RedisStreams,
        max_backoff: int = 60,
    ):
        self.symbol = symbol
        self.redis = redis
        self.max_backoff = max_backoff
        self._running = False
        self._failure_count = 0

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
                        await self._publish_price(msg)
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

    async def _publish_price(self, msg: dict[str, Any]) -> None:
        """Publish price update to Redis stream."""
        await self.redis.publish("market:prices", {
            "symbol": self.symbol,
            "price": msg["price"],
            "source": "binance",
            "market": msg["market"],
            "timestamp": str(int(time.time() * 1000)),
        })

    def _calculate_backoff(self, failure_count: int) -> int:
        """Calculate exponential backoff with cap."""
        backoff = min(2 ** failure_count, self.max_backoff)
        return max(1, backoff)
