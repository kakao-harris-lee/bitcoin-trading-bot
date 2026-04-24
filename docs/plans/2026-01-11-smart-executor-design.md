# Smart Executor Design

> Archived note (2026-04-24): this document was written for an older architecture that included removed futures, short, hedge, or multi-exchange paths. The active runtime is Binance spot-only, so use this file only as historical reference.


**Date:** 2026-01-11
**Status:** Draft
**Purpose:** Optimize exit execution using minute-by-minute data with split orders and volatility-adaptive trailing stops.

## Problem Statement

Current exit execution uses simple market orders at fixed stop-loss percentages. This leaves alpha on the table:
- Market orders accept whatever price is available
- Fixed stop percentages ignore current volatility conditions
- Single-order execution misses micro-bounce opportunities

## Solution Overview

A **SmartExecutor** task that:
1. Continuously adjusts trailing stop distance based on minute-level volatility
2. Executes exits via hybrid split orders (limit ladder + fallback sweep)
3. Captures "precise alpha" through better fill prices

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Strategies (V35, SidewaysV2, ShortV1)                      │
│         │                                                        │
│         ▼ exit signals                                          │
│  ┌──────────────────┐                                           │
│  │  SmartExecutor   │◄── Redis: market:prices (minute data)     │
│  │  (new task)      │                                           │
│  └────────┬─────────┘                                           │
│           │ optimized orders (split, timed)                     │
│           ▼                                                      │
│  Redis: orders stream                                           │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────┐                                           │
│  │  AsyncExecutor   │──► Binance API                            │
│  └──────────────────┘                                           │
└─────────────────────────────────────────────────────────────────┘
```

**Flow:**
1. Strategy detects exit condition → publishes to `exit_signals` stream
2. SmartExecutor consumes signals, analyzes minute data, decides execution plan
3. SmartExecutor publishes split orders to `orders` stream with timing
4. AsyncExecutor executes each slice as usual

**Key benefit:** Strategies remain simple. They just say "exit BTC long" — SmartExecutor handles the how.

---

## Volatility-Adaptive Trailing Stops

SmartExecutor continuously monitors positions and adjusts trailing stop distance based on minute-level volatility.

### Volatility Measurement

```
volatility_score = stddev(last 20 minute returns) / mean(last 20 minute returns)
```

### Trailing Distance Rules

| Volatility | Classification | Trail Distance | Rationale |
|------------|----------------|----------------|-----------|
| < 0.3% | Low (steady trend) | 0.8% | Tight trail locks in gains |
| 0.3-0.7% | Medium (normal) | 1.2% | Balanced protection |
| > 0.7% | High (choppy) | 1.8% | Avoid noise stop-outs |

### Micro-Adjustment Loop (runs every minute)

1. Fetch last 20 price points from `market:prices` stream
2. Calculate volatility score
3. Compute new trail distance from table above
4. If price made new high → update high water mark
5. Calculate current stop level: `stop = HWM × (1 - trail_distance)`
6. If current price ≤ stop → trigger exit signal with smart execution

### Smoothing

To avoid whiplash, trail distance changes are dampened — max 0.2% adjustment per minute. This prevents sudden tightening that could trigger premature exits.

---

## Hybrid Split Order Execution

When a stop-loss triggers, SmartExecutor executes a multi-phase exit strategy instead of a single market order.

### Phase 1: Limit Order Ladder (0-60 seconds)

Place 3 limit orders at progressively better prices:

```
Order A: 40% qty at current_price + 0.05%  (most likely to fill)
Order B: 35% qty at current_price + 0.12%  (catches small bounce)
Order C: 25% qty at current_price + 0.20%  (catches larger bounce)
```

### Phase 2: Volatility Check (at 30 seconds)

Analyze price action since trigger:
- If price trending down hard (3+ consecutive red candles) → cancel unfilled limits, sweep remaining with market order immediately
- If choppy/bouncing → extend ladder by 30 more seconds
- If bouncing strongly → raise limit prices by 0.05%

### Phase 3: Sweep Fallback (at 60-90 seconds max)

Cancel any remaining unfilled limit orders and execute market order for remaining quantity. Never let an exit hang beyond 90 seconds.

### Example Alpha Capture

| Execution Method | BTC Exit Price | Slippage |
|------------------|----------------|----------|
| Simple market order | $94,850 | -0.15% |
| Smart hybrid (ladder fills) | $94,920 | -0.08% |
| **Alpha captured** | **+$70 per BTC** | **+0.07%** |

---

## Configuration

Add to `config/strategies/allocation.json`:

```json
{
  "smart_executor": {
    "enabled": true,
    "strategies": ["v35_classic_wide", "sideways_v2", "short_v1"],
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
  }
}
```

---

## Safety Guardrails

| Risk | Mitigation |
|------|------------|
| Price crashes during ladder | Volatility check at 30s triggers immediate sweep |
| Limit orders not filling | Hard 90-second max, then market sweep |
| Network/API failure | Fallback to simple market order via AsyncExecutor |
| Partial fills leave dust | Sweep includes any quantity > min trade size |
| Kill switch activated mid-execution | Abort ladder, immediate market exit |

### Logging & Metrics

SmartExecutor publishes to `trades` stream with extra fields:
- `execution_method`: "smart_split" or "fallback_market"
- `alpha_captured`: difference vs. trigger price
- `fill_count`: number of partial fills
- `execution_duration_ms`: total time

---

## Implementation Structure

### New Files

```
trading/
├── executor/
│   └── smart_executor.py      # Main SmartExecutor task
├── streams/
│   └── exit_signals.py        # Exit signal stream handling
└── strategies/
    └── volatility_tracker.py  # Shared volatility calculations
```

### SmartExecutor Class Outline

```python
class SmartExecutor:
    """Intercepts exit signals, applies smart execution."""

    def __init__(self, redis, binance_client, config):
        self.volatility_tracker = VolatilityTracker(window=20)
        self.active_exits = {}  # symbol -> ExitPlan

    async def run(self):
        # Consume from exit_signals stream
        # Monitor positions for trailing stop triggers
        # Execute split orders via orders stream

    async def check_trailing_stops(self):
        # Called every minute
        # Updates HWM, calculates dynamic trail distance
        # Triggers exit when stop hit

    async def execute_smart_exit(self, symbol, quantity, trigger_price):
        # Phase 1: Place limit ladder
        # Phase 2: Monitor and adapt
        # Phase 3: Sweep fallback

    async def _place_limit_ladder(self, symbol, qty, base_price):
        # Creates tiered limit orders

    async def _volatility_check(self, symbol) -> str:
        # Returns: "trending_down" | "choppy" | "bouncing"

    async def _sweep_remaining(self, symbol, remaining_qty):
        # Market order for unfilled quantity
```

### Integration with Existing Strategies

Strategies change from publishing to `orders` stream directly to publishing exit intents to `exit_signals` stream. Entry orders still go directly to `orders` (no split needed for entries).

---

## Testing & Validation

### Unit Tests

```
tests/
├── test_smart_executor.py
│   ├── test_volatility_classification()
│   ├── test_trailing_distance_calculation()
│   ├── test_limit_ladder_placement()
│   ├── test_sweep_fallback_triggers()
│   └── test_kill_switch_aborts_execution()
└── test_volatility_tracker.py
    ├── test_stddev_calculation()
    └── test_damping_limits_adjustment()
```

### Backtesting Approach

Create a backtest module that replays historical minute data:

1. Load 30 days of minute OHLCV data
2. Simulate positions with known entry points
3. Compare exit results:
   - Baseline: simple market order at stop trigger price
   - SmartExecutor: simulate ladder fills using actual minute candles
4. Measure alpha captured per trade

### Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Average alpha per exit | > +0.05% | (smart_fill - trigger_price) / trigger_price |
| Execution success rate | > 99% | exits completed within 90s |
| Fallback rate | < 15% | sweeps triggered due to trending crash |
| Trailing stop accuracy | ±0.1% | actual exit vs. calculated stop level |

### Paper Trading Validation

Run SmartExecutor in paper mode for 2 weeks before live deployment. Dashboard tracks alpha captured vs. baseline in real-time.

---

## Implementation Plan

1. Create `volatility_tracker.py` with volatility calculation logic
2. Create `smart_executor.py` with core task structure
3. Implement trailing stop monitoring loop
4. Implement limit ladder placement
5. Implement volatility check and phase transitions
6. Implement sweep fallback
7. Add `exit_signals` stream and update strategies
8. Add configuration to `allocation.json`
9. Write unit tests
10. Create backtest simulation
11. Run paper trading validation
