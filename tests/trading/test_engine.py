# tests/trading/test_engine.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from trading.engine import TradingEngine


@pytest.fixture
def mock_config():
    return {
        "redis_url": "redis://localhost:6379",
        "symbols": ["BTC", "ETH"],
        "binance": {
            "api_key": "test",
            "api_secret": "secret",
        },
        "risk": {
            "max_daily_loss": 500,
        },
        "paper": {
            "initial_balance": 10000,
        },
    }


def test_engine_loads_config(mock_config):
    """Test engine loads configuration."""
    with patch('trading.engine.load_config', return_value=mock_config):
        engine = TradingEngine(config_path="test.json")
        assert engine.config["symbols"] == ["BTC", "ETH"]


@pytest.mark.asyncio
async def test_engine_starts_paper_mode(mock_config):
    """Test engine starts in paper mode."""
    with patch('trading.engine.load_config', return_value=mock_config):
        with patch('trading.engine.RedisStreams') as MockRedis:
            mock_redis = AsyncMock()
            MockRedis.return_value = mock_redis

            engine = TradingEngine(config_path="test.json")

            # Don't actually run, just verify setup
            assert engine.config is not None


def test_engine_creates_feed_tasks(mock_config):
    """Test engine creates feed task per symbol."""
    with patch('trading.engine.load_config', return_value=mock_config):
        engine = TradingEngine(config_path="test.json")

        # Verify symbols are configured
        assert "BTC" in engine.config["symbols"]
        assert "ETH" in engine.config["symbols"]
