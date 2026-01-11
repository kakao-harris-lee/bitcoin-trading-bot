# tests/trading/strategies/test_v35_long_task.py
import pytest
from unittest.mock import AsyncMock, patch
from collections import deque
import numpy as np
from trading.strategies.v35_long_task import V35LongTask


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.publish = AsyncMock(return_value="1234-0")
    redis.has_position = AsyncMock(return_value=False)
    redis.is_blocked = AsyncMock(return_value=False)
    redis.get_position = AsyncMock(return_value={})
    return redis


def test_v35_classify_bull_strong():
    """Test bull strong classification."""
    strategy = V35LongTask(symbols=["BTC"], redis=AsyncMock())

    # MFI >= 52, ADX >= 25 -> BULL_STRONG
    regime = strategy._classify_regime(mfi=55.0, adx=28.0)
    assert regime == "BULL_STRONG"


def test_v35_classify_bull_moderate():
    """Test bull moderate classification."""
    strategy = V35LongTask(symbols=["BTC"], redis=AsyncMock())

    # MFI >= 52, 20 <= ADX < 25 -> BULL_MODERATE
    regime = strategy._classify_regime(mfi=54.0, adx=22.0)
    assert regime == "BULL_MODERATE"


def test_v35_classify_sideways():
    """Test sideways classification."""
    strategy = V35LongTask(symbols=["BTC"], redis=AsyncMock())

    # 48 < MFI < 52 -> SIDEWAYS
    regime = strategy._classify_regime(mfi=50.0, adx=15.0)
    assert regime == "SIDEWAYS_NEUTRAL"


def test_v35_should_enter_on_bull():
    """Test entry conditions in bull market."""
    strategy = V35LongTask(symbols=["BTC"], redis=AsyncMock())

    # Should enter on BULL_STRONG or BULL_MODERATE
    assert strategy._should_enter("BULL_STRONG")
    assert strategy._should_enter("BULL_MODERATE")
    assert not strategy._should_enter("SIDEWAYS_NEUTRAL")
    assert not strategy._should_enter("BEAR_STRONG")


@pytest.mark.asyncio
async def test_v35_generates_buy_signal(mock_redis):
    """Test buy signal generation in bull regime."""
    strategy = V35LongTask(symbols=["BTC"], redis=mock_redis)

    # Mock indicator calculation to return bull conditions
    with patch.object(strategy, '_calculate_indicators') as mock_calc:
        mock_calc.return_value = {"mfi": 55.0, "adx": 28.0, "close": 43000.0}

        # Add enough price data
        strategy.price_buffer["BTC"] = deque([{"price": str(43000 + i)} for i in range(200)])

        signal = await strategy.evaluate("BTC")

        assert signal is not None
        assert signal["side"] == "buy"
        assert signal["symbol"] == "BTC"
        assert signal["market"] == "spot"
