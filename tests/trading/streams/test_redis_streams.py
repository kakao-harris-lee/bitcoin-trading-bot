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
import pytest_asyncio
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

    async def test_position_operations(self, redis_streams):
        """Test position hash operations."""
        mock_client = MagicMock()
        mock_client.hset = AsyncMock()
        mock_client.hgetall = AsyncMock(return_value={
            "quantity": "0.05",
            "entry_price": "43000",
            "strategy": "v35_long",
        })
        mock_client.exists = AsyncMock(return_value=1)
        mock_client.delete = AsyncMock()
        redis_streams._client = mock_client

        # Set position
        await redis_streams.set_position("BTC", "spot", {
            "quantity": "0.05",
            "entry_price": "43000",
            "strategy": "v35_long",
        })
        mock_client.hset.assert_called_once_with(
            "positions:BTC:spot",
            mapping={"quantity": "0.05", "entry_price": "43000", "strategy": "v35_long"}
        )

        # Check exists
        assert await redis_streams.has_position("BTC", "spot")
        mock_client.exists.assert_called_with("positions:BTC:spot")

        # Check non-existent position
        mock_client.exists.return_value = 0
        assert not await redis_streams.has_position("ETH", "spot")

        # Get position
        mock_client.exists.return_value = 1
        pos = await redis_streams.get_position("BTC", "spot")
        assert pos["quantity"] == "0.05"
        assert pos["strategy"] == "v35_long"
        mock_client.hgetall.assert_called_with("positions:BTC:spot")

        # Clear position
        await redis_streams.clear_position("BTC", "spot")
        mock_client.delete.assert_called_once_with("positions:BTC:spot")

    async def test_risk_operations(self, redis_streams):
        """Test risk hash operations."""
        mock_client = MagicMock()
        mock_client.hset = AsyncMock()
        mock_client.hgetall = AsyncMock(return_value={
            "kill_switch": "false",
            "daily_pnl": "0",
            "blocked": "false"
        })
        redis_streams._client = mock_client

        # Initialize risk
        await redis_streams.set_risk({
            "kill_switch": "false",
            "daily_pnl": "0",
            "blocked": "false"
        })
        mock_client.hset.assert_called_with(
            "risk",
            mapping={"kill_switch": "false", "daily_pnl": "0", "blocked": "false"}
        )

        # Check blocked (initially false)
        assert not await redis_streams.is_blocked()

        # Block
        mock_client.hgetall.return_value = {"blocked": "true"}
        assert await redis_streams.is_blocked()

        # Check kill switch (initially false)
        mock_client.hgetall.return_value = {"kill_switch": "false"}
        assert not await redis_streams.is_kill_switch_on()

        # Enable kill switch
        mock_client.hgetall.return_value = {"kill_switch": "true"}
        assert await redis_streams.is_kill_switch_on()

    async def test_publish_to_arbitrary_stream_name(self, redis_streams):
        """Test that publish works with arbitrary stream names including 'exit_signals'."""
        mock_client = MagicMock()
        mock_client.xadd = AsyncMock(return_value="1234567890-0")
        redis_streams._client = mock_client

        # Test with exit_signals stream
        msg_id = await redis_streams.publish("exit_signals", {
            "symbol": "BTC",
            "market": "futures",
            "quantity": "0.05",
            "trigger_price": "43000"
        })

        assert msg_id == "1234567890-0"
        mock_client.xadd.assert_called_once()
        call_args = mock_client.xadd.call_args
        assert call_args[0][0] == "exit_signals"
        assert call_args[0][1]["symbol"] == "BTC"

        # Test with other custom stream names
        mock_client.xadd.reset_mock()
        await redis_streams.publish("custom:stream", {"data": "value"})
        mock_client.xadd.assert_called_once()
        assert mock_client.xadd.call_args[0][0] == "custom:stream"


@pytest.mark.integration
@skip_if_no_redis
class TestRedisStreamsIntegration:
    """Integration tests requiring Redis running locally."""

    @pytest_asyncio.fixture
    async def connected_streams(self):
        """Create and connect RedisStreams instance."""
        from trading.streams.redis_streams import RedisStreams

        streams = RedisStreams(url="redis://localhost:6379/15")  # Use DB 15 for tests
        await streams.connect()

        yield streams

        # Teardown
        try:
            if streams._client:
                await streams._client.delete("test:stream", "test:key")
                await streams.disconnect()
        except Exception:
            pass  # Ignore cleanup errors

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

    async def test_exit_signals_stream_integration(self, connected_streams):
        """Test exit_signals stream with publish/consume cycle."""
        stream = "exit_signals"
        group = "smart-executor"
        consumer = "smart-executor-test"

        # Setup consumer group
        await connected_streams.create_consumer_group(stream, group)

        # Publish exit signal
        msg_id = await connected_streams.publish(stream, {
            "symbol": "BTC",
            "market": "futures",
            "quantity": "0.05",
            "trigger_price": "43000",
            "strategy": "v35_long"
        })
        assert msg_id is not None

        # Consume exit signal
        messages = await connected_streams.consume(stream, group, consumer, count=1)
        assert len(messages) == 1
        assert messages[0]["symbol"] == "BTC"
        assert messages[0]["market"] == "futures"
        assert messages[0]["quantity"] == "0.05"
        assert messages[0]["trigger_price"] == "43000"
        assert messages[0]["strategy"] == "v35_long"

        # Acknowledge message
        await connected_streams.ack(stream, group, messages[0]["_id"])

        # Verify no more messages
        messages = await connected_streams.consume(stream, group, consumer, count=1, block_ms=100)
        assert len(messages) == 0
