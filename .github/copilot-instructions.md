# Copilot Instructions for Bitcoin Trading Bot

## Architecture Overview

This is a **dual-exchange Bitcoin trading bot** with:

- **Binance Spot**: Long positions (MLP_Direction, Sideways_V2 strategies)
- **Binance**: Futures/short positions (Short_V1, H4_Short strategies)
- **RegimeRouter**: Market state oracle classifying MFI/ADX → 7 states (BULL*STRONG, BULL_MODERATE, SIDEWAYS*\_, BEAR\_\_)

Key insight: `RegimeRouter` is **read-only reference** — strategies decide independently whether to trade based on regime context.

### Critical Paths

| Component   | Path                                                | Purpose                              |
| ----------- | --------------------------------------------------- | ------------------------------------ |
| Entry point | `run.py`                                            | Single entry for paper/live modes    |
| Engine      | `trading/engine.py`                                 | Orchestrates feeds & strategies      |
| Factory     | `trading/strategies/components/strategy_factory.py` | Assembles strategies from components |
| Components  | `trading/strategies/components/*.py`                | Entry/Exit logic implementations     |
| Config      | `config/strategies/allocation.json`                 | Strategy composition & params        |
| Backtester  | `core/backtester.py`                                | Legacy functional backtester         |
| Adapter     | `core/component_adapter.py`                         | Bridges components to backtester     |

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
python scripts/optimize.py --strategy short_v1 --trials 100
```

## Strategy Development Pattern

**Component-Based Architecture:** Strategies are composed of **Entry** and **Exit** components.

1.  **Entry Component**:
    - Create `trading/strategies/components/{name}_entry.py`
    - Implement `IEntryStrategy` interface.
    - Return `Signal(side="buy")` or `None`.
2.  **Exit Component**:
    - Create `trading/strategies/components/{name}_exit.py`
    - Implement `IExitStrategy` interface.
    - Return `Signal(side="sell")` or `None`.
3.  **Registration**:
    - Import components in `strategy_factory.py`.
    - Add to `STRATEGY_REGISTRY` mapping.
4.  **Configuration**:
    - Define in `allocation.json` to mix & match entry/exit components.

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
# config/strategies/allocation.json strategy structure:
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
