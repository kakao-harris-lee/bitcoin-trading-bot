# Smart Executor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a SmartExecutor that optimizes exit execution using volatility-adaptive trailing stops and hybrid split orders.

**Architecture:** SmartExecutor sits between strategies and AsyncExecutor, intercepting exit signals, analyzing minute data for volatility, and executing exits via limit ladder with sweep fallback.

**Tech Stack:** Python 3.12, Redis Streams, asyncio, pytest

---

## Task 1: VolatilityTracker Class

**Files:**
- Create: `trading/strategies/volatility_tracker.py`
- Test: `tests/trading/strategies/test_volatility_tracker.py`

### Step 1: Write the failing test

Create test file:

```python
# tests/trading/strategies/test_volatility_tracker.py
import pytest
from trading.strategies.volatility_tracker import VolatilityTracker


def test_volatility_tracker_requires_minimum_data():
    """Tracker returns None when insufficient data."""
    tracker = VolatilityTracker(window=20)
    tracker.add_price(100.0)
    tracker.add_price(101.0)

    assert tracker.get_volatility() is None


def test_volatility_tracker_calculates_volatility():
    """Tracker calculates volatility from price returns."""
    tracker = VolatilityTracker(window=5)

    # Add 6 prices (need window+1 for returns)
    prices = [100.0, 101.0, 100.5, 102.0, 101.5, 103.0]
    for p in prices:
        tracker.add_price(p)

    vol = tracker.get_volatility()
    assert vol is not None
    assert 0 < vol < 0.05  # Reasonable volatility range


def test_volatility_classification_low():
    """Low volatility when stddev/mean < 0.003."""
    tracker = VolatilityTracker(window=5)

    # Steady uptrend with small moves
    prices = [100.0, 100.1, 100.2, 100.3, 100.4, 100.5]
    for p in prices:
        tracker.add_price(p)

    assert tracker.classify_volatility() == "low"


def test_volatility_classification_high():
    """High volatility when stddev/mean > 0.007."""
    tracker = VolatilityTracker(window=5)

    # Choppy with large swings
    prices = [100.0, 102.0, 99.0, 103.0, 98.0, 104.0]
    for p in prices:
        tracker.add_price(p)

    assert tracker.classify_volatility() == "high"


def test_get_trail_distance():
    """Trail distance varies by volatility classification."""
    tracker = VolatilityTracker(window=5)

    # Low vol config
    assert tracker.get_trail_distance("low") == 0.8
    assert tracker.get_trail_distance("medium") == 1.2
    assert tracker.get_trail_distance("high") == 1.8
```

### Step 2: Run test to verify it fails

Run: `pytest tests/trading/strategies/test_volatility_tracker.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'trading.strategies.volatility_tracker'"

### Step 3: Create __init__.py if needed

```bash
touch tests/trading/strategies/__init__.py
```

### Step 4: Write minimal implementation

```python
# trading/strategies/volatility_tracker.py
"""Volatility tracking for smart execution."""
from __future__ import annotations
from collections import deque
import statistics


class VolatilityTracker:
    """Tracks price volatility using rolling window of returns."""

    # Default trail distances by volatility level (percentage)
    TRAIL_DISTANCES = {
        "low": 0.8,
        "medium": 1.2,
        "high": 1.8,
    }

    # Volatility thresholds (stddev/mean of returns)
    LOW_VOL_THRESHOLD = 0.003
    HIGH_VOL_THRESHOLD = 0.007

    def __init__(self, window: int = 20):
        """Initialize tracker with rolling window size."""
        self.window = window
        self.prices: deque[float] = deque(maxlen=window + 1)

    def add_price(self, price: float) -> None:
        """Add a price point."""
        self.prices.append(price)

    def get_returns(self) -> list[float]:
        """Calculate percentage returns from prices."""
        if len(self.prices) < 2:
            return []

        returns = []
        prices_list = list(self.prices)
        for i in range(1, len(prices_list)):
            ret = (prices_list[i] - prices_list[i-1]) / prices_list[i-1]
            returns.append(ret)
        return returns

    def get_volatility(self) -> float | None:
        """Calculate volatility as stddev/mean of absolute returns."""
        returns = self.get_returns()
        if len(returns) < self.window:
            return None

        # Use last `window` returns
        recent = returns[-self.window:]
        abs_returns = [abs(r) for r in recent]

        if not abs_returns:
            return None

        mean_ret = statistics.mean(abs_returns)
        if mean_ret == 0:
            return 0.0

        stddev_ret = statistics.stdev(abs_returns) if len(abs_returns) > 1 else 0.0
        return stddev_ret / mean_ret if mean_ret > 0 else 0.0

    def classify_volatility(self) -> str:
        """Classify current volatility level."""
        vol = self.get_volatility()
        if vol is None:
            return "medium"  # Default when insufficient data

        if vol < self.LOW_VOL_THRESHOLD:
            return "low"
        elif vol > self.HIGH_VOL_THRESHOLD:
            return "high"
        else:
            return "medium"

    def get_trail_distance(self, classification: str | None = None) -> float:
        """Get trail distance percentage for volatility level."""
        if classification is None:
            classification = self.classify_volatility()
        return self.TRAIL_DISTANCES.get(classification, 1.2)

    def clear(self) -> None:
        """Clear all price data."""
        self.prices.clear()
```

### Step 5: Run test to verify it passes

Run: `pytest tests/trading/strategies/test_volatility_tracker.py -v`
Expected: PASS (5 tests)

### Step 6: Commit

```bash
git add trading/strategies/volatility_tracker.py tests/trading/strategies/
git commit -m "feat: add VolatilityTracker for smart execution

Calculates rolling volatility from minute price returns.
Classifies as low/medium/high with corresponding trail distances.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Add Limit Order Support to BinanceClient

**Files:**
- Modify: `trading/executor/binance_client.py`
- Test: `tests/trading/executor/test_binance_client.py`

### Step 1: Write the failing test

Create test file:

```python
# tests/trading/executor/test_binance_client.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from trading.executor.binance_client import BinanceClient


@pytest.fixture
def mock_client():
    client = BinanceClient(api_key="test", api_secret="test")
    client._spot_client = AsyncMock()
    client._futures_client = AsyncMock()
    client._is_mock = False
    return client


@pytest.mark.asyncio
async def test_limit_order_spot(mock_client):
    """Test placing spot limit order."""
    mock_client._spot_client.create_order = AsyncMock(return_value={
        "orderId": 12345,
        "executedQty": "0.0",
        "cummulativeQuoteQty": "0.0",
        "status": "NEW",
        "price": "95000.00",
    })

    result = await mock_client.limit_order(
        symbol="BTC",
        side="sell",
        quantity=0.01,
        price=95000.0,
        market="spot",
    )

    assert result["order_id"] == 12345
    assert result["status"] == "NEW"
    assert result["price"] == 95000.0
    mock_client._spot_client.create_order.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_order_spot(mock_client):
    """Test canceling spot order."""
    mock_client._spot_client.cancel_order = AsyncMock(return_value={
        "orderId": 12345,
        "status": "CANCELED",
    })

    result = await mock_client.cancel_order(
        symbol="BTC",
        order_id=12345,
        market="spot",
    )

    assert result["status"] == "CANCELED"


@pytest.mark.asyncio
async def test_get_order_status(mock_client):
    """Test getting order status."""
    mock_client._spot_client.get_order = AsyncMock(return_value={
        "orderId": 12345,
        "status": "PARTIALLY_FILLED",
        "executedQty": "0.005",
        "price": "95000.00",
    })

    result = await mock_client.get_order(
        symbol="BTC",
        order_id=12345,
        market="spot",
    )

    assert result["status"] == "PARTIALLY_FILLED"
    assert result["filled_qty"] == 0.005
```

### Step 2: Run test to verify it fails

Run: `pytest tests/trading/executor/test_binance_client.py -v`
Expected: FAIL with "AttributeError: 'BinanceClient' object has no attribute 'limit_order'"

### Step 3: Create test directory __init__.py

```bash
mkdir -p tests/trading/executor
touch tests/trading/executor/__init__.py
```

### Step 4: Add limit order methods to BinanceClient

Add after `market_order` method in `trading/executor/binance_client.py`:

```python
    async def limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        market: str,
    ) -> dict[str, Any]:
        """Place limit order on spot or futures."""
        pair = f"{symbol}USDT"

        try:
            if market == "futures":
                result = await self._futures_client.futures_create_order(
                    symbol=pair,
                    side=side.upper(),
                    type="LIMIT",
                    quantity=quantity,
                    price=price,
                    timeInForce="GTC",
                )
            else:
                result = await self._spot_client.create_order(
                    symbol=pair,
                    side=side.upper(),
                    type="LIMIT",
                    quantity=quantity,
                    price=price,
                    timeInForce="GTC",
                )

            return {
                "order_id": result["orderId"],
                "symbol": symbol,
                "side": side,
                "market": market,
                "price": float(result.get("price", price)),
                "quantity": quantity,
                "filled_qty": float(result.get("executedQty", 0)),
                "status": result["status"],
            }

        except Exception as e:
            logger.error(f"Limit order failed: {e}")
            raise

    async def cancel_order(
        self,
        symbol: str,
        order_id: int,
        market: str,
    ) -> dict[str, Any]:
        """Cancel an open order."""
        pair = f"{symbol}USDT"

        try:
            if market == "futures":
                result = await self._futures_client.futures_cancel_order(
                    symbol=pair,
                    orderId=order_id,
                )
            else:
                result = await self._spot_client.cancel_order(
                    symbol=pair,
                    orderId=order_id,
                )

            return {
                "order_id": result["orderId"],
                "status": result["status"],
            }

        except Exception as e:
            logger.error(f"Cancel order failed: {e}")
            raise

    async def get_order(
        self,
        symbol: str,
        order_id: int,
        market: str,
    ) -> dict[str, Any]:
        """Get order status."""
        pair = f"{symbol}USDT"

        try:
            if market == "futures":
                result = await self._futures_client.futures_get_order(
                    symbol=pair,
                    orderId=order_id,
                )
            else:
                result = await self._spot_client.get_order(
                    symbol=pair,
                    orderId=order_id,
                )

            return {
                "order_id": result["orderId"],
                "status": result["status"],
                "filled_qty": float(result.get("executedQty", 0)),
                "price": float(result.get("price", 0)),
            }

        except Exception as e:
            logger.error(f"Get order failed: {e}")
            raise
```

### Step 5: Run test to verify it passes

Run: `pytest tests/trading/executor/test_binance_client.py -v`
Expected: PASS (3 tests)

### Step 6: Commit

```bash
git add trading/executor/binance_client.py tests/trading/executor/
git commit -m "feat: add limit order support to BinanceClient

Adds limit_order, cancel_order, and get_order methods
for smart execution split orders.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: SmartExecutor Core Structure

**Files:**
- Create: `trading/executor/smart_executor.py`
- Test: `tests/trading/executor/test_smart_executor.py`

### Step 1: Write failing tests for core structure

```python
# tests/trading/executor/test_smart_executor.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from trading.executor.smart_executor import SmartExecutor


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get_position = AsyncMock(return_value=None)
    redis.is_kill_switch_on = AsyncMock(return_value=False)
    redis.publish = AsyncMock(return_value="1234-0")
    redis.consume = AsyncMock(return_value=[])
    redis.create_consumer_group = AsyncMock()
    redis.ack = AsyncMock()
    redis.client = AsyncMock()
    redis.client.xrange = AsyncMock(return_value=[])
    return redis


@pytest.fixture
def mock_binance():
    client = AsyncMock()
    client.limit_order = AsyncMock(return_value={
        "order_id": 12345,
        "status": "NEW",
        "price": 95000.0,
        "filled_qty": 0.0,
    })
    client.cancel_order = AsyncMock(return_value={"status": "CANCELED"})
    client.get_order = AsyncMock(return_value={
        "order_id": 12345,
        "status": "FILLED",
        "filled_qty": 0.01,
    })
    client.market_order = AsyncMock(return_value={
        "order_id": 12346,
        "filled_qty": 0.01,
        "filled_price": 94900.0,
        "status": "FILLED",
    })
    return client


@pytest.fixture
def config():
    return {
        "smart_executor": {
            "enabled": True,
            "trailing": {
                "volatility_window": 20,
                "low_vol_trail": 0.8,
                "med_vol_trail": 1.2,
                "high_vol_trail": 1.8,
            },
            "split_execution": {
                "ladder_tiers": [0.05, 0.12, 0.20],
                "ladder_weights": [0.40, 0.35, 0.25],
                "phase1_timeout_sec": 60,
                "max_execution_sec": 90,
            },
        }
    }


def test_smart_executor_init(mock_redis, mock_binance, config):
    """SmartExecutor initializes with config."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    assert executor.enabled is True
    assert executor.volatility_window == 20


@pytest.mark.asyncio
async def test_calculate_ladder_prices(mock_redis, mock_binance, config):
    """Calculate limit ladder prices."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    base_price = 100000.0
    prices = executor._calculate_ladder_prices(base_price)

    # Should have 3 tiers at +0.05%, +0.12%, +0.20%
    assert len(prices) == 3
    assert prices[0] == pytest.approx(100050.0, rel=0.001)  # +0.05%
    assert prices[1] == pytest.approx(100120.0, rel=0.001)  # +0.12%
    assert prices[2] == pytest.approx(100200.0, rel=0.001)  # +0.20%


@pytest.mark.asyncio
async def test_calculate_ladder_quantities(mock_redis, mock_binance, config):
    """Calculate quantity per ladder tier."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    total_qty = 0.10
    quantities = executor._calculate_ladder_quantities(total_qty)

    # Should split by weights: 40%, 35%, 25%
    assert len(quantities) == 3
    assert quantities[0] == pytest.approx(0.04, rel=0.01)
    assert quantities[1] == pytest.approx(0.035, rel=0.01)
    assert quantities[2] == pytest.approx(0.025, rel=0.01)
    assert sum(quantities) == pytest.approx(total_qty, rel=0.001)
```

### Step 2: Run test to verify it fails

Run: `pytest tests/trading/executor/test_smart_executor.py -v`
Expected: FAIL with "ModuleNotFoundError"

### Step 3: Write SmartExecutor skeleton

```python
# trading/executor/smart_executor.py
"""Smart executor for optimized exit execution."""
from __future__ import annotations
import asyncio
import logging
import time
import uuid
from typing import Any, TYPE_CHECKING
from dataclasses import dataclass, field

from trading.strategies.volatility_tracker import VolatilityTracker

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams
    from trading.executor.binance_client import BinanceClient

logger = logging.getLogger(__name__)


@dataclass
class ExitPlan:
    """Tracks an in-progress smart exit."""
    symbol: str
    market: str
    total_quantity: float
    trigger_price: float
    strategy: str
    start_time: float = field(default_factory=time.time)
    ladder_orders: list[dict] = field(default_factory=list)
    filled_quantity: float = 0.0
    phase: str = "ladder"  # ladder, sweep, complete


class SmartExecutor:
    """Intercepts exit signals and applies smart execution."""

    def __init__(
        self,
        redis: RedisStreams,
        binance_client: BinanceClient,
        config: dict,
    ):
        self.redis = redis
        self.client = binance_client
        self.config = config

        # Extract smart_executor config
        se_config = config.get("smart_executor", {})
        self.enabled = se_config.get("enabled", True)

        # Trailing config
        trailing = se_config.get("trailing", {})
        self.volatility_window = trailing.get("volatility_window", 20)
        self.trail_distances = {
            "low": trailing.get("low_vol_trail", 0.8),
            "medium": trailing.get("med_vol_trail", 1.2),
            "high": trailing.get("high_vol_trail", 1.8),
        }

        # Split execution config
        split = se_config.get("split_execution", {})
        self.ladder_tiers = split.get("ladder_tiers", [0.05, 0.12, 0.20])
        self.ladder_weights = split.get("ladder_weights", [0.40, 0.35, 0.25])
        self.phase1_timeout = split.get("phase1_timeout_sec", 60)
        self.max_execution_time = split.get("max_execution_sec", 90)

        # Volatility trackers per symbol
        self.volatility_trackers: dict[str, VolatilityTracker] = {}

        # Active exit plans
        self.active_exits: dict[str, ExitPlan] = {}

        # High water marks for trailing stops
        self.high_water_marks: dict[str, float] = {}

        self._running = False

    def _calculate_ladder_prices(self, base_price: float) -> list[float]:
        """Calculate limit prices for ladder tiers."""
        prices = []
        for tier_pct in self.ladder_tiers:
            price = base_price * (1 + tier_pct / 100)
            prices.append(round(price, 2))
        return prices

    def _calculate_ladder_quantities(self, total_qty: float) -> list[float]:
        """Calculate quantity for each ladder tier."""
        quantities = []
        for weight in self.ladder_weights:
            qty = total_qty * weight
            quantities.append(round(qty, 8))
        return quantities

    async def run(self) -> None:
        """Main loop: monitor positions, execute smart exits."""
        self._running = True
        group = "smart-executor"
        consumer = f"smart-exec-{uuid.uuid4().hex[:8]}"

        await self.redis.create_consumer_group("exit_signals", group)

        logger.info("SmartExecutor started")

        # Start background tasks
        asyncio.create_task(self._price_monitor_loop())
        asyncio.create_task(self._exit_execution_loop())

        while self._running:
            try:
                # Consume exit signals
                messages = await self.redis.consume(
                    "exit_signals", group, consumer, count=10, block_ms=1000
                )

                for msg in messages:
                    await self._handle_exit_signal(msg)
                    await self.redis.ack("exit_signals", group, msg["_id"])

            except Exception as e:
                logger.error(f"SmartExecutor error: {e}")
                await asyncio.sleep(1)

    def stop(self) -> None:
        """Signal executor to stop."""
        self._running = False

    async def _price_monitor_loop(self) -> None:
        """Monitor prices and update volatility trackers."""
        while self._running:
            try:
                # Read recent prices from market:prices stream
                # Update volatility trackers
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Price monitor error: {e}")

    async def _exit_execution_loop(self) -> None:
        """Monitor active exits and manage ladder phases."""
        while self._running:
            try:
                await self._check_active_exits()
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Exit execution error: {e}")

    async def _handle_exit_signal(self, signal: dict) -> None:
        """Handle incoming exit signal from strategy."""
        symbol = signal.get("symbol")
        market = signal.get("market", "spot")
        quantity = float(signal.get("quantity", 0))
        trigger_price = float(signal.get("trigger_price", 0))
        strategy = signal.get("strategy", "unknown")

        logger.info(f"Received exit signal: {symbol} {quantity} @ {trigger_price}")

        # Create exit plan
        plan = ExitPlan(
            symbol=symbol,
            market=market,
            total_quantity=quantity,
            trigger_price=trigger_price,
            strategy=strategy,
        )

        # Start ladder execution
        await self._execute_ladder(plan)

        # Track active exit
        self.active_exits[f"{symbol}:{market}"] = plan

    async def _execute_ladder(self, plan: ExitPlan) -> None:
        """Place limit order ladder."""
        prices = self._calculate_ladder_prices(plan.trigger_price)
        quantities = self._calculate_ladder_quantities(plan.total_quantity)

        for price, qty in zip(prices, quantities):
            try:
                result = await self.client.limit_order(
                    symbol=plan.symbol,
                    side="sell",
                    quantity=qty,
                    price=price,
                    market=plan.market,
                )
                plan.ladder_orders.append(result)
                logger.info(f"Placed ladder order: {qty} @ {price}")
            except Exception as e:
                logger.error(f"Ladder order failed: {e}")

    async def _check_active_exits(self) -> None:
        """Check status of active exit plans."""
        for key, plan in list(self.active_exits.items()):
            if plan.phase == "complete":
                continue

            elapsed = time.time() - plan.start_time

            # Check order fills
            filled = 0.0
            for order in plan.ladder_orders:
                try:
                    status = await self.client.get_order(
                        symbol=plan.symbol,
                        order_id=order["order_id"],
                        market=plan.market,
                    )
                    filled += status.get("filled_qty", 0)
                except Exception:
                    pass

            plan.filled_quantity = filled
            remaining = plan.total_quantity - filled

            # Check if complete
            if remaining <= 0:
                plan.phase = "complete"
                logger.info(f"Exit complete: {plan.symbol} all filled via ladder")
                continue

            # Phase transition: sweep if timeout
            if elapsed > self.max_execution_time and remaining > 0:
                await self._sweep_remaining(plan, remaining)
                plan.phase = "complete"

    async def _sweep_remaining(self, plan: ExitPlan, remaining_qty: float) -> None:
        """Cancel unfilled orders and sweep with market order."""
        logger.info(f"Sweeping remaining {remaining_qty} {plan.symbol}")

        # Cancel unfilled orders
        for order in plan.ladder_orders:
            try:
                await self.client.cancel_order(
                    symbol=plan.symbol,
                    order_id=order["order_id"],
                    market=plan.market,
                )
            except Exception:
                pass  # Order may already be filled/canceled

        # Market sweep
        try:
            result = await self.client.market_order(
                symbol=plan.symbol,
                side="sell",
                quantity=remaining_qty,
                market=plan.market,
            )
            logger.info(f"Sweep complete: {result}")
        except Exception as e:
            logger.error(f"Sweep failed: {e}")
```

### Step 4: Run test to verify it passes

Run: `pytest tests/trading/executor/test_smart_executor.py -v`
Expected: PASS (3 tests)

### Step 5: Commit

```bash
git add trading/executor/smart_executor.py tests/trading/executor/test_smart_executor.py
git commit -m "feat: add SmartExecutor core structure

Implements ladder calculation, exit plan tracking,
and sweep fallback logic skeleton.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 4: SmartExecutor Trailing Stop Logic

**Files:**
- Modify: `trading/executor/smart_executor.py`
- Modify: `tests/trading/executor/test_smart_executor.py`

### Step 1: Add trailing stop tests

Append to `tests/trading/executor/test_smart_executor.py`:

```python
@pytest.mark.asyncio
async def test_update_trailing_stop(mock_redis, mock_binance, config):
    """Test trailing stop updates with price."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    # Set up a position
    position = {
        "symbol": "BTC",
        "market": "spot",
        "entry_price": 100000.0,
        "quantity": 0.1,
        "strategy": "v35_classic_wide",
    }

    # Price goes up - HWM should update
    executor.update_high_water_mark("BTC", 101000.0)
    assert executor.high_water_marks["BTC"] == 101000.0

    # Price goes up more
    executor.update_high_water_mark("BTC", 102000.0)
    assert executor.high_water_marks["BTC"] == 102000.0

    # Price goes down - HWM stays
    executor.update_high_water_mark("BTC", 101500.0)
    assert executor.high_water_marks["BTC"] == 102000.0


@pytest.mark.asyncio
async def test_calculate_trailing_stop_price(mock_redis, mock_binance, config):
    """Calculate stop price from HWM and volatility."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    executor.high_water_marks["BTC"] = 100000.0

    # Low volatility = tight stop (0.8%)
    stop = executor.calculate_stop_price("BTC", "low")
    assert stop == pytest.approx(99200.0, rel=0.001)

    # High volatility = wide stop (1.8%)
    stop = executor.calculate_stop_price("BTC", "high")
    assert stop == pytest.approx(98200.0, rel=0.001)


@pytest.mark.asyncio
async def test_should_trigger_trailing_stop(mock_redis, mock_binance, config):
    """Trailing stop triggers when price drops below stop."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    executor.high_water_marks["BTC"] = 100000.0

    # Price above stop - no trigger
    assert executor.should_trigger_stop("BTC", 99500.0, "low") is False

    # Price at stop - trigger
    assert executor.should_trigger_stop("BTC", 99200.0, "low") is True

    # Price below stop - trigger
    assert executor.should_trigger_stop("BTC", 99000.0, "low") is True
```

### Step 2: Run test to verify it fails

Run: `pytest tests/trading/executor/test_smart_executor.py::test_update_trailing_stop -v`
Expected: FAIL with "AttributeError: 'SmartExecutor' object has no attribute 'update_high_water_mark'"

### Step 3: Add trailing stop methods to SmartExecutor

Add these methods to `SmartExecutor` class:

```python
    def update_high_water_mark(self, symbol: str, price: float) -> None:
        """Update high water mark for symbol."""
        current_hwm = self.high_water_marks.get(symbol, 0)
        if price > current_hwm:
            self.high_water_marks[symbol] = price

    def calculate_stop_price(self, symbol: str, volatility: str) -> float:
        """Calculate trailing stop price."""
        hwm = self.high_water_marks.get(symbol, 0)
        trail_pct = self.trail_distances.get(volatility, 1.2)
        return hwm * (1 - trail_pct / 100)

    def should_trigger_stop(
        self, symbol: str, current_price: float, volatility: str
    ) -> bool:
        """Check if trailing stop should trigger."""
        if symbol not in self.high_water_marks:
            return False
        stop_price = self.calculate_stop_price(symbol, volatility)
        return current_price <= stop_price
```

### Step 4: Run test to verify it passes

Run: `pytest tests/trading/executor/test_smart_executor.py -v`
Expected: PASS (6 tests)

### Step 5: Commit

```bash
git add trading/executor/smart_executor.py tests/trading/executor/test_smart_executor.py
git commit -m "feat: add trailing stop logic to SmartExecutor

Implements HWM tracking, volatility-based stop calculation,
and trigger detection.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Add exit_signals Stream to RedisStreams

**Files:**
- Modify: `trading/streams/redis_streams.py`
- Modify: `tests/trading/streams/test_redis_streams.py`

### Step 1: Write failing test

Add to `tests/trading/streams/test_redis_streams.py`:

```python
@pytest.mark.asyncio
async def test_publish_exit_signal():
    """Test publishing exit signal to stream."""
    redis = RedisStreams(url="redis://localhost:6379")
    await redis.connect()

    try:
        signal = {
            "symbol": "BTC",
            "market": "spot",
            "quantity": "0.01",
            "trigger_price": "95000",
            "strategy": "v35_classic_wide",
            "reason": "trailing stop",
        }

        msg_id = await redis.publish("exit_signals", signal)
        assert msg_id is not None
        assert "-" in msg_id  # Redis stream ID format
    finally:
        await redis.disconnect()
```

### Step 2: Run test to verify it passes

The existing `publish` method should already work for any stream name.

Run: `pytest tests/trading/streams/test_redis_streams.py::test_publish_exit_signal -v`
Expected: PASS (uses existing publish method)

### Step 3: Commit (if any changes needed)

No changes needed - `publish` already handles arbitrary streams.

---

## Task 6: Update Strategies to Use exit_signals Stream

**Files:**
- Modify: `trading/streams/base_strategy.py`
- Modify: `tests/trading/streams/test_base_strategy.py`

### Step 1: Write failing test

Add to `tests/trading/streams/test_base_strategy.py`:

```python
@pytest.mark.asyncio
async def test_strategy_publishes_exit_signal(mock_redis):
    """Test exit signal publishing for smart execution."""
    mock_redis.get_position = AsyncMock(return_value={
        "quantity": "0.01",
        "entry_price": "40000",
        "strategy": "test",
        "side": "buy",
    })

    class TestExitStrategy(BaseStrategyTask):
        async def evaluate(self, symbol: str) -> dict | None:
            return None

        async def evaluate_exit(self, symbol: str, position: dict) -> dict | None:
            return {
                "symbol": symbol,
                "side": "sell",
                "market": "spot",
                "quantity": position["quantity"],
                "trigger_price": "42000",
                "reason": "test exit",
            }

    strategy = TestExitStrategy(
        name="test",
        symbols=["BTC"],
        redis=mock_redis,
        market="spot",
        use_smart_exit=True,  # Enable smart exit
    )

    msg = {"symbol": "BTC", "price": "42000", "market": "spot", "_id": "1-0"}
    await strategy._handle_message(msg)

    # Should publish to exit_signals, not orders
    calls = mock_redis.publish.call_args_list
    assert len(calls) == 1
    assert calls[0][0][0] == "exit_signals"
```

### Step 2: Run test to verify it fails

Run: `pytest tests/trading/streams/test_base_strategy.py::test_strategy_publishes_exit_signal -v`
Expected: FAIL (no use_smart_exit parameter)

### Step 3: Modify BaseStrategyTask

Update `trading/streams/base_strategy.py`:

In `__init__`:
```python
    def __init__(
        self,
        name: str,
        symbols: list[str],
        redis: RedisStreams,
        market: str,
        buffer_size: int = 500,
        use_smart_exit: bool = False,
    ):
        self.name = name
        self.symbols = set(symbols)
        self.redis = redis
        self.market = market
        self.buffer_size = buffer_size
        self.use_smart_exit = use_smart_exit
        self.price_buffer: dict[str, deque] = {}
        self._running = False
```

In `_handle_message`, update the exit signal publishing:
```python
            if position.get("strategy") == self.name:
                exit_signal = await self.evaluate_exit(symbol, position)
                if exit_signal:
                    await self._publish_exit(exit_signal, position)
                    if not self.use_smart_exit:
                        await self.redis.clear_position(symbol, self.market)
            return
```

Add new method:
```python
    async def _publish_exit(self, signal: dict[str, Any], position: dict) -> None:
        """Publish exit signal to appropriate stream."""
        if self.use_smart_exit:
            # Add trigger price if not present
            if "trigger_price" not in signal:
                buffer = self.price_buffer.get(signal["symbol"], [])
                if buffer:
                    signal["trigger_price"] = buffer[-1]["price"]

            exit_signal = {
                "id": str(uuid.uuid4()),
                "strategy": self.name,
                **signal,
            }
            await self.redis.publish("exit_signals", exit_signal)
            logger.info(f"Strategy {self.name} published exit signal: {exit_signal}")
        else:
            await self._publish_order(signal)
```

### Step 4: Run test to verify it passes

Run: `pytest tests/trading/streams/test_base_strategy.py -v`
Expected: PASS

### Step 5: Commit

```bash
git add trading/streams/base_strategy.py tests/trading/streams/test_base_strategy.py
git commit -m "feat: add smart exit support to BaseStrategyTask

Strategies can publish to exit_signals stream when
use_smart_exit=True for SmartExecutor handling.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 7: Add Configuration Schema

**Files:**
- Modify: `config/strategies/allocation.json`

### Step 1: Add smart_executor config

Add to `config/strategies/allocation.json`:

```json
{
  "redis_url": "redis://localhost:6379",
  "symbols": ["BTC", "ETH", "SOL"],
  "binance": {
    "api_key": "${BINANCE_API_KEY}",
    "api_secret": "${BINANCE_API_SECRET}"
  },
  "strategies": {
    "v35_classic_wide": {
      "dynamic_sizing": true,
      "position_pct": 0.30,
      "position_size": 0.01,
      "use_smart_exit": true
    },
    "sideways_v2": {
      "dynamic_sizing": true,
      "position_pct": 0.20,
      "position_size": 0.01,
      "use_smart_exit": true
    },
    "short_v1": {
      "dynamic_sizing": true,
      "position_pct": 0.20,
      "position_size": 0.01,
      "use_smart_exit": true
    }
  },
  "smart_executor": {
    "enabled": true,
    "trailing": {
      "volatility_window": 20,
      "low_vol_trail": 0.8,
      "med_vol_trail": 1.2,
      "high_vol_trail": 1.8,
      "damping_max": 0.2
    },
    "split_execution": {
      "ladder_tiers": [0.05, 0.12, 0.20],
      "ladder_weights": [0.40, 0.35, 0.25],
      "phase1_timeout_sec": 60,
      "max_execution_sec": 90
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

### Step 2: Commit

```bash
git add config/strategies/allocation.json
git commit -m "feat: add smart_executor configuration

Adds trailing stop and split execution config.
Enables use_smart_exit for all strategies.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 8: Integrate SmartExecutor into Engine

**Files:**
- Modify: `trading/engine.py`
- Test: `tests/trading/test_engine.py`

### Step 1: Read current engine structure

First read `trading/engine.py` to understand integration point.

### Step 2: Add SmartExecutor startup

In the engine's task startup, add SmartExecutor after strategy tasks and before executor:

```python
# In engine.py startup sequence
if config.get("smart_executor", {}).get("enabled", False):
    from trading.executor.smart_executor import SmartExecutor
    smart_executor = SmartExecutor(redis, binance_client, config)
    asyncio.create_task(smart_executor.run())
```

### Step 3: Run existing engine tests

Run: `pytest tests/trading/test_engine.py -v`
Expected: PASS

### Step 4: Commit

```bash
git add trading/engine.py
git commit -m "feat: integrate SmartExecutor into engine

Starts SmartExecutor task when enabled in config.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 9: Add Volatility Check Phase Logic

**Files:**
- Modify: `trading/executor/smart_executor.py`
- Modify: `tests/trading/executor/test_smart_executor.py`

### Step 1: Add volatility check tests

```python
@pytest.mark.asyncio
async def test_volatility_check_trending_down(mock_redis, mock_binance, config):
    """Detect trending down from price action."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    # 3+ consecutive red candles
    prices = [100000, 99500, 99000, 98500]
    for p in prices:
        executor.volatility_trackers.setdefault("BTC", VolatilityTracker()).add_price(p)

    action = executor.analyze_price_action("BTC")
    assert action == "trending_down"


@pytest.mark.asyncio
async def test_volatility_check_bouncing(mock_redis, mock_binance, config):
    """Detect bouncing/choppy from price action."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    # Up-down-up pattern
    prices = [100000, 100500, 100200, 100700]
    for p in prices:
        executor.volatility_trackers.setdefault("BTC", VolatilityTracker()).add_price(p)

    action = executor.analyze_price_action("BTC")
    assert action in ["bouncing", "choppy"]
```

### Step 2: Add analyze_price_action method

```python
    def analyze_price_action(self, symbol: str) -> str:
        """Analyze recent price action for execution decisions."""
        tracker = self.volatility_trackers.get(symbol)
        if not tracker or len(tracker.prices) < 4:
            return "unknown"

        prices = list(tracker.prices)[-4:]

        # Count direction changes
        changes = []
        for i in range(1, len(prices)):
            changes.append(prices[i] - prices[i-1])

        # 3+ consecutive drops = trending down
        if all(c < 0 for c in changes):
            return "trending_down"

        # 3+ consecutive rises = trending up
        if all(c > 0 for c in changes):
            return "trending_up"

        # Mixed = choppy/bouncing
        return "bouncing"
```

### Step 3: Run tests

Run: `pytest tests/trading/executor/test_smart_executor.py -v`
Expected: PASS

### Step 4: Commit

```bash
git add trading/executor/smart_executor.py tests/trading/executor/test_smart_executor.py
git commit -m "feat: add price action analysis for phase transitions

Detects trending_down vs bouncing for sweep decisions.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 10: Run Full Test Suite

### Step 1: Run all tests

```bash
pytest --ignore=tests/test_web_api.py --ignore=tests/web/ -v
```

Expected: All tests pass

### Step 2: Commit any fixes

If any tests fail, fix and commit.

---

## Task 11: Final Integration Test

### Step 1: Create integration test

```python
# tests/trading/executor/test_smart_executor_integration.py
import pytest
from unittest.mock import AsyncMock
from trading.executor.smart_executor import SmartExecutor
from trading.strategies.volatility_tracker import VolatilityTracker


@pytest.mark.asyncio
async def test_full_exit_flow():
    """Test complete exit flow from signal to completion."""
    mock_redis = AsyncMock()
    mock_redis.consume = AsyncMock(return_value=[])
    mock_redis.create_consumer_group = AsyncMock()

    mock_binance = AsyncMock()
    mock_binance.limit_order = AsyncMock(return_value={
        "order_id": 12345,
        "status": "NEW",
        "filled_qty": 0.0,
    })
    mock_binance.get_order = AsyncMock(return_value={
        "order_id": 12345,
        "status": "FILLED",
        "filled_qty": 0.01,
    })

    config = {
        "smart_executor": {
            "enabled": True,
            "trailing": {"volatility_window": 5},
            "split_execution": {
                "ladder_tiers": [0.05, 0.10],
                "ladder_weights": [0.6, 0.4],
                "max_execution_sec": 5,
            },
        }
    }

    executor = SmartExecutor(mock_redis, mock_binance, config)

    # Simulate exit signal
    signal = {
        "symbol": "BTC",
        "market": "spot",
        "quantity": "0.1",
        "trigger_price": "95000",
        "strategy": "v35_classic_wide",
    }

    await executor._handle_exit_signal(signal)

    # Verify ladder orders placed
    assert mock_binance.limit_order.call_count == 2
    assert "BTC:spot" in executor.active_exits
```

### Step 2: Run integration test

Run: `pytest tests/trading/executor/test_smart_executor_integration.py -v`
Expected: PASS

### Step 3: Commit

```bash
git add tests/trading/executor/test_smart_executor_integration.py
git commit -m "test: add SmartExecutor integration test

Verifies complete exit flow from signal to ladder placement.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | VolatilityTracker | volatility_tracker.py |
| 2 | Limit order support | binance_client.py |
| 3 | SmartExecutor core | smart_executor.py |
| 4 | Trailing stop logic | smart_executor.py |
| 5 | exit_signals stream | redis_streams.py |
| 6 | Strategy integration | base_strategy.py |
| 7 | Configuration | allocation.json |
| 8 | Engine integration | engine.py |
| 9 | Volatility check | smart_executor.py |
| 10 | Full test suite | - |
| 11 | Integration test | test_smart_executor_integration.py |
