# Research: Backtest MLflow Visualization

**Date**: 2026-01-18
**Status**: Complete

## Research Questions

### 1. MLflow Best Practices for Local Experiment Tracking

**Decision**: Use MLflow with local file store (`./mlruns`) and manual logging API

**Rationale**:
- Local file store requires no server setup, ideal for individual developer use
- Manual logging provides precise control over what gets tracked
- `mlflow.start_run()` context manager ensures proper cleanup

**Key Patterns**:
```python
import mlflow

# Set experiment (creates if not exists)
mlflow.set_experiment("backtest-experiments")

with mlflow.start_run(run_name="v35_classic_wide_btc"):
    # Log parameters
    mlflow.log_param("strategy_name", "v35_classic_wide")
    mlflow.log_param("symbol", "BTC")
    mlflow.log_param("stop_loss_pct", 1.5)

    # Log metrics
    mlflow.log_metric("total_return_pct", 15.3)
    mlflow.log_metric("sharpe_ratio", 1.8)
    mlflow.log_metric("max_drawdown_pct", 12.5)

    # Log artifacts (files)
    mlflow.log_artifact("chart.png")
```

**Alternatives Considered**:
- MLflow Tracking Server: Overkill for single-user, adds deployment complexity
- Weights & Biases: Requires cloud account, not self-hosted
- Sacred: Less active development, MLflow has better ecosystem

---

### 2. Matplotlib Dual-Axis Chart Patterns for Financial Data

**Decision**: Use `matplotlib` with `twinx()` for dual y-axes, shared x-axis (time)

**Rationale**:
- Already in dependencies (matplotlib>=3.7.0)
- `twinx()` is the standard pattern for overlaying different scales
- PNG output integrates well with MLflow artifacts

**Key Pattern**:
```python
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

fig, ax1 = plt.subplots(figsize=(12, 6))

# Left axis: Strategy equity
color1 = 'tab:blue'
ax1.set_xlabel('Date')
ax1.set_ylabel('Strategy Equity ($)', color=color1)
ax1.plot(dates, equity_curve, color=color1, label='Strategy')
ax1.tick_params(axis='y', labelcolor=color1)

# Right axis: Benchmark price
ax2 = ax1.twinx()
color2 = 'tab:orange'
ax2.set_ylabel('Benchmark Price ($)', color=color2)
ax2.plot(dates, benchmark_prices, color=color2, label='Buy & Hold', linestyle='--')
ax2.tick_params(axis='y', labelcolor=color2)

# Legend combining both axes
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')

fig.tight_layout()
plt.savefig('backtest_chart.png', dpi=150)
```

**Alternatives Considered**:
- Plotly: Interactive but larger file size, HTML not PNG
- mplfinance: Good for candlesticks but not for equity curves
- seaborn: Built on matplotlib, no dual-axis advantage

---

### 3. Benchmark Calculation Methodology (Buy-and-Hold Return)

**Decision**: Calculate benchmark as if initial capital was invested at first price and held

**Rationale**:
- Industry standard comparison for active strategies
- Easy to understand and verify
- Already have price data in backtest DataFrame

**Formula**:
```python
def calculate_benchmark(df, initial_capital):
    """Calculate buy-and-hold benchmark curve.

    Args:
        df: DataFrame with 'close' prices and 'timestamp'
        initial_capital: Starting capital (same as strategy)

    Returns:
        Series with benchmark equity at each timestamp
    """
    first_price = df['close'].iloc[0]
    shares_bought = initial_capital / first_price
    benchmark_equity = shares_bought * df['close']
    return benchmark_equity

# Benchmark return percentage
benchmark_return_pct = ((df['close'].iloc[-1] - df['close'].iloc[0])
                        / df['close'].iloc[0]) * 100
```

**Key Metrics**:
- `benchmark_equity`: Time series of what capital would be worth
- `benchmark_return_pct`: Total percentage return of buy-and-hold

**Alternatives Considered**:
- Index benchmark (SPY): Not relevant for crypto
- Risk-adjusted benchmark: More complex, Sharpe ratio covers this

---

### 4. Sharpe Ratio Calculation from Equity Curve

**Decision**: Use annualized Sharpe ratio with daily returns and configurable risk-free rate

**Rationale**:
- Industry standard risk-adjusted return metric
- Constitution requires Sharpe >= 1.5 for strategy validation
- Annualization makes comparison across timeframes meaningful

**Formula**:
```python
import numpy as np

def calculate_sharpe_ratio(equity_curve, risk_free_rate=0.0, periods_per_year=365):
    """Calculate annualized Sharpe ratio from equity curve.

    Args:
        equity_curve: Series of equity values over time
        risk_free_rate: Annual risk-free rate (default 0 for simplicity)
        periods_per_year: Number of periods per year (365 for daily)

    Returns:
        Annualized Sharpe ratio
    """
    # Calculate returns
    returns = equity_curve.pct_change().dropna()

    # Annualize
    mean_return = returns.mean() * periods_per_year
    std_return = returns.std() * np.sqrt(periods_per_year)

    # Sharpe ratio
    if std_return == 0:
        return 0.0

    sharpe = (mean_return - risk_free_rate) / std_return
    return sharpe
```

**Additional Metrics** (from spec FR-005):
- `max_drawdown_pct`: Maximum peak-to-trough decline
- `win_rate`: Percentage of profitable trades
- `profit_factor`: Gross profit / Gross loss
- `total_trades`: Number of completed trades

**Max Drawdown Formula**:
```python
def calculate_max_drawdown(equity_curve):
    """Calculate maximum drawdown percentage."""
    peak = equity_curve.expanding(min_periods=1).max()
    drawdown = (equity_curve - peak) / peak * 100
    return drawdown.min()  # Most negative value
```

**Alternatives Considered**:
- Sortino ratio: Only uses downside volatility, more complex
- Calmar ratio: Uses max drawdown, we report separately

---

## Configuration Design

**Decision**: Use JSON config file with environment variable overrides

```json
{
  "mlflow": {
    "enabled": true,
    "tracking_uri": "./mlruns",
    "experiment_name": "backtest-experiments",
    "artifact_location": null
  },
  "visualization": {
    "chart_width": 12,
    "chart_height": 6,
    "dpi": 150,
    "format": "png"
  }
}
```

**Environment Variables**:
- `MLFLOW_TRACKING_URI`: Override tracking URI
- `MLFLOW_EXPERIMENT_NAME`: Override experiment name
- `MLFLOW_ENABLED`: Enable/disable (true/false)

---

## Graceful Degradation

**Decision**: Try-except wrapper around MLflow calls, log warnings on failure

```python
def log_to_mlflow(results, config):
    """Log backtest results to MLflow with graceful degradation."""
    if not config.get('mlflow', {}).get('enabled', True):
        logger.info("MLflow tracking disabled by configuration")
        return None

    try:
        import mlflow
        # ... logging code ...
        return run_id
    except ImportError:
        logger.warning("MLflow not installed, skipping experiment tracking")
        return None
    except Exception as e:
        logger.warning(f"MLflow logging failed: {e}, continuing without tracking")
        return None
```

---

## Summary of Decisions

| Question | Decision | Key Reason |
|----------|----------|------------|
| MLflow storage | Local file store (./mlruns) | No server setup needed |
| Logging approach | Manual API | Precise control |
| Chart library | matplotlib with twinx() | Already in deps, standard pattern |
| Benchmark | Buy-and-hold from day 1 | Industry standard |
| Sharpe calculation | Annualized with daily returns | Constitution compliance |
| Config format | JSON with env overrides | Flexible, familiar |
| Failure handling | Try-except with warnings | Graceful degradation (FR-007) |
