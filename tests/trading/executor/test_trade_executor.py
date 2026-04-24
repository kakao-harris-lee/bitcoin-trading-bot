import pytest
from unittest.mock import AsyncMock, MagicMock

from trading.executor.risk_controls import RiskControls
from trading.executor.trade_executor import TradeExecutor


class TestRiskControls:
    @pytest.fixture
    def config(self):
        config = MagicMock()
        config.daily_loss_limit_pct = 5.0
        config.max_position_size = 1.0
        return config

    @pytest.fixture
    def risk(self, config):
        return RiskControls(config)

    def test_kill_switch_blocks_trade(self, risk):
        risk.set_kill_switch(True)
        assert not risk.allow_trade("h4", {"action": "buy", "size": 0.1})

    def test_normal_trade_allowed(self, risk):
        assert risk.allow_trade("h4", {"action": "buy", "size": 0.1})

    def test_record_pnl_accumulates(self, risk):
        risk.record_pnl("h4", 2.0)
        risk.record_pnl("h4", -1.0)
        pnl = risk.get_daily_pnl()
        assert pnl["h4"] == 1.0


class TestTradeExecutor:
    @pytest.fixture
    def mock_redis(self):
        redis = AsyncMock()
        redis.consume = AsyncMock(return_value=[])
        redis.create_consumer_group = AsyncMock()
        redis.ack = AsyncMock()
        return redis

    @pytest.fixture
    def executor(self, mock_redis):
        config = MagicMock()
        config.binance_mode = "paper"
        config.daily_loss_limit_pct = 5.0
        config.max_position_size = 1.0
        binance = AsyncMock()
        return TradeExecutor(mock_redis, binance, config)

    def test_strategy_exchange_mapping(self, executor):
        assert executor.STRATEGY_EXCHANGE == {"h4": "binance"}
        assert executor.SIGNAL_STREAMS == ["signals:h4"]

    @pytest.mark.asyncio
    async def test_process_signal_paper_mode(self, executor):
        msg = {
            "stream": "signals:h4",
            "data": {
                "action": "buy",
                "price": 50000.0,
                "size": 0.1,
                "reason": "TEST",
            },
        }

        await executor.process_signal(msg)

        assert "h4" in executor._positions
        assert executor._positions["h4"]["active"] is True
        assert executor._positions["h4"]["entry_price"] == 50000.0

    @pytest.mark.asyncio
    async def test_process_signal_blocked_by_kill_switch(self, executor):
        executor.risk.set_kill_switch(True)

        msg = {
            "stream": "signals:h4",
            "data": {
                "action": "buy",
                "price": 50000.0,
                "size": 0.1,
                "reason": "TEST",
            },
        }

        await executor.process_signal(msg)

        assert "h4" not in executor._positions
