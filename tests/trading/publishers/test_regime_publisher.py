# tests/trading/publishers/test_regime_publisher.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd
from trading.publishers.regime_publisher import RegimePublisher


class TestRegimePublisher:
    @pytest.fixture
    def mock_redis(self):
        redis = AsyncMock()
        redis.publish = AsyncMock(return_value="1234-0")
        return redis

    @pytest.fixture
    def publisher(self, mock_redis):
        config = MagicMock()
        return RegimePublisher(mock_redis, config)

    def test_stream_name(self, publisher):
        assert publisher.stream_name == "market:regime"

    @pytest.mark.asyncio
    async def test_publish_regime(self, publisher, mock_redis):
        await publisher.publish_regime(
            regime="BULL",
            market_state="BULL_STRONG",
            mfi=65.0,
            adx=30.0
        )

        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == "market:regime"
        data = call_args[0][1]
        assert data["regime"] == "BULL"
        assert data["market_state"] == "BULL_STRONG"
        assert data["mfi"] == 65.0
        assert data["adx"] == 30.0
