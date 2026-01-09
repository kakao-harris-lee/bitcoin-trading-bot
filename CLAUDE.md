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
ENABLE_LIVE_TRADING=1 python run.py --trend live

# Run tests
pytest

## Project Structure

```
bitcoin-trading-bot/
├── run.py                          # Entry point
├── trading/                        # Main trading engine
│   ├── multi_asset_engine.py       # MultiAssetTradingEngine
│   ├── data/                       # Data feeds (feed_handler)
│   ├── strategy/                   # All strategies + classification
│   │   ├── base.py                 # BaseStrategy abstract class
│   │   ├── regime_router.py        # Market regime classification
│   │   ├── v35_long.py             # V35 long strategy
│   │   ├── short_v1.py             # Binance short strategy
│   │   ├── sideways_v1.py          # Sideways strategy v1
│   │   ├── sideways_v2.py          # Sideways strategy v2
│   │   ├── h4_conservative.py      # H4 conservative
│   │   └── h4_short.py             # H4 short
│   ├── execution/                  # Order execution, positions
│   │   ├── execution_manager.py
│   │   ├── position_manager.py
│   │   └── paper_account.py        # Paper trading simulator
│   ├── risk/                       # Risk management
│   │   ├── risk_manager.py
│   │   ├── risk_controls.py        # Kill switches, limits
│   │   └── trade_logger.py
│   ├── notification/               # Telegram integration
│   ├── adapters/                   # Exchange adapters (Upbit, Binance)
│   └── core/                       # Config, Redis, base classes
├── core/                           # Shared libraries
│   ├── data_loader.py              # Historical data loading
│   ├── backtester.py               # Backtesting engine
│   ├── market_analyzer.py          # Market indicators
│   └── types.py                    # Shared data types
├── config/                         # All configuration files
│   ├── strategies/                 # Strategy parameters
│   │   ├── v35_long.json
│   │   └── short_v1.json
│   └── tuned/                      # Tuned operational settings
│       └── selected_candidate.json
├── scripts/                        # CLI tools
│   ├── collectors/                 # Data collector modules
│   │   ├── upbit_collector.py      # Upbit API collector
│   │   ├── binance_collector.py    # Binance API collector
│   │   └── bin/                    # Go binaries
│   ├── backtest.py                 # Unified backtesting
│   ├── optimize.py                 # Parameter optimization
│   ├── collect_data.py             # Data collection
│   └── tune_router.py              # Router tuning
├── data/                           # Database files
│   ├── upbit_bitcoin.db            # Market data
│   └── binance_bitcoin.db          # Binance data
├── tests/                          # Test suite
├── web/                            # Dashboard (Flask)
└── docs/                           # Documentation
    └── plans/                      # Design & plan documents
```

## Key Files

- `run.py` - Single entry point for all trading modes
- `trading/engine.py` - Main engine class
- `trading/strategy/` - All strategy implementations
- `config/strategies/` - Strategy configuration files
- `config/tuned/selected_candidate.json` - Tuned operational settings
- `data/upbit_bitcoin.db` - Market data (read-only)

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

**Source code sync via git pull only:**

```bash
# On target server
cd ~/bitcoin-trading-bot
git pull origin main
./bot.sh restart --trend=live
```

**Prohibited:**
- SSH/rsync bulk file transfers
- Direct file uploads to server

All code changes must be committed, pushed, and pulled via git.

### Strategy Development Workflow

1. Create plan: `docs/plans/{DATE}-{name}-design.md`
2. Wait for user approval
3. Create feature branch: `git checkout -b feature/{strategy-name}`
4. Implement in `trading/strategy/{name}.py`
5. Add config in `config/strategies/{name}.json`
6. Run backtesting
7. Document results
8. Create PR and merge

### Backtesting Standards

- Training: 2020-01-01 ~ 2024-12-31
- Validation: 2025-01-01 ~ present (out-of-sample)
- Success: OOS return ≥15%, Sharpe ≥1.5, MDD ≤20%

### Fee Calculation

```
Cost per trade = 0.05% (entry) + 0.05% (exit) + 0.04% (slippage) = 0.14%
Minimum profit target: 1.4% (10x fees)
```

## Do's and Don'ts

**Do:**

- Reactive strategies (momentum-following)
- Simple conditions (2-3 max)
- Market filtering (trade BULL only)
- Large targets (1.5%+ to overcome fees)
- Use minute60+ timeframes

**Don't:**

- Predictive strategies (e.g., RSI < 30 -> buy)
- Complex indicator combos (3+ indicators)
- Over-optimisation (overfitting)
- Split trading (fee explosion)
- Day-level active trading

## Environment Setup

```bash
source .venv/bin/activate
brew install ta-lib  # macOS
pip install -r requirements.txt
```

## Architecture Notes

- **RegimeRouter**: Classifies market as BULL/SIDEWAYS/BEAR using MFI and ADX
- **Upbit**: Spot trading (v35 for BULL, sideways_v2 for SIDEWAYS)
- **Binance**: Futures short (SHORT_V1 for BEAR_STRONG only)
- **Risk**: Kill-switch via Telegram (`/kill_on`, `/kill_off`), 5% daily loss limit

## Active Technologies
- Python 3.10+ with type hints + pandas, sqlite3, existing Backtester class, TelegramNotifier (001-daily-backtest-comparison)
- SQLite (`trading_results.db` for trades, new table for reports) (001-daily-backtest-comparison)
- Python 3.9+ with type hints + Flask, Jinja2, vanilla JavaScript (existing stack) (001-dashboard-upgrade)
- SQLite (`data/*.db` for market data), JSON files (`logs/*.json` for trading logs) (001-dashboard-upgrade)
- Python 3.10+ with type hints + Flask (existing), Jinja2 (existing), vanilla JavaScript (existing) (001-trading-metrics-dashboard)
- SQLite (`data/*.db`), JSON logs (`logs/*.json`) - read-only access (001-trading-metrics-dashboard)

## Recent Changes
- 001-daily-backtest-comparison: Added Python 3.10+ with type hints + pandas, sqlite3, existing Backtester class, TelegramNotifier
