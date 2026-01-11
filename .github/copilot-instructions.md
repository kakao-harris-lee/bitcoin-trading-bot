# Copilot Instructions for Bitcoin Trading Bot

## Architecture Overview

This is a **dual-exchange Bitcoin trading bot** with:

- **Upbit** (Korea): Spot/long positions (V35, Sideways_V2 strategies)
- **Binance**: Futures/short positions (Short_V1, H4_Short strategies)
- **RegimeRouter**: Market state oracle classifying MFI/ADX → 7 states (BULL*STRONG, BULL_MODERATE, SIDEWAYS*_, BEAR\__)

Key insight: `RegimeRouter` is **read-only reference** — strategies decide independently whether to trade based on regime context.

### Critical Paths

| Component        | Path                            | Purpose                             |
| ---------------- | ------------------------------- | ----------------------------------- |
| Entry point      | `run.py`                        | Single entry for paper/live modes   |
| Engine           | `trading/multi_asset_engine.py` | Orchestrates all components         |
| Strategies       | `trading/strategy/*.py`         | Inherit from `BaseStrategy`         |
| Strategy configs | `config/strategies/*.json`      | Hyperparameters (thresholds, exits) |
| Backtester       | `core/backtester.py`            | Strategy validation                 |
| Data             | `core/data_loader.py`           | SQLite loader for Upbit/Binance     |

## Developer Commands

```bash
# Bot management (preferred)
./bot.sh start                    # Paper trading
./bot.sh start --trend=live       # Live trading (requires ENABLE_LIVE_TRADING=1)
./bot.sh stop && ./bot.sh status

# Testing
pytest                            # Run all tests
pytest tests/test_unified_backtester.py -v  # Specific test

# Backtesting
python scripts/backtest.py --by-year
python scripts/optimize.py --strategy v35_long --trials 100
```

## Strategy Development Pattern

1. Inherit from `BaseStrategy` in `trading/strategy/base.py`
2. Add JSON config to `config/strategies/{name}.json`
3. Use `core.data_loader.DataLoader` for historical data:
   ```python
   with DataLoader() as loader:
       df = loader.load_timeframe('day', start_date='2024-01-01')
   ```

### Backtesting Standards

- **Train period**: 2020-01-01 to 2024-12-31
- **Validation (OOS)**: 2025-01-01 to present
- **Success criteria**: OOS return ≥15%, Sharpe ≥1.5, MDD ≤20%
- **Fee model**: Entry 0.05% + Exit 0.05% + Slippage 0.04% = **0.14% per round trip**

## Code Conventions

### Imports

```python
# Core types from central location
from core.types import Exchange, Direction, MarketState, SignalMessage

# Indicators via unified module
from trading.indicators import add_all_indicators
```

### Configuration Loading

Strategy configs are JSON with nested sections:

```python
# config/strategies/v35_long.json structure:
{
  "market_classifier": { "mfi_bull_strong": 54, ... },
  "entry_conditions": { "momentum_rsi_bull_strong": 57, ... },
  "exit_conditions": { "tp_bull_strong_1": 0.053, "trailing_bull_strong": 0.065, ... }
}
```

### Korean Comments

Legacy code uses Korean comments. Maintain consistency when modifying existing files.

## Git Workflow

**Feature branches mandatory for new work:**

```bash
git checkout -b feature/{name}
# ... implement ...
git push -u origin feature/{name}
# Create PR to main
```

Never commit directly to `main`. Deploy via `git pull` only (no rsync/SSH uploads).

## Testing Notes

- Tests in `tests/` with `conftest.py` providing async fixtures
- Integration tests marked with `@pytest.mark.integration`
- Strategy result snapshots stored as `tests/test_*_result.json`

## Key Antipatterns to Avoid

- **Predictive entries** (e.g., "RSI < 30 → buy anticipating reversal") — use **reactive/momentum** entries
- **Over-optimization** — limit to 2-3 indicators per strategy
- **Sub-1% profit targets** — minimum 1.4% to cover 0.14% fees (10x buffer)
- **Active day trading** — prefer minute60+ timeframes

## Files to Consult

- [CLAUDE.md](../CLAUDE.md) — Quick reference and project rules
- [docs/strategies.md](../docs/strategies.md) — Detailed strategy specs
- [docs/architecture-review.md](../docs/architecture-review.md) — Component analysis
