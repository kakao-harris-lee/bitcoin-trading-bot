# Binance Futures-Only Architecture Refactor

**Date:** 2026-01-11
**Status:** Approved
**Goal:** Remove all Upbit code, consolidate to Binance Futures-only trading

## Summary

Simplify the trading system by removing Upbit spot trading and consolidating all trading to Binance Futures. This enables both long and short strategies with leverage while reducing codebase complexity.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                 Global Risk Manager                   │
│         Kill switch if portfolio MDD > 20%           │
└──────────────────────────────────────────────────────┘
                        │
┌───────────────────────┴───────────────────────┐
│              Shared Infrastructure             │
│  ┌─────────────┐  ┌───────────┐  ┌─────────┐  │
│  │ Price Feed  │  │ Indicator │  │  Redis  │  │
│  │ (WebSocket) │  │  Engine   │  │ Streams │  │
│  └─────────────┘  └───────────┘  └─────────┘  │
└───────────────────────────────────────────────┘
        │                               │
┌───────┴───────────┐         ┌────────┴──────────┐
│   V35 Long Pool   │         │  Short_V1 Pool    │
│   50% Capital     │         │   50% Capital     │
│                   │         │                   │
│ Direction: LONG   │         │ Direction: SHORT  │
│ Leverage: 1-3x    │         │ Leverage: 1-3x    │
└───────────────────┘         └───────────────────┘
        │                               │
        └───────────────┬───────────────┘
                        │
          ┌─────────────┴─────────────┐
          │   Binance Futures Executor │
          │      (LONG/SHORT/CLOSE)    │
          └───────────────────────────┘
```

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Exchange | Binance Futures only | Simplifies codebase, enables shorting |
| Spot trading | Removed | Futures with 1x leverage is equivalent |
| Strategies | V35 Long + Short_V1 | Proven strategies, both directions |
| Capital allocation | Separate 50/50 pools | Protects V35 from Short drawdowns |
| Position rule | Parallel execution | V35 trades independently, maintains win rate |
| Leverage | 1-3x conservative | Lower risk, shorting capability |
| Emergency control | Global kill switch | Close all if portfolio MDD > 20% |

## Code Cleanup

### Files to Delete

| Category | Files |
|----------|-------|
| Collectors | `scripts/collectors/upbit_collector.py` |
| Strategies | `trading/strategy/sideways_v1.py`, `trading/strategy/sideways_v2.py`, `trading/strategy/va02_long.py` |
| Strategy Runners | `trading/strategy_runners/sideways_v2.py`, `trading/strategy_runners/h4.py` |
| Tests | `tests/test_upbit_connection.py` |

### Files to Simplify

| File | Change |
|------|--------|
| `core/types.py` | Remove `Exchange.UPBIT`, remove `upbit_symbol` field |
| `trading/strategy/v35_long.py` | Change `Exchange.UPBIT` → `Exchange.BINANCE` |
| `trading/strategy_runners/v35.py` | Change exchange to "binance", update stream names |
| `trading/strategy_runners/base.py` | Remove Upbit references in comments |
| `trading/publishers/feed_publisher.py` | Remove Upbit stream references |
| `trading/core/data_cache.py` | Remove upbit option |
| `bot.sh` | Remove Upbit price display |
| `.env.example` | Remove Upbit API keys |

**Estimated removal:** ~2,000+ lines of dead code

## Strategy Configuration

### V35 Long (Futures)

```python
exchange = Exchange.BINANCE
symbol = "BTCUSDT"
leverage = 1  # default, scale to 3x on strong signals
capital_pool = 0.5  # 50% of total capital
```

Entry/exit logic unchanged - same RSI, MACD, MFI conditions.

### Short_V1 (Futures)

```python
exchange = Exchange.BINANCE
symbol = "BTCUSDT"
leverage = 1  # default, scale to 3x on strong signals
capital_pool = 0.5  # 50% of total capital
```

Already configured for Binance Futures, just needs Upbit cleanup.

## Risk Controls

| Level | Trigger | Action |
|-------|---------|--------|
| Strategy | Individual MDD > 10% | Pause that strategy |
| Portfolio | Combined MDD > 20% | Close ALL positions |
| Manual | Telegram `/kill_on` | Close ALL + block new |

## Data Infrastructure

### WebSocket Feeds

```
BinanceWebSocket (wss://fstream.binance.com)
├── btcusdt@kline_1m
├── btcusdt@kline_1h
└── btcusdt@markPrice
```

### Redis Streams

```
market:binance:prices   # Price updates
market:binance:kline    # Candle data
signals:v35_long        # V35 strategy signals
signals:short_v1        # Short strategy signals
```

## Execution Layer

```python
class BinanceFuturesExecutor:
    def __init__(self):
        self.client = BinanceClient(futures=True)
        self.pools = {
            "v35_long": CapitalPool(allocation=0.5),
            "short_v1": CapitalPool(allocation=0.5),
        }

    async def execute(self, strategy_id: str, action: str, size: float):
        pool = self.pools[strategy_id]
        if not pool.can_trade(size):
            return  # Insufficient capital in this pool

        await self.client.place_order(
            symbol="BTCUSDT",
            side=action,  # LONG or SHORT
            size=size,
            leverage=pool.leverage,
        )
```

## Testing & Verification

### Test Plan

| Test | Method |
|------|--------|
| Unit tests | Update existing tests, remove Upbit mocks |
| Capital isolation | Verify pools don't cross-contaminate |
| Kill switch | Trigger 20% MDD, confirm all positions close |
| Paper trading | Run 24-48h with Binance testnet |

### Verification Checklist

- [ ] No "upbit" string in codebase (grep verification)
- [ ] All tests pass (pytest)
- [ ] Both strategies can open positions simultaneously
- [ ] Individual strategy MDD pause works
- [ ] Global kill switch works
- [ ] Telegram notifications work

### Rollback Plan

1. Keep current code on `main` until verified
2. Implement on feature branch
3. Merge only after paper trading confirms behavior

## Implementation Order

1. **Phase 1: Cleanup** - Delete Upbit files, remove references
2. **Phase 2: Refactor** - Update strategies to use BINANCE exchange
3. **Phase 3: Capital Pools** - Implement separate pool accounting
4. **Phase 4: Risk Manager** - Add portfolio-level MDD tracking
5. **Phase 5: Testing** - Unit tests, integration tests, paper trading
