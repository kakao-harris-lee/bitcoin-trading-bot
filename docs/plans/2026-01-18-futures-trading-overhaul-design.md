# Futures Trading Overhaul Design

**Date:** 2026-01-18
**Status:** Approved
**Goal:** Complete futures trading redesign with proper short support, live funding rates, isolated margin, and liquidation protection.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Futures Trading System                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐      ┌─────────────────┐                   │
│  │ FundingTracker  │      │ LiquidationGuard│                   │
│  │ (new)           │      │ (new)           │                   │
│  └────────┬────────┘      └────────┬────────┘                   │
│           │                        │                             │
│           ▼                        ▼                             │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │              FuturesExecutor (enhanced)                      ││
│  │  - Handles LONG and SHORT positions                          ││
│  │  - Calculates P&L correctly for both directions              ││
│  │  - Applies funding fees every 8 hours                        ││
│  │  - Checks liquidation distance before every trade            ││
│  │  - Sets isolated margin mode on position open                ││
│  └─────────────────────────────────────────────────────────────┘│
│                           │                                      │
│           ┌───────────────┼───────────────┐                     │
│           ▼               ▼               ▼                     │
│    ┌──────────┐    ┌──────────┐    ┌──────────┐                 │
│    │ Position │    │ Position │    │ Position │                 │
│    │ BTCUSDT  │    │ ETHUSDT  │    │ SOLUSDT  │                 │
│    │ LONG 5x  │    │ SHORT 3x │    │ LONG 2x  │                 │
│    └──────────┘    └──────────┘    └──────────┘                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Component 1: FundingTracker

**Purpose:** Fetch live funding rates from Binance and apply them to open positions every 8 hours.

**Funding Rate Mechanics:**
- Binance perpetual futures have funding payments at 00:00, 08:00, 16:00 UTC
- If rate is positive: longs pay shorts
- If rate is negative: shorts pay longs
- Typical range: -0.1% to +0.1% per funding period

**Implementation:**

```python
# trading/risk/funding_tracker.py

@dataclass
class FundingRate:
    symbol: str
    rate: float          # e.g., 0.0001 = 0.01%
    next_funding_time: datetime

class FundingTracker:
    """Tracks and applies funding rates to futures positions."""

    FUNDING_TIMES_UTC = [0, 8, 16]  # Hours

    async def get_funding_rate(self, symbol: str) -> FundingRate:
        """Fetch current funding rate from Binance API."""
        # GET /fapi/v1/premiumIndex

    async def calculate_funding_payment(
        self,
        position_value: float,  # notional value
        rate: float,
        side: str  # "long" or "short"
    ) -> float:
        """Calculate funding payment (negative = you pay, positive = you receive)."""
        # Long pays when rate > 0
        # Short pays when rate < 0

    async def apply_funding_to_positions(self) -> list[dict]:
        """Apply funding to all open positions. Called by scheduler."""
```

**Data Storage (Redis):**
```
funding:{symbol}:rate      → "0.0001"
funding:{symbol}:next_time → "2026-01-18T16:00:00"
funding:history:{symbol}   → list of recent rates
```

---

## Component 2: LiquidationGuard

**Purpose:** Calculate liquidation prices and trigger pre-emptive exits before liquidation occurs.

**Liquidation Price Formula (Isolated Margin):**
```
For LONG:  Liq Price = Entry Price × (1 - 1/Leverage + Maintenance Margin Rate)
For SHORT: Liq Price = Entry Price × (1 + 1/Leverage - Maintenance Margin Rate)

Example (5x leverage, 0.4% maintenance margin):
- Entry: $100,000
- LONG liquidation:  $100,000 × (1 - 0.20 + 0.004) = $80,400
- SHORT liquidation: $100,000 × (1 + 0.20 - 0.004) = $119,600
```

**Implementation:**

```python
# trading/risk/liquidation_guard.py

@dataclass
class LiquidationInfo:
    symbol: str
    side: str
    entry_price: float
    liquidation_price: float
    current_price: float
    distance_pct: float      # How far from liquidation (%)
    should_exit: bool        # True if distance < threshold

class LiquidationGuard:
    """Monitors positions and triggers pre-emptive exits."""

    # Exit when price is within 20% of liquidation distance
    EXIT_THRESHOLD_PCT = 20.0

    # Binance maintenance margin rates by position size
    MAINTENANCE_MARGIN_RATES = {
        50_000: 0.004,      # 0.4% for < $50k
        250_000: 0.005,     # 0.5% for < $250k
        1_000_000: 0.01,    # 1.0% for < $1M
    }

    def calculate_liquidation_price(
        self,
        entry_price: float,
        leverage: int,
        side: str,  # "long" or "short"
        position_value: float
    ) -> float:
        """Calculate liquidation price for isolated margin position."""

    def check_position(
        self,
        position: Position,
        current_price: float
    ) -> LiquidationInfo:
        """Check if position should be pre-emptively closed."""

    async def monitor_all_positions(self) -> list[Signal]:
        """Check all positions, return exit signals for endangered ones."""
```

---

## Component 3: Enhanced Executor

**Purpose:** Fix P&L calculation and exit detection for both long and short positions.

**Current Problem (PaperExecutor):**
```python
# Only detects long exits
return side == "sell" and pos_side == "buy"

# P&L assumes long-only
pnl = (exit_price - entry_price) * quantity
```

**Fixed Logic:**

```python
# trading/executor/paper_executor.py (enhanced)

async def _is_exit_order(self, order: dict) -> bool:
    """Check if order closes an existing position."""
    position = await self.redis.get_position(symbol, market)
    if not position:
        return False

    pos_side = position.get("side")
    order_side = order["side"]

    # Long exit: sell closes buy
    # Short exit: buy closes sell
    return (
        (pos_side == "buy" and order_side == "sell") or
        (pos_side == "sell" and order_side == "buy")
    )

async def _calculate_exit_pnl(self, order: dict, fill: dict) -> dict:
    """Calculate P&L for both long and short positions."""
    position = await self.redis.get_position(symbol, market)
    entry_price = float(position["entry_price"])
    exit_price = fill["filled_price"]
    quantity = fill["filled_qty"]
    pos_side = position.get("side")
    leverage = int(position.get("leverage", 1))

    if pos_side == "buy":  # Long position
        pnl = (exit_price - entry_price) * quantity
    else:  # Short position
        pnl = (entry_price - exit_price) * quantity

    # Apply leverage to P&L
    pnl_with_leverage = pnl * leverage
    pnl_pct = (pnl / entry_price) * 100 * leverage

    return {"profit": pnl_with_leverage, "profit_pct": pnl_pct}
```

**Position Data Structure (Redis):**
```python
{
    "symbol": "BTC",
    "market": "futures",
    "side": "sell",           # "buy" for long, "sell" for short
    "quantity": "0.01",
    "entry_price": "100000",
    "leverage": "5",          # Track leverage
    "margin_mode": "isolated", # isolated or cross
    "liquidation_price": "119600",  # Pre-calculated
    "entry_time": "1705600000000",
    "strategy": "short_v1"
}
```

---

## Integration Flow

**Opening a Short Position:**

```
1. Strategy emits Signal(side="sell", market="futures")
          │
          ▼
2. LiquidationGuard.check_can_open()
   - Verify leverage is allowed (from LeverageManager)
   - Calculate projected liquidation price
          │
          ▼
3. BinanceClient.set_margin_mode("BTCUSDT", "ISOLATED")
          │
          ▼
4. BinanceClient.set_leverage("BTCUSDT", leverage)
          │
          ▼
5. Execute order (paper or live)
          │
          ▼
6. Store position with liquidation_price in Redis
          │
          ▼
7. FundingTracker starts tracking this position
```

---

## Error Handling

| Error | Response |
|-------|----------|
| Insufficient margin | Log warning, skip order, notify Telegram |
| Leverage too high | Cap to max allowed, proceed with reduced |
| Funding API fails | Use last known rate, retry in background |
| Near liquidation | Emergency exit signal, kill switch consideration |
| API rate limit | Exponential backoff (already implemented) |

**Graceful Degradation:**
- If FundingTracker fails → positions continue without funding adjustment
- If LiquidationGuard fails → fall back to stop-loss only
- If leverage API fails → use 1x (safest default)

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `trading/risk/funding_tracker.py` | CREATE |
| `trading/risk/liquidation_guard.py` | CREATE |
| `trading/executor/paper_executor.py` | MODIFY - fix short P&L |
| `trading/executor/async_executor.py` | MODIFY - add margin mode |
| `trading/strategies/components/models.py` | MODIFY - add leverage to Position |

---

## Implementation Order

1. **Fix PaperExecutor shorts** - Critical bug fix, enables testing
2. **Add leverage to Position model** - Required for P&L calculation
3. **Create LiquidationGuard** - Safety feature
4. **Create FundingTracker** - Accuracy improvement
5. **Integrate with AsyncExecutor** - Production readiness

---

## Success Criteria

- [ ] Paper trading correctly calculates short position P&L
- [ ] Liquidation prices calculated and displayed in dashboard
- [ ] Pre-emptive exits trigger at 80% distance to liquidation
- [ ] Funding rates fetched and applied every 8 hours
- [ ] All positions use isolated margin mode
- [ ] Existing tests pass, new tests cover short scenarios
