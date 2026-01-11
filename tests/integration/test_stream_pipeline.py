# tests/integration/test_stream_pipeline.py
"""Integration test for the full stream pipeline."""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from trading.streams import RedisStreams, BinanceFeedTask
from trading.strategies import V35LongTask
from trading.executor import PaperExecutor


@pytest.fixture
async def redis():
    """Create Redis connection for testing."""
    r = RedisStreams(url="redis://localhost:6379")
    await r.connect()

    # Clean up test streams
    await r._client.delete("market:prices", "orders", "trades", "alerts")
    await r._client.delete("positions:BTC:spot", "risk")

    yield r

    await r.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_pipeline(redis):
    """Test price -> strategy -> executor flow."""
    # Initialize risk
    await redis.set_risk({
        "kill_switch": "false",
        "blocked": "false",
        "daily_pnl": "0",
    })

    # Create strategy
    strategy = V35LongTask(
        symbols=["BTC"],
        redis=redis,
        config={"position_size": 0.01},
    )

    # Create paper executor
    executor = PaperExecutor(
        redis=redis,
        config={"initial_balance": 10000},
    )
    executor.last_prices = {"BTC": 43000.0}

    # Start strategy and executor in background
    strategy_task = asyncio.create_task(strategy.run())
    executor_task = asyncio.create_task(executor.run())

    # Simulate price updates
    for i in range(200):
        await redis.publish("market:prices", {
            "symbol": "BTC",
            "price": str(43000 + i * 10),  # Rising price
            "market": "spot",
            "source": "binance",
            "timestamp": str(i),
        })

    # Wait for processing
    await asyncio.sleep(2)

    # Check if order was created
    # (Strategy should have evaluated and possibly published order)

    # Cleanup
    strategy.stop()
    executor.stop()
    strategy_task.cancel()
    executor_task.cancel()

    try:
        await strategy_task
        await executor_task
    except asyncio.CancelledError:
        pass
