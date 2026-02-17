"""MLflow integration for tracking backtest experiments.

Provides graceful degradation when MLflow is unavailable.
"""

# pylint: disable=logging-fstring-interpolation,broad-exception-caught

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union

from core.backtest_result import BacktestResult
from core.mlflow_config import MLflowConfig

logger = logging.getLogger(__name__)


class MLflowTracker:
    """Track backtest experiments with MLflow.

    Provides:
    - Automatic parameter logging
    - Metrics logging (returns, Sharpe, drawdown, etc.)
    - Artifact logging (chart files)
    - Graceful degradation when MLflow unavailable

    Example:
        >>> tracker = MLflowTracker()
        >>> run_id = tracker.log_run(result, chart_path="chart.png")
        >>> if run_id:
        ...     print(f"Logged to: {tracker.get_experiment_url()}")
    """

    def __init__(self, config: Optional[MLflowConfig] = None):
        """Initialize tracker with optional configuration.

        Args:
            config: MLflow configuration. Uses defaults if not provided.
        """
        self.config = config or MLflowConfig()
        self._mlflow = None
        self._initialized = False

    @property
    def enabled(self) -> bool:
        """Check if MLflow tracking is enabled and available."""
        if not self.config.enabled:
            return False

        # Try to import mlflow
        if self._mlflow is None:
            try:
                import mlflow

                self._mlflow = mlflow
            except ImportError:
                logger.warning("MLflow not installed, tracking disabled")
                return False

        return True

    def _ensure_initialized(self) -> bool:
        """Initialize MLflow if not already done.

        Returns:
            True if initialization successful, False otherwise.
        """
        if not self.enabled:
            return False

        if self._initialized:
            return True

        try:
            self._mlflow.set_tracking_uri(self.config.tracking_uri)
            self._mlflow.set_experiment(self.config.experiment_name)
            self._initialized = True
            logger.info(
                f"MLflow initialized: experiment={self.config.experiment_name}, "
                f"tracking_uri={self.config.tracking_uri}"
            )
            return True
        except Exception as e:
            logger.warning(f"MLflow initialization failed: {e}")
            return False

    def log_run(
        self,
        result: Union[BacktestResult, Dict[str, Any]],
        chart_path: Optional[str] = None,
        run_name: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """Log a backtest run to MLflow.

        Args:
            result: BacktestResult or dict with backtest results
            chart_path: Path to chart PNG file to log as artifact
            run_name: Custom run name (auto-generated if not provided)
            tags: Additional tags to log

        Returns:
            MLflow run ID if successful, None otherwise.
        """
        if not self._ensure_initialized():
            return None

        try:
            strategy_name, symbol, params, metrics = self._extract_run_payload(result)
            run_name = run_name or self._build_run_name(strategy_name, symbol)

            with self._mlflow.start_run(run_name=run_name) as run:
                self._log_run_params(strategy_name, symbol, params)
                self._log_run_metrics(metrics)
                self._log_run_tags(strategy_name, symbol, tags)
                self._log_chart_artifact(chart_path)

                run_id = run.info.run_id
                logger.info(f"Logged MLflow run: {run_name} (id={run_id})")
                return run_id

        except Exception as e:
            logger.warning(f"MLflow logging failed: {e}, continuing without tracking")
            return None

    def _extract_run_payload(
        self, result: Union[BacktestResult, Dict[str, Any]]
    ) -> tuple[str, str, Dict[str, Any], Dict[str, Any]]:
        if isinstance(result, BacktestResult):
            metrics = {
                "total_return_pct": result.total_return_pct,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown_pct": result.max_drawdown_pct,
                "win_rate": result.win_rate,
                "total_trades": result.total_trades,
                "profit_factor": result.profit_factor,
                "benchmark_return_pct": result.benchmark_return_pct,
            }
            return result.strategy_name, result.symbol, result.params, metrics

        metrics = {
            "total_return_pct": result.get("total_return", 0.0),
            "sharpe_ratio": result.get("sharpe_ratio", 0.0),
            "max_drawdown_pct": result.get("max_drawdown_pct", 0.0),
            "win_rate": result.get("win_rate", 0.0),
            "total_trades": result.get("total_trades", 0),
            "profit_factor": result.get("profit_factor", 0.0),
            "benchmark_return_pct": result.get("benchmark_return_pct", 0.0),
        }
        return (
            result.get("strategy_name", "unknown"),
            result.get("symbol", "unknown"),
            result.get("params", {}),
            metrics,
        )

    def _build_run_name(self, strategy_name: str, symbol: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{strategy_name}_{symbol}_{timestamp}"

    def _log_run_params(self, strategy_name: str, symbol: str, params: Dict[str, Any]) -> None:
        self._mlflow.log_param("strategy_name", strategy_name)
        self._mlflow.log_param("symbol", symbol)
        for key, value in params.items():
            self._mlflow.log_param(key, str(value))

    def _log_run_metrics(self, metrics: Dict[str, Any]) -> None:
        for metric_name, metric_value in metrics.items():
            if metric_value is not None:
                self._mlflow.log_metric(metric_name, float(metric_value))

    def _log_run_tags(self, strategy_name: str, symbol: str, tags: Optional[Dict[str, str]]) -> None:
        self._mlflow.set_tag("strategy_name", strategy_name)
        self._mlflow.set_tag("symbol", symbol)
        if tags:
            for tag_key, tag_value in tags.items():
                self._mlflow.set_tag(tag_key, tag_value)

    def _log_chart_artifact(self, chart_path: Optional[str]) -> None:
        if chart_path and Path(chart_path).exists():
            self._mlflow.log_artifact(chart_path)
            logger.debug(f"Logged artifact: {chart_path}")

    def log_sweep(
        self,
        results: list,
        sweep_id: str,
        chart_paths: Optional[list] = None,
    ) -> list:
        """Log multiple backtest runs from a parameter sweep.

        Args:
            results: List of BacktestResult or dict objects
            sweep_id: Unique identifier for this sweep
            chart_paths: Optional list of chart paths (parallel to results)

        Returns:
            List of MLflow run IDs (None for failed logs)
        """
        run_ids = []

        for i, result in enumerate(results):
            chart_path = chart_paths[i] if chart_paths and i < len(chart_paths) else None
            tags = {"sweep_id": sweep_id}

            run_id = self.log_run(result, chart_path=chart_path, tags=tags)
            run_ids.append(run_id)

        return run_ids

    def get_experiment_url(self) -> Optional[str]:
        """Get URL to view experiment in MLflow UI.

        Returns:
            URL string if available, None otherwise.
        """
        if not self._ensure_initialized():
            return None

        try:
            experiment = self._mlflow.get_experiment_by_name(self.config.experiment_name)
            if experiment:
                # For local file store, provide instructions
                if self.config.tracking_uri.startswith("./") or self.config.tracking_uri.startswith("/"):
                    return f"Run 'mlflow ui --backend-store-uri {self.config.tracking_uri}' then open http://localhost:5000"
                else:
                    return f"{self.config.tracking_uri}/#/experiments/{experiment.experiment_id}"
            return None
        except Exception as e:
            logger.debug(f"Could not get experiment URL: {e}")
            return None

    def get_run_url(self, run_id: str) -> Optional[str]:
        """Get URL to view a specific run in MLflow UI.

        Args:
            run_id: MLflow run ID

        Returns:
            URL string if available, None otherwise.
        """
        if not self._ensure_initialized():
            return None

        try:
            run = self._mlflow.get_run(run_id)
            experiment_id = run.info.experiment_id

            if self.config.tracking_uri.startswith("./") or self.config.tracking_uri.startswith("/"):
                return f"Run 'mlflow ui --backend-store-uri {self.config.tracking_uri}' then open http://localhost:5000/#/experiments/{experiment_id}/runs/{run_id}"
            else:
                return f"{self.config.tracking_uri}/#/experiments/{experiment_id}/runs/{run_id}"
        except Exception as e:
            logger.debug(f"Could not get run URL: {e}")
            return None
