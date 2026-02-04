# Spot Trading Restoration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore spot trading functionality for V35 strategies while maintaining futures for Short/Sideways strategies.

**Architecture:** Unified BinanceClient with market branching in executors. V35 strategies use `market: "spot"`, Short/Sideways use `market: "futures"`. Dashboard shows hybrid view with combined summary and separated details.

**Tech Stack:** Python 3.12, asyncio, Redis, Flask, Binance API, pytest

**Reference Commit:** `cb172607^` (code before spot removal)

---

## Task 1: Restore BinanceClient Spot Methods

**Files:**
- Modify: `trading/executor/binance_client.py`
- Test: `tests/trading/executor/test_binance_client.py`

**Step 1: Update docstring and add spot order method**

```python
# trading/executor/binance_client.py line 1-2
"""Unified Binance client for spot and futures trading."""
```

**Step 2: Restore place_order market branching**

In `place_order` method, restore spot trading path:

```python
async def place_order(
    self,
    symbol: str,
    side: str,
    quantity: float,
    market: str = "futures",
    position_side: str | None = None,
) -> dict[str, Any]:
    """Execute market order on spot or futures.

    Args:
        symbol: Trading symbol (e.g., "BTC").
        side: Order side ("buy" or "sell").
        quantity: Order quantity.
        market: Market type ("spot" or "futures").
        position_side: Position side for hedge mode ("LONG" or "SHORT").
                      Required for futures in hedge mode.
    """
    pair = f"{symbol}USDT"

    try:
        if market == "futures":
            order_params = {
                "symbol": pair,
                "side": side.upper(),
                "type": "MARKET",
                "quantity": quantity,
            }
            if self._hedge_mode_enabled and position_side:
                order_params["positionSide"] = position_side.upper()

            result = await self._futures_client.futures_create_order(**order_params)
            filled_price = float(result.get("avgPrice", 0)) or \
                           float(result["cumQuote"]) / float(result["executedQty"])
        else:  # spot
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
```

**Step 3: Restore get_all_positions to include spot**

```python
async def get_all_positions(self) -> list[dict[str, Any]]:
    """Get all positions from both spot and futures."""
    spot = await self.get_spot_positions()
    futures = await self.get_futures_positions()
    return spot + futures
```

**Step 4: Add test for spot order**

```python
# tests/trading/executor/test_binance_client.py

@pytest.mark.asyncio
async def test_place_spot_order():
    """Test spot market order execution."""
    client = BinanceClient("key", "secret")
    client._spot_client = AsyncMock()
    client._spot_client.create_order = AsyncMock(return_value={
        "orderId": 12345,
        "executedQty": "0.1",
        "cummulativeQuoteQty": "9500.0",
        "status": "FILLED",
    })

    result = await client.place_order(
        symbol="BTC",
        side="buy",
        quantity=0.1,
        market="spot",
    )

    assert result["market"] == "spot"
    assert result["filled_qty"] == 0.1
    assert result["filled_price"] == 95000.0
    client._spot_client.create_order.assert_called_once()
```

**Step 5: Run tests**

```bash
DASHBOARD_PASSWORD=test pytest tests/trading/executor/test_binance_client.py -v
```

**Step 6: Commit**

```bash
git add trading/executor/binance_client.py tests/trading/executor/test_binance_client.py
git commit -m "feat(client): restore spot trading in BinanceClient"
```

---

## Task 2: Update AsyncExecutor for Market Branching

**Files:**
- Modify: `trading/executor/async_executor.py`
- Test: `tests/trading/executor/test_async_executor.py`

**Step 1: Update execute method for market branching**

The executor should handle spot orders without leverage/liquidation checks:

```python
async def _execute_order(self, order: dict) -> None:
    """Execute order based on market type."""
    market = order.get("market", "futures")
    symbol = order["symbol"]

    if market == "spot":
        # Spot: no leverage, no liquidation check
        await self._execute_spot_order(order)
    else:
        # Futures: existing logic with leverage
        await self._execute_futures_order(order)

async def _execute_spot_order(self, order: dict) -> None:
    """Execute spot order - simplified flow without leverage."""
    symbol = order["symbol"]
    side = order["side"]
    quantity = order["quantity"]

    result = await self.client.place_order(
        symbol=symbol,
        side=side,
        quantity=quantity,
        market="spot",
    )

    # Update Redis position
    await self._update_spot_position(symbol, result)

    # Publish to trades stream
    await self._publish_trade(result)
```

**Step 2: Add spot position update method**

```python
async def _update_spot_position(self, symbol: str, fill: dict) -> None:
    """Update Redis spot position after fill."""
    key = f"positions:{symbol}:spot"

    if fill["side"].lower() == "buy":
        # Add to position
        current = await self.redis.hgetall(key)
        current_qty = float(current.get("quantity", 0))
        current_avg = float(current.get("entry_price", 0))

        new_qty = current_qty + fill["filled_qty"]
        # Weighted average entry price
        if new_qty > 0:
            new_avg = (current_qty * current_avg + fill["filled_qty"] * fill["filled_price"]) / new_qty
        else:
            new_avg = fill["filled_price"]

        await self.redis.hset(key, mapping={
            "quantity": str(new_qty),
            "entry_price": str(new_avg),
            "market": "spot",
            "strategy": fill.get("strategy", ""),
            "timestamp": str(int(time.time() * 1000)),
        })
    else:
        # Reduce position
        current = await self.redis.hgetall(key)
        current_qty = float(current.get("quantity", 0))
        new_qty = max(0, current_qty - fill["filled_qty"])

        if new_qty == 0:
            await self.redis.delete(key)
        else:
            await self.redis.hset(key, "quantity", str(new_qty))
```

**Step 3: Add test**

```python
@pytest.mark.asyncio
async def test_executor_handles_spot_order():
    """Test executor routes spot orders correctly."""
    executor = AsyncExecutor(redis_mock, client_mock)

    order = {
        "symbol": "BTC",
        "side": "buy",
        "quantity": 0.1,
        "market": "spot",
        "strategy": "v35_classic_wide",
    }

    await executor._execute_order(order)

    # Verify spot method called, not futures
    client_mock.place_order.assert_called_with(
        symbol="BTC",
        side="buy",
        quantity=0.1,
        market="spot",
    )
```

**Step 4: Run tests**

```bash
DASHBOARD_PASSWORD=test pytest tests/trading/executor/test_async_executor.py -v
```

**Step 5: Commit**

```bash
git add trading/executor/async_executor.py tests/trading/executor/test_async_executor.py
git commit -m "feat(executor): add spot order handling to AsyncExecutor"
```

---

## Task 3: Update PaperExecutor for Spot Simulation

**Files:**
- Modify: `trading/executor/paper_executor.py`
- Test: `tests/trading/executor/test_paper_executor.py`

**Step 1: Add spot balance and position tracking**

```python
class PaperExecutor:
    def __init__(self, ...):
        # Existing futures tracking
        self.futures_balance: float = initial_balance
        self.futures_positions: dict = {}

        # Add spot tracking
        self.spot_balance: float = initial_balance
        self.spot_positions: dict = {}

        # Fee rates
        self.spot_fee_rate: float = 0.001  # 0.1%
        self.futures_fee_rate: float = 0.0005  # 0.05%
```

**Step 2: Add spot simulation method**

```python
async def _simulate_spot_fill(self, order: dict) -> dict:
    """Simulate spot order fill."""
    symbol = order["symbol"]
    side = order["side"].lower()
    quantity = order["quantity"]
    price = order.get("price", await self._get_current_price(symbol))

    # Apply fee
    fee = quantity * price * self.spot_fee_rate

    if side == "buy":
        cost = quantity * price + fee
        if cost > self.spot_balance:
            raise ValueError(f"Insufficient spot balance: need {cost}, have {self.spot_balance}")

        self.spot_balance -= cost

        # Update position
        if symbol in self.spot_positions:
            pos = self.spot_positions[symbol]
            new_qty = pos["quantity"] + quantity
            new_avg = (pos["quantity"] * pos["entry_price"] + quantity * price) / new_qty
            pos["quantity"] = new_qty
            pos["entry_price"] = new_avg
        else:
            self.spot_positions[symbol] = {
                "quantity": quantity,
                "entry_price": price,
                "market": "spot",
            }
    else:  # sell
        if symbol not in self.spot_positions:
            raise ValueError(f"No spot position for {symbol}")

        pos = self.spot_positions[symbol]
        if quantity > pos["quantity"]:
            raise ValueError(f"Cannot sell more than held: {quantity} > {pos['quantity']}")

        proceeds = quantity * price - fee
        self.spot_balance += proceeds

        pos["quantity"] -= quantity
        if pos["quantity"] == 0:
            del self.spot_positions[symbol]

    return {
        "order_id": int(time.time() * 1000),
        "symbol": symbol,
        "side": side,
        "market": "spot",
        "filled_qty": quantity,
        "filled_price": price,
        "fee": fee,
        "status": "FILLED",
    }
```

**Step 3: Route orders by market**

```python
async def execute_order(self, order: dict) -> dict:
    """Execute paper order based on market type."""
    market = order.get("market", "futures")

    if market == "spot":
        return await self._simulate_spot_fill(order)
    else:
        return await self._simulate_futures_fill(order)
```

**Step 4: Add test**

```python
@pytest.mark.asyncio
async def test_paper_executor_spot_buy():
    """Test paper executor simulates spot buy."""
    executor = PaperExecutor(initial_balance=10000)

    result = await executor.execute_order({
        "symbol": "BTC",
        "side": "buy",
        "quantity": 0.1,
        "price": 95000,
        "market": "spot",
    })

    assert result["market"] == "spot"
    assert result["filled_qty"] == 0.1
    assert executor.spot_balance < 10000  # Deducted
    assert "BTC" in executor.spot_positions
```

**Step 5: Run tests**

```bash
DASHBOARD_PASSWORD=test pytest tests/trading/executor/test_paper_executor.py -v
```

**Step 6: Commit**

```bash
git add trading/executor/paper_executor.py tests/trading/executor/test_paper_executor.py
git commit -m "feat(paper): add spot trading simulation to PaperExecutor"
```

---

## Task 4: Update Strategy Configuration

**Files:**
- Modify: `config/strategies/allocation.json`
- Modify: `trading/strategies/components/strategy_factory.py`

**Step 1: Add spot config section**

```json
{
  "spot": {
    "enabled": true,
    "fee_rate": 0.001
  },
  "futures": {
    "enabled": true,
    "default_leverage": 3
  }
}
```

**Step 2: Change V35 strategies to spot**

For each V35 strategy (`v35_classic_wide`, `tuned_v35_long_v2_core_overlay_v2`):

```json
{
  "v35_classic_wide": {
    "market": "spot",  // Changed from "futures"
    // ... rest unchanged
  }
}
```

**Step 3: Update StrategyFactory.get_market()**

```python
def get_market(self, strategy_name: str) -> str:
    """Get market type for strategy."""
    config = self._get_strategy_config(strategy_name)
    return config.get("market", "futures")
```

**Step 4: Verify with test**

```python
def test_v35_strategies_use_spot():
    """Verify V35 strategies are configured for spot."""
    factory = StrategyFactory(redis=None)

    v35_strategies = [
        "v35_classic_wide",
        "tuned_v35_long_v2_core_overlay_v2",
    ]

    for name in v35_strategies:
        assert factory.get_market(name) == "spot", f"{name} should use spot"

    # Short/Sideways should stay on futures
    assert factory.get_market("short_v1") == "futures"
```

**Step 5: Commit**

```bash
git add config/strategies/allocation.json trading/strategies/components/strategy_factory.py
git commit -m "config: migrate V35 strategies to spot trading"
```

---

## Task 5: Update Redis Key Schema

**Files:**
- Modify: `trading/streams/base_strategy.py`
- Modify: `trading/strategies/components/composite_task.py`

**Step 1: Update position key format**

```python
def get_position_key(symbol: str, market: str) -> str:
    """Get Redis key for position."""
    return f"positions:{symbol}:{market}"  # e.g., positions:BTC:spot
```

**Step 2: Update composite_task to use market-aware keys**

```python
async def _get_position(self, symbol: str) -> dict | None:
    """Get current position for symbol."""
    market = self.config.get("market", "futures")
    key = f"positions:{symbol}:{market}"
    return await self.redis.hgetall(key)
```

**Step 3: Commit**

```bash
git add trading/streams/base_strategy.py trading/strategies/components/composite_task.py
git commit -m "feat(redis): add market-aware position key schema"
```

---

## Task 6: Update Backtester for Spot

**Files:**
- Modify: `core/backtester.py`
- Modify: `scripts/backtest_risk_based_sizing.py`

**Step 1: Add market parameter to Backtester**

```python
class Backtester:
    def __init__(
        self,
        initial_capital: float = 10000,
        fee_rate: float = None,  # Auto-detect from market
        market: str = "futures",
    ):
        self.market = market

        if fee_rate is None:
            self.fee_rate = 0.001 if market == "spot" else 0.0005
        else:
            self.fee_rate = fee_rate

        # Spot has no leverage
        self.leverage = 1 if market == "spot" else 3
```

**Step 2: Disable liquidation for spot**

```python
def _check_liquidation(self, position, price) -> bool:
    """Check if position is liquidated (spot never liquidates)."""
    if self.market == "spot":
        return False
    return self._calculate_futures_liquidation(position, price)
```

**Step 3: Update backtest script**

```python
def main():
    # Get market from config
    market = config.get("market", "futures")

    backtester = RiskBasedBacktester(
        initial_capital=args.capital,
        fee_rate=0.001 if market == "spot" else 0.0005,
        market=market,
    )
```

**Step 4: Commit**

```bash
git add core/backtester.py scripts/backtest_risk_based_sizing.py
git commit -m "feat(backtest): add spot market support to backtester"
```

---

## Task 7: Add Enhanced Backtest Charts

**Files:**
- Modify: `scripts/backtest_risk_based_sizing.py`
- Create: `core/metrics.py` (add judgment metrics)

**Step 1: Add judgment metrics functions**

```python
# core/metrics.py

def calculate_cagr(equity_curve: pd.DataFrame, years: float) -> float:
    """Calculate Compound Annual Growth Rate."""
    if years <= 0:
        return 0.0
    start = equity_curve['total_equity'].iloc[0]
    end = equity_curve['total_equity'].iloc[-1]
    return (pow(end / start, 1 / years) - 1) * 100

def calculate_sortino_ratio(equity_curve: pd.DataFrame, risk_free: float = 0.0) -> float:
    """Calculate Sortino ratio (downside risk only)."""
    returns = equity_curve['total_equity'].pct_change().dropna()
    excess = returns - risk_free / 252
    downside = returns[returns < 0].std() * np.sqrt(252)
    if downside == 0:
        return 0.0
    return (returns.mean() * 252 - risk_free) / downside

def calculate_calmar_ratio(cagr: float, max_drawdown: float) -> float:
    """Calculate Calmar ratio (CAGR / MDD)."""
    if max_drawdown == 0:
        return 0.0
    return cagr / abs(max_drawdown)
```

**Step 2: Add 4-panel chart function**

```python
def create_judgment_chart(results: dict, df: pd.DataFrame, output_path: str):
    """Create 4-panel judgment chart."""
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # Panel 1: Equity vs Benchmark
    # Panel 2: Drawdown comparison
    # Panel 3: Trade distribution
    # Panel 4: Monthly returns heatmap

    # ... implementation

    plt.savefig(output_path, dpi=150, bbox_inches='tight')
```

**Step 3: Add judgment summary**

```python
def print_judgment_summary(results: dict, benchmark_return: float):
    """Print detailed judgment metrics."""
    print("\n" + "="*60)
    print("              JUDGMENT METRICS SUMMARY")
    print("="*60)
    # ... metrics comparison
```

**Step 4: Commit**

```bash
git add core/metrics.py scripts/backtest_risk_based_sizing.py
git commit -m "feat(backtest): add enhanced judgment charts and metrics"
```

---

## Task 8: Update Dashboard API

**Files:**
- Modify: `web/app.py`
- Test: `tests/web/test_app.py`

**Step 1: Add summary endpoint**

```python
@app.route('/api/summary')
@require_auth
def get_summary():
    """Get combined spot + futures summary."""
    spot_balance = get_spot_balance()
    futures_balance = get_futures_balance()
    spot_positions = get_spot_positions()
    futures_positions = get_futures_positions()

    return jsonify({
        "total_equity": spot_balance + futures_balance,
        "spot": {
            "balance": spot_balance,
            "positions": len(spot_positions),
        },
        "futures": {
            "balance": futures_balance,
            "positions": len(futures_positions),
        },
        "positions": spot_positions + futures_positions,
    })
```

**Step 2: Add spot-specific endpoints**

```python
@app.route('/api/spot/positions')
@require_auth
def get_spot_positions_api():
    """Get spot positions."""
    # Implementation

@app.route('/api/spot/balance')
@require_auth
def get_spot_balance_api():
    """Get spot balance."""
    # Implementation
```

**Step 3: Commit**

```bash
git add web/app.py tests/web/test_app.py
git commit -m "feat(api): add spot trading endpoints to dashboard"
```

---

## Task 9: Update Dashboard UI

**Files:**
- Modify: `web/templates/dashboard.html`
- Modify: `web/static/js/dashboard.js`

**Step 1: Add hybrid view layout**

Main dashboard shows combined summary with spot/futures cards.

**Step 2: Add tab navigation**

```html
<div class="tabs">
    <button class="tab active" data-tab="all">All</button>
    <button class="tab" data-tab="spot">Spot</button>
    <button class="tab" data-tab="futures">Futures</button>
</div>
```

**Step 3: Add JavaScript tab switching**

```javascript
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        const market = tab.dataset.tab;
        filterPositions(market);
    });
});
```

**Step 4: Commit**

```bash
git add web/templates/dashboard.html web/static/js/dashboard.js
git commit -m "feat(ui): add hybrid spot/futures dashboard view"
```

---

## Task 10: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update trading mode section**

```markdown
## Trading Mode

**Hybrid trading mode.** V35 strategies execute on Binance Spot, Short/Sideways strategies execute on Binance Futures.

- **Spot**: V35 strategies (no leverage, lower fees 0.1%)
- **Futures**: Short/Sideways strategies (leverage, hedging)
```

**Step 2: Update Redis section**

```markdown
### Hashes

- `positions:{symbol}:spot`: Spot position state (qty, entry_price, strategy).
- `positions:{symbol}:futures`: Futures position state (qty, entry_price, leverage).
```

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for hybrid spot/futures trading"
```

---

## Task 11: Final Integration Test

**Step 1: Run full test suite**

```bash
DASHBOARD_PASSWORD=test pytest tests/ -v --tb=short
```

**Step 2: Run spot backtest**

```bash
python scripts/backtest_risk_based_sizing.py --start 2024-01-01 --output outputs
```

**Step 3: Verify results show spot characteristics**

- Fee rate: 0.1%
- No leverage shown
- No funding costs
- No liquidation events

**Step 4: Final commit**

```bash
git add -A
git commit -m "test: verify spot trading integration"
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | BinanceClient spot methods | 2 |
| 2 | AsyncExecutor market branching | 2 |
| 3 | PaperExecutor spot simulation | 2 |
| 4 | Strategy configuration | 2 |
| 5 | Redis key schema | 2 |
| 6 | Backtester spot support | 2 |
| 7 | Enhanced judgment charts | 2 |
| 8 | Dashboard API | 2 |
| 9 | Dashboard UI | 2 |
| 10 | Documentation | 1 |
| 11 | Integration test | 0 |
| **Total** | | **~19 files** |
