# Quickstart: Backtest MLflow Visualization

**Date**: 2026-01-18

## Prerequisites

1. Python 3.9+
2. Existing bitcoin-trading-bot setup
3. MLflow installed: `pip install mlflow`

## Installation

```bash
# Add MLflow to dependencies (if not already in requirements.txt)
pip install mlflow

# Verify installation
python -c "import mlflow; print(mlflow.__version__)"
```

## Basic Usage

### 1. Run a Backtest with Visualization

```python
from core.backtester import Backtester
from core.data_loader import DataLoader

# Load price data
with DataLoader() as loader:
    df = loader.load_timeframe("minute60", start_date="2024-01-01", end_date="2024-06-30")

# Run backtest with MLflow tracking
backtester = Backtester()
result = backtester.run_strategy(
    df,
    strategy_name="v35_long",
    config={
        "stop_loss_pct": 1.5,
        "take_profit_pct": 3.0,
        "trailing_enabled": True,
    },
    symbol="BTC",
)

# View results
print(f"Total Return: {result.total_return_pct:.2f}%")
print(f"Benchmark Return: {result.benchmark_return_pct:.2f}%")
print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
print(f"Max Drawdown: {result.max_drawdown_pct:.2f}%")
```

### 2. Generate Dual-Axis Chart

```python
from core.backtest_visualizer import BacktestVisualizer

visualizer = BacktestVisualizer()
chart_path = visualizer.create_chart(result, output_path="backtest_chart.png")
print(f"Chart saved to: {chart_path}")
```

### 3. Log to MLflow

```python
from core.mlflow_tracker import MLflowTracker

tracker = MLflowTracker()
run_id = tracker.log_run(result, chart_path=chart_path)

if run_id:
    print(f"Logged to MLflow run: {run_id}")
    print(f"View at: {tracker.get_experiment_url()}")
```

### 4. View in MLflow UI

```bash
# Start MLflow UI
mlflow ui --backend-store-uri ./mlruns

# Open browser to http://localhost:5000
```

## Parameter Sweep

```python
from core.parameter_sweep import ParameterSweep, ParameterSweepRunner

# Define parameter grid
sweep = ParameterSweep(
    strategy_name="v35_long",
    symbol="BTC",
    parameter_grid={
        "stop_loss_pct": [1.0, 1.5, 2.0],
        "take_profit_pct": [2.0, 3.0, 4.0],
    },
    base_config={
        "position_size": 0.01,
        "trailing_enabled": True,
    },
)

print(f"Running {sweep.total_combinations} combinations...")

# Run sweep with progress
runner = ParameterSweepRunner(backtester)
results = runner.run(
    df, sweep,
    progress_callback=lambda cur, total: print(f"Progress: {cur}/{total}")
)

# Find best result
best = runner.get_best_result(results, metric="sharpe_ratio")
print(f"\nBest configuration:")
print(f"  Sharpe Ratio: {best.sharpe_ratio:.2f}")
print(f"  Parameters: {best.params}")
```

## Configuration

### config/mlflow.json

```json
{
  "mlflow": {
    "enabled": true,
    "tracking_uri": "./mlruns",
    "experiment_name": "backtest-experiments"
  },
  "visualization": {
    "chart_width": 12,
    "chart_height": 6,
    "dpi": 150,
    "format": "png"
  }
}
```

### Environment Variables

```bash
# Override MLflow settings
export MLFLOW_TRACKING_URI="./mlruns"
export MLFLOW_EXPERIMENT_NAME="my-experiment"
export MLFLOW_ENABLED="true"
```

## Disabling MLflow

```python
from core.mlflow_tracker import MLflowConfig

# Disable via config
config = MLflowConfig(enabled=False)
tracker = MLflowTracker(config)

# Or via environment
# export MLFLOW_ENABLED=false
```

## Troubleshooting

### MLflow not installed

```
WARNING: MLflow not installed, skipping experiment tracking
```

**Solution**: `pip install mlflow`

### Chart generation fails

```
ValueError: Result missing equity_curve or benchmark_curve
```

**Solution**: Ensure backtest ran successfully and produced results.

### MLflow UI not loading

```bash
# Check if port 5000 is in use
lsof -i :5000

# Use different port
mlflow ui --port 5001
```

## Comparing Multiple Runs in MLflow UI

After logging multiple backtest runs, you can compare them side-by-side in the MLflow UI.

### 1. Start MLflow UI

```bash
mlflow ui --backend-store-uri ./mlruns
# Open http://localhost:5000 in your browser
```

### 2. Filter Runs by Strategy or Symbol

Use the search bar to filter runs:
- By strategy: `tags.strategy_name = "v35_long"`
- By symbol: `tags.symbol = "BTC"`
- By sweep: `tags.sweep_id = "sweep_20240115"`

### 3. Select Runs to Compare

1. Check the boxes next to runs you want to compare
2. Click "Compare" button at the top
3. View metrics side-by-side in the comparison view

### 4. Key Metrics to Compare

| Metric | Good Value | Description |
|--------|------------|-------------|
| `sharpe_ratio` | >= 1.5 | Risk-adjusted return |
| `max_drawdown_pct` | <= 20% | Maximum loss from peak |
| `total_return_pct` | > benchmark | Strategy vs buy-and-hold |
| `win_rate` | >= 0.5 | Percentage of winning trades |
| `profit_factor` | >= 1.5 | Gross profit / gross loss |

### 5. Sort and Rank

Click column headers to sort runs by metric:
- Sort by `sharpe_ratio` descending to find best risk-adjusted strategies
- Sort by `total_return_pct` descending to find highest returns
- Sort by `max_drawdown_pct` ascending to find safest strategies

### 6. View Chart Artifacts

1. Click on a run name to open details
2. Scroll to "Artifacts" section
3. Click on chart PNG to view strategy vs benchmark visualization

## Next Steps

1. Review results in MLflow UI
2. Compare multiple runs side-by-side
3. Export best configuration to production
4. See [Constitution](/.specify/memory/constitution.md) for validation requirements:
   - Sharpe ratio >= 1.5
   - Max drawdown <= 20%
   - OOS return >= 15%
