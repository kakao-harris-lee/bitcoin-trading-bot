# Bitcoin Trading Bot - AI Coding Agent Instructions

## Project Overview

A systematic Bitcoin trading bot framework for iterative strategy development, backtesting, and optimization using 8 years of historical data (2017-2025, 4M+ records, 11 timeframes).

**Key Philosophy**: Evidence-based strategy development through rigorous backtesting with out-of-sample validation (2020-2024 training, 2025 validation).

## Architecture

### Core Components

- **`core/`** - Shared libraries (DataLoader, Backtester, KellyCalculator, MarketAnalyzer)
- **`strategies/`** - Versioned strategies with organized lifecycle:
  - Production: `v35_optimized/` (deployed on AWS, 23.91% CAGR, Sharpe 2.62)
  - Experimental: `v-a-01` to `v-a-15` series (perfect signal reproduction research)
  - Archive: `_archive/` (v01-v29), `_deprecated/` (v30-v46 abandoned strategies)
  - Support: `_library/`, `_templates/`, `_reports/`, `_analysis/`
- **`automation/`** - Data collection and validation scripts
- **`live_trading/`** - Real trading engine with Upbit API integration and Telegram notifications
- **`deployment/`** - AWS EC2 deployment scripts and systemd services
- **`web/`** - Dashboard (future)

### Database Architecture

- **`upbit_bitcoin.db`** (489MB, read-only) - Historical OHLCV data in tables `bitcoin_minute1`, `bitcoin_day`, etc.
- **`trading_results.db`** - Backtest results, trades, and hyperparameters

## Strategy Development Pattern

### Standard Strategy Structure

```python
class VxxStrategy:
    def __init__(self, config: Dict):
        self.config = config
        self.in_position = False
        self.entry_price = 0
        self.entry_time = None

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """
        Returns: {'action': 'buy'|'sell'|'hold', 'fraction': 0.0-1.0, 'reason': str}
        """
        if i < 30:  # Need warmup period for indicators
            return {'action': 'hold', 'reason': 'INSUFFICIENT_DATA'}
        # Strategy logic here...
```

### Required Files Per Strategy

- `strategy.py` - Core strategy class with `execute()` method
- `backtest.py` - Uses `core.Backtester` with standard configuration
- `config.json` - Hyperparameters (validated against best practices)
- `README.md` - Strategy documentation in Korean
- Optional: `optimize_optuna.py` for hyperparameter tuning

### Data Loading (Context Manager Pattern)

```python
from core import DataLoader

with DataLoader() as loader:
    df = loader.load_timeframe("day", start_date="2020-01-01", end_date="2024-12-31")
    # DataFrame columns: timestamp, open, high, low, close, volume
```

### Backtesting (Standard Configuration)

```python
from core.backtester import Backtester

backtester = Backtester(
    initial_capital=10_000_000,  # 10M KRW (standard)
    fee_rate=0.0005,             # 0.05% Upbit fee
    slippage=0.0002,             # 0.02% realistic slippage
    min_order_amount=10_000      # 10K KRW minimum
)

results = backtester.run(df, strategy_func, strategy_params)
# Returns: total_return, sharpe_ratio, max_drawdown, win_rate, num_trades, etc.
```

## Project-Specific Conventions

### Versioning

- Main series: `vXX_name/` (e.g., `v35_optimized/`)
- Experimental: `v-a-XX/` (targeting 45,254 "perfect signal" reproduction)
- **CRITICAL BUG**: v43/v45 have compound interest bugs - **DO NOT USE OR REFERENCE**

### Documentation Standards

- Korean language in `CLAUDE.md` (project master guide)
- Strategy reports: `YYMMDD-HHMM_STRATEGY_REPORT.md`
- Always include backtest periods, metrics, and comparison to Buy&Hold baseline

### Market State Classification

7-level system used across strategies (see `v35_optimized/market_classifier_v34.py`):

```python
MARKET_STATES = [
    'BULL_STRONG', 'BULL_MODERATE',           # Uptrends
    'SIDEWAYS_BULL', 'SIDEWAYS_NEUTRAL', 'SIDEWAYS_BEAR',  # Range-bound
    'BEAR_MODERATE', 'BEAR_STRONG'            # Downtrends
]
```

### Position Sizing

Use fractional Kelly criterion (0.25 factor) after establishing win rate via backtesting.

## Critical Implementation Details

### Timeframe Constants

```python
TIMEFRAMES = ["minute1", "minute3", "minute5", "minute10", "minute15",
              "minute30", "minute60", "minute240", "day", "week", "month"]
```

### Perfect Signals (v-a Series Context)

- Dataset: 45,254 historically profitable signals in `strategies/v41_scalping_voting/analysis/perfect_signals/`
- Evaluation: Combined score = Reproduction rate (40%) + Profit rate (60%)
- S-Tier threshold: 70%+ combined score
- Best performer: v-a-02 (74.12%, A-Tier) using data-driven optimization

### Known Issues & Fixes

- **Data gaps**: minute5 starts 2024-08-26; use `automation/collect_missing_data.py` to fill
- **TA-Lib dependency**: `brew install ta-lib` on macOS (required before pip install)
- **v43/v45 bug**: Wrong position calculation formula - never copy this pattern

## Production Deployment

### Current Production Stack

- Strategy: `v35_optimized/` with 7-level market classifier + dynamic exit management
- Platform: Docker Compose on dedicated server (49.247.171.64)
- Access: `ssh deploy@49.247.171.64`
- Monitoring: Telegram notifications via `live_trading/telegram_notifier.py`
- Performance: 23.91% CAGR, Sharpe 2.62, MDD -2.39%

### Deployment Workflow

```bash
# Server deployment
cd deployment
./deploy_to_server.sh

# Remote monitoring
./monitor_server.sh

# Direct server access
ssh deploy@49.247.171.64
cd /home/deploy/bitcoin-trading-bot
docker compose logs -f
```

See `deployment/SERVER_DEPLOYMENT.md` for complete setup guide.

## AI Market Analyzer v2 (In Progress)

**Status**: Phase 1 complete - integrated into v35_optimized in test mode (logs only, no trading impact)

**Architecture** (see `core/market_analyzer_v2_plan.md`):

- Multi-agent system: TrendAnalyzer, VolatilityAgent, VolumeAgent, SentimentAgent, CoordinatorAgent
- Models: LSTM/Transformer for trend prediction, GAN for volatility, CNN for volume patterns
- Training: Leverages 45,254 perfect signals from v-a series
- Real-time adaptation with confidence scoring

**Next Phase** (after 1 week AWS monitoring):

- Activate AI influence on trading decisions
- Add advanced agents with deep learning models
- Target: +0.5-1.5%p additional return improvement

## Essential Commands

```bash
# Setup
source upbit_history_db/venv/bin/activate
pip install -r requirements.txt

# Data validation
python automation/verify_all_timeframes.py

# Run production backtest
cd strategies/v35_optimized && python backtest.py

# Run experimental evaluation
cd strategies/v-a-02 && python run_universal_evaluation.py

# Hyperparameter optimization
cd strategies/<strategy_name> && python optimize_optuna.py

# Live trading (requires .env with API keys)
python live_trading/main.py
```

## Development Guidelines

1. **Always validate against v35_optimized patterns** - it's the production baseline
2. **Use out-of-sample testing** - train on 2020-2024, validate on 2025
3. **Document in Korean** - follow CLAUDE.md conventions
4. **Avoid overfitting** - compare to Buy&Hold, validate MDD and Sharpe ratio
5. **Test data integrity** - use `automation/verify_all_timeframes.py` before backtesting
6. **Follow naming conventions** - `YYMMDD-HHMM_` prefix for reports
7. **Reference AI v2 plan** - for any market analysis enhancements (`core/market_analyzer_v2_plan.md`)
