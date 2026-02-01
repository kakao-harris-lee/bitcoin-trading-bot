# Bitcoin Trading Bot

## Trading Mode

**Hybrid trading mode.** V35 strategies execute on Binance Spot, Short/Sideways strategies execute on Binance Futures.

| Market | Strategies | Characteristics |
|--------|------------|-----------------|
| **Spot** | V35 strategies (6 variants) | No leverage (1x), 0.1% fee, no liquidation risk |
| **Futures** | Short, Sideways | Leverage (1-3x), 0.05% fee, hedging capability |

**Why Hybrid?** V35 strategy analysis showed effectiveness only at 1% position sizing—scaling with leverage provided no benefit while adding complexity (funding costs, liquidation risk).

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
- [x] **Hybrid Mode**: V35 strategies on spot, Short/Sideways on futures.
- [x] **Observability**: Enhance `MetricsService` for component-specific events.

## 4. Coding Standards

- **Type Hinting**: Strict usage of Python type hints.
- **Async**: Keep all I/O non-blocking.
- **Logging**: Log every state change (e.g., "High Water Mark updated: 50000 -> 51000").
- **Error Handling**: Strategies must fail gracefully (log error, return Neutral signal) rather than crashing the engine.
- **No Hardcodes**: Never hardcode values that should be computed or passed as parameters. Use existing helper functions (e.g., `build_market_context()`) instead of manually constructing objects with placeholder values.

## Quick Reference

**Always add important documentation here!** When you create or discover:

- Futures Trading Architecture → `docs/plans/2026-01-18-futures-trading-overhaul-design.md`
- Futures Implementation Guide → `docs/plans/2026-01-18-futures-trading-overhaul-implementation.md`
- Quant Lab Design → `docs/plans/2026-01-20-quant-lab-design.md`
- Quant Lab Implementation → `docs/plans/2026-01-20-quant-lab-implementation.md`
- Trading Context Centralization → `docs/plans/2026-01-20-trading-context-centralization-design.md`
- Smart Executor Design → `docs/plans/2026-01-11-smart-executor-design.md`
- LSTM Strategy Design → `docs/plans/2026-01-02-lstm-strategy-design.md`
- Binance Stream Architecture → `docs/plans/2026-01-10-binance-stream-architecture.md`
- MLflow Optimization → `docs/plans/2026-01-20-optimize-mlflow-improvements.md`
- Volatility Breakout & LSTM Scaling → `docs/plans/2026-01-26-volatility-breakout-lstm-scaling-design.md`
- Enhanced Regime Detection v2 → `docs/plans/2026-01-27-enhanced-regime-detection-design.md`
- Risk-Based Position Sizing → `docs/plans/2026-01-30-risk-based-position-sizing-design.md`
- Spot Trading Restoration Design → `docs/plans/2026-01-31-spot-trading-restoration-design.md`
- Spot Trading Restoration Implementation → `docs/plans/2026-01-31-spot-trading-restoration-implementation.md`
- MLP Direction Strategy Design → `docs/plans/2026-02-01-mlp-direction-strategy-design.md`
- MLP Direction Strategy Implementation → `docs/plans/2026-02-01-mlp-direction-strategy-implementation.md`

This prevents context loss! Update this file immediately when you create important documentation.

```bash
# Bot management (recommended)
./bot.sh start                    # Paper mode (default)
./bot.sh start --trend=live       # Live trading
./bot.sh stop                     # Stop bot
./bot.sh restart                  # Restart (keeps current mode)
./bot.sh restart --trend=live     # Restart in live mode
./bot.sh status                   # Check status
./bot.sh logs                     # View logs

# Dashboard management (use this, NOT systemctl)
./dashboard.sh start              # Start dashboard
./dashboard.sh stop               # Stop dashboard
./dashboard.sh restart            # Restart dashboard
# Dashboard URL: http://localhost:5080/btc-dashboard

# Quant Lab worker (required for hyperparameter optimization)
cd web && python -m quant_lab.worker.runner  # Start worker
# Quant Lab URL: http://localhost:5080/btc-dashboard/quant-lab

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
│                   Binance Futures API                            │
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
│   │   └── components/             # Component system
│   │       ├── strategy_factory.py # Assembles strategies
│   │       ├── composite_task.py   # Universal task runner
│   │       ├── registry.py         # Component Registry
│   │       ├── v35_entry.py        # V35 Entry Logic
│   │       ├── v35_trailing_exit.py# V35 Exit Logic
│   │       ├── v35_persistent_exit.py # V35 Persistent Exit
│   │       ├── short_entry.py      # Short Entry Logic
│   │       ├── short_exit.py       # Short Exit Logic
│   │       ├── sideways_entry.py   # Sideways Entry Logic
│   │       ├── sideways_exit.py    # Sideways Exit Logic
│   │       ├── combined_entry.py   # Combined/Ensemble Entry
│   │       ├── combined_exit.py    # Combined/Ensemble Exit
│   │       └── state_manager.py    # Redis state persistence
│   ├── executor/                   # Order execution
│   │   ├── async_executor.py       # Live Binance executor
│   │   ├── paper_executor.py       # Paper trading simulator
│   │   └── smart_executor.py       # Smart execution (laddering)
│   ├── indicators/                 # Technical indicators
│   ├── observability/              # Metrics & events
│   ├── notification/               # Telegram integration
│   ├── risk/                       # Risk management
│   └── core/                       # Config, base classes
├── core/                           # Shared backtesting libraries
│   ├── component_adapter.py        # Adapter for Backtesting
│   ├── backtester.py               # Historical backtester
│   ├── mlflow_tracker.py           # MLflow integration
│   └── data_loader.py              # Historical data loading
├── web/                            # Dashboard & Quant Lab
│   ├── app.py                      # Flask dashboard
│   └── quant_lab/                  # Hyperparameter optimization
│       ├── routes.py               # API routes
│       ├── optimizer/              # Optuna integration
│       └── worker/                 # Background worker
├── lstm_trainer/                   # LSTM model training (standalone)
├── scripts/                        # Utility scripts
│   ├── backtest/                   # Backtest scripts
│   ├── collectors/                 # Data collectors
│   └── migrations/                 # DB migrations
├── config/
│   └── strategies/
│       └── allocation.json         # Main config
├── models/                         # Trained model artifacts
└── tests/                          # Test suite
```

## Key Files

- `run.py`: Entry point (paper/live mode).
- `trading/engine.py`: Orchestrates feeds and `CompositeStrategyTask` instances.
- `trading/strategies/components/strategy_factory.py`: The brain that builds strategies.
- `trading/strategies/components/composite_task.py`: The runner for components.
- `trading/executor/smart_executor.py`: Smart order execution with laddering.
- `core/component_adapter.py`: Allows components to run in the backtester.
- `core/mlflow_tracker.py`: MLflow experiment tracking.
- `web/app.py`: Flask dashboard application.
- `web/quant_lab/routes.py`: Quant Lab API endpoints.
- `config/strategies/allocation.json`: Configuration of active strategies.

## Redis Data Structures

### Streams

- `market:prices`: Price updates from Binance WebSocket.
- `orders`: Order intents from strategies.
- `trades`: Executed trade confirmations.
- `alerts`: System alerts and errors.
- `strategy:entry:events`: Entry condition evaluation events (observability).
- `strategy:exit:events`: Exit condition evaluation events (observability).
- `strategy:hwm:updates`: High-water-mark timeline updates (observability).
- `strategy:safety:events`: Safety filter rejection events (observability).

**Observability stream retention:** Event streams are auto-trimmed to 2000 entries (~24h of data). Enable via `emit_events: true` in `allocation.json`.

### Hashes

- `positions:{symbol}:spot`: Spot position state (qty, entry_price, strategy).
- `positions:{symbol}:futures`: Futures position state (qty, entry_price, leverage, liquidation_price).
- `balance:spot:usdt`: Spot USDT balance.
- `balance:futures:usdt`: Futures USDT balance.
- `risk`: Risk state (kill_switch, blocked, daily_pnl).
- `state:{strategy}:{symbol}`: Persistent strategy state (high_water_mark, etc).

## Configuration

`config/strategies/allocation.json`:

```json
{
  "redis_url": "redis://localhost:6379",
  "use_component_strategies": true,
  "symbols": ["BTC", "ETH", "SOL"],
  "defaults": {
    "volatility": { "window": 20, "low_threshold": 0.71, "high_threshold": 0.92 },
    "market_context": { "mfi_bull": 52.0, "mfi_bear": 48.0, "adx_trend": 20.0 }
  },
  "spot": { "enabled": true, "fee_rate": 0.001 },
  "futures": { "enabled": true, "default_leverage": 3 },
  "strategies": {
    "v35_long": {
      "market": "futures",
      "leverage": 3,
      "dynamic_sizing": true,
      "position_pct": 0.3,
      "use_smart_exit": true
    },
    "short_v1": {
      "market": "futures",
      "leverage": 3,
      "position_pct": 0.2
    }
  },
  "smart_executor": {
    "enabled": true,
    "trailing": { "low_vol_trail": 0.8, "med_vol_trail": 1.2, "high_vol_trail": 1.8 },
    "split_execution": { "ladder_tiers": [0.05, 0.12, 0.2], "ladder_weights": [0.4, 0.35, 0.25] }
  },
  "risk": { "max_daily_loss": 500 },
  "observability": { "emit_events": false }
}
```

Tuned strategies can include `regime_routing` for per-regime entry/exit parameters.

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

### Quant Lab (Hyperparameter Optimization)

Quant Lab uses Optuna for automated hyperparameter tuning with regime-aware optimization.

1. **Start Worker**: `cd web && python -m quant_lab.worker.runner`
2. **Access UI**: Dashboard → Quant Lab tab
3. **Create Study**: Select strategy, configure search space, set number of trials
4. **Apply Results**: Click "Apply" to push best parameters to `allocation.json`

Studies are stored in `web/quant_lab_studies.db` (SQLite).

## Fee Calculation

| Market | Fee Rate | Round Trip | With Slippage |
|--------|----------|------------|---------------|
| **Spot** | 0.10% | 0.20% | ~0.24% |
| **Futures** | 0.05% | 0.10% | ~0.14% |

Minimum profit targets:
- Spot: 2.4% (10x fees)
- Futures: 1.4% (10x fees)

## Risk-Based Position Sizing

v35_long_v2 전략은 **리스크 기반 포지션 사이징**을 사용합니다:

```
핵심 공식: qty = risk_budget / (stop_distance × entry_price)

예시 ($10,000 자산, 1% 리스크, 3% 손절):
- risk_budget = $10,000 × 1% = $100
- qty = $100 / (3% × $100,000) = 0.033 BTC
- 최대 손실 = 항상 $100 (자산의 1%)
```

**allocation.json 설정**:
```json
{
  "v35_long_v2": {
    "risk_based_sizing": true,
    "risk_per_trade_pct": 0.01,     // 트레이드당 1% 리스크
    "max_total_risk_pct": 0.05,     // 전체 포트폴리오 5% 리스크 캡
    "max_open_positions": 5,
    "correlation_filter": true,
    "corr_threshold": 0.75          // BTC-ETH 상관관계 > 0.75면 진입 차단
  }
}
```

**관련 파일**:
- `trading/risk/position_sizer.py`: 리스크 기반 수량 계산
- `trading/risk/portfolio_risk_manager.py`: 포트폴리오 리스크 캡
- `trading/risk/correlation_filter.py`: 상관관계 필터
- `docs/plans/2026-01-30-risk-based-position-sizing-design.md`: 전체 설계 문서

## Environment Setup

**This project uses a Python virtual environment (venv).** Always activate it before running any commands.

```bash
# Activate virtual environment (REQUIRED)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Required services
redis-server  # Redis must be running
```

**Important:** The dashboard, bot, and Quant Lab worker all run with the venv Python. Do not use system Python directly.

## Environment Variables

```bash
# Required for live trading
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret

# Required for Telegram notifications
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id

# Required for dashboard
DASHBOARD_PASSWORD=your_secure_password
DASHBOARD_USERNAME=admin  # Optional, defaults to "admin"

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

- Python 3.9+ (per requirements.txt)
- MLflow local file store (./mlruns) for development
- Optuna for hyperparameter optimization (Quant Lab)
- Redis for state persistence and stream communication

## Structured Trade Logging

Trade events are logged as single-line JSON to `logs/trades.jsonl` for easy analysis:

```bash
# View recent trades
tail -20 logs/trades.jsonl | jq .

# Filter by event type
grep '"event":"EXIT"' logs/trades.jsonl | jq .

# Filter by symbol
grep '"symbol":"BTC"' logs/trades.jsonl

# Analyze with script
python scripts/analyze_trades.py                    # Today's summary
python scripts/analyze_trades.py --last 7           # Last 7 days
python scripts/analyze_trades.py --filter BTC       # Filter by symbol
python scripts/analyze_trades.py --event EXIT       # Filter by event
```

**Event types:** ENTRY, EXIT, FILL, PNL, DECISION, ERROR, BALANCE

**Example log line:**
```json
{"ts":"2026-01-25T12:00:00","event":"EXIT","symbol":"BTC","price":101500,"qty":0.01,"pnl":15.0,"pnl_pct":1.5}
```

## Recent Changes

- 2026-01-31: Added V35 unified tuning APIs with growth-focused optimization (MDD ≤25% cap)
- 2026-01-31: Added Quant Lab security hardening (auth, input validation, path traversal protection)
- 2026-01-31: Restored spot trading for V35 strategies (hybrid spot/futures mode)
- 2026-01-31: Added hybrid dashboard view with spot/futures separation
- 2026-01-31: Added enhanced backtest judgment charts and metrics
- 2026-01-30: Added risk-based position sizing (1% risk per trade, 5% total risk cap)
- 2026-01-25: Added structured one-line JSON trade logging for analysis
- 2026-01-25: Synced strategy configs and LSTM updates
- 2026-01-23: Fixed backtest 0-trade bug and matplotlib threading issues
- 2026-01-23: Added Quant Lab "Apply" button to push tuned params to allocation.json
- 2026-01-22: Fixed dashboard paper/live mode separation for account data
- 2026-01-21: Added Quant Lab integration (hyperparameter optimization)
- 2026-01-20: Added observability events (entry/exit/HWM/safety) with API endpoints
- 2026-01-20: (Reverted 2026-01-31) Removed spot trading - system now trades futures only
- 2026-01-18: Added Smart Executor with ladder execution and volatility-based trailing
