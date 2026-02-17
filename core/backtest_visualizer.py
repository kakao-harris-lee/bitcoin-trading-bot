"""Backtest visualization with dual-axis charts for strategy vs benchmark comparison.

Includes mplfinance-based regime charts for indicator analysis.
"""

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import matplotlib
matplotlib.use('Agg')  # Use thread-safe backend before importing pyplot
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

try:
    import mplfinance as mpf
    HAS_MPLFINANCE = True
except ImportError:
    HAS_MPLFINANCE = False

from core.backtest_config import VisualizationConfig
from core.backtest_result import BacktestResult

logger = logging.getLogger(__name__)

# Regime color mapping for visualization
REGIME_COLORS = {
    'BULL_STRONG': '#4CAF50',     # Dark green
    'BULL_MODERATE': '#81C784',   # Light green
    'SIDEWAYS_UP': '#B0BEC5',     # Light gray-green
    'SIDEWAYS_FLAT': '#90A4AE',   # Gray
    'SIDEWAYS_DOWN': '#FFAB91',   # Light gray-red
    'BEAR_MODERATE': '#EF5350',   # Light red
    'BEAR_STRONG': '#C62828',     # Dark red
    'UNKNOWN': '#9E9E9E',         # Gray
}

# Allowed output formats for chart generation
ALLOWED_FORMATS = {"png", "svg", "pdf", "jpg", "jpeg"}

# Keep native timeframe for most charts; only resample very long series.
# Backtest data is commonly 4H bars, so 1 year ~= 2,190 points and should remain unresampled.
REGIME_RESAMPLE_THRESHOLD = 5000
REGIME_RESAMPLE_RULE = "D"


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for safe use in filenames.

    Removes or replaces characters that could be used for path traversal
    or other security issues.

    Args:
        name: Input string to sanitize

    Returns:
        Safe filename string containing only alphanumeric, underscore, hyphen, and dot
    """
    # Replace any non-alphanumeric characters (except underscore, hyphen, dot) with underscore
    safe = re.sub(r"[^\w\-.]", "_", name)
    # Remove any leading dots or path separators that might remain
    safe = safe.lstrip("._")
    # Collapse multiple underscores
    safe = re.sub(r"_+", "_", safe)
    return safe or "unnamed"


def _validate_output_path(output_path: str, base_dir: Optional[Path] = None) -> Path:
    """Validate and resolve output path to prevent path traversal.

    Args:
        output_path: The requested output path (can be absolute or relative)
        base_dir: Base directory that output must be within. Defaults to cwd.

    Returns:
        Resolved safe Path object

    Raises:
        ValueError: If path would escape base directory
    """
    output_path_obj = Path(output_path)

    # If output_path is absolute and its parent directory exists, use it directly
    # This allows callers to specify exact output locations
    if output_path_obj.is_absolute():
        resolved = output_path_obj.resolve()
        # Ensure parent directory exists
        if resolved.parent.exists():
            # Sanitize just the filename portion for safety
            safe_filename = _sanitize_filename(resolved.name)
            return resolved.parent / safe_filename
        # Fall through to relative path handling if parent doesn't exist

    # For relative paths, use base_dir
    if base_dir is None:
        base_dir = Path.cwd()

    base_dir = base_dir.resolve()

    # Get just the filename, stripping any directory components
    filename = output_path_obj.name
    safe_filename = _sanitize_filename(filename)

    # Construct path within base directory
    resolved = (base_dir / safe_filename).resolve()

    # Verify the resolved path is within base directory using proper path containment check
    try:
        resolved.relative_to(base_dir)
    except ValueError:
        raise ValueError(f"Output path escapes base directory: {output_path}")

    return resolved


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
        parsed = self._parse_backtest_result(result)
        equity_curve = parsed["equity_curve"]
        benchmark_curve = parsed["benchmark_curve"]
        strategy_name = parsed["strategy_name"]
        symbol = parsed["symbol"]
        total_return = parsed["total_return"]
        benchmark_return = parsed["benchmark_return"]

        if equity_curve is None or equity_curve.empty:
            logger.warning("No equity curve data, cannot generate chart")
            return None

        has_benchmark = benchmark_curve is not None and len(benchmark_curve) > 0

        fig, ax1 = plt.subplots(figsize=(self.config.width, self.config.height))
        timestamps, equity_values = self._extract_equity_series(equity_curve)

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

        if has_benchmark:
            line2 = self._plot_benchmark_axis(
                ax1=ax1,
                benchmark_curve=benchmark_curve,
                timestamps=timestamps,
                benchmark_return=benchmark_return,
            )
            lines = line1 + line2
            labels = [line1[0].get_label(), line2[0].get_label()]
        else:
            logger.warning("No benchmark data available, showing strategy-only chart")

        # Combined legend
        ax1.legend(lines, labels, loc=self.config.legend_location)

        chart_title = self._build_chart_title(title, strategy_name, symbol)
        plt.title(chart_title)

        # Use tight_layout with rect to reserve space for right Y-axis on dual-axis charts
        if has_benchmark:
            fig.tight_layout(rect=[0, 0, 0.88, 1])
        else:
            fig.tight_layout()

        safe_path, chart_format = self._resolve_chart_output_path(
            output_path=output_path,
            strategy_name=strategy_name,
            symbol=symbol,
        )
        if safe_path is None:
            plt.close(fig)
            return None

        plt.savefig(str(safe_path), dpi=self.config.dpi, format=chart_format)
        plt.close(fig)

        logger.info(f"Chart saved to: {safe_path}")
        return str(safe_path)

    def _parse_backtest_result(self, result: Union[BacktestResult, dict]) -> Dict[str, Any]:
        if isinstance(result, BacktestResult):
            return {
                "equity_curve": result.equity_curve,
                "benchmark_curve": result.benchmark_curve,
                "strategy_name": result.strategy_name,
                "symbol": result.symbol,
                "total_return": result.total_return_pct,
                "benchmark_return": result.benchmark_return_pct,
            }
        return {
            "equity_curve": result.get("equity_curve", pd.DataFrame()),
            "benchmark_curve": result.get("benchmark_curve"),
            "strategy_name": result.get("strategy_name", "Strategy"),
            "symbol": result.get("symbol", ""),
            "total_return": result.get("total_return", 0.0),
            "benchmark_return": result.get("benchmark_return_pct", 0.0),
        }

    def _extract_equity_series(self, equity_curve: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        if "timestamp" in equity_curve.columns:
            timestamps = pd.to_datetime(equity_curve["timestamp"])
        else:
            timestamps = equity_curve.index
        if "total_equity" in equity_curve.columns:
            equity_values = equity_curve["total_equity"]
        else:
            equity_values = equity_curve.iloc[:, -1]
        return timestamps, equity_values

    def _plot_benchmark_axis(
        self,
        ax1: Any,
        benchmark_curve: Any,
        timestamps: pd.Series,
        benchmark_return: float,
    ):
        ax2 = ax1.twinx()
        ax2.set_ylabel("Benchmark Equity ($)", color=self.config.benchmark_color)
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
        return line2

    def _build_chart_title(self, title: Optional[str], strategy_name: str, symbol: str) -> str:
        if title:
            return title
        chart_title = f"Backtest: {strategy_name}"
        if symbol:
            chart_title += f" ({symbol})"
        return chart_title

    def _resolve_chart_output_path(
        self,
        output_path: Optional[str],
        strategy_name: str,
        symbol: str,
    ) -> tuple[Optional[Path], str]:
        chart_format = self.config.format.lower()
        if chart_format not in ALLOWED_FORMATS:
            logger.warning(f"Invalid format '{chart_format}', defaulting to 'png'")
            chart_format = "png"
        if output_path is None:
            safe_strategy = _sanitize_filename(strategy_name)
            safe_symbol = _sanitize_filename(symbol) if symbol else "unknown"
            output_path = f"backtest_{safe_strategy}_{safe_symbol}.{chart_format}"
        try:
            safe_path = _validate_output_path(output_path)
        except ValueError as e:
            logger.error(f"Invalid output path: {e}")
            return None, chart_format
        return safe_path, chart_format

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
        colors = plt.cm.tab10.colors

        for i, result in enumerate(results):
            comparison = self._build_comparison_line(result, i)
            if comparison is None:
                continue
            ax.plot(
                comparison["timestamps"],
                comparison["normalized"],
                color=colors[i % len(colors)],
                label=comparison["label"],
                linewidth=1.5,
            )

        self._style_comparison_axes(ax, title)
        fig.tight_layout()
        safe_path, chart_format = self._resolve_comparison_output_path(output_path)
        if safe_path is None:
            plt.close(fig)
            return None

        plt.savefig(str(safe_path), dpi=self.config.dpi, format=chart_format)
        plt.close(fig)

        logger.info(f"Comparison chart saved to: {safe_path}")
        return str(safe_path)

    def _build_comparison_line(
        self, result: Union[BacktestResult, dict], index: int
    ) -> Optional[Dict[str, Any]]:
        if isinstance(result, BacktestResult):
            equity_curve = result.equity_curve
            strategy_name = result.strategy_name
            symbol = result.symbol
            total_return = result.total_return_pct
        else:
            equity_curve = result.get("equity_curve", pd.DataFrame())
            strategy_name = result.get("strategy_name", f"Strategy {index+1}")
            symbol = result.get("symbol", "")
            total_return = result.get("total_return", 0.0)

        if equity_curve is None or equity_curve.empty:
            return None
        timestamps = self._extract_comparison_timestamps(equity_curve)
        equity_values = self._extract_comparison_equity(equity_curve)
        if len(equity_values) == 0:
            return None
        initial_equity = equity_values.iloc[0]
        normalized = ((equity_values / initial_equity) - 1) * 100
        label = self._build_comparison_label(strategy_name, symbol, total_return)
        return {"timestamps": timestamps, "normalized": normalized, "label": label}

    def _extract_comparison_timestamps(self, equity_curve: pd.DataFrame):
        if "timestamp" in equity_curve.columns:
            return pd.to_datetime(equity_curve["timestamp"])
        return equity_curve.index

    def _extract_comparison_equity(self, equity_curve: pd.DataFrame):
        if "total_equity" in equity_curve.columns:
            return equity_curve["total_equity"]
        return equity_curve.iloc[:, -1]

    def _build_comparison_label(self, strategy_name: str, symbol: str, total_return: float) -> str:
        label = strategy_name
        if symbol:
            label += f" ({symbol})"
        return f"{label} [{total_return:+.2f}%]"

    def _style_comparison_axes(self, ax: plt.Axes, title: str) -> None:
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

    def _resolve_comparison_output_path(self, output_path: Optional[str]) -> tuple[Optional[Path], str]:
        chart_format = self.config.format.lower()
        if chart_format not in ALLOWED_FORMATS:
            logger.warning(f"Invalid format '{chart_format}', defaulting to 'png'")
            chart_format = "png"
        if output_path is None:
            output_path = f"comparison_chart.{chart_format}"
        try:
            safe_path = _validate_output_path(output_path)
        except ValueError as e:
            logger.error(f"Invalid output path: {e}")
            return None, chart_format
        return safe_path, chart_format

    def create_regime_chart(
        self,
        df: pd.DataFrame,
        trades: Optional[List[dict]] = None,
        equity_curve: Optional[List[dict]] = None,
        output_path: Optional[str] = None,
        title: str = "Regime Analysis Chart",
    ) -> Optional[str]:
        """Create mplfinance-based regime analysis chart."""
        if not HAS_MPLFINANCE:
            logger.error("mplfinance not installed. Run: pip install mplfinance")
            return None
        if df is None or df.empty:
            logger.warning("No data provided for regime chart")
            return None

        prepared = self._prepare_regime_chart_data(df, trades)
        if prepared is None:
            return None
        df, trades = prepared

        addplots, panel_ratios = self._build_regime_addplots(df, trades, equity_curve)
        style = self._build_regime_style()
        safe_path, chart_format = self._resolve_regime_output_path(output_path)
        if safe_path is None:
            return None

        try:
            fig, axes = mpf.plot(
                df,
                type="candle",
                style=style,
                addplot=addplots if addplots else None,
                volume=True,
                panel_ratios=panel_ratios,
                title=title,
                figsize=(self.config.width, self.config.height),
                returnfig=True,
                warn_too_much_data=5000,
            )
            if "regime" in df.columns:
                self._add_regime_background(fig, axes, df)
                self._add_regime_legend(fig)
            fig.savefig(
                str(safe_path),
                dpi=self.config.dpi,
                format=chart_format,
                bbox_inches="tight",
                facecolor="white",
            )
            plt.close(fig)
            logger.info(f"Regime chart saved to: {safe_path}")
            return str(safe_path)
        except Exception as e:
            logger.error(f"Failed to create regime chart: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _prepare_regime_chart_data(
        self,
        df: pd.DataFrame,
        trades: Optional[List[dict]],
    ) -> Optional[tuple[pd.DataFrame, Optional[List[dict]]]]:
        df = df.copy()
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df.set_index("timestamp", inplace=True)
        elif not isinstance(df.index, pd.DatetimeIndex):
            logger.warning("DataFrame needs timestamp column or DatetimeIndex")
            return None

        if len(df) > REGIME_RESAMPLE_THRESHOLD:
            df, trades = self._resample_regime_data(df, trades)

        if not self._has_required_regime_columns(df):
            return None

        df.columns = df.columns.str.lower()
        return df, trades

    def _resample_regime_data(
        self,
        df: pd.DataFrame,
        trades: Optional[List[dict]],
    ) -> tuple[pd.DataFrame, Optional[List[dict]]]:
        logger.info(
            "Resampling %s data points with rule=%s for chart visibility",
            len(df),
            REGIME_RESAMPLE_RULE,
        )
        ohlcv_agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        indicator_cols = [
            "rsi",
            "mfi",
            "adx",
            "bb_upper",
            "bb_lower",
            "bb_middle",
            "ema_50",
            "ema_120",
            "ema_200",
            "atr",
            "macd",
            "macd_signal",
            "macd_hist",
            "regime",
        ]
        indicator_agg = {col: "last" for col in indicator_cols if col in df.columns}
        agg_dict = {k: v for k, v in {**ohlcv_agg, **indicator_agg}.items() if k in df.columns}
        df = df.resample(REGIME_RESAMPLE_RULE).agg(agg_dict).dropna(subset=["close"])
        trades = self._aggregate_daily_trades(trades)
        logger.info("Resampled to %s bars (rule=%s)", len(df), REGIME_RESAMPLE_RULE)
        return df, trades

    def _aggregate_daily_trades(self, trades: Optional[List[dict]]) -> Optional[List[dict]]:
        if not trades:
            return trades
        daily_trades = {}
        for t in trades:
            ts = pd.to_datetime(t.get("timestamp"))
            day = ts.normalize()
            action = t.get("action", "").lower()
            key = (day, action)
            if key not in daily_trades:
                daily_trades[key] = {"timestamp": day, "action": action, "price": t.get("price", 0)}
        return list(daily_trades.values())

    def _has_required_regime_columns(self, df: pd.DataFrame) -> bool:
        required_cols = ["open", "high", "low", "close", "volume"]
        col_map = {c.lower(): c for c in df.columns}
        for req in required_cols:
            if req not in col_map:
                logger.warning(f"Missing required column: {req}")
                return False
        return True

    def _build_regime_addplots(
        self,
        df: pd.DataFrame,
        trades: Optional[List[dict]],
        equity_curve: Optional[List[dict]],
    ) -> tuple[List[Any], tuple[int, ...]]:
        addplots: List[Any] = []
        self._append_bollinger_addplots(df, addplots)
        return addplots, (8, 2)

    def _append_ema_addplots(self, df: pd.DataFrame, addplots: List[Any]) -> None:
        ema_specs = [
            ("ema_50", "#AB47BC", "-", 1.0, 0.75),
            ("ema_120", "#FB8C00", "-", 1.1, 0.8),
            ("ema_200", "#FDD835", "-", 1.2, 0.85),
        ]
        added = 0
        for column, color, linestyle, width, alpha in ema_specs:
            if column not in df.columns:
                continue
            series = df[column]
            if series.notna().sum() <= 0:
                continue
            addplots.append(
                mpf.make_addplot(
                    series.ffill().bfill(),
                    panel=0,
                    color=color,
                    linestyle=linestyle,
                    width=width,
                    alpha=alpha,
                )
            )
            added += 1
        if added > 0:
            logger.info(f"EMA overlays added to chart: {added}")

    def _append_momentum_panel_addplots(
        self,
        df: pd.DataFrame,
        addplots: List[Any],
        panel_index: int,
    ) -> bool:
        momentum_specs = [
            ("rsi", "#42A5F5"),
            ("mfi", "#26A69A"),
            ("adx", "#EF5350"),
        ]
        added = 0
        for column, color in momentum_specs:
            if column not in df.columns:
                continue
            series = df[column]
            if series.notna().sum() <= 0:
                continue
            plot_kwargs: Dict[str, Any] = {
                "panel": panel_index,
                "color": color,
                "width": 1.0,
            }
            if added == 0:
                plot_kwargs["ylabel"] = "RSI/MFI/ADX"
            addplots.append(
                mpf.make_addplot(
                    series.ffill().bfill().clip(lower=0, upper=100),
                    **plot_kwargs,
                )
            )
            added += 1

        if added <= 0:
            return False

        base_index = df.index
        for level in (30, 50, 70):
            addplots.append(
                mpf.make_addplot(
                    pd.Series(float(level), index=base_index),
                    panel=panel_index,
                    color="#9E9E9E" if level != 50 else "#757575",
                    linestyle="--",
                    width=0.8,
                    alpha=0.35,
                )
            )

        logger.info(f"Momentum panel added to chart: {added} indicators")
        return True

    def _append_macd_overlay_addplots(
        self,
        df: pd.DataFrame,
        addplots: List[Any],
    ) -> None:
        if "macd" not in df.columns or "macd_signal" not in df.columns:
            return

        macd = df["macd"].ffill().bfill()
        signal = df["macd_signal"].ffill().bfill()
        if macd.notna().sum() <= 0 or signal.notna().sum() <= 0:
            return

        hist = df["macd_hist"].ffill().bfill() if "macd_hist" in df.columns else (macd - signal)
        base_index = df.index

        addplots.append(
            mpf.make_addplot(
                macd,
                panel=0,
                color="#FFB74D",
                width=0.9,
                linestyle="-",
                alpha=0.85,
                secondary_y=True,
                ylabel="Return % / MACD",
            )
        )
        addplots.append(
            mpf.make_addplot(
                signal,
                panel=0,
                color="#4FC3F7",
                width=0.9,
                linestyle="--",
                alpha=0.8,
                secondary_y=True,
            )
        )
        addplots.append(
            mpf.make_addplot(
                hist,
                panel=0,
                type="bar",
                color="#B0BEC5",
                alpha=0.25,
                width=0.6,
                secondary_y=True,
            )
        )
        addplots.append(
            mpf.make_addplot(
                pd.Series(0.0, index=base_index),
                panel=0,
                color="#757575",
                linestyle="--",
                width=0.7,
                alpha=0.3,
                secondary_y=True,
            )
        )
        logger.info("MACD overlay added to main chart")

    def _append_atr_panel_addplots(
        self,
        df: pd.DataFrame,
        addplots: List[Any],
        panel_index: int,
    ) -> bool:
        if "atr" not in df.columns or "close" not in df.columns:
            return False

        close = df["close"].replace(0, np.nan)
        atr_pct = ((df["atr"] / close) * 100.0).replace([np.inf, -np.inf], np.nan)
        if atr_pct.notna().sum() <= 0:
            return False

        atr_pct = atr_pct.ffill().bfill().clip(lower=0)
        base_index = df.index
        addplots.append(
            mpf.make_addplot(
                atr_pct,
                panel=panel_index,
                color="#CE93D8",
                width=1.0,
                ylabel="ATR %",
            )
        )
        for level in (1.0, 2.0, 3.0):
            addplots.append(
                mpf.make_addplot(
                    pd.Series(float(level), index=base_index),
                    panel=panel_index,
                    color="#9E9E9E",
                    linestyle="--",
                    width=0.7,
                    alpha=0.3,
                )
            )
        logger.info("ATR% panel added to chart")
        return True

    def _append_bollinger_addplots(self, df: pd.DataFrame, addplots: List[Any]) -> None:
        # Always compute BB from displayed close series so chart matches visible timeframe.
        # TradingView default: Basis=SMA(20), Source=Close, StdDev=2.
        close = df["close"] if "close" in df.columns else None
        if close is None or close.notna().sum() < 20:
            logger.info(f"Insufficient close data for Bollinger overlay. Available: {list(df.columns)}")
            return

        bb_length = 20
        bb_mult = 2.0
        bb_middle = close.rolling(window=bb_length, min_periods=bb_length).mean()
        # Use biased stdev (ddof=0) to align with TradingView/Pine default behavior.
        bb_dev = close.rolling(window=bb_length, min_periods=bb_length).std(ddof=0)
        bb_upper = bb_middle + (bb_mult * bb_dev)
        bb_lower = bb_middle - (bb_mult * bb_dev)

        bb_upper = bb_upper.ffill()
        bb_lower = bb_lower.ffill()
        bb_middle = bb_middle.ffill()

        band_color = "#00ACC1"
        mid_color = "#006064"
        fill_color = "#4DD0E1"
        addplots.append(
            mpf.make_addplot(
                bb_upper,
                panel=0,
                color=band_color,
                width=1.8,
                linestyle="--",
                alpha=0.95,
            )
        )
        addplots.append(
            mpf.make_addplot(
                bb_lower,
                panel=0,
                color=band_color,
                width=1.8,
                linestyle="--",
                alpha=0.95,
                fill_between=dict(
                    y1=bb_lower.values,
                    y2=bb_upper.values,
                    alpha=0.10,
                    color=fill_color,
                ),
            )
        )
        if bb_middle is not None and bb_middle.notna().sum() > 0:
            addplots.append(
                mpf.make_addplot(
                    bb_middle,
                    panel=0,
                    color=mid_color,
                    width=1.6,
                    linestyle="-",
                    alpha=0.9,
                )
            )
        logger.info("Bollinger Bands overlay added (high-visibility mode)")

    def _append_trade_marker_addplots(
        self,
        df: pd.DataFrame,
        trades: Optional[List[dict]],
        addplots: List[Any],
    ) -> None:
        if not trades:
            return
        buy_signals = self._create_trade_markers(df, trades, "buy")
        sell_signals = self._create_trade_markers(df, trades, "sell")
        if buy_signals is not None and not buy_signals.isna().all():
            addplots.append(
                mpf.make_addplot(
                    buy_signals, panel=0, type="scatter", marker="^",
                    markersize=175, color="#00E676", edgecolors="#1B5E20", linewidths=1.2
                )
            )
            logger.info(f"Buy markers: {buy_signals.notna().sum()} signals")
        if sell_signals is not None and not sell_signals.isna().all():
            addplots.append(
                mpf.make_addplot(
                    sell_signals, panel=0, type="scatter", marker="v",
                    markersize=175, color="#FF5252", edgecolors="#B71C1C", linewidths=1.2
                )
            )
            logger.info(f"Sell markers: {sell_signals.notna().sum()} signals")

    def _append_equity_addplot(
        self,
        df: pd.DataFrame,
        equity_curve: Optional[List[dict]],
        addplots: List[Any],
    ) -> None:
        if not equity_curve:
            return
        try:
            equity_df = pd.DataFrame(equity_curve)
            equity_df["date"] = pd.to_datetime(equity_df["date"]).dt.date
            daily_equity = equity_df.groupby("date")["equity"].last().reset_index()
            initial_equity = daily_equity["equity"].iloc[0]
            if initial_equity <= 0:
                return

            daily_equity["return_pct"] = ((daily_equity["equity"] / initial_equity) - 1) * 100
            date_to_return = dict(zip(daily_equity["date"], daily_equity["return_pct"]))
            price_dates = df.index.date if isinstance(df.index, pd.DatetimeIndex) else pd.to_datetime(df.index).date
            aligned_returns = pd.Series([date_to_return.get(d, np.nan) for d in price_dates], index=df.index)
            aligned_returns = aligned_returns.ffill().fillna(0)
            addplots.append(
                mpf.make_addplot(
                    aligned_returns, panel=0, color="#E91E63", width=1.5,
                    linestyle="-", secondary_y=True, ylabel="Return %"
                )
            )
        except Exception as e:
            logger.warning(f"Failed to add equity overlay: {e}")

    def _build_regime_style(self):
        mc = mpf.make_marketcolors(
            up="#4CAF50",
            down="#F44336",
            edge="inherit",
            wick="inherit",
            volume={"up": "#81C784", "down": "#EF5350"},
        )
        return mpf.make_mpf_style(
            base_mpf_style="charles",
            marketcolors=mc,
            rc={"font.size": 7, "axes.titlesize": 8, "axes.labelsize": 7, "xtick.labelsize": 6, "ytick.labelsize": 6},
        )

    def _resolve_regime_output_path(self, output_path: Optional[str]) -> tuple[Optional[Path], str]:
        chart_format = self.config.format.lower()
        if chart_format not in ALLOWED_FORMATS:
            chart_format = "png"
        if output_path is None:
            output_path = f"regime_chart.{chart_format}"
        try:
            safe_path = _validate_output_path(output_path)
        except ValueError as e:
            logger.error(f"Invalid output path: {e}")
            return None, chart_format
        return safe_path, chart_format

    def _create_trade_markers(
        self,
        df: pd.DataFrame,
        trades: List[dict],
        action: str
    ) -> Optional[pd.Series]:
        """Create marker series for buy/sell signals.

        Args:
            df: DataFrame with price data
            trades: List of trade dicts
            action: 'buy' or 'sell'

        Returns:
            Series with marker positions (NaN where no marker)
        """
        markers = pd.Series(index=df.index, dtype=float)
        markers[:] = np.nan

        date_to_idx = self._build_date_to_index_lookup(df)

        matched = 0
        unmatched = 0

        for trade in trades:
            if not self._trade_matches_action(trade, action):
                continue
            idx = self._match_trade_index(df, trade, date_to_idx)
            if idx is None or idx not in df.index:
                unmatched += 1
                continue
            if action == 'buy':
                markers.loc[idx] = df.loc[idx, 'low'] * 0.995
            else:
                markers.loc[idx] = df.loc[idx, 'high'] * 1.005
            matched += 1

        if unmatched > 0:
            logger.debug(f"Trade markers: {matched} matched, {unmatched} unmatched for {action}")

        return markers if not markers.isna().all() else None

    def _build_date_to_index_lookup(self, df: pd.DataFrame) -> Dict[date, pd.Timestamp]:
        lookup: Dict[date, pd.Timestamp] = {}
        for idx in df.index:
            day = pd.to_datetime(idx).date()
            lookup.setdefault(day, idx)
        return lookup

    def _trade_matches_action(self, trade: dict, action: str) -> bool:
        trade_action = trade.get('action', '').lower()
        if action == 'buy':
            return trade_action in ('buy', 'long', 'entry')
        return trade_action in ('sell', 'short', 'exit', 'cover')

    def _match_trade_index(
        self,
        df: pd.DataFrame,
        trade: dict,
        date_to_idx: Dict[date, pd.Timestamp],
    ) -> Optional[pd.Timestamp]:
        ts = pd.to_datetime(trade.get('timestamp'))
        if ts in df.index:
            return ts
        return date_to_idx.get(ts.date())

    def _add_regime_background(
        self,
        fig: plt.Figure,
        axes: List[plt.Axes],
        df: pd.DataFrame
    ) -> None:
        """Add regime color background to the chart.

        Args:
            fig: Matplotlib figure
            axes: List of axes from mplfinance
            df: DataFrame with regime column
        """
        if 'regime' not in df.columns:
            return

        # Get the main price axis (first one)
        ax = axes[0]

        # Get x-axis limits in terms of data coordinates
        xlim = ax.get_xlim()

        # Create regime segments
        regimes = df['regime'].fillna('UNKNOWN')
        unique_regimes = regimes.unique()

        # Add vertical spans for each regime change
        prev_regime = None
        start_idx = 0

        for i, (idx, regime) in enumerate(regimes.items()):
            if regime != prev_regime:
                if prev_regime is not None and i > start_idx:
                    # Draw span for previous regime
                    color = REGIME_COLORS.get(prev_regime, REGIME_COLORS['UNKNOWN'])
                    ax.axvspan(start_idx, i, alpha=0.15, color=color, zorder=0)
                start_idx = i
                prev_regime = regime

        # Draw final segment
        if prev_regime is not None:
            color = REGIME_COLORS.get(prev_regime, REGIME_COLORS['UNKNOWN'])
            ax.axvspan(start_idx, len(df), alpha=0.15, color=color, zorder=0)

    def _add_regime_legend(self, fig: plt.Figure) -> None:
        """Add regime color legend to the figure.

        Args:
            fig: Matplotlib figure
        """
        legend_patches = [
            mpatches.Patch(color=REGIME_COLORS['BULL_STRONG'], alpha=0.5, label='BULL_STRONG'),
            mpatches.Patch(color=REGIME_COLORS['BULL_MODERATE'], alpha=0.5, label='BULL_MODERATE'),
            mpatches.Patch(color=REGIME_COLORS['SIDEWAYS_FLAT'], alpha=0.5, label='SIDEWAYS'),
            mpatches.Patch(color=REGIME_COLORS['BEAR_MODERATE'], alpha=0.5, label='BEAR_MODERATE'),
            mpatches.Patch(color=REGIME_COLORS['BEAR_STRONG'], alpha=0.5, label='BEAR_STRONG'),
        ]

        fig.legend(
            handles=legend_patches,
            loc='upper right',
            fontsize=6,
            framealpha=0.9,
            title='Regime',
            title_fontsize=7
        )

    def create_yearly_regime_charts(
        self,
        df: pd.DataFrame,
        trades: Optional[List[dict]] = None,
        equity_curve: Optional[List[dict]] = None,
        output_dir: Optional[str] = None,
        title_prefix: str = "Regime Analysis",
    ) -> List[str]:
        """Create separate regime charts for each year in the data.

        Useful for multi-year backtests where a single chart becomes too dense
        to show individual trade markers clearly.

        Args:
            df: DataFrame with OHLCV and indicator columns.
            trades: List of trade dicts with 'timestamp', 'action', 'price'
            equity_curve: List of dicts with 'date' and 'equity' for profit overlay
            output_dir: Directory to save charts. Uses current dir if None.
            title_prefix: Prefix for chart titles.

        Returns:
            List of paths to saved chart files.
        """
        if df is None or df.empty:
            logger.warning("No data provided for yearly regime charts")
            return []

        df = self._ensure_timestamp_column(df)
        years = sorted(df['timestamp'].dt.year.unique())

        if len(years) <= 1:
            chart_path = self.create_regime_chart(
                df, trades, equity_curve,
                output_path=f"{output_dir or '.'}/regime_chart.png",
                title=title_prefix
            )
            return [chart_path] if chart_path else []

        out_dir = self._ensure_output_dir(output_dir)
        return self._generate_yearly_regime_charts(df, years, trades, equity_curve, out_dir, title_prefix)

    def _ensure_timestamp_column(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        elif isinstance(df.index, pd.DatetimeIndex):
            df['timestamp'] = df.index
        return df

    def _ensure_output_dir(self, output_dir: Optional[str]) -> Path:
        out_dir = Path(output_dir) if output_dir else Path.cwd()
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    def _generate_yearly_regime_charts(
        self,
        df: pd.DataFrame,
        years: List[int],
        trades: Optional[List[dict]],
        equity_curve: Optional[List[dict]],
        output_dir: Path,
        title_prefix: str,
    ) -> List[str]:
        saved_paths: List[str] = []
        for year in years:
            year_df = df[df['timestamp'].dt.year == year].copy()
            if year_df.empty:
                continue
            year_trades = self._filter_records_by_year(trades, year, "timestamp")
            year_equity = self._filter_records_by_year(equity_curve, year, "date")
            output_path = output_dir / f"regime_{year}.png"
            chart_path = self.create_regime_chart(
                year_df,
                trades=year_trades,
                equity_curve=year_equity,
                output_path=str(output_path),
                title=f"{title_prefix} - {year}",
            )
            if chart_path:
                saved_paths.append(chart_path)
                logger.info(f"Generated yearly chart: {chart_path}")
        return saved_paths

    def _filter_records_by_year(
        self, records: Optional[List[dict]], year: int, date_key: str
    ) -> Optional[List[dict]]:
        if not records:
            return None
        filtered: List[dict] = []
        for record in records:
            ts = pd.to_datetime(record.get(date_key))
            if ts.year == year:
                filtered.append(record)
        return filtered

    def create_wide_regime_chart(
        self,
        df: pd.DataFrame,
        trades: Optional[List[dict]] = None,
        equity_curve: Optional[List[dict]] = None,
        output_path: Optional[str] = None,
        title: str = "Regime Analysis (Wide)",
    ) -> Optional[str]:
        """Create extra-wide regime chart for multi-year data.

        Uses a much wider figure to prevent trade markers from overlapping.
        Ideal for 3+ year backtests.

        Args:
            df: DataFrame with OHLCV and indicator columns.
            trades: List of trade dicts with 'timestamp', 'action', 'price'
            equity_curve: List of dicts with 'date' and 'equity' for profit overlay
            output_path: Path to save chart.
            title: Chart title.

        Returns:
            Path to saved chart file, or None if generation failed.
        """
        # Temporarily increase figure width for this chart
        original_width = self.config.width
        original_height = self.config.height

        # Calculate width based on data length
        # Aim for ~3-5 bars per 100 pixels
        if df is not None and len(df) > 0:
            # After daily resampling, we'll have ~365 bars per year
            estimated_days = len(df) if len(df) < 1000 else min(len(df) // 24, 2000)
            self.config.width = max(20, min(40, estimated_days // 50))
            self.config.height = 12  # Taller for better readability

        try:
            result = self.create_regime_chart(
                df, trades, equity_curve, output_path, title
            )
            return result
        finally:
            # Restore original dimensions
            self.config.width = original_width
            self.config.height = original_height
