# tests/trading/publishers/test_feed_publisher.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from trading.publishers.feed_publisher import FeedPublisher
from core.types import Exchange


class TestFeedPublisher:
    @pytest.fixture
    def mock_redis(self):
        redis = AsyncMock()
        redis.publish = AsyncMock(return_value="1234-0")
        return redis

    @pytest.fixture
    def publisher(self, mock_redis):
        config = MagicMock()
        return FeedPublisher(Exchange.UPBIT, mock_redis, config)

    def test_stream_name_upbit(self, publisher):
        assert publisher.stream_name == "market:upbit:prices"

    def test_stream_name_binance(self, mock_redis):
        config = MagicMock()
        publisher = FeedPublisher(Exchange.BINANCE, mock_redis, config)
        assert publisher.stream_name == "market:binance:prices"

    @pytest.mark.asyncio
    async def test_publish_price(self, publisher, mock_redis):
        await publisher.publish_price(
            price=50000.0,
            volume=100.0,
            timestamp="2026-01-02T10:00:00"
        )

        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == "market:upbit:prices"
        assert call_args[0][1]["price"] == 50000.0
        assert call_args[0][1]["volume"] == 100.0
