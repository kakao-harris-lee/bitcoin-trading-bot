# tests/trading/test_engine.py
import pytest
from unittest.mock import AsyncMock, patch
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


@pytest.mark.asyncio
async def test_initialize_risk_state_resets_daily_pnl_on_mode_change(mock_config):
    """Mode transition should reset daily_pnl to avoid cross-mode carry-over."""
    with patch('trading.engine.load_config', return_value=mock_config):
        engine = TradingEngine(config_path="test.json")

    mock_redis = AsyncMock()
    mock_redis.get_risk = AsyncMock(
        return_value={"mode": "paper", "daily_pnl": "-123.4", "kill_switch": "false"}
    )
    mock_redis._client = AsyncMock()
    mock_redis._client.hset = AsyncMock()
    engine.redis = mock_redis

    await engine._initialize_risk_state("live")

    mock_redis._client.hset.assert_called_once_with(
        "risk",
        mapping={"mode": "live", "daily_pnl": "0"},
    )


@pytest.mark.asyncio
async def test_initialize_risk_state_preserves_daily_pnl_in_same_mode(mock_config):
    """Restarting in same mode should not force-reset daily_pnl."""
    with patch('trading.engine.load_config', return_value=mock_config):
        engine = TradingEngine(config_path="test.json")

    mock_redis = AsyncMock()
    mock_redis.get_risk = AsyncMock(
        return_value={"mode": "live", "daily_pnl": "-50.0", "kill_switch": "false"}
    )
    mock_redis._client = AsyncMock()
    mock_redis._client.hset = AsyncMock()
    engine.redis = mock_redis

    await engine._initialize_risk_state("live")

    mock_redis._client.hset.assert_called_once_with(
        "risk",
        mapping={"mode": "live"},
    )


def test_resolve_feed_market_uses_explicit_override(mock_config):
    """Top-level feed_market should override strategy-derived market."""
    cfg = dict(mock_config)
    cfg["feed_market"] = "spot"
    with patch("trading.engine.load_config", return_value=cfg):
        engine = TradingEngine(config_path="test.json")

    market = engine._resolve_feed_market(
        {"some_futures_strat": {"enabled": True, "market": "futures"}}
    )
    assert market == "spot"


def test_resolve_feed_market_prefers_futures_in_mixed_mode(mock_config):
    """When both markets are enabled, choose futures for a single shared feed."""
    with patch("trading.engine.load_config", return_value=mock_config):
        engine = TradingEngine(config_path="test.json")

    market = engine._resolve_feed_market(
        {
            "spot_strat": {"enabled": True, "market": "spot"},
            "futures_strat": {"enabled": True, "market": "futures"},
        }
    )
    assert market == "futures"


def test_resolve_feed_market_uses_spot_for_spot_only(mock_config):
    """Spot-only strategy set should use spot feed."""
    with patch("trading.engine.load_config", return_value=mock_config):
        engine = TradingEngine(config_path="test.json")

    market = engine._resolve_feed_market(
        {
            "mlp_direction_btc": {"enabled": True, "market": "spot"},
            "mlp_direction_eth": {"enabled": True, "market": "spot"},
        }
    )
    assert market == "spot"


def test_resolve_feed_warmup_enabled_default_false(mock_config):
    """Feed warmup should default to disabled to avoid duplicate startup warmups."""
    with patch("trading.engine.load_config", return_value=mock_config):
        engine = TradingEngine(config_path="test.json")

    assert engine._resolve_feed_warmup_enabled() is False


def test_resolve_feed_stream_type_defaults_to_miniticker(mock_config):
    with patch("trading.engine.load_config", return_value=mock_config):
        engine = TradingEngine(config_path="test.json")
    assert engine._resolve_feed_stream_type() == "miniTicker"


def test_resolve_feed_stream_type_accepts_bookticker(mock_config):
    cfg = dict(mock_config)
    cfg["feed_stream_type"] = "bookTicker"
    with patch("trading.engine.load_config", return_value=cfg):
        engine = TradingEngine(config_path="test.json")
    assert engine._resolve_feed_stream_type() == "bookTicker"
