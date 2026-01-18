"""Backtest visualization with dual-axis charts for strategy vs benchmark comparison."""

import logging
from pathlib import Path
from typing import List, Optional, Union

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from core.backtest_config import VisualizationConfig
from core.backtest_result import BacktestResult

logger = logging.getLogger(__name__)


class BacktestVisualizer:
    """Generate dual-axis charts showing strategy equity vs benchmark price.

    Creates matplotlib charts with:
    - Left y-axis: Strategy equity curve
    - Right y-axis: Benchmark (buy-and-hold) equity curve
    - Shared x-axis: Time

    Example:
        >>> visualizer = BacktestVisualizer()
        >>> chart_path = visualizer.create_chart(result, output_path="backtest.png")
        >>> print(f"Chart saved to: {chart_path}")
    """

    def __init__(self, config: Optional[VisualizationConfig] = None):
        """Initialize visualizer with optional configuration.

        Args:
            config: Visualization configuration. Uses defaults if not provided.
        """
        self.config = config or VisualizationConfig()

    def create_chart(
        self,
        result: Union[BacktestResult, dict],
        output_path: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Optional[str]:
        """Create dual-axis chart from backtest result.

        Args:
            result: BacktestResult or legacy dict with equity_curve and benchmark_curve
            output_path: Path to save chart. If None, generates from result metadata.
            title: Chart title. If None, generates from result metadata.

        Returns:
            Path to saved chart file, or None if generation failed.
        """
        # Extract data from result
        if isinstance(result, BacktestResult):
            equity_curve = result.equity_curve
            benchmark_curve = result.benchmark_curve
            strategy_name = result.strategy_name
            symbol = result.symbol
            total_return = result.total_return_pct
            benchmark_return = result.benchmark_return_pct
        else:
            equity_curve = result.get("equity_curve", pd.DataFrame())
            benchmark_curve = result.get("benchmark_curve")
            strategy_name = result.get("strategy_name", "Strategy")
            symbol = result.get("symbol", "")
            total_return = result.get("total_return", 0.0)
            benchmark_return = result.get("benchmark_return_pct", 0.0)

        # Validate data
        if equity_curve is None or equity_curve.empty:
            logger.warning("No equity curve data, cannot generate chart")
            return None

        # Handle edge case: missing benchmark data
        has_benchmark = benchmark_curve is not None and len(benchmark_curve) > 0

        # Create figure
        fig, ax1 = plt.subplots(figsize=(self.config.width, self.config.height))

        # Extract timestamps and equity values
        if "timestamp" in equity_curve.columns:
            timestamps = pd.to_datetime(equity_curve["timestamp"])
        else:
            timestamps = equity_curve.index

        if "total_equity" in equity_curve.columns:
            equity_values = equity_curve["total_equity"]
        else:
            # Fallback for different column names
            equity_values = equity_curve.iloc[:, -1]

        # Left axis: Strategy equity
        ax1.set_xlabel("Date")
        ax1.set_ylabel("Strategy Equity ($)", color=self.config.strategy_color)
        line1 = ax1.plot(
            timestamps,
            equity_values,
            color=self.config.strategy_color,
            linestyle=self.config.strategy_linestyle,
            label=f"Strategy ({total_return:+.2f}%)",
            linewidth=1.5,
        )
        ax1.tick_params(axis="y", labelcolor=self.config.strategy_color)

        # Format x-axis dates
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.xticks(rotation=45)

        if self.config.grid:
            ax1.grid(True, alpha=0.3)

        lines = line1
        labels = [line1[0].get_label()]

        # Right axis: Benchmark equity (if available)
        if has_benchmark:
            ax2 = ax1.twinx()
            ax2.set_ylabel("Benchmark Equity ($)", color=self.config.benchmark_color)

            # Align benchmark timestamps with equity curve if needed
            if hasattr(benchmark_curve, "index"):
                bench_timestamps = pd.to_datetime(benchmark_curve.index)
                bench_values = benchmark_curve.values
            else:
                bench_timestamps = timestamps
                bench_values = benchmark_curve

            line2 = ax2.plot(
                bench_timestamps,
                bench_values,
                color=self.config.benchmark_color,
                linestyle=self.config.benchmark_linestyle,
                label=f"Buy & Hold ({benchmark_return:+.2f}%)",
                linewidth=1.5,
            )
            ax2.tick_params(axis="y", labelcolor=self.config.benchmark_color)

            lines = line1 + line2
            labels = [line1[0].get_label(), line2[0].get_label()]
        else:
            logger.warning("No benchmark data available, showing strategy-only chart")

        # Combined legend
        ax1.legend(lines, labels, loc=self.config.legend_location)

        # Title
        if title:
            chart_title = title
        else:
            chart_title = f"Backtest: {strategy_name}"
            if symbol:
                chart_title += f" ({symbol})"
        plt.title(chart_title)

        fig.tight_layout()

        # Generate output path if not provided
        if output_path is None:
            safe_name = strategy_name.replace("/", "_").replace(" ", "_")
            output_path = f"backtest_{safe_name}_{symbol}.{self.config.format}"

        # Save chart
        plt.savefig(output_path, dpi=self.config.dpi, format=self.config.format)
        plt.close(fig)

        logger.info(f"Chart saved to: {output_path}")
        return output_path

    def create_comparison_chart(
        self,
        results: List[Union[BacktestResult, dict]],
        output_path: Optional[str] = None,
        title: str = "Strategy Comparison",
    ) -> Optional[str]:
        """Create chart comparing multiple backtest results.

        Args:
            results: List of BacktestResult or dict objects to compare
            output_path: Path to save chart
            title: Chart title

        Returns:
            Path to saved chart file, or None if generation failed.
        """
        if not results:
            logger.warning("No results to compare")
            return None

        fig, ax = plt.subplots(figsize=(self.config.width, self.config.height))

        # Color cycle for multiple strategies
        colors = plt.cm.tab10.colors

        for i, result in enumerate(results):
            if isinstance(result, BacktestResult):
                equity_curve = result.equity_curve
                strategy_name = result.strategy_name
                symbol = result.symbol
                total_return = result.total_return_pct
            else:
                equity_curve = result.get("equity_curve", pd.DataFrame())
                strategy_name = result.get("strategy_name", f"Strategy {i+1}")
                symbol = result.get("symbol", "")
                total_return = result.get("total_return", 0.0)

            if equity_curve is None or equity_curve.empty:
                continue

            # Extract timestamps and equity
            if "timestamp" in equity_curve.columns:
                timestamps = pd.to_datetime(equity_curve["timestamp"])
            else:
                timestamps = equity_curve.index

            if "total_equity" in equity_curve.columns:
                equity_values = equity_curve["total_equity"]
            else:
                equity_values = equity_curve.iloc[:, -1]

            # Normalize to percentage return for comparison
            initial_equity = equity_values.iloc[0]
            normalized = ((equity_values / initial_equity) - 1) * 100

            label = f"{strategy_name}"
            if symbol:
                label += f" ({symbol})"
            label += f" [{total_return:+.2f}%]"

            ax.plot(
                timestamps,
                normalized,
                color=colors[i % len(colors)],
                label=label,
                linewidth=1.5,
            )

        ax.set_xlabel("Date")
        ax.set_ylabel("Return (%)")
        ax.axhline(y=0, color="gray", linestyle="--", alpha=0.5)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.xticks(rotation=45)

        if self.config.grid:
            ax.grid(True, alpha=0.3)

        ax.legend(loc=self.config.legend_location)
        plt.title(title)

        fig.tight_layout()

        # Generate output path if not provided
        if output_path is None:
            output_path = f"comparison_chart.{self.config.format}"

        plt.savefig(output_path, dpi=self.config.dpi, format=self.config.format)
        plt.close(fig)

        logger.info(f"Comparison chart saved to: {output_path}")
        return output_path
