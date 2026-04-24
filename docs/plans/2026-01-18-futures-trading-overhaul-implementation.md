# Futures Trading Overhaul Implementation Plan

> Archived note (2026-04-24): this document describes a retired futures/short/hedge path. The active runtime is now Binance spot-only. Keep this file only as historical reference, not as an implementation guide.


> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix short position handling in paper trading, add liquidation protection, and integrate live funding rates for complete futures trading support.

**Architecture:** Enhanced executor correctly handles both long/short P&L. LiquidationGuard calculates liquidation prices and triggers pre-emptive exits. FundingTracker fetches and applies Binance funding rates every 8 hours.

**Tech Stack:** Python 3.9+, Redis, Binance Futures API, pytest

---

## Phase 1: Fix Paper Executor Short Position Handling

### Task 1.1: Fix Exit Detection for Short Positions

**Files:**
- Modify: `trading/executor/paper_executor.py:207-219`
- Test: `tests/trading/executor/test_paper_executor.py`

**Step 1: Write failing test for short exit detection**

Create or add to test file:

```python
# tests/trading/executor/test_paper_executor.py

import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_is_exit_order_detects_short_exit():
    """Buy order should close a short (sell) position."""
    from trading.executor.paper_executor import PaperExecutor

    # Mock Redis
    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(return_value={
        "side": "sell",  # Short position
        "quantity": "0.01",
        "entry_price": "100000",
    })

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    # Buy order should close short position
    order = {"symbol": "BTC", "market": "futures", "side": "buy"}
    result = await executor._is_exit_order(order)

    assert result is True, "Buy should close short position"


@pytest.mark.asyncio
async def test_is_exit_order_detects_long_exit():
    """Sell order should close a long (buy) position."""
    from trading.executor.paper_executor import PaperExecutor

    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(return_value={
        "side": "buy",  # Long position
        "quantity": "0.01",
        "entry_price": "100000",
    })

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    order = {"symbol": "BTC", "market": "futures", "side": "sell"}
    result = await executor._is_exit_order(order)

    assert result is True, "Sell should close long position"


@pytest.mark.asyncio
async def test_is_exit_order_returns_false_for_new_position():
    """Order should not be exit if no position exists."""
    from trading.executor.paper_executor import PaperExecutor

    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(return_value=None)

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    order = {"symbol": "BTC", "market": "futures", "side": "sell"}
    result = await executor._is_exit_order(order)

    assert result is False, "No position means not an exit"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/trading/executor/test_paper_executor.py::test_is_exit_order_detects_short_exit -v
```

Expected: FAIL (current code only checks for long exits)

**Step 3: Fix the _is_exit_order method**

In `trading/executor/paper_executor.py`, replace the `_is_exit_order` method:

```python
async def _is_exit_order(self, order: dict) -> bool:
    """Check if order is an exit (closing position)."""
    symbol = order["symbol"]
    market = order["market"]
    order_side = order["side"]

    position = await self.redis.get_position(symbol, market)
    if not position:
        return False

    pos_side = position.get("side", "buy")

    # Long exit: sell closes buy
    # Short exit: buy closes sell
    return (
        (pos_side == "buy" and order_side == "sell") or
        (pos_side == "sell" and order_side == "buy")
    )
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/trading/executor/test_paper_executor.py -v -k "is_exit_order"
```

Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add trading/executor/paper_executor.py tests/trading/executor/test_paper_executor.py
git commit -m "fix: detect short position exits in paper executor"
```

---

### Task 1.2: Fix P&L Calculation for Short Positions

**Files:**
- Modify: `trading/executor/paper_executor.py:221-245`
- Test: `tests/trading/executor/test_paper_executor.py`

**Step 1: Write failing tests for short P&L calculation**

Add to test file:

```python
@pytest.mark.asyncio
async def test_calculate_pnl_for_profitable_short():
    """Short P&L: profit when price drops."""
    from trading.executor.paper_executor import PaperExecutor

    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(return_value={
        "side": "sell",  # Short position
        "quantity": "0.01",
        "entry_price": "100000",
        "leverage": "1",
    })
    mock_redis.get_risk = AsyncMock(return_value={"daily_pnl": "0"})
    mock_redis.hset = AsyncMock()

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    order = {"symbol": "BTC", "market": "futures", "side": "buy"}
    fill = {"filled_qty": 0.01, "filled_price": 95000}  # Price dropped

    result = await executor._calculate_exit_pnl(order, fill)

    # Short profit: (entry - exit) * qty = (100000 - 95000) * 0.01 = 50
    assert result["profit"] == pytest.approx(50.0, rel=0.01)
    assert result["profit_pct"] == pytest.approx(5.0, rel=0.01)


@pytest.mark.asyncio
async def test_calculate_pnl_for_losing_short():
    """Short P&L: loss when price rises."""
    from trading.executor.paper_executor import PaperExecutor

    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(return_value={
        "side": "sell",
        "quantity": "0.01",
        "entry_price": "100000",
        "leverage": "1",
    })
    mock_redis.get_risk = AsyncMock(return_value={"daily_pnl": "0"})
    mock_redis.hset = AsyncMock()

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    order = {"symbol": "BTC", "market": "futures", "side": "buy"}
    fill = {"filled_qty": 0.01, "filled_price": 102000}  # Price rose

    result = await executor._calculate_exit_pnl(order, fill)

    # Short loss: (entry - exit) * qty = (100000 - 102000) * 0.01 = -20
    assert result["profit"] == pytest.approx(-20.0, rel=0.01)
    assert result["profit_pct"] == pytest.approx(-2.0, rel=0.01)


@pytest.mark.asyncio
async def test_calculate_pnl_for_long_still_works():
    """Long P&L should still work correctly."""
    from trading.executor.paper_executor import PaperExecutor

    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(return_value={
        "side": "buy",
        "quantity": "0.01",
        "entry_price": "100000",
        "leverage": "1",
    })
    mock_redis.get_risk = AsyncMock(return_value={"daily_pnl": "0"})
    mock_redis.hset = AsyncMock()

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    order = {"symbol": "BTC", "market": "futures", "side": "sell"}
    fill = {"filled_qty": 0.01, "filled_price": 105000}  # Price rose

    result = await executor._calculate_exit_pnl(order, fill)

    # Long profit: (exit - entry) * qty = (105000 - 100000) * 0.01 = 50
    assert result["profit"] == pytest.approx(50.0, rel=0.01)
    assert result["profit_pct"] == pytest.approx(5.0, rel=0.01)
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/trading/executor/test_paper_executor.py::test_calculate_pnl_for_profitable_short -v
```

Expected: FAIL (current code calculates long P&L only)

**Step 3: Fix the _calculate_exit_pnl method**

In `trading/executor/paper_executor.py`, replace `_calculate_exit_pnl`:

```python
async def _calculate_exit_pnl(self, order: dict, fill: dict) -> dict | None:
    """Calculate P&L when exiting a position (long or short)."""
    symbol = order["symbol"]
    market = order["market"]

    position = await self.redis.get_position(symbol, market)
    if not position:
        return None

    entry_price = float(position.get("entry_price", 0))
    exit_price = fill["filled_price"]
    quantity = fill["filled_qty"]
    pos_side = position.get("side", "buy")
    leverage = int(position.get("leverage", 1))

    if entry_price <= 0 or quantity <= 0:
        return None

    # Calculate P&L based on position direction
    if pos_side == "buy":  # Long position
        pnl = (exit_price - entry_price) * quantity
    else:  # Short position
        pnl = (entry_price - exit_price) * quantity

    # Apply leverage
    pnl_with_leverage = pnl * leverage
    pnl_pct = ((pnl / entry_price) * 100) * leverage

    # Update daily P&L
    risk = await self.redis.get_risk()
    daily_pnl = float(risk.get("daily_pnl", 0)) + pnl_with_leverage
    await self.redis.hset("risk", {"daily_pnl": str(daily_pnl)})

    direction = "Long" if pos_side == "buy" else "Short"
    logger.info(f"Paper P&L ({direction}): {symbol} {pnl_with_leverage:+.2f} USDT ({pnl_pct:+.2f}%)")

    return {"profit": pnl_with_leverage, "profit_pct": pnl_pct}
```

**Step 4: Run all P&L tests**

```bash
pytest tests/trading/executor/test_paper_executor.py -v -k "calculate_pnl"
```

Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add trading/executor/paper_executor.py tests/trading/executor/test_paper_executor.py
git commit -m "fix: calculate P&L correctly for short positions"
```

---

### Task 1.3: Add Leverage to Position Storage

**Files:**
- Modify: `trading/executor/paper_executor.py:197-205`
- Modify: `trading/strategies/components/models.py`

**Step 1: Update Position model to include leverage**

In `trading/strategies/components/models.py`, find the Position dataclass and add leverage:

```python
@dataclass
class Position:
    """Current open position state."""

    symbol: str
    entry_price: float
    quantity: float
    side: str = "buy"  # "buy" for long, "sell" for short
    market: str = "spot"
    strategy: str = ""
    entry_time: int = 0
    leverage: int = 1  # NEW: leverage multiplier
    liquidation_price: float = 0.0  # NEW: for futures
```

**Step 2: Update _update_position to store leverage**

In `trading/executor/paper_executor.py`, modify `_update_position`:

```python
async def _update_position(self, order: dict, fill: dict) -> None:
    """Update position in Redis."""
    leverage = order.get("leverage", 1)

    await self.redis.set_position(order["symbol"], order["market"], {
        "quantity": str(fill["filled_qty"]),
        "entry_price": str(fill["filled_price"]),
        "strategy": order["strategy"],
        "entry_time": str(int(time.time() * 1000)),
        "side": order["side"],
        "leverage": str(leverage),
    })
```

**Step 3: Run existing tests to ensure no regression**

```bash
pytest tests/trading/executor/test_paper_executor.py -v
```

Expected: All tests PASS

**Step 4: Commit**

```bash
git add trading/executor/paper_executor.py trading/strategies/components/models.py
git commit -m "feat: add leverage tracking to position storage"
```

---

## Phase 2: LiquidationGuard

### Task 2.1: Create LiquidationGuard Class

**Files:**
- Create: `trading/risk/liquidation_guard.py`
- Test: `tests/trading/risk/test_liquidation_guard.py`

**Step 1: Write failing tests for liquidation price calculation**

Create test file:

```python
# tests/trading/risk/test_liquidation_guard.py

import pytest
from trading.risk.liquidation_guard import LiquidationGuard, LiquidationInfo


class TestLiquidationPriceCalculation:
    """Test liquidation price calculations for isolated margin."""

    def test_long_liquidation_price_5x(self):
        """Long 5x: liquidation when price drops ~20%."""
        guard = LiquidationGuard()

        liq_price = guard.calculate_liquidation_price(
            entry_price=100000,
            leverage=5,
            side="buy",
            position_value=10000,
        )

        # Formula: entry * (1 - 1/leverage + mmr)
        # 100000 * (1 - 0.20 + 0.004) = 80400
        assert liq_price == pytest.approx(80400, rel=0.01)

    def test_short_liquidation_price_5x(self):
        """Short 5x: liquidation when price rises ~20%."""
        guard = LiquidationGuard()

        liq_price = guard.calculate_liquidation_price(
            entry_price=100000,
            leverage=5,
            side="sell",
            position_value=10000,
        )

        # Formula: entry * (1 + 1/leverage - mmr)
        # 100000 * (1 + 0.20 - 0.004) = 119600
        assert liq_price == pytest.approx(119600, rel=0.01)

    def test_long_liquidation_price_10x(self):
        """Long 10x: liquidation when price drops ~10%."""
        guard = LiquidationGuard()

        liq_price = guard.calculate_liquidation_price(
            entry_price=100000,
            leverage=10,
            side="buy",
            position_value=10000,
        )

        # 100000 * (1 - 0.10 + 0.004) = 90400
        assert liq_price == pytest.approx(90400, rel=0.01)


class TestLiquidationDistanceCheck:
    """Test position safety checks."""

    def test_safe_long_position(self):
        """Position far from liquidation should be safe."""
        guard = LiquidationGuard()

        info = guard.check_position_safety(
            entry_price=100000,
            current_price=95000,
            liquidation_price=80400,
            side="buy",
        )

        assert info.should_exit is False
        assert info.distance_pct > 20  # Far from liquidation

    def test_dangerous_long_position(self):
        """Position close to liquidation should trigger exit."""
        guard = LiquidationGuard()

        info = guard.check_position_safety(
            entry_price=100000,
            current_price=82000,  # Very close to 80400 liquidation
            liquidation_price=80400,
            side="buy",
        )

        assert info.should_exit is True
        assert info.distance_pct < 20  # Within danger zone
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/trading/risk/test_liquidation_guard.py -v
```

Expected: FAIL (module doesn't exist)

**Step 3: Create LiquidationGuard implementation**

Create `trading/risk/liquidation_guard.py`:

```python
"""
LiquidationGuard - Monitors positions and triggers pre-emptive exits.

Calculates liquidation prices for isolated margin positions and
exits before reaching liquidation to protect capital.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class LiquidationInfo:
    """Information about position liquidation risk."""

    symbol: str
    side: str
    entry_price: float
    current_price: float
    liquidation_price: float
    distance_pct: float  # Distance to liquidation as percentage
    should_exit: bool    # True if within danger zone


class LiquidationGuard:
    """Monitors positions and triggers pre-emptive exits before liquidation."""

    # Exit when price is within this % of liquidation distance
    EXIT_THRESHOLD_PCT = 20.0

    # Binance maintenance margin rates by position notional value
    # https://www.binance.com/en/futures/trading-rules/perpetual/leverage-margin
    MAINTENANCE_MARGIN_RATES = [
        (50_000, 0.004),       # 0.4% for < $50k
        (250_000, 0.005),      # 0.5% for < $250k
        (1_000_000, 0.01),     # 1.0% for < $1M
        (5_000_000, 0.025),    # 2.5% for < $5M
        (float('inf'), 0.05),  # 5.0% for >= $5M
    ]

    def __init__(self, exit_threshold_pct: float = None):
        """Initialize LiquidationGuard.

        Args:
            exit_threshold_pct: Exit when within this % of liquidation. Default 20%.
        """
        self.exit_threshold_pct = exit_threshold_pct or self.EXIT_THRESHOLD_PCT

    def get_maintenance_margin_rate(self, position_value: float) -> float:
        """Get maintenance margin rate based on position size.

        Args:
            position_value: Position notional value in USDT.

        Returns:
            Maintenance margin rate as decimal (e.g., 0.004 for 0.4%).
        """
        for threshold, rate in self.MAINTENANCE_MARGIN_RATES:
            if position_value < threshold:
                return rate
        return self.MAINTENANCE_MARGIN_RATES[-1][1]

    def calculate_liquidation_price(
        self,
        entry_price: float,
        leverage: int,
        side: str,
        position_value: float,
    ) -> float:
        """Calculate liquidation price for isolated margin position.

        Args:
            entry_price: Position entry price.
            leverage: Leverage multiplier (e.g., 5 for 5x).
            side: "buy" for long, "sell" for short.
            position_value: Position notional value in USDT.

        Returns:
            Liquidation price.
        """
        mmr = self.get_maintenance_margin_rate(position_value)

        if side == "buy":  # Long
            # Liquidation when price drops
            # Liq = Entry * (1 - 1/Leverage + MMR)
            liq_price = entry_price * (1 - (1 / leverage) + mmr)
        else:  # Short
            # Liquidation when price rises
            # Liq = Entry * (1 + 1/Leverage - MMR)
            liq_price = entry_price * (1 + (1 / leverage) - mmr)

        return liq_price

    def check_position_safety(
        self,
        entry_price: float,
        current_price: float,
        liquidation_price: float,
        side: str,
        symbol: str = "UNKNOWN",
    ) -> LiquidationInfo:
        """Check if position is in danger of liquidation.

        Args:
            entry_price: Position entry price.
            current_price: Current market price.
            liquidation_price: Pre-calculated liquidation price.
            side: "buy" for long, "sell" for short.
            symbol: Trading symbol for logging.

        Returns:
            LiquidationInfo with safety assessment.
        """
        if side == "buy":  # Long
            # Distance = how far current price is from liquidation
            # For longs, liquidation is below current price
            total_distance = entry_price - liquidation_price
            current_distance = current_price - liquidation_price
        else:  # Short
            # For shorts, liquidation is above current price
            total_distance = liquidation_price - entry_price
            current_distance = liquidation_price - current_price

        # Calculate distance as percentage of total range
        if total_distance > 0:
            distance_pct = (current_distance / total_distance) * 100
        else:
            distance_pct = 100.0  # Safe if no distance

        # Determine if should exit
        should_exit = distance_pct < self.exit_threshold_pct

        if should_exit:
            logger.warning(
                f"LIQUIDATION WARNING: {symbol} {side.upper()} is {distance_pct:.1f}% "
                f"from liquidation (threshold: {self.exit_threshold_pct}%)"
            )

        return LiquidationInfo(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            current_price=current_price,
            liquidation_price=liquidation_price,
            distance_pct=distance_pct,
            should_exit=should_exit,
        )
```

**Step 4: Run tests**

```bash
pytest tests/trading/risk/test_liquidation_guard.py -v
```

Expected: All tests PASS

**Step 5: Commit**

```bash
git add trading/risk/liquidation_guard.py tests/trading/risk/test_liquidation_guard.py
git commit -m "feat: add LiquidationGuard for pre-emptive exit protection"
```

---

### Task 2.2: Export LiquidationGuard from risk module

**Files:**
- Modify: `trading/risk/__init__.py`

**Step 1: Add export**

In `trading/risk/__init__.py`, add:

```python
from trading.risk.liquidation_guard import LiquidationGuard, LiquidationInfo
```

**Step 2: Commit**

```bash
git add trading/risk/__init__.py
git commit -m "chore: export LiquidationGuard from risk module"
```

---

## Phase 3: FundingTracker

### Task 3.1: Create FundingTracker Class

**Files:**
- Create: `trading/risk/funding_tracker.py`
- Test: `tests/trading/risk/test_funding_tracker.py`

**Step 1: Write failing tests**

Create test file:

```python
# tests/trading/risk/test_funding_tracker.py

import pytest
from trading.risk.funding_tracker import FundingTracker


class TestFundingPaymentCalculation:
    """Test funding payment calculations."""

    def test_long_pays_positive_funding(self):
        """Long pays when funding rate is positive."""
        tracker = FundingTracker()

        payment = tracker.calculate_funding_payment(
            position_value=10000,  # $10k position
            rate=0.0001,           # 0.01% funding rate
            side="buy",
        )

        # Long pays: -10000 * 0.0001 = -1.0
        assert payment == pytest.approx(-1.0, rel=0.01)

    def test_short_receives_positive_funding(self):
        """Short receives when funding rate is positive."""
        tracker = FundingTracker()

        payment = tracker.calculate_funding_payment(
            position_value=10000,
            rate=0.0001,
            side="sell",
        )

        # Short receives: +10000 * 0.0001 = +1.0
        assert payment == pytest.approx(1.0, rel=0.01)

    def test_long_receives_negative_funding(self):
        """Long receives when funding rate is negative."""
        tracker = FundingTracker()

        payment = tracker.calculate_funding_payment(
            position_value=10000,
            rate=-0.0002,  # -0.02% negative rate
            side="buy",
        )

        # Long receives: -10000 * -0.0002 = +2.0
        assert payment == pytest.approx(2.0, rel=0.01)

    def test_short_pays_negative_funding(self):
        """Short pays when funding rate is negative."""
        tracker = FundingTracker()

        payment = tracker.calculate_funding_payment(
            position_value=10000,
            rate=-0.0002,
            side="sell",
        )

        # Short pays: +10000 * -0.0002 = -2.0
        assert payment == pytest.approx(-2.0, rel=0.01)
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/trading/risk/test_funding_tracker.py -v
```

Expected: FAIL (module doesn't exist)

**Step 3: Create FundingTracker implementation**

Create `trading/risk/funding_tracker.py`:

```python
"""
FundingTracker - Fetches and applies Binance funding rates.

Binance perpetual futures have funding payments at 00:00, 08:00, 16:00 UTC.
Positive rate: longs pay shorts.
Negative rate: shorts pay longs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FundingRate:
    """Current funding rate information."""

    symbol: str
    rate: float               # e.g., 0.0001 = 0.01%
    next_funding_time: datetime


class FundingTracker:
    """Tracks and applies funding rates to futures positions."""

    # Funding times in UTC
    FUNDING_HOURS_UTC = [0, 8, 16]

    def __init__(self, binance_client=None):
        """Initialize FundingTracker.

        Args:
            binance_client: Optional BinanceClient for fetching live rates.
        """
        self._client = binance_client
        self._rate_cache: dict[str, FundingRate] = {}

    def calculate_funding_payment(
        self,
        position_value: float,
        rate: float,
        side: str,
    ) -> float:
        """Calculate funding payment for a position.

        Args:
            position_value: Position notional value in USDT.
            rate: Funding rate as decimal (e.g., 0.0001 for 0.01%).
            side: "buy" for long, "sell" for short.

        Returns:
            Payment amount (negative = you pay, positive = you receive).
        """
        # Funding payment formula:
        # Payment = Position Value × Funding Rate
        #
        # If rate > 0: longs pay shorts
        # If rate < 0: shorts pay longs

        if side == "buy":  # Long
            # Long pays when rate is positive (negative payment)
            # Long receives when rate is negative (positive payment)
            return -position_value * rate
        else:  # Short
            # Short receives when rate is positive (positive payment)
            # Short pays when rate is negative (negative payment)
            return position_value * rate

    async def get_funding_rate(self, symbol: str) -> Optional[FundingRate]:
        """Fetch current funding rate from Binance.

        Args:
            symbol: Trading symbol (e.g., "BTC" or "BTCUSDT").

        Returns:
            FundingRate or None if fetch fails.
        """
        if not self._client:
            logger.warning("No Binance client configured for funding rates")
            return None

        # Normalize symbol
        pair = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol

        try:
            # GET /fapi/v1/premiumIndex
            data = await self._client._futures_client.futures_mark_price(symbol=pair)

            rate = float(data.get("lastFundingRate", 0))
            next_time = int(data.get("nextFundingTime", 0))

            funding_rate = FundingRate(
                symbol=symbol,
                rate=rate,
                next_funding_time=datetime.fromtimestamp(next_time / 1000, tz=timezone.utc),
            )

            # Cache it
            self._rate_cache[symbol] = funding_rate

            logger.info(
                f"Funding rate for {symbol}: {rate*100:.4f}%, "
                f"next: {funding_rate.next_funding_time}"
            )

            return funding_rate

        except Exception as e:
            logger.error(f"Failed to fetch funding rate for {symbol}: {e}")
            # Return cached rate if available
            return self._rate_cache.get(symbol)

    def get_next_funding_time(self) -> datetime:
        """Get the next funding time in UTC.

        Returns:
            Next funding datetime.
        """
        now = datetime.now(timezone.utc)
        current_hour = now.hour

        # Find next funding hour
        for hour in self.FUNDING_HOURS_UTC:
            if hour > current_hour:
                return now.replace(hour=hour, minute=0, second=0, microsecond=0)

        # Next funding is tomorrow at 00:00 UTC
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        return tomorrow + timedelta(days=1)

    def is_funding_time(self) -> bool:
        """Check if current time is within a funding window.

        Returns:
            True if within 1 minute of a funding time.
        """
        now = datetime.now(timezone.utc)
        return now.hour in self.FUNDING_HOURS_UTC and now.minute < 1
```

**Step 4: Run tests**

```bash
pytest tests/trading/risk/test_funding_tracker.py -v
```

Expected: All tests PASS

**Step 5: Commit**

```bash
git add trading/risk/funding_tracker.py tests/trading/risk/test_funding_tracker.py
git commit -m "feat: add FundingTracker for Binance funding rate integration"
```

---

### Task 3.2: Export FundingTracker from risk module

**Files:**
- Modify: `trading/risk/__init__.py`

**Step 1: Add export**

```python
from trading.risk.funding_tracker import FundingTracker, FundingRate
```

**Step 2: Commit**

```bash
git add trading/risk/__init__.py
git commit -m "chore: export FundingTracker from risk module"
```

---

## Phase 4: Integration

### Task 4.1: Integrate LiquidationGuard with PaperExecutor

**Files:**
- Modify: `trading/executor/paper_executor.py`

**Step 1: Add LiquidationGuard to PaperExecutor**

In `trading/executor/paper_executor.py`, update imports and __init__:

```python
from trading.risk.liquidation_guard import LiquidationGuard

class PaperExecutor:
    def __init__(self, redis: RedisStreams, config: dict):
        # ... existing code ...

        # Add liquidation guard
        self.liquidation_guard = LiquidationGuard()
```

**Step 2: Calculate liquidation price when opening position**

Update `_update_position`:

```python
async def _update_position(self, order: dict, fill: dict) -> None:
    """Update position in Redis with liquidation price."""
    leverage = int(order.get("leverage", 1))
    position_value = fill["filled_price"] * fill["filled_qty"]

    # Calculate liquidation price
    liq_price = self.liquidation_guard.calculate_liquidation_price(
        entry_price=fill["filled_price"],
        leverage=leverage,
        side=order["side"],
        position_value=position_value,
    )

    await self.redis.set_position(order["symbol"], order["market"], {
        "quantity": str(fill["filled_qty"]),
        "entry_price": str(fill["filled_price"]),
        "strategy": order["strategy"],
        "entry_time": str(int(time.time() * 1000)),
        "side": order["side"],
        "leverage": str(leverage),
        "liquidation_price": str(liq_price),
    })

    logger.info(
        f"Position opened: {order['symbol']} {order['side'].upper()} "
        f"{leverage}x @ {fill['filled_price']}, liq: {liq_price:.2f}"
    )
```

**Step 3: Commit**

```bash
git add trading/executor/paper_executor.py
git commit -m "feat: integrate LiquidationGuard with PaperExecutor"
```

---

### Task 4.2: Run Full Test Suite

**Step 1: Run all tests**

```bash
pytest tests/ --ignore=tests/test_web_api.py --ignore=tests/web/ -v 2>&1 | tail -30
```

Expected: All tests PASS

**Step 2: Final commit if any cleanup needed**

```bash
git status
# If any uncommitted changes:
git add -A && git commit -m "chore: test cleanup and fixes"
```

---

## Summary

| Phase | Tasks | Description |
|-------|-------|-------------|
| 1 | 1.1-1.3 | Fix PaperExecutor for short positions |
| 2 | 2.1-2.2 | Create LiquidationGuard |
| 3 | 3.1-3.2 | Create FundingTracker |
| 4 | 4.1-4.2 | Integration and testing |

**Total Tasks:** 9
**Estimated Commits:** 9-10
