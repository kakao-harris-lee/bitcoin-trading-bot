# tests/trading/strategies/test_sideways_v2_task.py
import pytest
from unittest.mock import AsyncMock, patch
from collections import deque
from trading.strategies.sideways_v2_task import SidewaysV2Task


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.publish = AsyncMock(return_value="1234-0")
    redis.has_position = AsyncMock(return_value=False)
    redis.is_blocked = AsyncMock(return_value=False)
    return redis


def test_sideways_classify_sideways_neutral():
    """Test sideways neutral classification."""
    strategy = SidewaysV2Task(symbols=["BTC"], redis=AsyncMock())

    # 48 < MFI < 52, ADX < 20 -> SIDEWAYS_NEUTRAL
    regime = strategy._classify_regime(mfi=50.0, adx=15.0)
    assert regime == "SIDEWAYS_NEUTRAL"


def test_sideways_should_enter():
    """Test entry conditions."""
    strategy = SidewaysV2Task(symbols=["BTC"], redis=AsyncMock())

    # Should only enter on SIDEWAYS regimes
    assert strategy._should_enter("SIDEWAYS_NEUTRAL")
    assert strategy._should_enter("SIDEWAYS_BULL")
    assert strategy._should_enter("SIDEWAYS_BEAR")
    assert not strategy._should_enter("BULL_STRONG")
    assert not strategy._should_enter("BEAR_STRONG")


@pytest.mark.asyncio
async def test_sideways_generates_signal_in_range(mock_redis):
    """Test signal generation in sideways market."""
    strategy = SidewaysV2Task(symbols=["BTC"], redis=mock_redis)

    with patch.object(strategy, '_calculate_indicators') as mock_calc:
        mock_calc.return_value = {
            "mfi": 50.0,
            "adx": 12.0,
            "close": 43000.0,
            "rsi": 35.0,  # Oversold
        }

        strategy.price_buffer["BTC"] = deque([{"price": str(43000 + i)} for i in range(200)])

        signal = await strategy.evaluate("BTC")

        assert signal is not None
        assert signal["side"] == "buy"
        assert "SIDEWAYS" in signal["reason"]
