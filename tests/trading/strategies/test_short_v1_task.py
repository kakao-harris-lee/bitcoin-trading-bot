# tests/trading/strategies/test_short_v1_task.py
import pytest
from unittest.mock import AsyncMock, patch
from collections import deque
from trading.strategies.short_v1_task import ShortV1Task


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.publish = AsyncMock(return_value="1234-0")
    redis.has_position = AsyncMock(return_value=False)
    redis.is_blocked = AsyncMock(return_value=False)
    return redis


def test_short_classify_bear_strong():
    """Test bear strong classification."""
    strategy = ShortV1Task(symbols=["BTC"], redis=AsyncMock())

    # MFI <= 48, ADX >= 20 -> BEAR_STRONG
    regime = strategy._classify_regime(mfi=45.0, adx=25.0)
    assert regime == "BEAR_STRONG"


def test_short_should_enter():
    """Test entry conditions."""
    strategy = ShortV1Task(symbols=["BTC"], redis=AsyncMock())

    # Should only enter on BEAR_STRONG
    assert strategy._should_enter("BEAR_STRONG")
    assert not strategy._should_enter("BEAR_MODERATE")
    assert not strategy._should_enter("SIDEWAYS_NEUTRAL")
    assert not strategy._should_enter("BULL_STRONG")


@pytest.mark.asyncio
async def test_short_generates_sell_signal(mock_redis):
    """Test short signal generation in bear market."""
    strategy = ShortV1Task(symbols=["BTC"], redis=mock_redis)

    with patch.object(strategy, '_calculate_indicators') as mock_calc:
        mock_calc.return_value = {
            "mfi": 42.0,
            "adx": 28.0,
            "close": 43000.0,
            "rsi": 72.0,  # Overbought - good for short entry
        }

        strategy.price_buffer["BTC"] = deque([{"price": str(43000 + i)} for i in range(200)])

        signal = await strategy.evaluate("BTC")

        assert signal is not None
        assert signal["side"] == "sell"
        assert signal["market"] == "futures"
        assert "BEAR_STRONG" in signal["reason"]
