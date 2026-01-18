# CLI Interface: Backtest MLflow Visualization

**Date**: 2026-01-18
**Status**: Complete

## Overview

This feature extends the existing backtest CLI with MLflow integration and visualization. The interfaces are primarily Python APIs called from scripts or notebooks.

## Python API Contracts

### 1. Backtester.run_strategy() (Enhanced)

Existing method enhanced with visualization and MLflow support.

```python
def run_strategy(
    self,
    df: pd.DataFrame,
    strategy_name: str,
    config: Optional[Dict[str, Any]] = None,
    symbol: str = "BTC",
    *,
    # NEW parameters
    mlflow_config: Optional[MLflowConfig] = None,
    generate_chart: bool = True,
    chart_path: Optional[str] = None,
) -> BacktestResult:
    """Run backtest with optional MLflow tracking and visualization.

    Args:
        df: Price DataFrame (timestamp, open, high, low, close, volume)
        strategy_name: Strategy name (e.g., "v35_long")
        config: Strategy configuration parameters
        symbol: Trading symbol
        mlflow_config: MLflow configuration (None = auto-detect from config/env)
        generate_chart: Whether to generate dual-axis chart
        chart_path: Path to save chart (None = temp file for MLflow artifact)

    Returns:
        BacktestResult with equity_curve, benchmark_curve, and metrics

    Example:
        >>> result = backtester.run_strategy(
        ...     df, "v35_long",
        ...     config={"stop_loss_pct": 1.5},
        ...     mlflow_config=MLflowConfig(experiment_name="my-experiment"),
        ... )
        >>> print(f"Return: {result.total_return_pct:.2f}%")
        >>> print(f"Sharpe: {result.sharpe_ratio:.2f}")
    """
```

---

### 2. BacktestVisualizer

New module for chart generation.

```python
class BacktestVisualizer:
    """Generate dual-axis charts for backtest results."""

    def __init__(self, config: Optional[VisualizationConfig] = None):
        """Initialize visualizer.

        Args:
            config: Visualization settings (uses defaults if None)
        """

    def create_chart(
        self,
        result: BacktestResult,
        output_path: Optional[str] = None,
    ) -> str:
        """Create dual-axis chart showing strategy vs benchmark.

        Args:
            result: Backtest result with equity_curve and benchmark_curve
            output_path: Path to save chart (generates temp file if None)

        Returns:
            Path to saved chart file

        Raises:
            ValueError: If result missing required data
        """

    def create_comparison_chart(
        self,
        results: List[BacktestResult],
        output_path: Optional[str] = None,
    ) -> str:
        """Create chart comparing multiple backtest results.

        Args:
            results: List of backtest results to compare
            output_path: Path to save chart

        Returns:
            Path to saved chart file
        """
```

---

### 3. MLflowTracker

New module for experiment tracking.

```python
class MLflowTracker:
    """Track backtest experiments in MLflow."""

    def __init__(self, config: Optional[MLflowConfig] = None):
        """Initialize tracker.

        Args:
            config: MLflow configuration (auto-detects if None)
        """

    def log_run(
        self,
        result: BacktestResult,
        chart_path: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """Log backtest result to MLflow.

        Args:
            result: Backtest result to log
            chart_path: Path to chart artifact (optional)
            tags: Additional tags for the run

        Returns:
            MLflow run ID, or None if logging failed/disabled

        Example:
            >>> tracker = MLflowTracker()
            >>> run_id = tracker.log_run(result, chart_path="chart.png")
            >>> print(f"Logged as run: {run_id}")
        """

    def log_sweep(
        self,
        sweep: ParameterSweep,
        results: List[BacktestResult],
        charts: Optional[List[str]] = None,
    ) -> List[str]:
        """Log parameter sweep results to MLflow.

        All runs are tagged with sweep ID for grouping.

        Args:
            sweep: Parameter sweep configuration
            results: List of backtest results
            charts: Optional list of chart paths

        Returns:
            List of MLflow run IDs
        """

    @property
    def enabled(self) -> bool:
        """Check if MLflow tracking is enabled."""

    def get_experiment_url(self) -> Optional[str]:
        """Get URL to view experiment in MLflow UI."""
```

---

### 4. ParameterSweepRunner

New module for grid search.

```python
class ParameterSweepRunner:
    """Run parameter sweeps with MLflow tracking."""

    def __init__(
        self,
        backtester: Backtester,
        mlflow_tracker: Optional[MLflowTracker] = None,
        visualizer: Optional[BacktestVisualizer] = None,
    ):
        """Initialize sweep runner.

        Args:
            backtester: Backtester instance
            mlflow_tracker: MLflow tracker (optional)
            visualizer: Chart visualizer (optional)
        """

    def run(
        self,
        df: pd.DataFrame,
        sweep: ParameterSweep,
        *,
        generate_charts: bool = True,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[BacktestResult]:
        """Execute parameter sweep.

        Args:
            df: Price DataFrame
            sweep: Parameter sweep configuration
            generate_charts: Whether to generate charts for each run
            progress_callback: Called with (current, total) for progress

        Returns:
            List of backtest results

        Example:
            >>> sweep = ParameterSweep(
            ...     strategy_name="v35_long",
            ...     symbol="BTC",
            ...     parameter_grid={
            ...         "stop_loss_pct": [1.0, 1.5, 2.0],
            ...         "take_profit_pct": [2.0, 3.0],
            ...     },
            ...     base_config={"position_size": 0.01},
            ... )
            >>> runner = ParameterSweepRunner(backtester)
            >>> results = runner.run(df, sweep)
            >>> best = max(results, key=lambda r: r.sharpe_ratio)
            >>> print(f"Best Sharpe: {best.sharpe_ratio:.2f}")
        """

    def get_best_result(
        self,
        results: List[BacktestResult],
        metric: str = "sharpe_ratio",
    ) -> BacktestResult:
        """Get best result by specified metric.

        Args:
            results: List of backtest results
            metric: Metric to optimize ("sharpe_ratio", "total_return_pct", etc.)

        Returns:
            Best performing result
        """
```

---

## CLI Scripts (Optional Enhancement)

Future enhancement: Add CLI commands for common operations.

```bash
# Run backtest with MLflow tracking
python -m core.backtest \
    --strategy v35_long \
    --symbol BTC \
    --start 2024-01-01 \
    --end 2024-12-31 \
    --mlflow

# Run parameter sweep
python -m core.parameter_sweep \
    --strategy v35_long \
    --symbol BTC \
    --param stop_loss_pct 1.0 1.5 2.0 \
    --param take_profit_pct 2.0 3.0 4.0 \
    --mlflow

# Launch MLflow UI
mlflow ui --backend-store-uri ./mlruns
```

---

## Error Handling

All API methods follow graceful degradation pattern:

```python
# MLflowTracker.log_run() error handling
try:
    import mlflow
    # ... logging code ...
    return run_id
except ImportError:
    logger.warning("MLflow not installed")
    return None
except mlflow.MlflowException as e:
    logger.warning(f"MLflow error: {e}")
    return None
except Exception as e:
    logger.warning(f"Unexpected error logging to MLflow: {e}")
    return None
```

---

## Return Types Summary

| Method | Returns | On Error |
|--------|---------|----------|
| `run_strategy()` | `BacktestResult` | Raises exception |
| `create_chart()` | `str` (path) | Raises exception |
| `log_run()` | `Optional[str]` | Returns `None` |
| `log_sweep()` | `List[str]` | Returns partial list |
| `ParameterSweepRunner.run()` | `List[BacktestResult]` | Raises exception |
