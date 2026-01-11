# tests/trading/strategy_runners/test_base.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from trading.strategy_runners.base import StandaloneStrategy, Signal


class TestSignal:
    def test_signal_to_dict(self):
        signal = Signal(
            action="buy",
            price=50000.0,
            reason="MOMENTUM_ENTRY",
            size=0.1,
            strategy="v35"
        )
        result = signal.to_dict()
        assert result["action"] == "buy"
        assert result["price"] == 50000.0
        assert result["reason"] == "MOMENTUM_ENTRY"
        assert result["size"] == 0.1
        assert result["strategy"] == "v35"
        assert "timestamp" in result


class ConcreteStrategy(StandaloneStrategy):
    """Concrete implementation for testing"""

    @property
    def name(self) -> str:
        return "test_strategy"

    @property
    def exchange(self) -> str:
        return "binance"

    @property
    def subscribed_streams(self) -> list:
        return ["market:binance:prices"]

    async def on_price(self, price_data: dict):
        if price_data.get("price", 0) > 50000:
            return Signal(
                action="buy",
                price=price_data["price"],
                reason="TEST_SIGNAL",
                size=0.1,
                strategy=self.name
            )
        return None


class TestStandaloneStrategy:
    @pytest.fixture
    def mock_redis(self):
        redis = AsyncMock()
        redis.consume = AsyncMock(return_value=[])
        redis.publish = AsyncMock()
        return redis

    @pytest.fixture
    def strategy(self, mock_redis):
        config = MagicMock()
        return ConcreteStrategy(mock_redis, config)

    def test_strategy_name(self, strategy):
        assert strategy.name == "test_strategy"

    def test_strategy_exchange(self, strategy):
        assert strategy.exchange == "binance"

    def test_subscribed_streams(self, strategy):
        assert strategy.subscribed_streams == ["market:binance:prices"]

    @pytest.mark.asyncio
    async def test_on_price_generates_signal(self, strategy):
        price_data = {"price": 55000.0, "volume": 100}
        signal = await strategy.on_price(price_data)
        assert signal is not None
        assert signal.action == "buy"

    @pytest.mark.asyncio
    async def test_on_price_no_signal(self, strategy):
        price_data = {"price": 45000.0, "volume": 100}
        signal = await strategy.on_price(price_data)
        assert signal is None
