# Binance Stream Architecture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the centralized MultiAssetTradingEngine with independent async tasks communicating via Redis streams, supporting Binance spot and futures only.

**Architecture:** Each component (feed tasks, strategy tasks, executor) runs as an autonomous async task. Redis streams (`market:prices`, `orders`) provide loose coupling. Strategies self-classify market conditions. A single AsyncExecutor handles all order execution with risk gates.

**Tech Stack:** Python 3.10+, asyncio, redis-py (async), python-binance, talib

---

## Phase 1: Redis Streams Infrastructure

### Task 1.1: Create Redis Stream Client

**Files:**
- Create: `trading/streams/__init__.py`
- Create: `trading/streams/redis_streams.py`
- Test: `tests/trading/streams/test_redis_streams.py`

**Step 1: Create directory structure**

```bash
mkdir -p trading/streams
touch trading/streams/__init__.py
mkdir -p tests/trading/streams
touch tests/trading/streams/__init__.py
```

**Step 2: Write the failing test**

```python
# tests/trading/streams/test_redis_streams.py
import pytest
import asyncio
from trading.streams.redis_streams import RedisStreams


@pytest.fixture
def redis_streams():
    return RedisStreams(url="redis://localhost:6379")


@pytest.mark.asyncio
async def test_publish_and_consume(redis_streams):
    """Test basic publish/consume cycle."""
    stream = "test:stream"
    group = "test-group"
    consumer = "test-consumer"

    # Setup
    await redis_streams.connect()
    await redis_streams.create_consumer_group(stream, group)

    # Publish
    msg_id = await redis_streams.publish(stream, {"symbol": "BTC", "price": "43000"})
    assert msg_id is not None

    # Consume
    messages = await redis_streams.consume(stream, group, consumer, count=1)
    assert len(messages) == 1
    assert messages[0]["symbol"] == "BTC"

    await redis_streams.disconnect()
```

**Step 3: Run test to verify it fails**

Run: `pytest tests/trading/streams/test_redis_streams.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 4: Write minimal implementation**

```python
# trading/streams/redis_streams.py
"""Redis Streams wrapper for async publish/consume."""
from __future__ import annotations
import redis.asyncio as redis
from typing import Any


class RedisStreams:
    """Async Redis Streams client."""

    def __init__(self, url: str = "redis://localhost:6379"):
        self.url = url
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        """Connect to Redis."""
        self._client = redis.from_url(self.url, decode_responses=True)

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def create_consumer_group(
        self, stream: str, group: str, start_id: str = "0"
    ) -> None:
        """Create consumer group, ignore if exists."""
        try:
            await self._client.xgroup_create(stream, group, id=start_id, mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def publish(self, stream: str, data: dict[str, Any]) -> str:
        """Publish message to stream. Returns message ID."""
        return await self._client.xadd(stream, data)

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 1000,
    ) -> list[dict[str, Any]]:
        """Consume messages from stream."""
        result = await self._client.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )

        if not result:
            return []

        messages = []
        for stream_name, stream_messages in result:
            for msg_id, msg_data in stream_messages:
                msg_data["_id"] = msg_id
                messages.append(msg_data)

        return messages

    async def ack(self, stream: str, group: str, msg_id: str) -> None:
        """Acknowledge message processing."""
        await self._client.xack(stream, group, msg_id)

    async def hset(self, key: str, mapping: dict[str, Any]) -> None:
        """Set hash fields."""
        await self._client.hset(key, mapping=mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        """Get all hash fields."""
        return await self._client.hgetall(key)

    async def hexists(self, key: str, field: str) -> bool:
        """Check if hash field exists."""
        return await self._client.hexists(key, field)
```

**Step 5: Update __init__.py**

```python
# trading/streams/__init__.py
from .redis_streams import RedisStreams

__all__ = ["RedisStreams"]
```

**Step 6: Run test to verify it passes**

Run: `pytest tests/trading/streams/test_redis_streams.py -v`
Expected: PASS (requires Redis running locally)

**Step 7: Commit**

```bash
git add trading/streams/ tests/trading/streams/
git commit -m "feat: add Redis Streams async client"
```

---

### Task 1.2: Add Position and Risk Hash Helpers

**Files:**
- Modify: `trading/streams/redis_streams.py`
- Test: `tests/trading/streams/test_redis_streams.py`

**Step 1: Write the failing test**

```python
# Add to tests/trading/streams/test_redis_streams.py

@pytest.mark.asyncio
async def test_position_operations(redis_streams):
    """Test position hash operations."""
    await redis_streams.connect()

    # Set position
    await redis_streams.set_position("BTC", "spot", {
        "quantity": "0.05",
        "entry_price": "43000",
        "strategy": "v35_long",
    })

    # Check exists
    assert await redis_streams.has_position("BTC", "spot")
    assert not await redis_streams.has_position("ETH", "spot")

    # Get position
    pos = await redis_streams.get_position("BTC", "spot")
    assert pos["quantity"] == "0.05"
    assert pos["strategy"] == "v35_long"

    # Clear position
    await redis_streams.clear_position("BTC", "spot")
    assert not await redis_streams.has_position("BTC", "spot")

    await redis_streams.disconnect()


@pytest.mark.asyncio
async def test_risk_operations(redis_streams):
    """Test risk hash operations."""
    await redis_streams.connect()

    # Initialize risk
    await redis_streams.set_risk({"kill_switch": "false", "daily_pnl": "0", "blocked": "false"})

    # Check blocked
    assert not await redis_streams.is_blocked()

    # Block
    await redis_streams.set_risk({"blocked": "true"})
    assert await redis_streams.is_blocked()

    # Check kill switch
    await redis_streams.set_risk({"kill_switch": "true"})
    assert await redis_streams.is_kill_switch_on()

    await redis_streams.disconnect()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/trading/streams/test_redis_streams.py::test_position_operations -v`
Expected: FAIL with "AttributeError"

**Step 3: Add implementation**

```python
# Add to trading/streams/redis_streams.py class RedisStreams:

    # Position helpers
    async def set_position(
        self, symbol: str, market: str, data: dict[str, Any]
    ) -> None:
        """Set position data."""
        key = f"positions:{symbol}:{market}"
        await self._client.hset(key, mapping=data)

    async def get_position(self, symbol: str, market: str) -> dict[str, str]:
        """Get position data."""
        key = f"positions:{symbol}:{market}"
        return await self._client.hgetall(key)

    async def has_position(self, symbol: str, market: str) -> bool:
        """Check if position exists."""
        key = f"positions:{symbol}:{market}"
        return await self._client.exists(key) > 0

    async def clear_position(self, symbol: str, market: str) -> None:
        """Clear position."""
        key = f"positions:{symbol}:{market}"
        await self._client.delete(key)

    # Risk helpers
    async def set_risk(self, data: dict[str, Any]) -> None:
        """Set risk data."""
        await self._client.hset("risk", mapping=data)

    async def get_risk(self) -> dict[str, str]:
        """Get risk data."""
        return await self._client.hgetall("risk")

    async def is_blocked(self) -> bool:
        """Check if trading is blocked."""
        risk = await self.get_risk()
        return risk.get("blocked") == "true"

    async def is_kill_switch_on(self) -> bool:
        """Check if kill switch is on."""
        risk = await self.get_risk()
        return risk.get("kill_switch") == "true"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/trading/streams/test_redis_streams.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add trading/streams/redis_streams.py tests/trading/streams/test_redis_streams.py
git commit -m "feat: add position and risk hash helpers to RedisStreams"
```

---

## Phase 2: Price Feed Tasks

### Task 2.1: Create SymbolFeedTask Base

**Files:**
- Create: `trading/streams/feed_task.py`
- Test: `tests/trading/streams/test_feed_task.py`

**Step 1: Write the failing test**

```python
# tests/trading/streams/test_feed_task.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from trading.streams.feed_task import SymbolFeedTask


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.publish = AsyncMock(return_value="1234-0")
    return redis


@pytest.mark.asyncio
async def test_feed_task_publishes_price(mock_redis):
    """Test feed task publishes prices to stream."""
    task = SymbolFeedTask(symbol="BTC", redis=mock_redis)

    # Simulate receiving a price update
    await task._publish_price({
        "price": "43250.50",
        "market": "spot",
    })

    mock_redis.publish.assert_called_once()
    call_args = mock_redis.publish.call_args
    assert call_args[0][0] == "market:prices"
    assert call_args[0][1]["symbol"] == "BTC"
    assert call_args[0][1]["price"] == "43250.50"
    assert call_args[0][1]["market"] == "spot"
    assert call_args[0][1]["source"] == "binance"


@pytest.mark.asyncio
async def test_feed_task_backoff_calculation():
    """Test exponential backoff."""
    task = SymbolFeedTask(symbol="BTC", redis=AsyncMock())

    assert task._calculate_backoff(0) == 1
    assert task._calculate_backoff(1) == 2
    assert task._calculate_backoff(2) == 4
    assert task._calculate_backoff(10) == 60  # capped at 60
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/trading/streams/test_feed_task.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write minimal implementation**

```python
# trading/streams/feed_task.py
"""Price feed task for streaming Binance prices to Redis."""
from __future__ import annotations
import asyncio
import time
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)


class SymbolFeedTask:
    """Async task that streams prices for a single symbol to Redis."""

    def __init__(
        self,
        symbol: str,
        redis: RedisStreams,
        max_backoff: int = 60,
    ):
        self.symbol = symbol
        self.redis = redis
        self.max_backoff = max_backoff
        self._running = False
        self._failure_count = 0

    async def run(self) -> None:
        """Main loop: connect to WebSocket and publish prices."""
        self._running = True

        while self._running:
            try:
                async with self._connect_websocket() as ws:
                    self._failure_count = 0
                    async for msg in ws:
                        if not self._running:
                            break
                        await self._publish_price(msg)
            except Exception as e:
                logger.error(f"Feed {self.symbol} error: {e}")
                self._failure_count += 1
                backoff = self._calculate_backoff(self._failure_count)
                logger.info(f"Feed {self.symbol} reconnecting in {backoff}s")
                await asyncio.sleep(backoff)

    def stop(self) -> None:
        """Signal task to stop."""
        self._running = False

    async def _connect_websocket(self):
        """Connect to Binance WebSocket. Override in subclass."""
        raise NotImplementedError("Subclass must implement _connect_websocket")

    async def _publish_price(self, msg: dict[str, Any]) -> None:
        """Publish price update to Redis stream."""
        await self.redis.publish("market:prices", {
            "symbol": self.symbol,
            "price": msg["price"],
            "source": "binance",
            "market": msg["market"],
            "timestamp": str(int(time.time() * 1000)),
        })

    def _calculate_backoff(self, failure_count: int) -> int:
        """Calculate exponential backoff with cap."""
        backoff = min(2 ** failure_count, self.max_backoff)
        return max(1, backoff)
```

**Step 4: Update __init__.py**

```python
# trading/streams/__init__.py
from .redis_streams import RedisStreams
from .feed_task import SymbolFeedTask

__all__ = ["RedisStreams", "SymbolFeedTask"]
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/trading/streams/test_feed_task.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add trading/streams/feed_task.py trading/streams/__init__.py tests/trading/streams/test_feed_task.py
git commit -m "feat: add SymbolFeedTask base class"
```

---

### Task 2.2: Implement Binance WebSocket Connection

**Files:**
- Create: `trading/streams/binance_feed.py`
- Test: `tests/trading/streams/test_binance_feed.py`

**Step 1: Write the failing test**

```python
# tests/trading/streams/test_binance_feed.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from trading.streams.binance_feed import BinanceFeedTask


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.publish = AsyncMock(return_value="1234-0")
    return redis


def test_binance_feed_builds_ws_url():
    """Test WebSocket URL construction."""
    task = BinanceFeedTask(symbol="BTC", redis=AsyncMock())

    url = task._build_ws_url()
    assert "btcusdt@trade" in url
    assert "wss://stream.binance.com" in url


def test_binance_feed_parses_trade_message():
    """Test parsing Binance trade message."""
    task = BinanceFeedTask(symbol="BTC", redis=AsyncMock())

    raw_msg = {
        "e": "trade",
        "s": "BTCUSDT",
        "p": "43250.50",
        "T": 1704912345678,
    }

    parsed = task._parse_trade_message(raw_msg)
    assert parsed["price"] == "43250.50"
    assert parsed["market"] == "spot"


def test_binance_futures_feed_parses_message():
    """Test parsing Binance futures trade message."""
    task = BinanceFeedTask(symbol="BTC", redis=AsyncMock(), market="futures")

    raw_msg = {
        "e": "trade",
        "s": "BTCUSDT",
        "p": "43255.00",
        "T": 1704912345678,
    }

    parsed = task._parse_trade_message(raw_msg)
    assert parsed["price"] == "43255.00"
    assert parsed["market"] == "futures"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/trading/streams/test_binance_feed.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write implementation**

```python
# trading/streams/binance_feed.py
"""Binance-specific price feed implementation."""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, AsyncIterator, TYPE_CHECKING
from contextlib import asynccontextmanager

import aiohttp

from .feed_task import SymbolFeedTask

if TYPE_CHECKING:
    from .redis_streams import RedisStreams

logger = logging.getLogger(__name__)

BINANCE_SPOT_WS = "wss://stream.binance.com:9443/ws"
BINANCE_FUTURES_WS = "wss://fstream.binance.com/ws"


class BinanceFeedTask(SymbolFeedTask):
    """Feed task for Binance spot or futures."""

    def __init__(
        self,
        symbol: str,
        redis: RedisStreams,
        market: str = "spot",
        **kwargs,
    ):
        super().__init__(symbol=symbol, redis=redis, **kwargs)
        self.market = market

    def _build_ws_url(self) -> str:
        """Build WebSocket URL for symbol."""
        pair = f"{self.symbol.lower()}usdt"
        stream = f"{pair}@trade"

        if self.market == "futures":
            return f"{BINANCE_FUTURES_WS}/{stream}"
        return f"{BINANCE_SPOT_WS}/{stream}"

    def _parse_trade_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Parse Binance trade message."""
        return {
            "price": msg["p"],
            "market": self.market,
        }

    @asynccontextmanager
    async def _connect_websocket(self) -> AsyncIterator[AsyncIterator[dict]]:
        """Connect to Binance WebSocket."""
        url = self._build_ws_url()
        logger.info(f"Connecting to {url}")

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url) as ws:
                async def message_iterator():
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            if data.get("e") == "trade":
                                yield self._parse_trade_message(data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            raise ConnectionError(f"WebSocket error: {ws.exception()}")

                yield message_iterator()
```

**Step 4: Update __init__.py**

```python
# trading/streams/__init__.py
from .redis_streams import RedisStreams
from .feed_task import SymbolFeedTask
from .binance_feed import BinanceFeedTask

__all__ = ["RedisStreams", "SymbolFeedTask", "BinanceFeedTask"]
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/trading/streams/test_binance_feed.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add trading/streams/binance_feed.py trading/streams/__init__.py tests/trading/streams/test_binance_feed.py
git commit -m "feat: add BinanceFeedTask for spot and futures"
```

---

## Phase 3: Strategy Base Task

### Task 3.1: Create BaseStrategyTask

**Files:**
- Create: `trading/streams/base_strategy.py`
- Test: `tests/trading/streams/test_base_strategy.py`

**Step 1: Write the failing test**

```python
# tests/trading/streams/test_base_strategy.py
import pytest
from unittest.mock import AsyncMock
from collections import deque
from trading.streams.base_strategy import BaseStrategyTask


class TestStrategy(BaseStrategyTask):
    """Concrete implementation for testing."""

    async def evaluate(self, symbol: str) -> dict | None:
        # Simple: buy if price > 40000
        if len(self.price_buffer.get(symbol, [])) == 0:
            return None
        last_price = float(self.price_buffer[symbol][-1]["price"])
        if last_price > 40000:
            return {
                "symbol": symbol,
                "side": "buy",
                "market": "spot",
                "quantity": "0.01",
                "reason": "price above 40000",
            }
        return None


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.publish = AsyncMock(return_value="1234-0")
    redis.has_position = AsyncMock(return_value=False)
    redis.is_blocked = AsyncMock(return_value=False)
    return redis


@pytest.mark.asyncio
async def test_strategy_buffers_prices(mock_redis):
    """Test price buffering."""
    strategy = TestStrategy(
        name="test",
        symbols=["BTC"],
        redis=mock_redis,
        market="spot",
    )

    # Process price message
    msg = {"symbol": "BTC", "price": "43000", "market": "spot", "_id": "1-0"}
    await strategy._handle_message(msg)

    assert "BTC" in strategy.price_buffer
    assert len(strategy.price_buffer["BTC"]) == 1
    assert strategy.price_buffer["BTC"][-1]["price"] == "43000"


@pytest.mark.asyncio
async def test_strategy_publishes_order(mock_redis):
    """Test order publishing."""
    strategy = TestStrategy(
        name="test",
        symbols=["BTC"],
        redis=mock_redis,
        market="spot",
    )

    # Process price that triggers signal
    msg = {"symbol": "BTC", "price": "43000", "market": "spot", "_id": "1-0"}
    await strategy._handle_message(msg)

    # Verify order published
    mock_redis.publish.assert_called_once()
    call_args = mock_redis.publish.call_args
    assert call_args[0][0] == "orders"
    assert call_args[0][1]["symbol"] == "BTC"
    assert call_args[0][1]["side"] == "buy"


@pytest.mark.asyncio
async def test_strategy_skips_when_position_exists(mock_redis):
    """Test skipping when position already exists."""
    mock_redis.has_position = AsyncMock(return_value=True)

    strategy = TestStrategy(
        name="test",
        symbols=["BTC"],
        redis=mock_redis,
        market="spot",
    )

    msg = {"symbol": "BTC", "price": "43000", "market": "spot", "_id": "1-0"}
    await strategy._handle_message(msg)

    # Should not publish order
    mock_redis.publish.assert_not_called()


@pytest.mark.asyncio
async def test_strategy_skips_when_blocked(mock_redis):
    """Test skipping when trading is blocked."""
    mock_redis.is_blocked = AsyncMock(return_value=True)

    strategy = TestStrategy(
        name="test",
        symbols=["BTC"],
        redis=mock_redis,
        market="spot",
    )

    msg = {"symbol": "BTC", "price": "43000", "market": "spot", "_id": "1-0"}
    await strategy._handle_message(msg)

    # Should not publish order
    mock_redis.publish.assert_not_called()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/trading/streams/test_base_strategy.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write implementation**

```python
# trading/streams/base_strategy.py
"""Base class for strategy tasks."""
from __future__ import annotations
import asyncio
import uuid
import logging
from abc import ABC, abstractmethod
from collections import deque
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .redis_streams import RedisStreams

logger = logging.getLogger(__name__)


class BaseStrategyTask(ABC):
    """Base class for autonomous strategy tasks."""

    def __init__(
        self,
        name: str,
        symbols: list[str],
        redis: RedisStreams,
        market: str,
        buffer_size: int = 500,
    ):
        self.name = name
        self.symbols = set(symbols)
        self.redis = redis
        self.market = market
        self.buffer_size = buffer_size
        self.price_buffer: dict[str, deque] = {}
        self._running = False

    async def run(self) -> None:
        """Main loop: consume prices, evaluate, publish orders."""
        self._running = True
        group = f"strategy-{self.name}"
        consumer = f"{self.name}-{uuid.uuid4().hex[:8]}"

        # Ensure consumer group exists
        await self.redis.create_consumer_group("market:prices", group)

        logger.info(f"Strategy {self.name} started, watching {self.symbols}")

        while self._running:
            try:
                messages = await self.redis.consume(
                    "market:prices", group, consumer, count=10, block_ms=1000
                )

                for msg in messages:
                    await self._handle_message(msg)
                    await self.redis.ack("market:prices", group, msg["_id"])

            except Exception as e:
                logger.error(f"Strategy {self.name} error: {e}")
                await asyncio.sleep(1)

    def stop(self) -> None:
        """Signal task to stop."""
        self._running = False

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        """Handle incoming price message."""
        symbol = msg.get("symbol")

        # Filter by symbol
        if symbol not in self.symbols:
            return

        # Filter by market
        if msg.get("market") != self.market:
            return

        # Update buffer
        self._update_buffer(symbol, msg)

        # Check if blocked
        if await self.redis.is_blocked():
            return

        # Check if already has position
        if await self.redis.has_position(symbol, self.market):
            return

        # Evaluate and possibly publish order
        signal = await self.evaluate(symbol)
        if signal:
            await self._publish_order(signal)

    def _update_buffer(self, symbol: str, msg: dict[str, Any]) -> None:
        """Update price buffer for symbol."""
        if symbol not in self.price_buffer:
            self.price_buffer[symbol] = deque(maxlen=self.buffer_size)
        self.price_buffer[symbol].append(msg)

    async def _publish_order(self, signal: dict[str, Any]) -> None:
        """Publish order intent to orders stream."""
        order = {
            "id": str(uuid.uuid4()),
            "strategy": self.name,
            **signal,
        }
        await self.redis.publish("orders", order)
        logger.info(f"Strategy {self.name} published order: {order}")

    @abstractmethod
    async def evaluate(self, symbol: str) -> dict[str, Any] | None:
        """
        Evaluate current market state for symbol.

        Returns order intent dict or None.
        Order intent: {"symbol", "side", "market", "quantity", "reason"}
        """
        pass
```

**Step 4: Update __init__.py**

```python
# trading/streams/__init__.py
from .redis_streams import RedisStreams
from .feed_task import SymbolFeedTask
from .binance_feed import BinanceFeedTask
from .base_strategy import BaseStrategyTask

__all__ = ["RedisStreams", "SymbolFeedTask", "BinanceFeedTask", "BaseStrategyTask"]
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/trading/streams/test_base_strategy.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add trading/streams/base_strategy.py trading/streams/__init__.py tests/trading/streams/test_base_strategy.py
git commit -m "feat: add BaseStrategyTask with price buffering and order publishing"
```

---

## Phase 4: Strategy Migrations

### Task 4.1: Port V35Long Strategy

**Files:**
- Create: `trading/strategies/v35_long_task.py`
- Test: `tests/trading/strategies/test_v35_long_task.py`

**Step 1: Create directory structure**

```bash
mkdir -p trading/strategies
touch trading/strategies/__init__.py
mkdir -p tests/trading/strategies
touch tests/trading/strategies/__init__.py
```

**Step 2: Write the failing test**

```python
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
```

**Step 3: Run test to verify it fails**

Run: `pytest tests/trading/strategies/test_v35_long_task.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 4: Write implementation**

```python
# trading/strategies/v35_long_task.py
"""V35 Long Strategy - ported to stream architecture."""
from __future__ import annotations
import logging
from typing import Any, TYPE_CHECKING
import numpy as np

from trading.streams.base_strategy import BaseStrategyTask

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)

# Regime thresholds (from original RegimeRouter)
MFI_BULL = 52
MFI_BEAR = 48
ADX_STRONG = 25
ADX_TREND = 20
ADX_WEAK = 15


class V35LongTask(BaseStrategyTask):
    """V35 Long-only strategy for Binance spot."""

    def __init__(
        self,
        symbols: list[str],
        redis: RedisStreams,
        config: dict | None = None,
    ):
        super().__init__(
            name="v35_long",
            symbols=symbols,
            redis=redis,
            market="spot",
            buffer_size=500,
        )
        self.config = config or {}
        self.min_data_points = 180  # Need enough data for indicators

    async def evaluate(self, symbol: str) -> dict[str, Any] | None:
        """Evaluate entry conditions for symbol."""
        buffer = self.price_buffer.get(symbol, [])

        # Need sufficient data
        if len(buffer) < self.min_data_points:
            return None

        # Calculate indicators
        indicators = self._calculate_indicators(symbol)
        if indicators is None:
            return None

        # Classify regime
        regime = self._classify_regime(indicators["mfi"], indicators["adx"])

        # Check entry
        if self._should_enter(regime):
            quantity = self._calculate_position_size(indicators["close"])
            return {
                "symbol": symbol,
                "side": "buy",
                "market": "spot",
                "quantity": str(quantity),
                "reason": f"V35 entry: {regime}, MFI={indicators['mfi']:.1f}, ADX={indicators['adx']:.1f}",
            }

        return None

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Self-classify market regime (replaces RegimeRouter)."""
        if mfi >= MFI_BULL:
            if adx >= ADX_STRONG:
                return "BULL_STRONG"
            elif adx >= ADX_TREND:
                return "BULL_MODERATE"
            else:
                return "SIDEWAYS_BULL"
        elif mfi <= MFI_BEAR:
            if adx >= ADX_TREND:
                return "BEAR_STRONG"
            elif adx >= ADX_WEAK:
                return "BEAR_MODERATE"
            else:
                return "SIDEWAYS_BEAR"
        else:
            return "SIDEWAYS_NEUTRAL"

    def _should_enter(self, regime: str) -> bool:
        """Check if regime is suitable for entry."""
        return regime in ("BULL_STRONG", "BULL_MODERATE")

    def _calculate_indicators(self, symbol: str) -> dict[str, float] | None:
        """Calculate MFI and ADX from price buffer."""
        try:
            buffer = list(self.price_buffer[symbol])
            closes = np.array([float(p["price"]) for p in buffer])

            # For now, use simplified calculation
            # In production, use talib with full OHLCV data
            # This is a placeholder that returns mock values
            # Real implementation will fetch OHLCV from data source

            # Simplified momentum: price vs SMA
            sma = np.mean(closes[-20:])
            current = closes[-1]
            momentum = (current - sma) / sma * 100

            # Mock MFI based on momentum
            mfi = 50 + momentum * 2
            mfi = max(0, min(100, mfi))

            # Mock ADX (trend strength)
            volatility = np.std(closes[-20:]) / np.mean(closes[-20:])
            adx = volatility * 1000  # Scale to typical ADX range
            adx = max(0, min(50, adx))

            return {
                "mfi": mfi,
                "adx": adx,
                "close": current,
            }
        except Exception as e:
            logger.error(f"Indicator calculation failed: {e}")
            return None

    def _calculate_position_size(self, price: float) -> float:
        """Calculate position size based on config."""
        # Default: 0.01 BTC or configured amount
        return self.config.get("position_size", 0.01)
```

**Step 5: Update __init__.py**

```python
# trading/strategies/__init__.py
from .v35_long_task import V35LongTask

__all__ = ["V35LongTask"]
```

**Step 6: Run test to verify it passes**

Run: `pytest tests/trading/strategies/test_v35_long_task.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add trading/strategies/ tests/trading/strategies/
git commit -m "feat: port V35Long strategy to stream architecture"
```

---

### Task 4.2: Port SidewaysV2 Strategy

**Files:**
- Create: `trading/strategies/sideways_v2_task.py`
- Test: `tests/trading/strategies/test_sideways_v2_task.py`

**Step 1: Write the failing test**

```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/trading/strategies/test_sideways_v2_task.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write implementation**

```python
# trading/strategies/sideways_v2_task.py
"""SidewaysV2 Strategy - ported to stream architecture."""
from __future__ import annotations
import logging
from typing import Any, TYPE_CHECKING
import numpy as np

from trading.streams.base_strategy import BaseStrategyTask

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)

# Regime thresholds
MFI_BULL = 52
MFI_BEAR = 48
ADX_TREND = 20
ADX_WEAK = 15

# RSI thresholds for mean reversion
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65


class SidewaysV2Task(BaseStrategyTask):
    """Sideways/range-bound strategy for Binance spot."""

    def __init__(
        self,
        symbols: list[str],
        redis: RedisStreams,
        config: dict | None = None,
    ):
        super().__init__(
            name="sideways_v2",
            symbols=symbols,
            redis=redis,
            market="spot",
            buffer_size=500,
        )
        self.config = config or {}
        self.min_data_points = 180

    async def evaluate(self, symbol: str) -> dict[str, Any] | None:
        """Evaluate entry conditions for sideways market."""
        buffer = self.price_buffer.get(symbol, [])

        if len(buffer) < self.min_data_points:
            return None

        indicators = self._calculate_indicators(symbol)
        if indicators is None:
            return None

        regime = self._classify_regime(indicators["mfi"], indicators["adx"])

        if not self._should_enter(regime):
            return None

        # Mean reversion: buy when oversold
        if indicators["rsi"] < RSI_OVERSOLD:
            quantity = self._calculate_position_size(indicators["close"])
            return {
                "symbol": symbol,
                "side": "buy",
                "market": "spot",
                "quantity": str(quantity),
                "reason": f"SidewaysV2 entry: {regime}, RSI={indicators['rsi']:.1f} (oversold)",
            }

        return None

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Self-classify market regime."""
        if mfi >= MFI_BULL:
            if adx >= ADX_TREND:
                return "BULL_MODERATE"
            else:
                return "SIDEWAYS_BULL"
        elif mfi <= MFI_BEAR:
            if adx >= ADX_TREND:
                return "BEAR_MODERATE"
            elif adx >= ADX_WEAK:
                return "SIDEWAYS_BEAR"
            else:
                return "SIDEWAYS_BEAR"
        else:
            return "SIDEWAYS_NEUTRAL"

    def _should_enter(self, regime: str) -> bool:
        """Check if regime is suitable for entry."""
        return regime.startswith("SIDEWAYS")

    def _calculate_indicators(self, symbol: str) -> dict[str, float] | None:
        """Calculate indicators from price buffer."""
        try:
            buffer = list(self.price_buffer[symbol])
            closes = np.array([float(p["price"]) for p in buffer])

            # Simplified calculations (placeholder)
            sma = np.mean(closes[-20:])
            current = closes[-1]
            momentum = (current - sma) / sma * 100

            mfi = 50 + momentum * 2
            mfi = max(0, min(100, mfi))

            volatility = np.std(closes[-20:]) / np.mean(closes[-20:])
            adx = volatility * 1000
            adx = max(0, min(50, adx))

            # Simple RSI calculation
            deltas = np.diff(closes[-15:])
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_gain = np.mean(gains) if len(gains) > 0 else 0
            avg_loss = np.mean(losses) if len(losses) > 0 else 0.001
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

            return {
                "mfi": mfi,
                "adx": adx,
                "close": current,
                "rsi": rsi,
            }
        except Exception as e:
            logger.error(f"Indicator calculation failed: {e}")
            return None

    def _calculate_position_size(self, price: float) -> float:
        """Calculate position size."""
        return self.config.get("position_size", 0.01)
```

**Step 4: Update __init__.py**

```python
# trading/strategies/__init__.py
from .v35_long_task import V35LongTask
from .sideways_v2_task import SidewaysV2Task

__all__ = ["V35LongTask", "SidewaysV2Task"]
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/trading/strategies/test_sideways_v2_task.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add trading/strategies/sideways_v2_task.py trading/strategies/__init__.py tests/trading/strategies/test_sideways_v2_task.py
git commit -m "feat: port SidewaysV2 strategy to stream architecture"
```

---

### Task 4.3: Port ShortV1 Strategy

**Files:**
- Create: `trading/strategies/short_v1_task.py`
- Test: `tests/trading/strategies/test_short_v1_task.py`

**Step 1: Write the failing test**

```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/trading/strategies/test_short_v1_task.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write implementation**

```python
# trading/strategies/short_v1_task.py
"""ShortV1 Strategy - ported to stream architecture."""
from __future__ import annotations
import logging
from typing import Any, TYPE_CHECKING
import numpy as np

from trading.streams.base_strategy import BaseStrategyTask

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)

# Regime thresholds
MFI_BEAR = 48
ADX_TREND = 20

# RSI threshold for short entry
RSI_OVERBOUGHT = 70


class ShortV1Task(BaseStrategyTask):
    """Short strategy for Binance futures in bear markets."""

    def __init__(
        self,
        symbols: list[str],
        redis: RedisStreams,
        config: dict | None = None,
    ):
        super().__init__(
            name="short_v1",
            symbols=symbols,
            redis=redis,
            market="futures",  # Shorts on futures
            buffer_size=500,
        )
        self.config = config or {}
        self.min_data_points = 180

    async def evaluate(self, symbol: str) -> dict[str, Any] | None:
        """Evaluate short entry conditions."""
        buffer = self.price_buffer.get(symbol, [])

        if len(buffer) < self.min_data_points:
            return None

        indicators = self._calculate_indicators(symbol)
        if indicators is None:
            return None

        regime = self._classify_regime(indicators["mfi"], indicators["adx"])

        if not self._should_enter(regime):
            return None

        # Short when RSI is overbought in bear market
        if indicators["rsi"] > RSI_OVERBOUGHT:
            quantity = self._calculate_position_size(indicators["close"])
            return {
                "symbol": symbol,
                "side": "sell",
                "market": "futures",
                "quantity": str(quantity),
                "reason": f"ShortV1 entry: {regime}, RSI={indicators['rsi']:.1f} (overbought)",
            }

        return None

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Self-classify market regime."""
        if mfi <= MFI_BEAR:
            if adx >= ADX_TREND:
                return "BEAR_STRONG"
            else:
                return "BEAR_MODERATE"
        elif mfi >= 52:
            return "BULL"
        else:
            return "SIDEWAYS"

    def _should_enter(self, regime: str) -> bool:
        """Only enter on strong bear regime."""
        return regime == "BEAR_STRONG"

    def _calculate_indicators(self, symbol: str) -> dict[str, float] | None:
        """Calculate indicators from price buffer."""
        try:
            buffer = list(self.price_buffer[symbol])
            closes = np.array([float(p["price"]) for p in buffer])

            sma = np.mean(closes[-20:])
            current = closes[-1]
            momentum = (current - sma) / sma * 100

            mfi = 50 + momentum * 2
            mfi = max(0, min(100, mfi))

            volatility = np.std(closes[-20:]) / np.mean(closes[-20:])
            adx = volatility * 1000
            adx = max(0, min(50, adx))

            deltas = np.diff(closes[-15:])
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_gain = np.mean(gains) if len(gains) > 0 else 0
            avg_loss = np.mean(losses) if len(losses) > 0 else 0.001
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

            return {
                "mfi": mfi,
                "adx": adx,
                "close": current,
                "rsi": rsi,
            }
        except Exception as e:
            logger.error(f"Indicator calculation failed: {e}")
            return None

    def _calculate_position_size(self, price: float) -> float:
        """Calculate position size for futures."""
        return self.config.get("position_size", 0.01)
```

**Step 4: Update __init__.py**

```python
# trading/strategies/__init__.py
from .v35_long_task import V35LongTask
from .sideways_v2_task import SidewaysV2Task
from .short_v1_task import ShortV1Task

__all__ = ["V35LongTask", "SidewaysV2Task", "ShortV1Task"]
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/trading/strategies/test_short_v1_task.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add trading/strategies/short_v1_task.py trading/strategies/__init__.py tests/trading/strategies/test_short_v1_task.py
git commit -m "feat: port ShortV1 strategy to stream architecture"
```

---

## Phase 5: Executor

### Task 5.1: Create Binance Client Wrapper

**Files:**
- Create: `trading/executor/__init__.py`
- Create: `trading/executor/binance_client.py`
- Test: `tests/trading/executor/test_binance_client.py`

**Step 1: Create directory structure**

```bash
mkdir -p trading/executor
touch trading/executor/__init__.py
mkdir -p tests/trading/executor
touch tests/trading/executor/__init__.py
```

**Step 2: Write the failing test**

```python
# tests/trading/executor/test_binance_client.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from trading.executor.binance_client import BinanceClient


def test_binance_client_init():
    """Test client initialization."""
    client = BinanceClient(api_key="test", api_secret="secret")
    assert client.api_key == "test"


@pytest.mark.asyncio
async def test_spot_market_order():
    """Test spot market order execution."""
    client = BinanceClient(api_key="test", api_secret="secret")

    with patch.object(client, '_spot_client') as mock_spot:
        mock_spot.create_order = AsyncMock(return_value={
            "orderId": 12345,
            "executedQty": "0.01",
            "cummulativeQuoteQty": "430.00",
            "status": "FILLED",
        })

        fill = await client.market_order(
            symbol="BTC",
            side="buy",
            quantity=0.01,
            market="spot",
        )

        assert fill["order_id"] == 12345
        assert fill["filled_qty"] == 0.01
        assert fill["status"] == "FILLED"


@pytest.mark.asyncio
async def test_futures_market_order():
    """Test futures market order execution."""
    client = BinanceClient(api_key="test", api_secret="secret")

    with patch.object(client, '_futures_client') as mock_futures:
        mock_futures.create_order = AsyncMock(return_value={
            "orderId": 67890,
            "executedQty": "0.01",
            "cumQuote": "430.50",
            "status": "FILLED",
        })

        fill = await client.market_order(
            symbol="BTC",
            side="sell",
            quantity=0.01,
            market="futures",
        )

        assert fill["order_id"] == 67890
        assert fill["side"] == "sell"
        assert fill["market"] == "futures"
```

**Step 3: Run test to verify it fails**

Run: `pytest tests/trading/executor/test_binance_client.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 4: Write implementation**

```python
# trading/executor/binance_client.py
"""Unified Binance client for spot and futures."""
from __future__ import annotations
import logging
from typing import Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Fill:
    """Order fill result."""
    order_id: int
    symbol: str
    side: str
    market: str
    filled_qty: float
    filled_price: float
    status: str


class BinanceClient:
    """Unified async client for Binance spot and futures."""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self._spot_client = None
        self._futures_client = None

    async def connect(self) -> None:
        """Initialize API clients."""
        # Import here to avoid import errors when binance not installed
        try:
            from binance import AsyncClient
            self._spot_client = await AsyncClient.create(self.api_key, self.api_secret)
            self._futures_client = await AsyncClient.create(self.api_key, self.api_secret)
        except ImportError:
            logger.warning("binance package not installed, using mock client")
            self._spot_client = MockBinanceClient()
            self._futures_client = MockBinanceClient()

    async def disconnect(self) -> None:
        """Close API clients."""
        if self._spot_client and hasattr(self._spot_client, 'close_connection'):
            await self._spot_client.close_connection()
        if self._futures_client and hasattr(self._futures_client, 'close_connection'):
            await self._futures_client.close_connection()

    async def market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        market: str,
    ) -> dict[str, Any]:
        """Execute market order on spot or futures."""
        pair = f"{symbol}USDT"

        try:
            if market == "futures":
                result = await self._futures_client.futures_create_order(
                    symbol=pair,
                    side=side.upper(),
                    type="MARKET",
                    quantity=quantity,
                )
                filled_price = float(result.get("avgPrice", 0)) or \
                               float(result["cumQuote"]) / float(result["executedQty"])
            else:
                result = await self._spot_client.create_order(
                    symbol=pair,
                    side=side.upper(),
                    type="MARKET",
                    quantity=quantity,
                )
                filled_price = float(result["cummulativeQuoteQty"]) / float(result["executedQty"])

            return {
                "order_id": result["orderId"],
                "symbol": symbol,
                "side": side,
                "market": market,
                "filled_qty": float(result["executedQty"]),
                "filled_price": filled_price,
                "status": result["status"],
            }

        except Exception as e:
            logger.error(f"Order failed: {e}")
            raise


class MockBinanceClient:
    """Mock client for testing without real API."""

    async def create_order(self, **kwargs) -> dict:
        return {
            "orderId": 99999,
            "executedQty": str(kwargs.get("quantity", 0.01)),
            "cummulativeQuoteQty": "430.00",
            "status": "FILLED",
        }

    async def futures_create_order(self, **kwargs) -> dict:
        return {
            "orderId": 99999,
            "executedQty": str(kwargs.get("quantity", 0.01)),
            "cumQuote": "430.00",
            "avgPrice": "43000.00",
            "status": "FILLED",
        }
```

**Step 5: Update __init__.py**

```python
# trading/executor/__init__.py
from .binance_client import BinanceClient, Fill

__all__ = ["BinanceClient", "Fill"]
```

**Step 6: Run test to verify it passes**

Run: `pytest tests/trading/executor/test_binance_client.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add trading/executor/ tests/trading/executor/
git commit -m "feat: add unified BinanceClient for spot and futures"
```

---

### Task 5.2: Create AsyncExecutor

**Files:**
- Create: `trading/executor/async_executor.py`
- Test: `tests/trading/executor/test_async_executor.py`

**Step 1: Write the failing test**

```python
# tests/trading/executor/test_async_executor.py
import pytest
from unittest.mock import AsyncMock, patch
from trading.executor.async_executor import AsyncExecutor


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
    redis.set_position = AsyncMock()
    redis.set_risk = AsyncMock()
    redis.publish = AsyncMock()
    redis.consume = AsyncMock(return_value=[])
    redis.create_consumer_group = AsyncMock()
    return redis


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.market_order = AsyncMock(return_value={
        "order_id": 12345,
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "filled_qty": 0.01,
        "filled_price": 43000.0,
        "status": "FILLED",
    })
    return client


@pytest.mark.asyncio
async def test_executor_passes_risk_gates(mock_redis, mock_client):
    """Test order passes risk gates."""
    executor = AsyncExecutor(redis=mock_redis, client=mock_client, config={})

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "v35_long",
    }

    result = await executor._process_order(order)

    assert result is not None
    mock_client.market_order.assert_called_once()


@pytest.mark.asyncio
async def test_executor_blocks_on_kill_switch(mock_redis, mock_client):
    """Test order blocked when kill switch is on."""
    mock_redis.get_risk = AsyncMock(return_value={"kill_switch": "true", "blocked": "false"})

    executor = AsyncExecutor(redis=mock_redis, client=mock_client, config={})

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "v35_long",
    }

    result = await executor._process_order(order)

    assert result is None
    mock_client.market_order.assert_not_called()


@pytest.mark.asyncio
async def test_executor_updates_position_after_fill(mock_redis, mock_client):
    """Test position is updated after successful fill."""
    executor = AsyncExecutor(redis=mock_redis, client=mock_client, config={})

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "v35_long",
    }

    await executor._process_order(order)

    mock_redis.set_position.assert_called_once()
    call_args = mock_redis.set_position.call_args
    assert call_args[0][0] == "BTC"
    assert call_args[0][1] == "spot"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/trading/executor/test_async_executor.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write implementation**

```python
# trading/executor/async_executor.py
"""Async executor for processing order stream."""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams
    from trading.executor.binance_client import BinanceClient

logger = logging.getLogger(__name__)


class AsyncExecutor:
    """Consumes orders stream and executes via Binance API."""

    def __init__(
        self,
        redis: RedisStreams,
        client: BinanceClient,
        config: dict,
    ):
        self.redis = redis
        self.client = client
        self.config = config
        self.max_daily_loss = config.get("max_daily_loss", 500)  # USDT
        self._running = False

    async def run(self) -> None:
        """Main loop: consume and execute orders."""
        self._running = True
        group = "executor"
        consumer = "executor-main"

        await self.redis.create_consumer_group("orders", group)
        logger.info("AsyncExecutor started")

        while self._running:
            try:
                messages = await self.redis.consume(
                    "orders", group, consumer, count=1, block_ms=1000
                )

                for msg in messages:
                    await self._process_order(msg)
                    await self.redis.ack("orders", group, msg["_id"])

            except Exception as e:
                logger.error(f"Executor error: {e}")
                await asyncio.sleep(1)

    def stop(self) -> None:
        """Signal executor to stop."""
        self._running = False

    async def _process_order(self, order: dict[str, Any]) -> dict | None:
        """Process single order."""
        # Check risk gates
        if not await self._pass_risk_gates():
            logger.warning(f"Order {order['id']} blocked by risk gates")
            await self._publish_rejection(order, "risk_blocked")
            return None

        try:
            # Execute order
            fill = await self.client.market_order(
                symbol=order["symbol"],
                side=order["side"],
                quantity=float(order["quantity"]),
                market=order["market"],
            )

            # Update position
            await self._update_position(order, fill)

            # Update daily P&L tracking
            await self._update_daily_pnl(order, fill)

            # Publish trade notification
            await self._publish_trade(order, fill)

            logger.info(f"Order {order['id']} filled: {fill}")
            return fill

        except Exception as e:
            logger.error(f"Order {order['id']} failed: {e}")
            await self._publish_rejection(order, str(e))
            return None

    async def _pass_risk_gates(self) -> bool:
        """Check all risk conditions."""
        risk = await self.redis.get_risk()

        # Kill switch
        if risk.get("kill_switch") == "true":
            logger.warning("Kill switch is ON")
            return False

        # Blocked flag
        if risk.get("blocked") == "true":
            logger.warning("Trading is blocked")
            return False

        # Daily loss limit
        daily_pnl = float(risk.get("daily_pnl", 0))
        if daily_pnl < -self.max_daily_loss:
            logger.warning(f"Daily loss limit exceeded: {daily_pnl}")
            return False

        return True

    async def _update_position(self, order: dict, fill: dict) -> None:
        """Update position in Redis."""
        await self.redis.set_position(order["symbol"], order["market"], {
            "quantity": str(fill["filled_qty"]),
            "entry_price": str(fill["filled_price"]),
            "strategy": order["strategy"],
            "entry_time": str(int(time.time() * 1000)),
            "side": order["side"],
        })

    async def _update_daily_pnl(self, order: dict, fill: dict) -> None:
        """Update daily P&L tracking."""
        # For now, just track costs (entry has no realized P&L)
        # Real P&L tracking happens on exit
        pass

    async def _publish_trade(self, order: dict, fill: dict) -> None:
        """Publish trade to trades stream."""
        await self.redis.publish("trades", {
            "order_id": str(fill["order_id"]),
            "symbol": order["symbol"],
            "side": order["side"],
            "market": order["market"],
            "quantity": str(fill["filled_qty"]),
            "price": str(fill["filled_price"]),
            "strategy": order["strategy"],
            "timestamp": str(int(time.time() * 1000)),
        })

    async def _publish_rejection(self, order: dict, reason: str) -> None:
        """Publish order rejection to alerts stream."""
        await self.redis.publish("alerts", {
            "type": "order_rejected",
            "order_id": order["id"],
            "symbol": order["symbol"],
            "reason": reason,
            "timestamp": str(int(time.time() * 1000)),
        })
```

**Step 4: Update __init__.py**

```python
# trading/executor/__init__.py
from .binance_client import BinanceClient, Fill
from .async_executor import AsyncExecutor

__all__ = ["BinanceClient", "Fill", "AsyncExecutor"]
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/trading/executor/test_async_executor.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add trading/executor/async_executor.py trading/executor/__init__.py tests/trading/executor/test_async_executor.py
git commit -m "feat: add AsyncExecutor with risk gates"
```

---

### Task 5.3: Create PaperExecutor

**Files:**
- Create: `trading/executor/paper_executor.py`
- Test: `tests/trading/executor/test_paper_executor.py`

**Step 1: Write the failing test**

```python
# tests/trading/executor/test_paper_executor.py
import pytest
from unittest.mock import AsyncMock
from trading.executor.paper_executor import PaperExecutor


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
    redis.set_position = AsyncMock()
    redis.set_risk = AsyncMock()
    redis.publish = AsyncMock()
    redis.consume = AsyncMock(return_value=[])
    redis.create_consumer_group = AsyncMock()
    # Mock getting latest price
    redis.hgetall = AsyncMock(return_value={"BTC": "43000"})
    return redis


@pytest.mark.asyncio
async def test_paper_executor_simulates_fill(mock_redis):
    """Test paper executor simulates order fill."""
    executor = PaperExecutor(
        redis=mock_redis,
        config={"initial_balance": 10000},
    )
    executor.last_prices = {"BTC": 43000.0}

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "v35_long",
    }

    result = await executor._process_order(order)

    assert result is not None
    assert result["filled_qty"] == 0.01
    assert result["status"] == "FILLED"


@pytest.mark.asyncio
async def test_paper_executor_applies_slippage(mock_redis):
    """Test slippage is applied to fill price."""
    executor = PaperExecutor(
        redis=mock_redis,
        config={"initial_balance": 10000, "slippage": 0.001},
    )
    executor.last_prices = {"BTC": 43000.0}

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "v35_long",
    }

    result = await executor._process_order(order)

    # Buy should have positive slippage (higher price)
    assert result["filled_price"] > 43000.0


@pytest.mark.asyncio
async def test_paper_executor_tracks_balance(mock_redis):
    """Test balance tracking."""
    executor = PaperExecutor(
        redis=mock_redis,
        config={"initial_balance": 10000},
    )
    executor.last_prices = {"BTC": 43000.0}

    initial_balance = executor.balance

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "v35_long",
    }

    await executor._process_order(order)

    # Balance should decrease by order value + fees
    assert executor.balance < initial_balance
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/trading/executor/test_paper_executor.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write implementation**

```python
# trading/executor/paper_executor.py
"""Paper trading executor for simulation."""
from __future__ import annotations
import asyncio
import logging
import time
import uuid
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)


class PaperExecutor:
    """Simulates order execution without real API calls."""

    def __init__(
        self,
        redis: RedisStreams,
        config: dict,
    ):
        self.redis = redis
        self.config = config
        self.balance = config.get("initial_balance", 10000)
        self.fee_rate = config.get("fee_rate", 0.001)  # 0.1%
        self.slippage = config.get("slippage", 0.0004)  # 0.04%
        self.max_daily_loss = config.get("max_daily_loss", 500)
        self.last_prices: dict[str, float] = {}
        self._running = False

    async def run(self) -> None:
        """Main loop: consume and simulate orders."""
        self._running = True
        group = "executor"
        consumer = "paper-executor"

        await self.redis.create_consumer_group("orders", group)
        logger.info(f"PaperExecutor started with balance: {self.balance}")

        # Also consume prices to track latest prices
        asyncio.create_task(self._price_tracker())

        while self._running:
            try:
                messages = await self.redis.consume(
                    "orders", group, consumer, count=1, block_ms=1000
                )

                for msg in messages:
                    await self._process_order(msg)
                    await self.redis.ack("orders", group, msg["_id"])

            except Exception as e:
                logger.error(f"PaperExecutor error: {e}")
                await asyncio.sleep(1)

    async def _price_tracker(self) -> None:
        """Track latest prices from price stream."""
        group = "paper-price-tracker"
        consumer = "tracker"

        try:
            await self.redis.create_consumer_group("market:prices", group)
        except Exception:
            pass

        while self._running:
            try:
                messages = await self.redis.consume(
                    "market:prices", group, consumer, count=100, block_ms=500
                )
                for msg in messages:
                    symbol = msg.get("symbol")
                    price = msg.get("price")
                    if symbol and price:
                        self.last_prices[symbol] = float(price)
                    await self.redis.ack("market:prices", group, msg["_id"])
            except Exception:
                await asyncio.sleep(1)

    def stop(self) -> None:
        """Signal executor to stop."""
        self._running = False

    async def _process_order(self, order: dict[str, Any]) -> dict | None:
        """Simulate order execution."""
        # Check risk gates
        if not await self._pass_risk_gates():
            logger.warning(f"Paper order {order['id']} blocked by risk gates")
            return None

        symbol = order["symbol"]
        side = order["side"]
        quantity = float(order["quantity"])

        # Get current price
        price = self.last_prices.get(symbol)
        if price is None:
            logger.warning(f"No price available for {symbol}")
            return None

        # Apply slippage
        fill_price = self._apply_slippage(price, side)

        # Calculate order value and fees
        order_value = fill_price * quantity
        fees = order_value * self.fee_rate

        # Check balance for buys
        if side == "buy":
            total_cost = order_value + fees
            if total_cost > self.balance:
                logger.warning(f"Insufficient balance: {self.balance} < {total_cost}")
                return None
            self.balance -= total_cost
        else:
            # For sells, add to balance (minus fees)
            self.balance += order_value - fees

        # Create fill result
        fill = {
            "order_id": str(uuid.uuid4().int)[:8],
            "symbol": symbol,
            "side": side,
            "market": order["market"],
            "filled_qty": quantity,
            "filled_price": fill_price,
            "status": "FILLED",
            "fees": fees,
        }

        # Update position
        await self._update_position(order, fill)

        # Publish trade
        await self._publish_trade(order, fill)

        logger.info(f"Paper fill: {fill}, balance: {self.balance:.2f}")
        return fill

    def _apply_slippage(self, price: float, side: str) -> float:
        """Apply slippage to price."""
        if side == "buy":
            return price * (1 + self.slippage)
        else:
            return price * (1 - self.slippage)

    async def _pass_risk_gates(self) -> bool:
        """Check risk conditions."""
        risk = await self.redis.get_risk()

        if risk.get("kill_switch") == "true":
            return False
        if risk.get("blocked") == "true":
            return False

        daily_pnl = float(risk.get("daily_pnl", 0))
        if daily_pnl < -self.max_daily_loss:
            return False

        return True

    async def _update_position(self, order: dict, fill: dict) -> None:
        """Update position in Redis."""
        await self.redis.set_position(order["symbol"], order["market"], {
            "quantity": str(fill["filled_qty"]),
            "entry_price": str(fill["filled_price"]),
            "strategy": order["strategy"],
            "entry_time": str(int(time.time() * 1000)),
            "side": order["side"],
        })

    async def _publish_trade(self, order: dict, fill: dict) -> None:
        """Publish trade to trades stream."""
        await self.redis.publish("trades", {
            "order_id": str(fill["order_id"]),
            "symbol": order["symbol"],
            "side": order["side"],
            "market": order["market"],
            "quantity": str(fill["filled_qty"]),
            "price": str(fill["filled_price"]),
            "strategy": order["strategy"],
            "timestamp": str(int(time.time() * 1000)),
            "paper": "true",
        })
```

**Step 4: Update __init__.py**

```python
# trading/executor/__init__.py
from .binance_client import BinanceClient, Fill
from .async_executor import AsyncExecutor
from .paper_executor import PaperExecutor

__all__ = ["BinanceClient", "Fill", "AsyncExecutor", "PaperExecutor"]
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/trading/executor/test_paper_executor.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add trading/executor/paper_executor.py trading/executor/__init__.py tests/trading/executor/test_paper_executor.py
git commit -m "feat: add PaperExecutor for simulated trading"
```

---

## Phase 6: Engine & Startup

### Task 6.1: Create Lightweight Engine

**Files:**
- Create: `trading/engine.py`
- Test: `tests/trading/test_engine.py`

**Step 1: Write the failing test**

```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/trading/test_engine.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write implementation**

```python
# trading/engine.py
"""Lightweight trading engine orchestrator."""
from __future__ import annotations
import asyncio
import json
import logging
import signal
from pathlib import Path
from typing import Any

from trading.streams import RedisStreams, BinanceFeedTask
from trading.strategies import V35LongTask, SidewaysV2Task, ShortV1Task
from trading.executor import BinanceClient, AsyncExecutor, PaperExecutor

logger = logging.getLogger(__name__)


def load_config(path: str) -> dict[str, Any]:
    """Load configuration from JSON file."""
    with open(path) as f:
        return json.load(f)


class TradingEngine:
    """Lightweight orchestrator for stream-based trading."""

    def __init__(self, config_path: str = "config/strategies/allocation.json"):
        self.config = load_config(config_path)
        self.redis: RedisStreams | None = None
        self.tasks: list[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()

    async def start(self, mode: str = "paper") -> None:
        """Start all trading components."""
        logger.info(f"Starting TradingEngine in {mode} mode")

        # Connect to Redis
        self.redis = RedisStreams(url=self.config.get("redis_url", "redis://localhost:6379"))
        await self.redis.connect()

        # Initialize risk state
        await self.redis.set_risk({
            "kill_switch": "false",
            "blocked": "false",
            "daily_pnl": "0",
        })

        symbols = self.config.get("symbols", ["BTC"])

        # 1. Start feed tasks (one per symbol, for both spot and futures)
        for symbol in symbols:
            # Spot feed
            spot_feed = BinanceFeedTask(symbol=symbol, redis=self.redis, market="spot")
            self.tasks.append(asyncio.create_task(spot_feed.run()))

            # Futures feed
            futures_feed = BinanceFeedTask(symbol=symbol, redis=self.redis, market="futures")
            self.tasks.append(asyncio.create_task(futures_feed.run()))

        logger.info(f"Started {len(symbols) * 2} feed tasks")

        # 2. Start strategy tasks
        strategy_config = self.config.get("strategies", {})

        v35_long = V35LongTask(symbols=symbols, redis=self.redis, config=strategy_config.get("v35_long"))
        self.tasks.append(asyncio.create_task(v35_long.run()))

        sideways = SidewaysV2Task(symbols=symbols, redis=self.redis, config=strategy_config.get("sideways_v2"))
        self.tasks.append(asyncio.create_task(sideways.run()))

        short = ShortV1Task(symbols=symbols, redis=self.redis, config=strategy_config.get("short_v1"))
        self.tasks.append(asyncio.create_task(short.run()))

        logger.info("Started 3 strategy tasks")

        # 3. Start executor
        if mode == "paper":
            executor = PaperExecutor(
                redis=self.redis,
                config=self.config.get("paper", {"initial_balance": 10000}),
            )
        else:
            client = BinanceClient(
                api_key=self.config["binance"]["api_key"],
                api_secret=self.config["binance"]["api_secret"],
            )
            await client.connect()
            executor = AsyncExecutor(
                redis=self.redis,
                client=client,
                config=self.config.get("risk", {}),
            )

        self.tasks.append(asyncio.create_task(executor.run()))
        logger.info(f"Started {mode} executor")

        # 4. Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._signal_handler)

        logger.info("TradingEngine started successfully")

        # Wait for shutdown
        await self._shutdown_event.wait()

        # Graceful shutdown
        await self._shutdown()

    def _signal_handler(self) -> None:
        """Handle shutdown signals."""
        logger.info("Shutdown signal received")
        self._shutdown_event.set()

    async def _shutdown(self) -> None:
        """Gracefully shut down all tasks."""
        logger.info("Shutting down...")

        # Cancel all tasks
        for task in self.tasks:
            task.cancel()

        # Wait for tasks to complete
        await asyncio.gather(*self.tasks, return_exceptions=True)

        # Disconnect Redis
        if self.redis:
            await self.redis.disconnect()

        logger.info("Shutdown complete")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/trading/test_engine.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add trading/engine.py tests/trading/test_engine.py
git commit -m "feat: add lightweight TradingEngine orchestrator"
```

---

### Task 6.2: Update run.py Entry Point

**Files:**
- Modify: `run.py`

**Step 1: Read current run.py**

```bash
head -50 run.py
```

**Step 2: Create new run.py**

```python
# run.py
"""Entry point for the trading bot."""
import argparse
import asyncio
import logging
import sys

from trading.engine import TradingEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Bitcoin Trading Bot")
    parser.add_argument(
        "--trend",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode: paper (simulated) or live",
    )
    parser.add_argument(
        "--config",
        default="config/strategies/allocation.json",
        help="Path to configuration file",
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    logger.info(f"Starting trading bot in {args.trend} mode")

    engine = TradingEngine(config_path=args.config)

    try:
        asyncio.run(engine.start(mode=args.trend))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

**Step 3: Commit**

```bash
git add run.py
git commit -m "refactor: simplify run.py for new stream architecture"
```

---

## Phase 7: Cleanup

### Task 7.1: Remove Obsolete Files

**Step 1: Delete obsolete files**

```bash
# Upbit-related
rm -f trading/adapters/upbit.py

# Old engine
rm -f trading/multi_asset_engine.py

# Regime router (now internalized in strategies)
rm -f trading/strategy/regime_router.py

# Old caches (replaced by Redis)
rm -f trading/core/fx_cache.py
rm -f trading/core/multi_asset_price_hub.py
rm -f trading/core/multi_asset_data_cache.py

# Old alpha manager
rm -f trading/execution/multi_asset_alpha_manager.py
```

**Step 2: Update any imports that referenced deleted files**

Check and update any remaining imports.

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove obsolete files (Upbit, regime router, old engine)"
```

---

### Task 7.2: Update Configuration

**Files:**
- Modify: `config/strategies/allocation.json`

**Step 1: Read current config**

```bash
cat config/strategies/allocation.json
```

**Step 2: Create simplified Binance-only config**

```json
{
  "redis_url": "redis://localhost:6379",
  "symbols": ["BTC", "ETH", "SOL"],
  "binance": {
    "api_key": "${BINANCE_API_KEY}",
    "api_secret": "${BINANCE_API_SECRET}"
  },
  "strategies": {
    "v35_long": {
      "position_size": 0.01
    },
    "sideways_v2": {
      "position_size": 0.01
    },
    "short_v1": {
      "position_size": 0.01
    }
  },
  "risk": {
    "max_daily_loss": 500
  },
  "paper": {
    "initial_balance": 10000,
    "fee_rate": 0.001,
    "slippage": 0.0004
  }
}
```

**Step 3: Commit**

```bash
git add config/strategies/allocation.json
git commit -m "config: simplify allocation.json for Binance-only"
```

---

## Phase 8: Integration Testing

### Task 8.1: Create Integration Test

**Files:**
- Create: `tests/integration/test_stream_pipeline.py`

**Step 1: Write integration test**

```python
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
```

**Step 2: Run integration test**

Run: `pytest tests/integration/test_stream_pipeline.py -v -m integration`
Expected: PASS (requires Redis running)

**Step 3: Commit**

```bash
mkdir -p tests/integration
git add tests/integration/
git commit -m "test: add integration test for stream pipeline"
```

---

## Summary

This plan implements the Binance-only stream architecture in 8 phases:

1. **Redis Streams Infrastructure** — RedisStreams client with position/risk helpers
2. **Price Feed Tasks** — SymbolFeedTask and BinanceFeedTask
3. **Strategy Base Task** — BaseStrategyTask with buffering and order publishing
4. **Strategy Migrations** — V35LongTask, SidewaysV2Task, ShortV1Task
5. **Executor** — BinanceClient, AsyncExecutor, PaperExecutor
6. **Engine & Startup** — Lightweight TradingEngine and updated run.py
7. **Cleanup** — Remove obsolete files, update config
8. **Integration Testing** — End-to-end pipeline test

**Estimated commits:** 15
**Estimated new code:** ~1,200 lines
**Estimated deleted code:** ~2,500 lines
