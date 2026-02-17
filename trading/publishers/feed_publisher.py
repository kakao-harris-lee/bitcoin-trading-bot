"""
Feed Publisher - Publishes price data to Redis streams

Wraps exchange WebSocket handlers and publishes to:
- market:binance:prices
"""
# pylint: disable=broad-exception-caught

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from core.types import Exchange

logger = logging.getLogger(__name__)


class FeedPublisher:
    """Publishes price data from exchange feeds to Redis streams."""

    def __init__(self, exchange: Exchange, redis_client, config):
        """
        Args:
            exchange: Exchange enum (BINANCE)
            redis_client: RedisClient instance
            config: Configuration
        """
        self.exchange = exchange
        self.redis = redis_client
        self.config = config
        self.running = True
        self.logger = logging.getLogger(f"feed.{exchange.value}")

        self._last_price = 0.0
        self._last_publish_time = None

    @property
    def stream_name(self) -> str:
        """Redis stream name for this exchange's prices."""
        return f"market:{self.exchange.value}:prices"

    async def publish_price(
        self,
        price: float,
        volume: float,
        timestamp: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> str:
        """Publish price update to Redis stream.

        Args:
            price: Current price
            volume: Trade volume
            timestamp: ISO timestamp (defaults to now)
            extra: Additional data to include

        Returns:
            Redis message ID
        """
        data = {
            "exchange": self.exchange.value,
            "price": price,
            "volume": volume,
            "timestamp": timestamp or datetime.now().isoformat(),
        }

        if extra:
            data.update(extra)

        message_id = await self.redis.publish(self.stream_name, data)

        self._last_price = price
        self._last_publish_time = datetime.now()

        return message_id

    async def run(self, ws_handler):
        """Run feed publisher with WebSocket handler.

        Args:
            ws_handler: WebSocketHandler instance (Binance)
        """
        self.logger.info("Starting %s feed publisher...", self.exchange.value)

        # Set callback to publish prices
        ws_handler.set_callback(self._on_price_message)

        # Connect and run WebSocket
        while self.running:
            try:
                if not getattr(ws_handler, "_connected", False):
                    await ws_handler.connect()

                await ws_handler.receive_loop()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Feed error: %s", e)
                await asyncio.sleep(5)
                await ws_handler.reconnect()

        await ws_handler.disconnect()
        self.logger.info("%s feed publisher stopped", self.exchange.value)

    def _on_price_message(self, price_msg):
        """Callback for WebSocket price messages."""
        task = asyncio.create_task(self._safe_publish_price(price_msg))
        # Add callback to log any exceptions
        task.add_done_callback(self._handle_task_exception)

    def _handle_task_exception(self, task: asyncio.Task):
        """Log exceptions from background tasks."""
        try:
            exc = task.exception()
            if exc:
                self.logger.error("Price publish failed: %s", exc)
        except asyncio.CancelledError:
            pass

    async def _safe_publish_price(self, price_msg):
        """Safely publish price with error handling."""
        try:
            await self.publish_price(
                price=price_msg.price,
                volume=price_msg.volume,
                timestamp=price_msg.timestamp.isoformat() if price_msg.timestamp else None,
            )
        except Exception as e:
            self.logger.error("Failed to publish price: %s", e)
            raise  # Re-raise for the done callback to catch

    def stop(self):
        """Stop the publisher gracefully."""
        self.running = False
