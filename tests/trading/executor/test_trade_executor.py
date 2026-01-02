# tests/trading/executor/test_trade_executor.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from trading.executor.trade_executor import TradeExecutor
from trading.executor.risk_controls import RiskControls


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
        assert not risk.allow_trade("v35", {"action": "buy", "size": 0.1})

    def test_normal_trade_allowed(self, risk):
        assert risk.allow_trade("v35", {"action": "buy", "size": 0.1})

    def test_daily_loss_blocks_trade(self, risk):
        # Record losses exceeding limit
        risk.record_pnl("v35", -3.0)
        risk.record_pnl("short_v1", -3.0)

        assert not risk.allow_trade("v35", {"action": "buy", "size": 0.1})

    def test_position_size_blocks_trade(self, risk):
        # Size exceeds max
        assert not risk.allow_trade("v35", {"action": "buy", "size": 1.5})

    def test_record_pnl_accumulates(self, risk):
        risk.record_pnl("v35", 2.0)
        risk.record_pnl("v35", -1.0)
        pnl = risk.get_daily_pnl()
        assert pnl["v35"] == 1.0


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
        config.upbit_mode = "paper"
        config.binance_mode = "paper"
        config.daily_loss_limit_pct = 5.0
        config.max_position_size = 1.0
        upbit = AsyncMock()
        binance = AsyncMock()
        return TradeExecutor(mock_redis, upbit, binance, config)

    def test_strategy_exchange_mapping(self, executor):
        assert executor.STRATEGY_EXCHANGE["v35"] == "upbit"
        assert executor.STRATEGY_EXCHANGE["short_v1"] == "binance"
        assert executor.STRATEGY_EXCHANGE["premium"] == "both"

    @pytest.mark.asyncio
    async def test_process_signal_paper_mode(self, executor):
        msg = {
            "stream": "signals:v35",
            "data": {
                "action": "buy",
                "price": 50000.0,
                "size": 0.1,
                "reason": "TEST"
            }
        }

        await executor.process_signal(msg)

        # Should have recorded paper position
        assert "v35" in executor._positions
        assert executor._positions["v35"]["active"] is True
        assert executor._positions["v35"]["entry_price"] == 50000.0

    @pytest.mark.asyncio
    async def test_process_signal_blocked_by_kill_switch(self, executor):
        executor.risk.set_kill_switch(True)

        msg = {
            "stream": "signals:v35",
            "data": {
                "action": "buy",
                "price": 50000.0,
                "size": 0.1,
                "reason": "TEST"
            }
        }

        await executor.process_signal(msg)

        # Should NOT have recorded position
        assert "v35" not in executor._positions
