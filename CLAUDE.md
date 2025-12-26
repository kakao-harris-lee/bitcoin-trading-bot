# Bitcoin Trading Bot

## Quick Reference

```bash
# Run paper trading
python run.py --mode paper

# Run live trading (requires ENABLE_LIVE_TRADING=1)
ENABLE_LIVE_TRADING=1 python run.py --mode live

# Run tests
pytest

# Docker
docker-compose up -d
docker-compose logs -f paper-trading
```

## Project Structure

```
bitcoin-trading-bot/
├── run.py                          # Entry point
├── trading/                        # Main trading engine
│   ├── engine.py                   # DualPaperTradingEngine
│   ├── core/                       # Infrastructure (redis, config, risk)
│   ├── adapters/                   # Exchange adapters (Upbit, Binance)
│   ├── modules/                    # Execution modules & strategies
│   └── notifications/              # Telegram integration
├── strategies/                     # Strategy configs & backtests
│   ├── v35_optimized/              # Current production strategy
│   ├── SHORT_V1/                   # Binance short strategy
│   └── _plans/                     # Strategy plan documents
├── core/                           # Shared libs (data_loader, backtester)
├── web/                            # Dashboard (Flask)
├── analysis/                       # Tuned settings (selected_candidate.json)
└── docs/                           # Documentation
```

## Key Files

- `run.py` - Single entry point for all trading modes
- `trading/engine.py` - Main engine class
- `strategies/v35_optimized/` - Current production strategy
- `analysis/selected_candidate.json` - Tuned operational settings
- `upbit_bitcoin.db` - Market data (read-only)
- `trading_results.db` - Backtest/trading results

## Development Rules

### Strategy Development Workflow

1. Create plan: `strategies/_plans/{DATE}.v{NN}.{name}.plan.md`
2. Wait for user approval
3. Implement in `strategies/v{NN}_{name}/`
4. Run backtesting
5. Document results

### Strategy Directory Structure

```
strategies/v{NN}_{name}/
├── config.json      # Hyperparameters
├── strategy.py      # Strategy logic
├── backtest.py      # Backtesting script
└── results.json     # Results (auto-generated)
```

### Backtesting Standards

- Training: 2020-01-01 ~ 2024-12-31
- Validation: 2025-01-01 ~ present (out-of-sample)
- Success: OOS return ≥15%, Sharpe ≥1.5, MDD ≤20%

### Fee Calculation

```
Cost per trade = 0.05% (entry) + 0.05% (exit) + 0.04% (slippage) = 0.14%
Minimum profit target: 1.4% (10× fees)
```

## Do's and Don'ts

**Do:**

- Reactive strategies (momentum-following)
- Simple conditions (2-3 max)
- Market filtering (trade BULL only)
- Large targets (1.5%+ to overcome fees)
- Use minute60+ timeframes

**Don't:**

- Predictive strategies (e.g., RSI < 30 → buy)
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
