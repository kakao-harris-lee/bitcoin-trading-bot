# Async Trading Engine V2 Design

> Archived note (2026-04-24): this document was written for an older architecture that included removed futures, short, hedge, or multi-exchange paths. The active runtime is Binance spot-only, so use this file only as historical reference.


**Date:** 2025-12-28
**Status:** Draft - Pending Approval
**Goal:** Full async rewrite of trading engine for maximum speed and real-time responsiveness

> Note: Kimchi premium arbitrage has been removed from the codebase. Premium-specific sections below are historical.

## Overview

Replace the synchronous `DualPaperTradingEngine` with an event-driven async architecture that:
- Uses WebSocket feeds instead of REST API polling
- Caches data in-memory instead of DB reads per cycle
- Fetches real-time USD/KRW exchange rates
- Evaluates strategies reactively on significant price moves

### Performance Targets

| Operation | Current | Target |
|-----------|---------|--------|
| Price fetch | 200-500ms | <1ms |
| Indicator calculation | 50-100ms | <10ms |
| Premium calculation | 5ms | <1ms |
| Full iteration | 500-1000ms | <50ms |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AsyncTradingEngine                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐               │
│  │ FeedHandler  │    │ DataCache    │    │ FXRateCache  │               │
│  │ (WebSocket)  │───▶│ (In-Memory)  │◀───│ (USD/KRW)    │               │
│  └──────────────┘    └──────────────┘    └──────────────┘               │
│         │                   │                   │                        │
│         ▼                   ▼                   ▼                        │
│  ┌─────────────────────────────────────────────────────────┐            │
│  │                    PriceHub (Central Cache)              │            │
│  │  • Upbit price (real-time WebSocket)                     │            │
│  │  • Binance price (real-time WebSocket)                   │            │
│  │  • USD/KRW rate (5-min refresh)                          │            │
│  │  • Derived metrics (Kimchi premium removed)              │            │
│  └─────────────────────────────────────────────────────────┘            │
│                              │                                           │
│                              │ asyncio.Queue (in-process)               │
│                              │                                           │
│         ┌────────────────────┼────────────────────┐                     │
│         ▼                    ▼                    ▼                     │
│  ┌────────────┐      ┌────────────┐      ┌────────────┐                │
│  │ Strategy   │      │ Strategy   │      │  Health    │                │
│  │ Runner     │      │ Runner     │      │  Monitor   │                │
│  │ (Upbit)    │      │ (Binance)  │      │            │                │
│  └────────────┘      └────────────┘      └────────────┘                │
│         │                    │                                          │
│         └────────────────────┘                                          │
│                    │                                                     │
│                    ▼                                                     │
│          ┌────────────────┐                                             │
│          │ AsyncExecutor  │                                             │
│          │ (order queue)  │                                             │
│          └────────────────┘                                             │
└─────────────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| FX Rate API | exchangerate-api.com | Free tier (1500 req/month), simple REST |
| Candle Data | Hybrid (ticks + DB) | Current candle from ticks, history from DB |
| Eval Trigger | Price change >0.1% | Event-driven, avoids unnecessary computation |
| Message Passing | In-process queues | No Redis dependency, simpler deployment |

## Component Specifications

### 1. PriceHub

Central price cache with subscriber notification.

```python
class PriceHub:
    _prices: Dict[str, PriceMessage]     # {"upbit": ..., "binance": ...}
    _fx_rate: float                       # USD/KRW rate
    _cached_premium: PremiumInfo          # Pre-calculated
    _subscribers: List[asyncio.Queue]     # Strategy runners subscribe
    _last_prices: Dict[str, float]        # For change detection
    _price_change_threshold: float = 0.001  # 0.1%

    async def update_price(self, exchange: str, msg: PriceMessage):
        """Called by FeedHandler on every WebSocket message."""
        old_price = self._last_prices.get(exchange, 0)
        new_price = msg.price

        self._prices[exchange] = msg
        self._last_prices[exchange] = new_price
        self._recalculate_premium()

        # Notify subscribers only on significant change
        if old_price > 0:
            change_pct = abs(new_price - old_price) / old_price
            if change_pct >= self._price_change_threshold:
                await self._notify_subscribers(exchange, change_pct)

    def get_prices(self) -> Dict[str, float]:
        """Instant access - no network, no DB."""
        return {k: v.price for k, v in self._prices.items()}

    def get_premium(self) -> PremiumInfo:
        """Pre-calculated on every price update."""
        return self._cached_premium

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to price change events."""
        queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue
```

### 2. DataCache

In-memory OHLCV with hybrid update strategy.

```python
class DataCache:
    _cache: Dict[str, pd.DataFrame]       # {"minute60": df, "day": df}
    _current_candle: Dict[str, OHLCV]     # Building from ticks
    _candle_start: Dict[str, datetime]    # Candle start time
    _max_rows: int = 5000                 # Memory limit per timeframe
    _sync_interval: int = 300             # DB sync every 5 min

    async def start(self):
        """Initial load from DB (once at startup)."""
        await asyncio.to_thread(self._load_initial_data)
        asyncio.create_task(self._db_sync_loop())

    def _load_initial_data(self):
        """Sync DB load for startup."""
        loader = DataLoader()
        for tf in ["minute60", "day"]:
            self._cache[tf] = loader.load_timeframe(
                tf, start_date="2024-01-01"
            ).tail(self._max_rows)

    async def _db_sync_loop(self):
        """Background sync with DB for historical accuracy."""
        while True:
            await asyncio.sleep(self._sync_interval)
            await asyncio.to_thread(self._sync_from_db)

    def _sync_from_db(self):
        """Refresh cache from DB - runs in thread."""
        loader = DataLoader()
        for tf in ["minute60", "day"]:
            fresh = loader.load_timeframe(tf, start_date="2024-01-01")
            self._cache[tf] = fresh.tail(self._max_rows)

    def update_from_tick(self, price: float, volume: float, timestamp: datetime):
        """Aggregate tick into current candle."""
        # Determine candle boundaries
        minute = timestamp.replace(second=0, microsecond=0)
        hour = minute.replace(minute=0)

        self._update_candle("minute60", hour, price, volume)

    def _update_candle(self, tf: str, start: datetime, price: float, volume: float):
        """Update or create candle."""
        if tf not in self._current_candle or self._candle_start.get(tf) != start:
            # New candle
            self._current_candle[tf] = OHLCV(
                open=price, high=price, low=price, close=price, volume=volume
            )
            self._candle_start[tf] = start
        else:
            # Update existing
            candle = self._current_candle[tf]
            candle.high = max(candle.high, price)
            candle.low = min(candle.low, price)
            candle.close = price
            candle.volume += volume

    def get_df(self, timeframe: str, periods: int = 200) -> pd.DataFrame:
        """Instant access - returns copy of cached data."""
        return self._cache[timeframe].tail(periods).copy()
```

### 3. FXRateCache

Real-time USD/KRW exchange rate.

```python
class FXRateCache:
    _rate: float = 1450.0                 # Fallback value
    _updated_at: Optional[datetime] = None
    _refresh_interval: int = 300          # 5 minutes
    _api_url: str = "https://api.exchangerate-api.com/v4/latest/USD"

    async def start(self):
        """Start background refresh loop."""
        await self._fetch_rate()  # Initial fetch
        asyncio.create_task(self._refresh_loop())

    async def _refresh_loop(self):
        while True:
            await asyncio.sleep(self._refresh_interval)
            try:
                await self._fetch_rate()
            except Exception as e:
                logger.warning(f"FX rate fetch failed: {e}, using {self._rate}")

    async def _fetch_rate(self):
        """Fetch from exchangerate-api.com."""
        async with aiohttp.ClientSession() as session:
            async with session.get(self._api_url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._rate = float(data["rates"]["KRW"])
                    self._updated_at = datetime.now()
                    logger.info(f"FX rate updated: {self._rate:.2f} KRW/USD")

    @property
    def rate(self) -> float:
        return self._rate

    @property
    def is_stale(self) -> bool:
        if self._updated_at is None:
            return True
        age = (datetime.now() - self._updated_at).total_seconds()
        return age > self._refresh_interval * 2
```

### 4. StrategyRunner

Event-driven strategy evaluation.

```python
class StrategyRunner:
    def __init__(self, exchange: str, price_hub: PriceHub, data_cache: DataCache):
        self.exchange = exchange
        self.price_hub = price_hub
        self.data_cache = data_cache
        self.strategies: Dict[str, BaseStrategy] = {}
        self._position: Optional[Position] = None

    async def run(self, regime: str) -> Optional[Signal]:
        """Evaluate appropriate strategy for current regime."""
        strategy = self._select_strategy(regime)
        if not strategy:
            return None

        # Get cached data (instant)
        prices = self.price_hub.get_prices()
        df = self.data_cache.get_df("minute60", periods=200)

        # Run strategy in thread pool (strategies are sync)
        signal = await asyncio.to_thread(
            strategy.generate_signal,
            df,
            prices[self.exchange]
        )

        return signal

    def _select_strategy(self, regime: str) -> Optional[BaseStrategy]:
        """Select strategy based on regime and exchange."""
        if self.exchange == "upbit":
            if regime.startswith("BULL"):
                return self.strategies.get("v35")
            elif regime.startswith("SIDEWAYS"):
                return self.strategies.get("sideways_v2")
        elif self.exchange == "binance":
            if regime in ("BEAR", "BEAR_STRONG", "BEAR_MODERATE"):
                return self.strategies.get("short_v1")
        return None
```

### 5. AsyncTradingEngine

Main engine orchestrating all components.

```python
class AsyncTradingEngine:
    def __init__(self, config: EngineConfig):
        self.config = config

        # Core components (no Redis)
        self.price_hub = PriceHub()
        self.data_cache = DataCache()
        self.fx_cache = FXRateCache()
        self.feed_handler = FeedHandler(
            upbit_symbols=["KRW-BTC"],
            binance_symbols=["btcusdt"],
        )

        # Strategy runners
        self.upbit_runner = StrategyRunner("upbit", self.price_hub, self.data_cache)
        self.binance_runner = StrategyRunner("binance", self.price_hub, self.data_cache)

        # Execution
        self.executor = AsyncExecutor(config.execution_mode)

        # Monitoring
        self.health_monitor = HealthMonitor(self)
        self.premium_tracker = PremiumTracker()

        # State
        self._running = False
        self._regime_cache: Optional[str] = None
        self._regime_updated_at: Optional[datetime] = None

    async def start(self):
        """Initialize and start all components."""
        logger.info("Starting AsyncTradingEngine...")

        # 1. Load initial data
        await self.data_cache.start()
        await self.fx_cache.start()

        # 2. Connect WebSockets
        await self.feed_handler.start()

        # 3. Wire callbacks
        self.feed_handler.set_price_callback(self._on_price_message)

        # 4. Start background tasks
        self._running = True
        await asyncio.gather(
            self._main_loop(),
            self.health_monitor.run(),
            self._regime_update_loop(),
        )

    async def stop(self):
        """Graceful shutdown."""
        self._running = False
        await self.feed_handler.stop()
        await self.executor.drain()
        logger.info("AsyncTradingEngine stopped")

    async def _on_price_message(self, msg: PriceMessage):
        """Callback from FeedHandler on every WebSocket tick."""
        # Update caches
        await self.price_hub.update_price(msg.exchange.value, msg)
        self.data_cache.update_from_tick(msg.price, msg.ohlcv.volume, msg.timestamp)
        self.premium_tracker.record(self.price_hub.get_premium())

    async def _main_loop(self):
        """Main event loop - reacts to significant price changes."""
        price_queue = self.price_hub.subscribe()

        while self._running:
            try:
                # Wait for price change event (blocking)
                event = await asyncio.wait_for(price_queue.get(), timeout=60)

                # Check kill-switch
                if await self._is_killed():
                    continue

                # Evaluate strategies
                await self._evaluate_and_execute()

            except asyncio.TimeoutError:
                # No price change in 60s - still alive, check health
                continue
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                await asyncio.sleep(1)

    async def _evaluate_and_execute(self):
        """Run strategies and execute signals."""
        regime = self._regime_cache or "SIDEWAYS"

        # Concurrent strategy evaluation
        signals = await asyncio.gather(
            self.upbit_runner.run(regime),
            self.binance_runner.run(regime),
            return_exceptions=True,
        )

        # Submit valid signals
        for signal in signals:
            if signal and not isinstance(signal, Exception):
                await self.executor.submit(signal)

    async def _regime_update_loop(self):
        """Update regime every 5 minutes."""
        while self._running:
            try:
                df = self.data_cache.get_df("day", periods=180)
                regime = await asyncio.to_thread(
                    self._calculate_regime, df
                )
                self._regime_cache = regime
                self._regime_updated_at = datetime.now()
                logger.info(f"Regime updated: {regime}")
            except Exception as e:
                logger.error(f"Regime update failed: {e}")

            await asyncio.sleep(300)  # 5 minutes

    async def _is_killed(self) -> bool:
        """Non-blocking kill-switch check."""
        return await asyncio.to_thread(
            kill_switch_active,
            self.config.kill_switch_file
        )
```

## File Structure

```
trading/
├── engine.py                    # Keep: sync engine (fallback)
├── async_engine.py              # NEW: AsyncTradingEngine
├── core/
│   ├── price_hub.py             # NEW
│   ├── data_cache.py            # NEW
│   ├── fx_cache.py              # NEW
│   ├── health_monitor.py        # NEW
│   └── ...
├── data/
│   └── feed_handler.py          # MODIFY: add direct callbacks
├── strategy/
│   ├── strategy_runner.py       # NEW
│   └── ...
├── execution/
│   ├── async_executor.py        # NEW
│   └── ...
run.py                           # MODIFY: add --engine flag
```

## Migration Plan

### Phase 1: Foundation (Days 1-2)
- Create `price_hub.py`, `data_cache.py`, `fx_cache.py`
- Unit tests for each component
- Validate caching logic

### Phase 2: Engine Shell (Days 3-4)
- Create `async_engine.py` skeleton
- Create `strategy_runner.py`
- Create `async_executor.py`
- Wire up FeedHandler

### Phase 3: Integration (Days 5-6)
- Modify `feed_handler.py` for direct callbacks
- Add `--engine async` flag to `run.py`
- Shadow mode: run async alongside sync, compare outputs

### Phase 4: Validation (Days 7-14)
- Paper trading with async engine (1 week)
- Performance benchmarks
- Fix edge cases

### Phase 5: Cutover (Day 15+)
- Live trading with `--engine async`
- Monitor for 2 weeks
- Deprecate sync engine

## Entry Point

```python
# run.py
import asyncio

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=['sync', 'async'], default='sync')
    # ... other args
    args = parser.parse_args()

    if args.engine == 'async':
        asyncio.run(async_main(args))
    else:
        sync_main(args)  # Current behavior

async def async_main(args):
    config = EngineConfig.from_args(args)
    engine = AsyncTradingEngine(config)

    try:
        await engine.start()
    except KeyboardInterrupt:
        await engine.stop()
```

```bash
# Usage
./bot.sh start paper --engine async    # Paper with async
./bot.sh start live --engine sync      # Live with sync (safe default)
./bot.sh start live --engine async     # Live with async (after validation)
```

## Error Handling

| Failure | Detection | Recovery |
|---------|-----------|----------|
| WebSocket disconnect | `is_connected = False` | Auto-reconnect (existing) |
| Stale price (>60s) | `PriceHub` age check | REST fallback, alert |
| FX API down | Exception in fetch | Use last rate, log warning |
| Strategy exception | `gather(return_exceptions=True)` | Skip, continue others |
| Memory bloat | `DataCache._max_rows` | Auto-trim to 5000 rows |

## Validation Criteria

| Metric | Requirement |
|--------|-------------|
| Price latency | <10ms from WebSocket to PriceHub |
| Eval latency | <50ms per strategy |
| Memory usage | <500MB steady state |
| Uptime | >99.9% (reconnect within 60s) |
| Signal parity | Match sync engine signals in shadow mode |

## Open Items

- [ ] Confirm exchangerate-api.com free tier limits
- [ ] Define exact price change threshold (0.1% proposed)
- [ ] Dashboard updates for async metrics
- [ ] Telegram notification integration
