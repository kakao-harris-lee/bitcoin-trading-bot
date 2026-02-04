"""Parameter sweep functionality for grid search with MLflow logging."""

import logging
import re
import uuid
from dataclasses import dataclass, field
from functools import reduce
from itertools import product
from operator import mul
from typing import Any, Callable, Dict, Iterator, List, Optional, Union

import pandas as pd

from core.backtest_result import BacktestResult
from core.mlflow_config import MLflowConfig

logger = logging.getLogger(__name__)


def _sanitize_sweep_id(sweep_id: str) -> str:
    """Sanitize sweep_id for safe use in filenames.

    Args:
        sweep_id: The sweep identifier

    Returns:
        Safe string containing only alphanumeric and underscore
    """
    # Only allow alphanumeric and underscore
    safe = re.sub(r"[^\w]", "_", sweep_id)
    return safe[:64]  # Limit length


@dataclass
class ParameterSweep:
    """Configuration for parameter grid search.

    Defines the parameter space to explore during a sweep.

    Attributes:
        strategy_name: Strategy name to test
        symbol: Trading symbol
        parameter_grid: Dictionary mapping parameter names to lists of values
        base_config: Base configuration that sweep parameters override
        parallel: Whether to run combinations in parallel (future use)
        max_combinations: Optional limit on total runs

    Example:
        >>> sweep = ParameterSweep(
        ...     strategy_name="v35_classic_wide",
        ...     symbol="BTC",
        ...     parameter_grid={
        ...         "stop_loss_pct": [1.0, 1.5, 2.0],
        ...         "take_profit_pct": [2.0, 3.0, 4.0],
        ...     },
        ...     base_config={"position_size": 0.01},
        ... )
        >>> print(f"Total combinations: {sweep.total_combinations}")  # 9
    """

    strategy_name: str
    symbol: str
    parameter_grid: Dict[str, List[Any]]
    base_config: Dict[str, Any] = field(default_factory=dict)

    # Execution settings
    parallel: bool = False  # Future: parallel execution
    max_combinations: Optional[int] = None  # Limit total runs

    def generate_combinations(self) -> Iterator[Dict[str, Any]]:
        """Generate all parameter combinations.

        Yields:
            Configuration dictionaries with base_config merged with each combination.
        """
        keys = list(self.parameter_grid.keys())
        values = list(self.parameter_grid.values())

        count = 0
        for combo in product(*values):
            if self.max_combinations and count >= self.max_combinations:
                break

            config = self.base_config.copy()
            for key, value in zip(keys, combo):
                config[key] = value

            yield config
            count += 1

    @property
    def total_combinations(self) -> int:
        """Calculate total number of combinations."""
        if not self.parameter_grid:
            return 0

        total = reduce(mul, (len(v) for v in self.parameter_grid.values()), 1)
        if self.max_combinations:
            return min(total, self.max_combinations)
        return total


class ParameterSweepRunner:
    """Run parameter sweeps with automatic MLflow logging.

    Executes backtests for all parameter combinations and optionally
    logs results to MLflow with sweep grouping.

    Example:
        >>> runner = ParameterSweepRunner(backtester)
        >>> results = runner.run(df, sweep, progress_callback=print_progress)
        >>> best = runner.get_best_result(results, metric="sharpe_ratio")
    """

    def __init__(
        self,
        backtester: "Backtester",
        mlflow_tracker: Optional["MLflowTracker"] = None,
        visualizer: Optional["BacktestVisualizer"] = None,
    ):
        """Initialize sweep runner.

        Args:
            backtester: Backtester instance to use for running tests
            mlflow_tracker: Optional MLflowTracker for logging (created if None)
            visualizer: Optional BacktestVisualizer for charts (created if None)
        """
        self.backtester = backtester
        self._mlflow_tracker = mlflow_tracker
        self._visualizer = visualizer

    @property
    def mlflow_tracker(self) -> Optional["MLflowTracker"]:
        """Get or create MLflow tracker."""
        if self._mlflow_tracker is None:
            try:
                from core.mlflow_tracker import MLflowTracker

                self._mlflow_tracker = MLflowTracker()
            except ImportError:
                pass
        return self._mlflow_tracker

    @property
    def visualizer(self) -> Optional["BacktestVisualizer"]:
        """Get or create visualizer."""
        if self._visualizer is None:
            try:
                from core.backtest_visualizer import BacktestVisualizer

                self._visualizer = BacktestVisualizer()
            except ImportError:
                pass
        return self._visualizer

    def run(
        self,
        df: pd.DataFrame,
        sweep: ParameterSweep,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        log_to_mlflow: bool = True,
        generate_charts: bool = True,
    ) -> List[BacktestResult]:
        """Run parameter sweep.

        Args:
            df: Price data DataFrame
            sweep: ParameterSweep configuration
            progress_callback: Optional callback(current, total) for progress
            log_to_mlflow: Whether to log results to MLflow
            generate_charts: Whether to generate chart for each run

        Returns:
            List of BacktestResult objects, one per combination
        """
        results = []
        chart_paths = []
        total = sweep.total_combinations
        # Generate safe sweep_id using UUID (inherently safe)
        sweep_id = f"sweep_{uuid.uuid4().hex[:8]}"
        safe_sweep_id = _sanitize_sweep_id(sweep_id)

        logger.info(f"Starting parameter sweep: {total} combinations (sweep_id={safe_sweep_id})")

        for i, config in enumerate(sweep.generate_combinations()):
            if progress_callback:
                progress_callback(i + 1, total)

            # Run backtest
            result = self.backtester.run_strategy(
                df,
                strategy_name=sweep.strategy_name,
                config=config,
                symbol=sweep.symbol,
                return_backtest_result=True,
            )

            results.append(result)

            # Generate chart with sanitized filename
            chart_path = None
            if generate_charts and self.visualizer:
                try:
                    # Use sanitized sweep_id in filename
                    safe_filename = f"{safe_sweep_id}_run_{i+1}.png"
                    chart_path = self.visualizer.create_chart(
                        result,
                        output_path=safe_filename,
                    )
                    chart_paths.append(chart_path)
                except Exception as e:
                    logger.warning(f"Chart generation failed for run {i+1}: {e}")
                    chart_paths.append(None)

        # Log all results to MLflow
        if log_to_mlflow and self.mlflow_tracker and self.mlflow_tracker.enabled:
            try:
                self.mlflow_tracker.log_sweep(
                    results,
                    sweep_id=safe_sweep_id,
                    chart_paths=chart_paths if generate_charts else None,
                )
                logger.info(f"Logged {len(results)} runs to MLflow (sweep_id={safe_sweep_id})")
            except Exception as e:
                logger.warning(f"MLflow logging failed for sweep: {e}")

        return results

    def get_best_result(
        self,
        results: List[BacktestResult],
        metric: str = "sharpe_ratio",
        minimize: bool = False,
    ) -> Optional[BacktestResult]:
        """Find the best result by specified metric.

        Args:
            results: List of BacktestResult objects
            metric: Metric name to optimize (e.g., "sharpe_ratio", "total_return_pct")
            minimize: If True, find minimum instead of maximum

        Returns:
            Best BacktestResult, or None if results is empty
        """
        if not results:
            return None

        def get_metric_value(result: BacktestResult) -> float:
            value = getattr(result, metric, None)
            if value is None:
                return float("-inf") if not minimize else float("inf")
            return value

        if minimize:
            return min(results, key=get_metric_value)
        else:
            return max(results, key=get_metric_value)

    def get_top_results(
        self,
        results: List[BacktestResult],
        metric: str = "sharpe_ratio",
        n: int = 5,
        minimize: bool = False,
    ) -> List[BacktestResult]:
        """Get top N results by specified metric.

        Args:
            results: List of BacktestResult objects
            metric: Metric name to optimize
            n: Number of top results to return
            minimize: If True, get lowest instead of highest

        Returns:
            List of top N BacktestResult objects, sorted by metric
        """
        if not results:
            return []

        def get_metric_value(result: BacktestResult) -> float:
            value = getattr(result, metric, None)
            if value is None:
                return float("-inf") if not minimize else float("inf")
            return value

        sorted_results = sorted(results, key=get_metric_value, reverse=not minimize)
        return sorted_results[:n]
