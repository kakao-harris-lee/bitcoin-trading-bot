# Dynamic Rebalancing Design

**Date:** 2025-12-28
**Status:** Approved
**Scope:** Unified Position Manager with automatic delta-neutral rebalancing

## Problem

When Alpha strategies execute trades (buy/sell BTC on Upbit), the hedge position on Binance is NOT adjusted, breaking delta neutrality.

**Example:**
```
Start:    Upbit 0.5 BTC long + Binance 0.5 BTC short = Delta neutral
Alpha buys 0.1 BTC → Upbit 0.6 BTC + Binance 0.5 BTC = +0.1 BTC exposure!
```

Current HedgeManager only opens/closes based on premium signals, not position changes.

## Solution

Create a **Unified Position Manager** that:
1. Tracks all positions (Upbit long + Binance short) centrally
2. Calculates delta drift in real-time
3. Uses dynamic threshold based on premium volatility
4. Triggers automatic rebalancing when drift exceeds threshold

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  PositionManager                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │ Upbit Long  │  │Binance Short│  │ Delta Calc  │ │
│  │  Tracking   │  │  Tracking   │  │  + Trigger  │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘ │
│         └────────────────┴────────────────┘         │
│                          │                          │
│              on_alpha_trade() / flush_rebalance()   │
│                          │                          │
│              ┌───────────▼───────────┐             │
│              │  Dynamic Threshold    │             │
│              │  (from premium σ)     │             │
│              └───────────┬───────────┘             │
└──────────────────────────┼──────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │    HedgeManager         │
              │  adjust_position(qty)   │
              └─────────────────────────┘
```

## Dynamic Threshold

Threshold varies by premium volatility (σ from PremiumController):

| Market State | Premium σ | Threshold | Rationale |
|--------------|-----------|-----------|-----------|
| Calm | < 0.5% | 3% | Low rebalance cost, tight neutrality |
| Normal | 0.5-1.5% | 5% | Balanced |
| Volatile | > 1.5% | 8% | Avoid whipsaw rebalances |

## New Component: PositionManager

**File:** `trading/execution/position_manager.py`

```python
@dataclass
class DeltaState:
    """Current delta exposure state."""
    long_btc: float          # Upbit BTC holdings
    short_btc: float         # Binance short position
    net_delta: float         # long - short
    drift_pct: float         # abs(net_delta) / long_btc * 100
    threshold_pct: float     # Current dynamic threshold
    needs_rebalance: bool    # drift_pct > threshold_pct

@dataclass
class RebalanceResult:
    """Result of a rebalance operation."""
    direction: str           # "increase" or "decrease"
    qty_adjusted: float      # BTC quantity adjusted
    new_short_qty: float     # New total short position
    fees_paid: float         # Fees for adjustment
    success: bool

class PositionManager:
    """Unified position tracking with automatic rebalancing."""

    def __init__(
        self,
        upbit_account: PaperTradingAccount,
        hedge_manager: HedgeManager,
        premium_controller: PremiumController,
        config: Dict[str, Any],
    ):
        self.upbit_account = upbit_account
        self.hedge_manager = hedge_manager
        self.premium_controller = premium_controller

        # Threshold config
        self.calm_threshold = config.get("calm_threshold_pct", 3.0)
        self.normal_threshold = config.get("normal_threshold_pct", 5.0)
        self.volatile_threshold = config.get("volatile_threshold_pct", 8.0)
        self.volatility_calm = config.get("volatility_calm", 0.5)
        self.volatility_high = config.get("volatility_high", 1.5)

        # Batching state
        self._pending_delta: float = 0.0
        self._last_rebalance_time: Optional[datetime] = None
        self._min_rebalance_interval: int = config.get("min_rebalance_interval", 30)

    def get_dynamic_threshold(self) -> float:
        """Calculate threshold based on premium volatility."""
        stats = self.premium_controller.get_stats()
        if stats is None:
            return self.normal_threshold

        sigma = stats.std
        if sigma < self.volatility_calm:
            return self.calm_threshold
        elif sigma > self.volatility_high:
            return self.volatile_threshold
        else:
            # Linear interpolation
            ratio = (sigma - self.volatility_calm) / (self.volatility_high - self.volatility_calm)
            return self.calm_threshold + ratio * (self.volatile_threshold - self.calm_threshold)

    def get_delta_state(self) -> DeltaState:
        """Calculate current delta exposure."""
        _, long_btc = self.upbit_account.get_balance()
        short_btc = self.hedge_manager.hedge_position.qty if self.hedge_manager.hedge_position else 0.0

        net_delta = long_btc - short_btc
        drift_pct = abs(net_delta) / long_btc * 100 if long_btc > 0 else 0.0
        threshold_pct = self.get_dynamic_threshold()

        return DeltaState(
            long_btc=long_btc,
            short_btc=short_btc,
            net_delta=net_delta,
            drift_pct=drift_pct,
            threshold_pct=threshold_pct,
            needs_rebalance=drift_pct > threshold_pct,
        )

    def on_alpha_trade(self, qty_change: float, direction: str) -> None:
        """Accumulate delta changes from Alpha trades."""
        if direction == "buy":
            self._pending_delta += qty_change
        else:
            self._pending_delta -= qty_change

    async def flush_rebalance(self, binance_price: float) -> Optional[RebalanceResult]:
        """Execute batched rebalance if threshold exceeded."""
        if not self.hedge_manager.hedge_position:
            self._pending_delta = 0.0
            return None  # No position to adjust

        state = self.get_delta_state()
        if not state.needs_rebalance:
            self._pending_delta = 0.0
            return None

        # Check minimum interval
        now = datetime.now()
        if self._last_rebalance_time:
            elapsed = (now - self._last_rebalance_time).total_seconds()
            if elapsed < self._min_rebalance_interval:
                return None

        # Execute adjustment
        target_qty = state.long_btc  # 1:1 delta-neutral
        result = await self.hedge_manager.adjust_position(target_qty, binance_price)

        if result and result.success:
            self._last_rebalance_time = now
            self._pending_delta = 0.0

        return result
```

## Changes to HedgeManager

**File:** `trading/execution/hedge_manager.py`

Add new method:

```python
async def adjust_position(self, target_qty: float, current_price: float) -> Optional[RebalanceResult]:
    """
    Adjust existing hedge position to match target quantity.

    Args:
        target_qty: Desired short BTC quantity
        current_price: Current Binance BTC price

    Returns:
        RebalanceResult with adjustment details
    """
    if not self.hedge_position:
        return None

    current_qty = self.hedge_position.qty
    diff = target_qty - current_qty

    if abs(diff) < 0.0001:  # Negligible
        return None

    if diff > 0:
        return await self._increase_short(diff, current_price)
    else:
        return await self._decrease_short(abs(diff), current_price)

async def _increase_short(self, qty: float, price: float) -> RebalanceResult:
    """Increase short position (Alpha bought more)."""
    # Check margin availability
    margin_required = qty * price
    available = self.capital * self.config["max_capital_usage_pct"]

    if margin_required > available:
        qty = available / price  # Partial fill
        margin_required = qty * price

    # Execute order
    if self.execution_mode == "live":
        success = await self.account.open_short(qty, price)
    else:
        success = self._sync_open_short(qty, price)

    if success:
        fee = margin_required * (self.config["fee_pct"] + self.config["slippage_pct"]) / 100
        self.capital -= fee
        self.hedge_position.qty += qty

        return RebalanceResult(
            direction="increase",
            qty_adjusted=qty,
            new_short_qty=self.hedge_position.qty,
            fees_paid=fee,
            success=True,
        )

    return RebalanceResult(direction="increase", qty_adjusted=0, new_short_qty=self.hedge_position.qty, fees_paid=0, success=False)

async def _decrease_short(self, qty: float, price: float) -> RebalanceResult:
    """Decrease short position (Alpha sold some)."""
    # Can't decrease more than current position
    qty = min(qty, self.hedge_position.qty)

    # Execute order
    if self.execution_mode == "live":
        success = await self.account.close_short(qty, price)
    else:
        success = self._sync_close_short(qty, price)

    if success:
        fee = qty * price * (self.config["fee_pct"] + self.config["slippage_pct"]) / 100
        self.capital -= fee
        self.hedge_position.qty -= qty

        # If fully closed, clear position
        if self.hedge_position.qty < 0.0001:
            self.hedge_position = None

        return RebalanceResult(
            direction="decrease",
            qty_adjusted=qty,
            new_short_qty=self.hedge_position.qty if self.hedge_position else 0,
            fees_paid=fee,
            success=True,
        )

    return RebalanceResult(direction="decrease", qty_adjusted=0, new_short_qty=self.hedge_position.qty, fees_paid=0, success=False)
```

## Changes to Engine

**File:** `trading/engine.py`

### Initialize PositionManager

```python
def _init_hedge_infrastructure(self, hedge_config: Dict[str, Any]) -> None:
    # ... existing code ...

    # Initialize PositionManager (after HedgeManager)
    position_manager_config = {
        "calm_threshold_pct": hedge_config.get("calm_threshold_pct", 3.0),
        "normal_threshold_pct": hedge_config.get("normal_threshold_pct", 5.0),
        "volatile_threshold_pct": hedge_config.get("volatile_threshold_pct", 8.0),
        "volatility_calm": hedge_config.get("volatility_calm", 0.5),
        "volatility_high": hedge_config.get("volatility_high", 1.5),
        "min_rebalance_interval": hedge_config.get("min_rebalance_interval", 30),
    }
    self.position_manager = PositionManager(
        upbit_account=self.upbit_account,
        hedge_manager=self.hedge_manager,
        premium_controller=self.premium_controller,
        config=position_manager_config,
    )
    print("✅ PositionManager 초기화 완료")
```

### Integration in run_iteration

```python
def run_iteration(self) -> bool:
    # ... existing code ...

    # Execute Alpha strategies
    self._execute_upbit_strategies_concurrent(current_price, regime, decision)

    # NEW: Flush rebalance after Alpha execution
    if self.position_manager and self.hedge_manager.hedge_position:
        rebalance_result = self._flush_position_rebalance(prices)
        if rebalance_result:
            print(f"🔄 Rebalance: {rebalance_result.direction} {rebalance_result.qty_adjusted:.4f} BTC")

    # Execute Hedge strategy (existing)
    self._execute_hedge_strategy(prices, premium_info)

    # ... rest of iteration ...

def _flush_position_rebalance(self, prices: Dict[str, float]) -> Optional[RebalanceResult]:
    """Flush pending rebalance after Alpha execution."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        self.position_manager.flush_rebalance(prices['binance'])
    )
```

## Changes to AlphaManager

**File:** `trading/execution/alpha_manager.py`

### Add position_manager reference

```python
def __init__(self, ..., position_manager: Optional[PositionManager] = None):
    # ... existing code ...
    self.position_manager = position_manager
```

### Notify after trades

```python
def _execute_buy(self, pos: StrategyPosition, signal: AlphaSignal, price: float) -> None:
    # ... existing execution code ...

    # Notify PositionManager
    if self.position_manager:
        self.position_manager.on_alpha_trade(btc_amount, "buy")

def _execute_sell(self, pos: StrategyPosition, signal: AlphaSignal, price: float) -> None:
    # ... existing execution code ...

    # Notify PositionManager
    if self.position_manager:
        self.position_manager.on_alpha_trade(pos.btc, "sell")
```

## Error Handling

| Scenario | Handling |
|----------|----------|
| Adjust fails (API error) | Retry 2x, log warning, continue |
| Insufficient margin | Partial fill up to available |
| Rapid Alpha trades | Batch into single adjustment |
| No hedge position | Skip rebalancing |
| Rate limiting | Respect min_rebalance_interval (30s) |

## Configuration

Default values in `config/strategies/allocation.json`:

```json
{
  "hedge": {
    "rebalancing": {
      "calm_threshold_pct": 3.0,
      "normal_threshold_pct": 5.0,
      "volatile_threshold_pct": 8.0,
      "volatility_calm": 0.5,
      "volatility_high": 1.5,
      "min_rebalance_interval": 30
    }
  }
}
```

## Testing

1. **Unit tests:** Dynamic threshold, delta state, batching
2. **Integration:** Alpha trade → rebalance trigger
3. **Edge cases:** No position, partial fills, rapid trades

## Files Modified

- `trading/execution/position_manager.py` — New file
- `trading/execution/hedge_manager.py` — Add adjust_position()
- `trading/execution/alpha_manager.py` — Add position_manager notification
- `trading/engine.py` — Initialize and integrate PositionManager
- `tests/test_position_manager.py` — New test file

## Rollback

Remove PositionManager initialization from engine.py. AlphaManager notifications are no-ops if position_manager is None.
