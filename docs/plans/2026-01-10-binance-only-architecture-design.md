# Binance-Only Stream Architecture Design

**Date:** 2026-01-10
**Status:** Proposed
**Author:** Claude (brainstorming session)

## Overview

This document describes a major architectural redesign of the bitcoin trading bot. The goal is to simplify the system by:

1. Eliminating Upbit-related code (Binance-only)
2. Replacing the centralized MultiAssetTradingEngine with independent async tasks
3. Removing the regime router (strategies self-classify)
4. Using Redis streams as the sole communication mechanism between components
5. Unifying Binance spot and futures APIs in a single AsyncExecutor

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Single Python Process                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ BTC Feed     │  │ ETH Feed     │  │ SOL Feed     │  ...      │
│  │ (async task) │  │ (async task) │  │ (async task) │           │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘           │
│         │                 │                 │                    │
│         └─────────────────┼─────────────────┘                    │
│                           ▼                                      │
│                 Redis: market:prices stream                      │
│                           │                                      │
│         ┌─────────────────┼─────────────────┐                    │
│         ▼                 ▼                 ▼                    │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐            │
│  │ V35     │   │ SidewaysV2  │   │ ShortV1     │            │
│  │ (async task)│   │ (async task)│   │ (async task)│            │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘            │
│         │                 │                 │                    │
│         └─────────────────┼─────────────────┘                    │
│                           ▼                                      │
│                 Redis: orders stream                             │
│                           │                                      │
│                           ▼                                      │
│                 ┌──────────────────┐                             │
│                 │  AsyncExecutor   │◄── Redis: positions (hash)  │
│                 │  (async task)    │◄── Redis: risk (hash)       │
│                 └────────┬─────────┘                             │
│                          │                                       │
│                          ▼                                       │
│                   Binance API (spot + futures)                   │
└─────────────────────────────────────────────────────────────────┘
```

**Key principles:**
- No central orchestrator — each task runs autonomously
- Redis streams as the only coupling between components
- Strategies self-classify — no regime router dependency

## Redis Streams & Data Structures

Three Redis structures form the communication backbone:

### 1. `market:prices` stream

Published by feed tasks, consumed by strategies.

```python
{
    "symbol": "BTC",
    "price": "43250.50",
    "source": "binance",
    "market": "spot",        # or "futures"
    "timestamp": "1704912345678"
}
```

Each strategy subscribes as a consumer group member. Redis handles delivery — if a strategy crashes and restarts, it resumes from where it left off.

### 2. `orders` stream

Published by strategies, consumed by AsyncExecutor.

```python
{
    "id": "uuid-1234",
    "symbol": "BTC",
    "side": "buy",           # or "sell"
    "market": "spot",        # or "futures"
    "quantity": "0.05",
    "strategy": "v35_classic_wide",
    "reason": "MFI crossover + ADX strong"
}
```

### 3. `positions` hash

Written by AsyncExecutor, read by strategies.

```python
# Key: "positions:{symbol}:{market}"
{
    "quantity": "0.05",
    "entry_price": "43100.00",
    "strategy": "v35_classic_wide",
    "entry_time": "1704912000000",
    "unrealized_pnl": "7.52"
}
```

### 4. `risk` hash

```python
# Key: "risk"
{
    "kill_switch": "false",
    "daily_pnl": "-234.50",
    "blocked": "false"
}
```

Strategies check `positions` before entering (avoid duplicate positions) and `risk:blocked` before publishing orders.

## Price Feed Tasks

Each symbol gets a dedicated async task that maintains a WebSocket connection to Binance and publishes prices to Redis.

**Responsibilities:**
- Connect to Binance WebSocket (spot + futures streams for the symbol)
- Parse incoming price ticks
- Publish to `market:prices` stream
- Handle reconnection with exponential backoff
- Track connection health

**Implementation:**

```python
class SymbolFeedTask:
    def __init__(self, symbol: str, redis: Redis):
        self.symbol = symbol
        self.redis = redis

    async def run(self):
        while True:
            try:
                async with self._connect_websocket() as ws:
                    async for msg in ws:
                        await self._publish_price(msg)
            except ConnectionError:
                await asyncio.sleep(self._backoff())

    async def _publish_price(self, msg: dict):
        await self.redis.xadd("market:prices", {
            "symbol": self.symbol,
            "price": msg["price"],
            "source": "binance",
            "market": msg["market"],
            "timestamp": str(int(time.time() * 1000))
        })
```

**Startup flow:**
1. Read `allocation.json` for enabled symbols
2. Spawn one `SymbolFeedTask` per symbol
3. Each task independently connects and streams

**Failure isolation:** If ETH WebSocket drops, BTC and SOL keep running. The failed task reconnects independently.

## Strategy Tasks

Each strategy runs as an autonomous async task, subscribing to the price stream and publishing order intents.

**Responsibilities:**
- Subscribe to `market:prices` stream (filtered by relevant symbols)
- Maintain internal price buffer for indicator calculation
- Self-classify market conditions (replaces regime router)
- Check `positions` hash before entering
- Check `risk` hash before trading
- Publish order intents to `orders` stream

**Base class:**

```python
class BaseStrategyTask:
    def __init__(self, symbols: list[str], redis: Redis, config: dict):
        self.symbols = set(symbols)
        self.redis = redis
        self.config = config
        self.price_buffer: dict[str, deque] = {}  # symbol -> recent prices

    async def run(self):
        async for msg in self.redis.xreadgroup("market:prices", ...):
            symbol = msg["symbol"]
            if symbol not in self.symbols:
                continue

            self._update_buffer(symbol, msg)

            if await self._should_evaluate(symbol):
                signal = await self.evaluate(symbol)
                if signal:
                    await self._publish_order(signal)

    async def evaluate(self, symbol: str) -> dict | None:
        """Override in subclass. Return order intent or None."""
        raise NotImplementedError

    async def _has_position(self, symbol: str, market: str) -> bool:
        return await self.redis.hexists(f"positions:{symbol}:{market}")

    async def _is_blocked(self) -> bool:
        return await self.redis.hget("risk", "blocked") == "true"
```

**Key difference from current design:** Strategies no longer receive regime classification — they compute entry/exit conditions internally using their own indicator logic.

## AsyncExecutor

The AsyncExecutor is the single point of order execution. It consumes from the `orders` stream and interfaces with Binance APIs.

**Responsibilities:**
- Consume order intents from `orders` stream
- Apply risk gates before execution
- Execute via Binance spot or futures API
- Update `positions` hash after fills
- Update `risk` hash (daily P&L tracking)
- Publish trade confirmations to `trades` stream (for logging/Telegram)

**Implementation:**

```python
class AsyncExecutor:
    def __init__(self, redis: Redis, config: dict):
        self.redis = redis
        self.spot_client = BinanceSpotClient(config)
        self.futures_client = BinanceFuturesClient(config)
        self.risk_limits = config["risk"]

    async def run(self):
        async for msg in self.redis.xreadgroup("orders", ...):
            order = OrderIntent.from_dict(msg)

            if not await self._pass_risk_gates(order):
                await self._reject_order(order, "risk_blocked")
                continue

            try:
                fill = await self._execute(order)
                await self._update_position(order.symbol, order.market, fill)
                await self._update_daily_pnl(fill)
                await self._publish_trade(order, fill)
            except BinanceError as e:
                await self._handle_execution_error(order, e)

    async def _pass_risk_gates(self, order: OrderIntent) -> bool:
        risk = await self.redis.hgetall("risk")
        if risk.get("kill_switch") == "true":
            return False
        if float(risk.get("daily_pnl", 0)) < -self.risk_limits["max_daily_loss"]:
            return False
        return True

    async def _execute(self, order: OrderIntent) -> Fill:
        client = self.futures_client if order.market == "futures" else self.spot_client
        return await client.market_order(order.symbol, order.side, order.quantity)
```

**Risk gates checked:**
- Kill switch (Telegram-controlled)
- Daily loss limit (5% default)
- Position size limits per symbol

## Paper Trading Mode

Paper mode uses a `PaperExecutor` that intercepts the `orders` stream, simulating fills without calling Binance APIs.

**Design:**
- Same interface as `AsyncExecutor`
- Consumes from same `orders` stream
- Simulates fills with realistic slippage and fees
- Updates same `positions` and `risk` hashes
- Strategies don't know if they're in paper or live mode

**Implementation:**

```python
class PaperExecutor:
    def __init__(self, redis: Redis, config: dict):
        self.redis = redis
        self.fee_rate = 0.001  # 0.1% taker fee
        self.slippage = 0.0004  # 0.04% slippage
        self.balances = {
            "USDT": config["paper"]["initial_balance"]
        }

    async def run(self):
        async for msg in self.redis.xreadgroup("orders", ...):
            order = OrderIntent.from_dict(msg)

            if not await self._pass_risk_gates(order):
                continue

            # Get current price from recent market:prices
            price = await self._get_current_price(order.symbol)

            # Simulate fill with slippage
            fill_price = self._apply_slippage(price, order.side)
            fill = self._simulate_fill(order, fill_price)

            # Update state exactly like live executor
            await self._update_position(order.symbol, order.market, fill)
            await self._update_daily_pnl(fill)
            await self._publish_trade(order, fill)

    def _apply_slippage(self, price: float, side: str) -> float:
        factor = 1 + self.slippage if side == "buy" else 1 - self.slippage
        return price * factor
```

**Startup selection:**

```python
# In main.py
if args.trend == "paper":
    executor = PaperExecutor(redis, config)
else:
    executor = AsyncExecutor(redis, config)
```

## Strategy Migration

Porting the three strategies to the new architecture. Each becomes a self-contained async task.

### V35 → CompositeStrategyTask (Binance Spot)

**Current:** Relies on RegimeRouter for BULL classification, receives regime context.

**New:**
- Internalize MFI/ADX classification logic from RegimeRouter
- Entry: MFI >= 52, ADX >= 20 (self-computed)
- Exit: Existing MACD/RSI conditions + trailing stop
- Market: `spot`
- Symbols: All enabled symbols from config

### SidewaysV2 → SidewaysV2Task (Binance Spot)

**Current:** Activated when regime is SIDEWAYS.

**New:**
- Internalize sideways detection: 48 < MFI < 52, ADX < 20
- Range breakout and mean reversion logic unchanged
- Market: `spot`
- Competes with V35 — only one can hold position per symbol

### ShortV1 → ShortV1Task (Binance Futures)

**Current:** Activated when regime is BEAR_STRONG.

**New:**
- Internalize bear detection: MFI <= 48, ADX >= 20
- RSI overbought entry conditions unchanged
- Market: `futures`
- Can run simultaneously with spot strategies (different market)

### Position Conflict Resolution

Since V35 and SidewaysV2 both target spot, they check `positions:{symbol}:spot` before entering. First to enter holds the position. Exit signals are only processed by the strategy that opened the position (tracked in position hash).

## File Structure

### Delete (Upbit-related and obsolete)

```
trading/adapters/upbit.py                      # Upbit adapter
trading/strategy/regime_router.py              # Centralized regime router
trading/core/fx_cache.py                       # KRW/USD conversion
trading/core/multi_asset_price_hub.py          # Replaced by Redis
trading/core/multi_asset_data_cache.py         # Replaced by Redis
trading/execution/multi_asset_alpha_manager.py # No longer needed
trading/multi_asset_engine.py                  # The big orchestrator
```

### Create (new architecture)

```
trading/
├── streams/
│   ├── __init__.py
│   ├── feed_task.py          # SymbolFeedTask
│   └── base_strategy.py      # BaseStrategyTask
├── strategies/
│   ├── components/composite_task.py      # CompositeStrategyTask
│   ├── sideways_v2_task.py   # SidewaysV2Task
│   └── short_v1_task.py      # ShortV1Task
├── executor/
│   ├── async_executor.py     # Live executor
│   ├── paper_executor.py     # Paper executor
│   └── binance_client.py     # Unified spot+futures client
└── engine.py                 # Lightweight startup orchestrator
```

### Modify

```
run.py                                    # New startup flow
config/strategies/allocation.json         # Simplified, Binance-only
trading/risk/risk_controls.py             # Redis-based kill switch
trading/notification/telegram_notifier.py # Subscribe to trades stream
```

### Keep unchanged

```
core/backtester.py            # Still needed for strategy development
core/data_loader.py           # Still needed for backtesting
scripts/                      # CLI tools
web/                          # Dashboard (adapt to new data sources)
```

## Startup Flow

The new `engine.py` is a lightweight orchestrator that spawns all async tasks and manages graceful shutdown.

```python
# engine.py
class TradingEngine:
    async def start(self, mode: str):
        config = load_config("config/strategies/allocation.json")
        redis = await Redis.connect(config["redis_url"])

        # 1. Spawn feed tasks (one per enabled symbol)
        feed_tasks = []
        for symbol in config["symbols"]:
            task = SymbolFeedTask(symbol, redis)
            feed_tasks.append(asyncio.create_task(task.run()))

        # 2. Spawn strategy tasks
        strategy_tasks = [
            asyncio.create_task(CompositeStrategyTask(config, redis).run()),
            asyncio.create_task(SidewaysV2Task(config, redis).run()),
            asyncio.create_task(ShortV1Task(config, redis).run()),
        ]

        # 3. Spawn executor (paper or live)
        if mode == "paper":
            executor = PaperExecutor(redis, config)
        else:
            executor = AsyncExecutor(redis, config)
        executor_task = asyncio.create_task(executor.run())

        # 4. Spawn supporting services
        telegram = TelegramNotifier(redis, config)
        telegram_task = asyncio.create_task(telegram.run())

        # 5. Wait for shutdown signal
        await self._wait_for_shutdown()

        # 6. Graceful shutdown
        for task in [*feed_tasks, *strategy_tasks, executor_task, telegram_task]:
            task.cancel()
```

**run.py simplified:**

```python
if __name__ == "__main__":
    parser.add_argument("--trend", choices=["paper", "live"], default="paper")
    args = parser.parse_args()

    engine = TradingEngine()
    asyncio.run(engine.start(args.trend))
```

~100 lines total, down from 662.

## Error Handling & Monitoring

### Feed Task Failures

- WebSocket disconnect → exponential backoff reconnect (1s, 2s, 4s... max 60s)
- After 5 consecutive failures → publish alert to `alerts` stream
- Other symbols unaffected — isolation by design

### Strategy Task Failures

- Uncaught exception → log error, continue processing next message
- Redis connection lost → retry with backoff, resume from last acknowledged message
- Consumer group semantics ensure no missed prices after recovery

### Executor Failures

- Binance API error → log, publish to `alerts`, skip order (strategy can retry)
- Rate limit hit → backoff, queue orders internally
- Position update failure → critical alert, pause execution until manual review

### Health Monitoring via Redis

```python
# health hash - updated by each task every 30s
# Key: "health:{component}"
{
    "feed:BTC": {"last_ping": "1704912345", "status": "healthy"},
    "feed:ETH": {"last_ping": "1704912340", "status": "healthy"},
    "strategy:v35_classic_wide": {"last_ping": "1704912344", "status": "healthy"},
    "executor": {"last_ping": "1704912345", "status": "healthy"}
}
```

### Telegram Alerts

- TelegramNotifier subscribes to `alerts` stream
- Immediate notification on critical failures
- Existing `/kill_on`, `/kill_off` commands update `risk:kill_switch`

## Trade-offs

### What You Gain

| Before | After |
|--------|-------|
| 662-line MultiAssetTradingEngine | ~100-line lightweight engine |
| Upbit + Binance adapters | Single Binance client (spot + futures) |
| Centralized regime router | Self-classifying strategies |
| Complex price hub + data cache | Redis streams (standard, debuggable) |
| Tightly coupled components | Independent async tasks |
| KRW/USD conversion logic | Eliminated |

### Trade-offs to Consider

1. **Redis dependency** — Redis becomes critical infrastructure. If Redis dies, everything stops. Mitigation: Redis is battle-tested, can add Redis Sentinel for HA later.

2. **Increased network hops** — Price → Redis → Strategy adds latency vs direct callback. Mitigation: Redis on localhost, sub-millisecond overhead. Strategies operate on minute+ timeframes anyway.

3. **Strategy competition** — V35 and SidewaysV2 might race to enter the same position. Mitigation: Position hash check before entry. First wins, clean semantics.

4. **Debugging complexity** — Distributed async tasks harder to trace than single orchestrator. Mitigation: Structured logging with correlation IDs, Redis stream inspection tools.

### Lines of Code Estimate

- Delete: ~2,500 lines (engine, adapters, regime router, caches)
- Create: ~1,200 lines (tasks, executor, new engine)
- Net reduction: ~1,300 lines

## Implementation Sequence

1. Set up Redis streams infrastructure
2. Implement SymbolFeedTask with Binance WebSocket
3. Implement BaseStrategyTask base class
4. Port V35 → CompositeStrategyTask
5. Port SidewaysV2 → SidewaysV2Task
6. Port ShortV1 → ShortV1Task
7. Implement AsyncExecutor with Binance spot/futures
8. Implement PaperExecutor
9. Create new lightweight engine.py
10. Update run.py startup flow
11. Adapt TelegramNotifier to new architecture
12. Update web dashboard data sources
13. Delete obsolete files
14. Integration testing
