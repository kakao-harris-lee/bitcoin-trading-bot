# Bitcoin Trading Bot

# Bitcoin Trading Bot

## 1. System Architecture

The system uses a **Component-based Architecture**, utilizing the Factory pattern to dynamically assemble strategies from modular entry and exit components.

### Core Concepts

- **CompositeStrategyTask**: The universal runner. It manages Redis I/O, state persistence (`StateManager`), and error handling. It delegates logic to components.
- **StrategyFactory**: Assembles strategies (`allocation.json` → `CompositeStrategyTask` with specific Entry/Exit classes).
- **IEntryStrategy**: Pure logic component. Input: `MarketData`. Output: `Signal` (Buy/None).
- **IExitStrategy**: Position management component. Input: `Position`, `MarketData`. Output: `Signal` (Sell/None).
- **RegimeRouter**: Oracle that classifies market state (MFI/ADX). Read-only reference.

## 2. Critical System Features

### A. Persistence (Redis-backed State)

- **StateManager**: Automatically saves/loads stateful variables (e.g., `high_water_mark`, `entry_count`).
- **Key Schema**: `state:{strategy_name}:{symbol}:{variable_name}`.

### B. Dynamic Configuration

- Strategies are not hardcoded.
- `allocation.json` defines which Entry/Exit components to pair.
- Supports "Mix & Match" (e.g., V35 Entry + Experimental Exit).

### C. Unified Backtesting

- `ComponentStrategyAdapter` bridges the live components to the historical backtester.
- Ensures `scripts/backtest_experimental.py` runs the *exact same logic* as the live engine.

## 3. Implementation Roadmap

- [x] **Core Refactoring**: `IEntryStrategy` / `IExitStrategy` interfaces.
- [x] **Component Migration**: Logic extracted from monolithic tasks.
- [x] **Factory Integration**: `Engine` uses `StrategyFactory`.
- [x] **Cleanup**: Legacy monolithic tasks (`V35LongTask`, etc.) deleted.
- [x] **Persistence**: `StateManager` implemented.
- [ ] **Observability**: Enhance `MetricsService` for component-specific events.

## 4. Coding Standards

- **Type Hinting**: Strict usage of Python type hints.
- **Async**: Keep all I/O non-blocking.
- **Logging**: Log every state change (e.g., "High Water Mark updated: 50000 -> 51000").
- **Error Handling**: Strategies must fail gracefully (log error, return Neutral signal) rather than crashing the engine.

## Quick Reference

**Always add important documentation here!** When you create or discover:

- Futures Trading Architecture → `docs/plans/2026-01-18-futures-trading-overhaul-design.md`
- Futures Implementation Guide → `docs/plans/2026-01-18-futures-trading-overhaul-implementation.md`
- Database Schema → Add Reference Paths Here
- Troubleshooting → Add Reference Paths Here
- Setup Guide → Add Reference Paths Here

This prevents context loss! Update this file immediately when you create important documentation.

```bash
# Bot management (recommended)
./bot.sh start                    # Paper mode (default)
./bot.sh start --trend=live       # Live trading
./bot.sh stop                     # Stop bot
./bot.sh restart --trend=live     # Restart
./bot.sh status                   # Check status
./bot.sh logs                     # View logs

# Direct run (alternative)
python run.py --trend paper
python run.py --trend live

# Run tests
pytest
```

## Architecture Overview

The bot uses a **stream-based component architecture** with Redis as the communication backbone:

```
┌─────────────────────────────────────────────────────────────────┐
│                         Single Python Process                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ BTC Feed     │  │ ETH Feed     │  │ SOL Feed     │           │
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
│  │RegimeRouter │   │V35 Composite│   │ShortV1 Comp │            │
│  │(Oracle)     │   │(Task)       │   │(Task)       │            │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘            │
│         │                 │                 │                    │
│         │ (Reads)         │                 │                    │
│         └─────────────────┼─────────────────┘                    │
│                           ▼                                      │
│                 Redis: orders stream                             │
│                           │                                      │
│                           ▼                                      │
│                 ┌──────────────────┐                             │
│                 │  Executor        │◄── Redis: positions (hash)  │
│                 │  (Paper/Live)    │◄── Redis: risk (hash)       │
│                 └────────┬─────────┘                             │
│                          │                                       │
│                          ▼                                       │
│                 Redis: trades stream ──► TelegramTask            │
│                          │                                       │
│                          ▼                                       │
│                   Binance API (spot + futures)                   │
└─────────────────────────────────────────────────────────────────┘
```

**Key principles:**

- **Component Driven**: Strategies are assembled from minimal Entry/Exit classes.
- **Regime Aware**: `RegimeRouter` publishes market state; Strategies subscribe to it.
- **Unified Logic**: Same component code runs in Live Engine and Backtester.
- **Redis Decoupling**: Streams connect Feeds, Strategies, and Executor.

## Project Structure

```
bitcoin-trading-bot/
├── run.py                          # Entry point
├── trading/
│   ├── engine.py                   # Main Orchestrator
│   ├── streams/                    # Redis streams infrastructure
│   │   ├── redis_streams.py        # RedisStreams client
│   │   ├── feed_task.py            # Base feed task
│   │   └── binance_feed.py         # BinanceFeedTask
│   ├── strategies/                 # Strategy Logic
│   │   ├── components/             # >>> NEW COMPONENT SYSTEM <<<
│   │   │   ├── strategy_factory.py # Assembles strategies
│   │   │   ├── v35_entry.py        # V35 Logic
│   │   │   ├── v35_trailing_exit.py# V35 Exit Logic
│   │   │   └── registry.py         # Component Registry
│   │   └── ...
│   ├── executor/                   # Order execution
│   │   ├── async_executor.py       # Live Binance executor
│   │   ├── paper_executor.py       # Paper trading simulator
│   ├── notification/               # Telegram integration
│   ├── risk/                       # Risk management
│   └── core/                       # Config, base classes
├── core/                           # Shared libraries
│   ├── component_adapter.py        # Adapter for Backtesting
│   ├── backtester.py               # Historical backtester
│   └── market_analyzer.py          # Market indicators
├── config/
│   └── strategies/
│       └── allocation.json         # Main config (strategies mapping)
└── tests/                          # Test suite
```

## Key Files

- `run.py`: Entry point (paper/live mode).
- `trading/engine.py`: Orchestrates feeds and `CompositeStrategyTask` instances.
- `trading/strategies/components/strategy_factory.py`: The brain that builds strategies.
- `trading/strategies/components/composite_task.py`: The runner for components.
- `core/component_adapter.py`: Allows components to run in the backtester.
- `config/strategies/allocation.json`: Configuration of active strategies.

## Redis Data Structures

### Streams

- `market:prices`: Price updates from Binance WebSocket.
- `orders`: Order intents from strategies.
- `trades`: Executed trade confirmations.
- `alerts`: System alerts and errors.

### Hashes

- `positions:{symbol}:{market}`: Position state (qty, entry_price, strategy).
- `risk`: Risk state (kill_switch, blocked, daily_pnl).
- `state:{strategy}:{symbol}`: Persistent strategy state (high_water_mark, etc).

## Configuration

`config/strategies/allocation.json`:

```json
{
  "redis_url": "redis://localhost:6379",
  "use_component_strategies": true,
  "strategies": {
    "v35_long": { "position_size": 0.01, "market": "futures" },
    "sideways_v2": { "position_size": 0.01, "market": "futures" }
  },
  "risk": { "max_daily_loss": 500 }
}
```

## Development Rules

### Git Workflow

**New features must be developed on feature branches and merged via PR:**

1. Create feature branch: `git checkout -b feature/{name}`
2. Implement and commit changes
3. Push branch: `git push -u origin feature/{name}`
4. Create PR to main
5. Merge after review

**Never commit new features directly to main.**

### Component Development

1. **Entry**: Create `trading/strategies/components/{name}_entry.py` (implements `IEntryStrategy`).
2. **Exit**: Create `trading/strategies/components/{name}_exit.py` (implements `IExitStrategy`).
3. **Register**: Add to `STRATEGY_REGISTRY` in `registry.py`.
4. **Test**: Run `pytest tests/` to verify logic.
5. **Backtest**: Use `scripts/run_unified_backtest.py`.

## Fee Calculation

```
Cost per trade = 0.05% (entry) + 0.05% (exit) + 0.04% (slippage) = 0.14%
Minimum profit target: 1.4% (10x fees)
```

## Environment Setup

```bash
source .venv/bin/activate
pip install -r requirements.txt

# Required services
redis-server  # Redis must be running
```

## Environment Variables

```bash
# Required for live trading
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret

# Required for Telegram notifications
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id

# Optional
REDIS_URL=redis://localhost:6379
```

## Do's and Don'ts

**Do:**

- Reactive strategies (momentum-following)
- Simple conditions (2-3 max)
- Self-classifying market conditions
- Large targets (1.5%+ to overcome fees)
- Use minute60+ timeframes

**Don't:**

- Predictive strategies (e.g., RSI < 30 -> buy)
- Complex indicator combos (3+ indicators)
- Over-optimisation (overfitting)
- Split trading (fee explosion)
- Day-level active trading

## Active Technologies

- Python 3.9+ (per requirements.txt) (001-backtest-mlflow-viz)
- MLflow local file store (./mlruns) for development, configurable for production (001-backtest-mlflow-viz)

## Recent Changes

- 001-backtest-mlflow-viz: Added Python 3.9+ (per requirements.txt)
