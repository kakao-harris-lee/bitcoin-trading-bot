# Bitcoin Trading Bot - AI Agent Instructions

## Project Architecture

This is a **systematic Bitcoin trading bot development framework** that iteratively creates, backtests, and optimizes trading strategies using historical data (2017-2025, 8 years, 4M+ records).

### Core Components

- **`core/`** - Shared libraries for data loading, backtesting engine, Kelly criterion calculations
- **`strategies/`** - Version-controlled strategy implementations (v01-v45+, v-a-01+ series)
- **`automation/`** - Data collection and strategy development automation
- **`upbit_bitcoin.db`** - Primary price data (489MB, 11 timeframes from minute1 to month)
- **`trading_results.db`** - Centralized backtest results storage

### Current Strategy Status

**Production Ready**: `v35_optimized/` (Sharpe 2.24, MDD -2.33%, 13-25% annual returns)
**Testing Phase**: `v-a-xx/` series (v-a-01 to v-a-15) with extensive backtests completed

- v-a-02: A-Tier performance (74.12% reproduction rate) - near S-Tier
- v-a-15: Ultimate adaptive strategy targeting +43-59% returns
  **Strategy Selection**: Evaluating best candidate for live deployment
  **CRITICAL**: v43/v45 have compound interest calculation bugs - **DO NOT USE**

## Development Workflows

### Strategy Development Pattern

```python
# 1. Create strategy class inheriting common patterns
class VxxStrategy:
    def __init__(self, config: Dict):
        self.config = config
        self.in_position = False

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        # Return {'action': 'buy'/'sell'/'hold', 'fraction': 0.0-1.0, 'reason': str}
```

### Required Files for New Strategy

- `strategy.py` - Main strategy logic
- `backtest.py` - Backtesting script using `core.Backtester`
- `config.json` - Hyperparameters
- Optional: `optimize_optuna.py` for hyperparameter tuning

### Data Loading Pattern

```python
from core import DataLoader

with DataLoader() as loader:
    df = loader.load_timeframe("day", start_date="2020-01-01", end_date="2024-12-31")
    # df contains: timestamp, open, high, low, close, volume
```

### Backtesting Pattern

```python
from core.backtester import Backtester

backtester = Backtester(
    initial_capital=10_000_000,  # 10M KRW
    fee_rate=0.0005,             # 0.05%
    slippage=0.0002              # 0.02%
)

results = backtester.run(df, strategy)
# Returns: total_return, sharpe_ratio, max_drawdown, win_rate, etc.
```

## Project-Specific Conventions

### Versioning & Documentation

- Strategy versions: `vXX_name/` (e.g., `v35_optimized/`)
- New experimental series: `v-a-XX/` (targeting perfect signal reproduction)
- Documentation: Korean language in `CLAUDE.md`, strategy reports in markdown
- Results naming: `YYMMDD-HHMM_STRATEGY_REPORT.md`

### Trading Configuration Standards

```python
STANDARD_CONFIG = {
    'initial_capital': 10_000_000,  # 10M KRW
    'fee_rate': 0.0005,             # 0.05% Upbit fee
    'slippage': 0.0002,             # 0.02% slippage
    'min_order_amount': 10_000      # 10K KRW minimum
}
```

### Market State Classification

Many strategies use 7-level market classification:

- `BULL_STRONG`, `BULL_WEAK`, `SIDEWAYS_BULL`, `SIDEWAYS_NEUTRAL`
- `SIDEWAYS_BEAR`, `BEAR_WEAK`, `BEAR_STRONG`

### Kelly Criterion Integration

All strategies should use fractional Kelly (0.25) for position sizing after establishing win rate.

## Critical Technical Details

### Database Schema

- **upbit_bitcoin.db**: Tables named `bitcoin_minute1`, `bitcoin_day`, etc.
- **trading_results.db**: `strategies`, `backtest_results`, `trades`, `hyperparameters`

### Timeframe Mapping

```python
TIMEFRAMES = ["minute1", "minute3", "minute5", "minute10", "minute15",
              "minute30", "minute60", "minute240", "day", "week", "month"]
```

### Perfect Signals Context

The v-a series targets reproducing 45,254 "perfect signals" extracted using future data:

- Location: `strategies/v41_scalping_voting/analysis/perfect_signals/`
- Evaluation: Reproduction rate (40%) + profit rate (60%) = combined score
- Target: 70%+ for S-Tier (production ready)
- Current best: v-a-02 at 74.12% (S-Tier performance)

### Strategy Testing Status

- **v-a-01**: Failed (7.74% reproduction, C-Tier) - wrong signal patterns
- **v-a-02**: Success (74.12% reproduction, A-Tier) - data-driven optimization
- **v-a-15**: Advanced (targeting +43-59% returns) - multi-strategy adaptive approach
- **Testing complete**: Most v-a series have backtest results for deployment evaluation
- Evaluation: Reproduction rate (40%) + profit rate (60%) = combined score
- Target: 70%+ for S-Tier (production ready)

### Known Issues
- **v43/v45 Bug**: Position calculation uses `capital / (capital * 1.0007)` instead of proper BTC quantity
- **Data Gaps**: minute5 data starts 2024-08-26, use `automation/collect_missing_data.py`
- **Dependencies**: Requires TA-Lib (brew install ta-lib on macOS)

## Next Development Phase: AI Market Analyzer v2

**Status**: Planning phase - AI Agent-based market analysis system
**Goal**: Upgrade simple TA-Lib market_analyzer to multi-agent AI system
**Foundation**: v35 stability + v-a series perfect signal reproduction + v10 RL experience
**Plan Location**: `core/market_analyzer_v2_plan.md`

### Key Features
- **Multi-Agent Architecture**: Trend, Volatility, Volume, Sentiment, Coordinator agents
- **Perfect Signal Integration**: Leverage 45,254 perfect signals from v-a series
- **Real-time Adaptation**: Online learning with confidence scoring
- **Backward Compatibility**: Maintains v35 7-level market classification

## Quick Commands

```bash
# Environment setup
source v1_db생성/venv/bin/activate
pip install -r requirements.txt

# Data verification
python automation/verify_all_timeframes.py

# Run strategy backtest (production ready)
cd strategies/v35_optimized && python backtest.py

# Run v-a series evaluation (testing)
cd strategies/v-a-02 && python run_universal_evaluation.py

# Optimize hyperparameters
python optimize_optuna.py

# View AI market analyzer v2 plan
cat core/market_analyzer_v2_plan.md
```

When implementing new strategies, always validate against existing patterns in `v35_optimized/` (production) or `v-a-02/` (S-Tier reproduction). **Next focus**: AI Market Analyzer v2 development following the detailed plan in `core/market_analyzer_v2_plan.md`.
