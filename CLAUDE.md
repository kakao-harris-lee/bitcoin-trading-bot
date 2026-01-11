# Bitcoin Trading Bot

## Quick Reference

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

The bot uses a **stream-based architecture** with Redis as the communication backbone:

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
│  │ V35Long     │   │ SidewaysV2  │   │ ShortV1     │            │
│  │ (async task)│   │ (async task)│   │ (async task)│            │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘            │
│         │                 │                 │                    │
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
- No central orchestrator — each task runs autonomously
- Redis streams as the only coupling between components
- Strategies self-classify market conditions (no regime router)
- Binance-only (spot + futures)

## Project Structure

```
bitcoin-trading-bot/
├── run.py                          # Entry point
├── trading/
│   ├── engine.py                   # Lightweight orchestrator
│   ├── streams/                    # Redis streams infrastructure
│   │   ├── redis_streams.py        # RedisStreams client
│   │   ├── feed_task.py            # Base feed task
│   │   ├── binance_feed.py         # BinanceFeedTask (WebSocket)
│   │   └── base_strategy.py        # BaseStrategyTask
│   ├── strategies/                 # Strategy task implementations
│   │   ├── v35_long_task.py        # V35Long (spot, MFI>=52, ADX>=20)
│   │   ├── sideways_v2_task.py     # SidewaysV2 (spot, 48<MFI<52)
│   │   └── short_v1_task.py        # ShortV1 (futures, MFI<=48)
│   ├── executor/                   # Order execution
│   │   ├── async_executor.py       # Live Binance executor
│   │   ├── paper_executor.py       # Paper trading simulator
│   │   └── binance_client.py       # Unified spot+futures client
│   ├── notification/               # Telegram integration
│   │   ├── telegram_task.py        # Stream-based notifications
│   │   ├── telegram_notifier.py    # Legacy notifier
│   │   └── telegram_commands.py    # Legacy command handler
│   ├── strategy/                   # Legacy strategies (for backtesting)
│   ├── risk/                       # Risk management
│   └── core/                       # Config, base classes
├── core/                           # Shared libraries
│   ├── data_loader.py              # Historical data loading
│   ├── backtester.py               # Backtesting engine
│   └── market_analyzer.py          # Market indicators
├── config/
│   └── strategies/
│       └── allocation.json         # Main config (symbols, strategies)
├── scripts/                        # CLI tools
├── data/                           # Database files
├── tests/                          # Test suite
├── web/                            # Dashboard (Flask + Redis)
│   ├── app.py                      # Flask routes
│   └── services/
│       └── metrics_service.py      # Redis-based metrics
└── docs/
    └── plans/                      # Design documents
```

## Key Files

- `run.py` - Entry point (paper/live mode)
- `trading/engine.py` - Lightweight orchestrator (~100 lines)
- `trading/streams/redis_streams.py` - Redis client wrapper
- `trading/strategies/*_task.py` - Self-classifying strategy tasks
- `trading/executor/paper_executor.py` - Paper trading simulator
- `config/strategies/allocation.json` - Main configuration

## Redis Data Structures

### Streams
- `market:prices` - Price updates from Binance WebSocket
- `orders` - Order intents from strategies
- `trades` - Executed trade confirmations
- `alerts` - System alerts and errors

### Hashes
- `positions:{symbol}:{market}` - Position state (qty, entry_price, strategy)
- `risk` - Risk state (kill_switch, blocked, daily_pnl)

## Configuration

`config/strategies/allocation.json`:
```json
{
  "redis_url": "redis://localhost:6379",
  "symbols": ["BTC", "ETH", "SOL"],
  "binance": {
    "api_key": "${BINANCE_API_KEY}",
    "api_secret": "${BINANCE_API_SECRET}"
  },
  "strategies": {
    "v35_long": { "position_size": 0.01 },
    "sideways_v2": { "position_size": 0.01 },
    "short_v1": { "position_size": 0.01 }
  },
  "risk": { "max_daily_loss": 500 },
  "paper": {
    "initial_balance": 10000,
    "fee_rate": 0.001,
    "slippage": 0.0004
  }
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

### Deployment

```bash
# On target server
cd ~/bitcoin-trading-bot
git pull origin main
./bot.sh restart --trend=live
```

### Strategy Development

1. Create plan: `docs/plans/{DATE}-{name}-design.md`
2. Wait for user approval
3. Create feature branch
4. Implement as a task in `trading/strategies/{name}_task.py`
5. Self-classify market conditions (MFI/ADX thresholds)
6. Run backtesting
7. Create PR and merge

## Strategy Classification

Strategies self-classify market conditions using MFI and ADX:

| Strategy | Market | Entry Conditions |
|----------|--------|------------------|
| V35Long | spot | MFI >= 52, ADX >= 20 (BULL) |
| SidewaysV2 | spot | 48 < MFI < 52, ADX < 20 (SIDEWAYS) |
| ShortV1 | futures | MFI <= 48, ADX >= 20 (BEAR) |

## Risk Management

- **Kill switch**: `/kill_on`, `/kill_off` via Telegram
- **Daily loss limit**: Configurable (default $500)
- **Position conflicts**: First strategy to enter holds position

## Telegram Commands

- `/info` - Show current status (positions, P&L, kill switch)
- `/kill_on` - Enable kill switch (stop trading)
- `/kill_off` - Disable kill switch (resume trading)
- `/help` - Show available commands

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
