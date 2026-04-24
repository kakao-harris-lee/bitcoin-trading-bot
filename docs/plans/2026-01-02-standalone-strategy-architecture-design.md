# Standalone Strategy Architecture Design

> Archived note (2026-04-24): this document was written for an older architecture that included removed futures, short, hedge, or multi-exchange paths. The active runtime is Binance spot-only, so use this file only as historical reference.


## Problem Statement

Current system has **double regime filtering** causing reduced trade opportunities:

1. **RegimeRouter** (external): Classifies market and decides which strategy to run
2. **V35 Entry Strategy** (internal): Has its own MarketClassifier that gates entries

Result: Trading opportunities blocked in SIDEWAYS_DOWN or technical rebound zones, leading to sharp decline in trade frequency and deteriorating profitability.

> Note: Kimchi premium arbitrage has been removed from the live codebase. References to `PREMIUM` below are historical and should not be re-enabled.

## Solution: Event-Driven Standalone Strategies

Transform from centralized engine to event-driven architecture where:
- Each strategy is an independent async coroutine
- Strategies subscribe directly to Redis streams
- RegimeRouter becomes advisory only (no gating)
- Dedicated executor handles risk controls and trade execution

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        run.py (Orchestrator)                     │
│  Spawns all coroutines, monitors health, restarts on failure    │
└─────────────────────────────────────────────────────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
┌──────────────┐      ┌──────────────────┐      ┌──────────────┐
│ Feed Handlers │      │  Regime Publisher │      │   Executor   │
│(Upbit/Binance)│      │    (Advisory)     │      │ (Risk+Trade) │
└──────┬───────┘      └────────┬─────────┘      └──────▲───────┘
       │                       │                       │
       ▼                       ▼                       │
  market:upbit:prices    market:regime           signals:*
  market:binance:prices                                │
                                                       │
  ┌────────────────────────────────────────────────────┤
  │                                                    │
  │  ┌─────────────────────────────────────────────┐   │
  │  │              Strategy Coroutines            │   │
  │  ├─────────────────────────────────────────────┤   │
  │  │                                             │   │
  │  │  V35 ←── upbit:prices, regime               │───┤
  │  │                                             │   │
  │  │  SHORT_V1 ←── binance:prices, regime        │───┤
  │  │                                             │   │
  │  │  SIDEWAYS_V2 ←── upbit:prices, regime       │───┤
  │  │                                             │   │
  │  │  H4_CONSERVATIVE ←── upbit:prices, regime   │───┤
  │  │                                             │   │
  │  │  PREMIUM ←── upbit:prices, binance:prices   │───┘
  │  │                                             │
  │  └─────────────────────────────────────────────┘
  │
  └── Each strategy subscribes to only what it needs
```

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Process model | Multi-coroutine (single process) | Simpler deployment, matches bot.sh workflow |
| Signal flow | Redis-mediated | Full decoupling, signals persisted/auditable |
| Executor role | Hybrid | Dumb per-strategy execution, centralized risk controls |
| RegimeRouter | Advisory only | Strategies informed but autonomous, no hard gating |
| Strategy scope | Core 4 strategies | V35, SHORT_V1, SIDEWAYS_V2, H4 (PREMIUM retired) |
| Entry point | Single orchestrator | One run.py spawns all coroutines |
| Mode control | Per-exchange flags | --upbit=live --binance=paper (current approach) |
| Data flow | Per-exchange streams | Strategies subscribe to what they need |
| Failure handling | Restart individual | Failed coroutine restarts, others continue, Telegram alert |

## Redis Stream Structure

| Stream | Publisher | Consumers | Data |
|--------|-----------|-----------|------|
| `market:upbit:prices` | FeedHandler(Upbit) | V35, SIDEWAYS_V2, H4, PREMIUM | `{price, volume, timestamp}` |
| `market:binance:prices` | FeedHandler(Binance) | SHORT_V1, PREMIUM | `{price, volume, timestamp}` |
| `market:regime` | RegimePublisher | All strategies (optional) | `{regime, market_state, mfi, adx}` |
| `signals:v35` | V35 Strategy | Executor | `{action, price, reason, size}` |
| `signals:short_v1` | SHORT_V1 Strategy | Executor | `{action, price, reason, size}` |
| `signals:sideways_v2` | SIDEWAYS_V2 Strategy | Executor | `{action, price, reason, size}` |
| `signals:h4` | H4 Strategy | Executor | `{action, price, reason, size}` |
| `signals:premium` | PREMIUM Strategy | Executor | `{action, exchange, price, reason}` |

**Consumer groups:**
- Each strategy has its own consumer group for price streams
- Executor has one consumer group consuming all `signals:*` streams

**Message retention:**
- Price streams: ~10,000 messages (rolling)
- Signal streams: ~1,000 messages (audit trail)

## Component Designs

### StandaloneStrategy Base Class

```python
class StandaloneStrategy(ABC):
    """Base class for all standalone strategy coroutines"""

    def __init__(self, redis_client, config):
        self.redis = redis_client
        self.config = config
        self.position = None  # Each strategy tracks its own position
        self.running = True

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy identifier (e.g., 'v35', 'short_v1')"""

    @property
    @abstractmethod
    def subscribed_streams(self) -> List[str]:
        """Streams this strategy needs"""

    @abstractmethod
    async def on_price(self, price_data: dict) -> Optional[Signal]:
        """Process price update, return signal if any"""

    async def run(self):
        """Main loop - subscribe and process"""
        while self.running:
            messages = await self.redis.consume(
                streams=self.subscribed_streams,
                group=f"strategy:{self.name}",
                consumer=self.name
            )
            for msg in messages:
                signal = await self.on_price(msg)
                if signal:
                    await self.redis.publish(f"signals:{self.name}", signal.to_dict())
```

### TradeExecutor

```python
class TradeExecutor:
    """Consumes signals, applies risk controls, executes trades"""

    def __init__(self, redis_client, upbit_adapter, binance_adapter, config):
        self.redis = redis_client
        self.upbit = upbit_adapter
        self.binance = binance_adapter
        self.risk_manager = RiskManager(config)
        self.notifier = TelegramNotifier(config)
        self.upbit_mode = config.upbit_mode
        self.binance_mode = config.binance_mode

    async def run(self):
        signal_streams = [
            "signals:v35", "signals:short_v1", "signals:sideways_v2",
            "signals:h4", "signals:premium"
        ]
        while self.running:
            messages = await self.redis.consume(
                streams=signal_streams, group="executor", consumer="main"
            )
            for msg in messages:
                await self.process_signal(msg)

    async def process_signal(self, msg):
        strategy = msg["stream"].split(":")[1]
        signal = msg["data"]

        if not self.risk_manager.allow_trade(strategy, signal):
            return

        if strategy in ["v35", "sideways_v2", "h4"]:
            await self.execute_upbit(strategy, signal)
        elif strategy == "short_v1":
            await self.execute_binance(strategy, signal)
        elif strategy == "premium":
            await self.execute_premium(signal)

        await self.notifier.send_trade_alert(strategy, signal)
```

### TradingOrchestrator

```python
class TradingOrchestrator:
    """Spawns and monitors all trading coroutines"""

    def __init__(self, config):
        self.config = config
        self.redis = RedisClient(config.redis)
        self.tasks: Dict[str, asyncio.Task] = {}
        self.notifier = TelegramNotifier(config)

    async def run(self):
        await self.redis.connect()

        coroutines = {
            "feed:upbit": FeedHandler(Exchange.UPBIT, self.redis),
            "feed:binance": FeedHandler(Exchange.BINANCE, self.redis),
            "regime": RegimePublisher(self.redis),
            "strategy:v35": V35Strategy(self.redis, self.config),
            "strategy:short_v1": ShortV1Strategy(self.redis, self.config),
            "strategy:sideways_v2": SidewaysV2Strategy(self.redis, self.config),
            "strategy:h4": H4Strategy(self.redis, self.config),
            "strategy:premium": PremiumStrategy(self.redis, self.config),
            "executor": TradeExecutor(self.redis, self.config),
        }

        for name, coro in coroutines.items():
            self.tasks[name] = asyncio.create_task(self._run_with_restart(name, coro))

        await asyncio.gather(*self.tasks.values())

    async def _run_with_restart(self, name: str, component):
        while True:
            try:
                await component.run()
            except Exception as e:
                await self.notifier.send_alert(f"⚠️ {name} crashed: {e}\nRestarting in 5s...")
                await asyncio.sleep(5)
```

## Directory Structure

```
trading/
├── orchestrator.py          # TradingOrchestrator (new)
├── engine.py                # Keep for backward compat, deprecated
│
├── strategies/              # Standalone strategy coroutines (new)
│   ├── __init__.py
│   ├── base.py              # StandaloneStrategy ABC
│   ├── v35.py               # V35 standalone
│   ├── short_v1.py          # SHORT_V1 standalone
│   ├── sideways_v2.py       # SIDEWAYS_V2 standalone
│   └── h4.py                # H4_CONSERVATIVE standalone
│
├── executor/                # Trade execution (new)
│   ├── __init__.py
│   ├── trade_executor.py    # TradeExecutor
│   └── risk_controls.py     # Kill switch, daily limits
│
├── publishers/              # Redis publishers (new)
│   ├── __init__.py
│   ├── regime_publisher.py  # RegimePublisher (advisory)
│   └── feed_publisher.py    # Wraps FeedHandler → Redis
│
├── strategy/                # Keep existing (internal logic reuse)
├── data/                    # Existing - unchanged
├── adapters/                # Existing - unchanged
├── core/                    # Existing - unchanged
└── notification/            # Existing - unchanged

run.py                       # Updated to use TradingOrchestrator
```

## Migration Plan

### Phase 1: Infrastructure (no behavior change)
- Add `trading/strategies/base.py` - StandaloneStrategy ABC
- Add `trading/publishers/regime_publisher.py` - RegimePublisher
- Add `trading/publishers/feed_publisher.py` - wrap existing FeedHandler
- Add `trading/executor/trade_executor.py` - TradeExecutor skeleton
- Update Redis stream config for new streams

### Phase 2: Migrate V35 first (single strategy proof)
- Create `trading/strategies/v35.py` - standalone V35
- Remove internal MarketClassifier gating (signals in all states)
- Test in paper mode alongside old engine
- Validate signal generation matches expectations

### Phase 3: Migrate remaining strategies
- SHORT_V1, SIDEWAYS_V2, H4, PREMIUM
- Each as standalone coroutine
- Test each individually

### Phase 4: Orchestrator integration
- Add `trading/orchestrator.py`
- Update `run.py` to use new orchestrator
- Update `bot.sh` if needed
- Full paper trading test

### Phase 5: Production cutover
- Deploy to server via git pull
- Run in paper mode first
- Switch to live after validation
- Keep old `engine.py` as fallback for 1 week

## Rollback Plan

If issues arise, revert `run.py` to use old `DualPaperTradingEngine`. Old engine.py preserved for this purpose.

## Expected Outcomes

- **More trades**: Strategies generate signals in all market states
- **Better responsiveness**: V35 regains original aggressive profit structure
- **Simplified architecture**: No complex routing logic
- **True event-driven**: Each strategy independently reacts to market data
- **Auditability**: All signals persisted in Redis streams
- **Resilience**: Individual coroutine failures don't crash entire system
