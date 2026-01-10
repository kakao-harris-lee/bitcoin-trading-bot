# tests/trading/streams/test_redis_streams.py
"""
Redis Streams unit tests.

Tests cover:
- Connection/disconnection
- Consumer group creation
- Message publish/consume
- Hash operations (hset/hgetall/hexists)
- Message acknowledgment

Note: Tests require Redis running locally. Integration tests are skipped if Redis is unavailable.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


# Mark all tests as asyncio
pytestmark = pytest.mark.asyncio


def is_redis_available() -> bool:
    """Check if Redis is available locally."""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', 6379))
        sock.close()
        return result == 0
    except Exception:
        return False


# Skip integration tests if Redis is not available
REDIS_AVAILABLE = is_redis_available()
skip_if_no_redis = pytest.mark.skipif(
    not REDIS_AVAILABLE,
    reason="Redis not available at localhost:6379"
)


@pytest.fixture
def redis_streams():
    """Create RedisStreams instance."""
    from trading.streams.redis_streams import RedisStreams
    return RedisStreams(url="redis://localhost:6379")


class TestRedisStreamsUnit:
    """Unit tests using mocks (no Redis required)."""

    async def test_init(self):
        """Test RedisStreams initialization."""
        from trading.streams.redis_streams import RedisStreams

        streams = RedisStreams(url="redis://localhost:6379")
        assert streams.url == "redis://localhost:6379"
        assert streams._client is None

    async def test_connect_creates_client(self, redis_streams):
        """Test connect creates Redis client."""
        with patch('redis.asyncio.from_url') as mock_from_url:
            mock_client = MagicMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_from_url.return_value = mock_client

            await redis_streams.connect()

            mock_from_url.assert_called_once_with(
                "redis://localhost:6379",
                decode_responses=True
            )
            assert redis_streams._client is not None

    async def test_disconnect_closes_client(self, redis_streams):
        """Test disconnect closes Redis client."""
        mock_client = MagicMock()
        mock_client.aclose = AsyncMock()
        redis_streams._client = mock_client

        await redis_streams.disconnect()

        mock_client.aclose.assert_called_once()
        assert redis_streams._client is None

    async def test_create_consumer_group_success(self, redis_streams):
        """Test consumer group creation."""
        mock_client = MagicMock()
        mock_client.xgroup_create = AsyncMock()
        redis_streams._client = mock_client

        await redis_streams.create_consumer_group("test:stream", "test-group")

        mock_client.xgroup_create.assert_called_once_with(
            "test:stream", "test-group", id="0", mkstream=True
        )

    async def test_create_consumer_group_already_exists(self, redis_streams):
        """Test consumer group creation when group already exists."""
        import redis.asyncio as aioredis

        mock_client = MagicMock()
        mock_client.xgroup_create = AsyncMock(
            side_effect=aioredis.ResponseError("BUSYGROUP Consumer Group name already exists")
        )
        redis_streams._client = mock_client

        # Should not raise
        await redis_streams.create_consumer_group("test:stream", "test-group")

    async def test_publish_returns_message_id(self, redis_streams):
        """Test publish returns message ID."""
        mock_client = MagicMock()
        mock_client.xadd = AsyncMock(return_value="1234567890-0")
        redis_streams._client = mock_client

        msg_id = await redis_streams.publish("test:stream", {"key": "value"})

        assert msg_id == "1234567890-0"
        mock_client.xadd.assert_called_once()

    async def test_consume_returns_messages(self, redis_streams):
        """Test consume returns parsed messages."""
        mock_client = MagicMock()
        mock_client.xreadgroup = AsyncMock(return_value=[
            ("test:stream", [
                ("1234567890-0", {"symbol": "BTC", "price": "43000"})
            ])
        ])
        redis_streams._client = mock_client

        messages = await redis_streams.consume(
            "test:stream", "test-group", "test-consumer", count=1
        )

        assert len(messages) == 1
        assert messages[0]["symbol"] == "BTC"
        assert messages[0]["price"] == "43000"
        assert messages[0]["_id"] == "1234567890-0"

    async def test_consume_returns_empty_on_no_messages(self, redis_streams):
        """Test consume returns empty list when no messages."""
        mock_client = MagicMock()
        mock_client.xreadgroup = AsyncMock(return_value=None)
        redis_streams._client = mock_client

        messages = await redis_streams.consume(
            "test:stream", "test-group", "test-consumer"
        )

        assert messages == []

    async def test_ack_message(self, redis_streams):
        """Test message acknowledgment."""
        mock_client = MagicMock()
        mock_client.xack = AsyncMock()
        redis_streams._client = mock_client

        await redis_streams.ack("test:stream", "test-group", "1234567890-0")

        mock_client.xack.assert_called_once_with(
            "test:stream", "test-group", "1234567890-0"
        )

    async def test_hset(self, redis_streams):
        """Test hash set operation."""
        mock_client = MagicMock()
        mock_client.hset = AsyncMock()
        redis_streams._client = mock_client

        await redis_streams.hset("test:key", {"field1": "value1"})

        mock_client.hset.assert_called_once_with("test:key", mapping={"field1": "value1"})

    async def test_hgetall(self, redis_streams):
        """Test hash get all operation."""
        mock_client = MagicMock()
        mock_client.hgetall = AsyncMock(return_value={"field1": "value1"})
        redis_streams._client = mock_client

        result = await redis_streams.hgetall("test:key")

        assert result == {"field1": "value1"}
        mock_client.hgetall.assert_called_once_with("test:key")

    async def test_hexists(self, redis_streams):
        """Test hash field exists check."""
        mock_client = MagicMock()
        mock_client.hexists = AsyncMock(return_value=True)
        redis_streams._client = mock_client

        result = await redis_streams.hexists("test:key", "field1")

        assert result is True
        mock_client.hexists.assert_called_once_with("test:key", "field1")


@pytest.mark.integration
@skip_if_no_redis
class TestRedisStreamsIntegration:
    """Integration tests requiring Redis running locally."""

    @pytest.fixture
    def connected_streams(self, event_loop):
        """Create and connect RedisStreams instance (sync fixture wrapping async)."""
        from trading.streams.redis_streams import RedisStreams

        streams = RedisStreams(url="redis://localhost:6379/15")  # Use DB 15 for tests

        async def setup():
            await streams.connect()
            return streams

        async def teardown(s):
            if s._client:
                await s._client.delete("test:stream", "test:key")
                await s.disconnect()

        instance = event_loop.run_until_complete(setup())
        yield instance
        event_loop.run_until_complete(teardown(instance))

    async def test_publish_and_consume(self, connected_streams):
        """Test basic publish/consume cycle."""
        stream = "test:stream"
        group = "test-group"
        consumer = "test-consumer"

        # Setup
        await connected_streams.create_consumer_group(stream, group)

        # Publish
        msg_id = await connected_streams.publish(stream, {"symbol": "BTC", "price": "43000"})
        assert msg_id is not None

        # Consume
        messages = await connected_streams.consume(stream, group, consumer, count=1)
        assert len(messages) == 1
        assert messages[0]["symbol"] == "BTC"

    async def test_hash_operations(self, connected_streams):
        """Test hash operations cycle."""
        key = "test:key"

        # Set
        await connected_streams.hset(key, {"symbol": "BTC", "price": "43000"})

        # Get
        result = await connected_streams.hgetall(key)
        assert result["symbol"] == "BTC"
        assert result["price"] == "43000"

        # Exists
        assert await connected_streams.hexists(key, "symbol") is True
        assert await connected_streams.hexists(key, "nonexistent") is False
