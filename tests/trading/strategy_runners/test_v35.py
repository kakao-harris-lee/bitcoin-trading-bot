# tests/trading/strategy_runners/test_v35.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd
import numpy as np
from trading.strategy_runners.v35 import V35Strategy


class TestV35Strategy:
    @pytest.fixture
    def mock_redis(self):
        redis = AsyncMock()
        redis.consume = AsyncMock(return_value=[])
        redis.publish = AsyncMock()
        redis.create_consumer_group = AsyncMock()
        return redis

    @pytest.fixture
    def config(self):
        config = MagicMock()
        config.v35 = {
            "rsi_period": 14,
            "mfi_period": 14,
            "adx_period": 14,
            "stop_loss": -0.015,
        }
        return config

    @pytest.fixture
    def strategy(self, mock_redis, config):
        return V35Strategy(mock_redis, config)

    def test_name(self, strategy):
        assert strategy.name == "v35"

    def test_exchange(self, strategy):
        assert strategy.exchange == "upbit"

    def test_subscribed_streams(self, strategy):
        assert "market:upbit:prices" in strategy.subscribed_streams

    @pytest.mark.asyncio
    async def test_on_price_no_signal_without_data(self, strategy):
        # Without enough data, should return None
        # Mock DataLoader to return empty DataFrame
        with patch('trading.strategy_runners.v35.DataLoader') as mock_loader:
            mock_instance = MagicMock()
            mock_instance.load_timeframe.return_value = pd.DataFrame()
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_loader.return_value = mock_instance

            signal = await strategy.on_price({"price": 50000, "volume": 100})
            assert signal is None

    @pytest.mark.asyncio
    async def test_on_regime_updates_market_state(self, strategy):
        await strategy.on_regime({
            "regime": "BULL",
            "market_state": "BULL_STRONG"
        })
        assert strategy._current_regime == "BULL"
        assert strategy._market_state == "BULL_STRONG"

    def test_position_tracking(self, strategy):
        # Initially not in position
        assert strategy.in_position is False

        # Enter position
        strategy.enter_position(50000.0, 0.1)
        assert strategy.in_position is True
        assert strategy.entry_price == 50000.0

        # Exit position
        strategy.exit_position()
        assert strategy.in_position is False
        assert strategy.entry_price == 0.0

    def test_get_tp_levels_bull_strong(self, strategy):
        strategy._market_state = "BULL_STRONG"
        levels = strategy._get_tp_levels()
        # Should have aggressive TP levels in bull
        assert len(levels) == 3
        assert levels[0][0] == 0.03  # First TP at 3%

    def test_get_tp_levels_sideways(self, strategy):
        strategy._market_state = "SIDEWAYS"
        levels = strategy._get_tp_levels()
        # Should have tighter TP levels
        assert len(levels) == 2
        assert levels[0][0] == 0.015  # First TP at 1.5%
