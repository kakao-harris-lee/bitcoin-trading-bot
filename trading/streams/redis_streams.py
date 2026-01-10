# trading/streams/redis_streams.py
"""Redis Streams wrapper for async publish/consume."""
from __future__ import annotations

import redis.asyncio as redis
from typing import Any


class RedisStreams:
    """Async Redis Streams client.

    Provides a simple interface for:
    - Publishing messages to streams
    - Consuming messages via consumer groups
    - Hash operations for state storage

    Usage:
        streams = RedisStreams(url="redis://localhost:6379")
        await streams.connect()

        # Publish
        msg_id = await streams.publish("prices", {"symbol": "BTC", "price": "43000"})

        # Consume
        await streams.create_consumer_group("prices", "strategy-group")
        messages = await streams.consume("prices", "strategy-group", "consumer-1")

        await streams.disconnect()
    """

    def __init__(self, url: str = "redis://localhost:6379"):
        """Initialize RedisStreams client.

        Args:
            url: Redis connection URL (e.g., redis://localhost:6379/0)
        """
        self.url = url
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        """Connect to Redis."""
        self._client = redis.from_url(self.url, decode_responses=True)

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def create_consumer_group(
        self, stream: str, group: str, start_id: str = "0"
    ) -> None:
        """Create consumer group, ignore if exists.

        Args:
            stream: Stream name
            group: Consumer group name
            start_id: Start reading from this ID ("0" = beginning, "$" = new only)
        """
        try:
            await self._client.xgroup_create(stream, group, id=start_id, mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def publish(self, stream: str, data: dict[str, Any]) -> str:
        """Publish message to stream.

        Args:
            stream: Stream name
            data: Message data (flat dict with string values)

        Returns:
            Message ID assigned by Redis
        """
        return await self._client.xadd(stream, data)

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 1000,
    ) -> list[dict[str, Any]]:
        """Consume messages from stream via consumer group.

        Args:
            stream: Stream name
            group: Consumer group name
            consumer: Consumer name (unique within group)
            count: Maximum messages to return
            block_ms: Block timeout in milliseconds (0 = no block)

        Returns:
            List of message dicts with _id field added
        """
        result = await self._client.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )

        if not result:
            return []

        messages = []
        for stream_name, stream_messages in result:
            for msg_id, msg_data in stream_messages:
                msg_data["_id"] = msg_id
                messages.append(msg_data)

        return messages

    async def ack(self, stream: str, group: str, msg_id: str) -> None:
        """Acknowledge message processing.

        Args:
            stream: Stream name
            group: Consumer group name
            msg_id: Message ID to acknowledge
        """
        await self._client.xack(stream, group, msg_id)

    async def hset(self, key: str, mapping: dict[str, Any]) -> None:
        """Set hash fields.

        Args:
            key: Hash key
            mapping: Field-value pairs to set
        """
        await self._client.hset(key, mapping=mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        """Get all hash fields.

        Args:
            key: Hash key

        Returns:
            Dict of field-value pairs
        """
        return await self._client.hgetall(key)

    async def hexists(self, key: str, field: str) -> bool:
        """Check if hash field exists.

        Args:
            key: Hash key
            field: Field name

        Returns:
            True if field exists
        """
        return await self._client.hexists(key, field)
