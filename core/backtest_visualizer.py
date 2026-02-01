"""Backtest visualization with dual-axis charts for strategy vs benchmark comparison.

Includes mplfinance-based regime charts for indicator analysis.
"""

import logging
import re
from pathlib import Path
from typing import List, Optional, Union

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

        # Use tight_layout with rect to reserve space for right Y-axis on dual-axis charts
        if has_benchmark:
            fig.tight_layout(rect=[0, 0, 0.88, 1])
        else:
            fig.tight_layout()

        # Validate format
        chart_format = self.config.format.lower()
        if chart_format not in ALLOWED_FORMATS:
            logger.warning(f"Invalid format '{chart_format}', defaulting to 'png'")
            chart_format = "png"

        # Generate output path if not provided
        if output_path is None:
            safe_strategy = _sanitize_filename(strategy_name)
            safe_symbol = _sanitize_filename(symbol) if symbol else "unknown"
            output_path = f"backtest_{safe_strategy}_{safe_symbol}.{chart_format}"

        # Validate and sanitize output path
        try:
            safe_path = _validate_output_path(output_path)
        except ValueError as e:
            logger.error(f"Invalid output path: {e}")
            plt.close(fig)
            return None

        # Save chart
        plt.savefig(str(safe_path), dpi=self.config.dpi, format=chart_format)
        plt.close(fig)

        logger.info(f"Chart saved to: {safe_path}")
        return str(safe_path)

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

        # Validate format
        chart_format = self.config.format.lower()
        if chart_format not in ALLOWED_FORMATS:
            logger.warning(f"Invalid format '{chart_format}', defaulting to 'png'")
            chart_format = "png"

        # Generate output path if not provided
        if output_path is None:
            output_path = f"comparison_chart.{chart_format}"

        # Validate and sanitize output path
        try:
            safe_path = _validate_output_path(output_path)
        except ValueError as e:
            logger.error(f"Invalid output path: {e}")
            plt.close(fig)
            return None

        plt.savefig(str(safe_path), dpi=self.config.dpi, format=chart_format)
        plt.close(fig)

        logger.info(f"Comparison chart saved to: {safe_path}")
        return str(safe_path)

    def create_regime_chart(
        self,
        df: pd.DataFrame,
        trades: Optional[List[dict]] = None,
        equity_curve: Optional[List[dict]] = None,
        output_path: Optional[str] = None,
        title: str = "Regime Analysis Chart",
    ) -> Optional[str]:
        """Create mplfinance-based regime analysis chart.

        Generates a compact 3-panel chart:
        - Main panel: Candlestick + Bollinger Bands + trade markers + equity overlay
        - Panel 2: MFI + ADX overlay
        - Panel 3: Volume + Regime color background

        Args:
            df: DataFrame with OHLCV and indicator columns.
                Required: open, high, low, close, volume
                Optional: bb_upper, bb_lower, mfi, adx, regime
            trades: List of trade dicts with 'timestamp', 'action', 'price'
            equity_curve: List of dicts with 'date' and 'equity' for profit overlay
            output_path: Path to save chart. Auto-generated if None.
            title: Chart title.

        Returns:
            Path to saved chart file, or None if generation failed.
        """
        if not HAS_MPLFINANCE:
            logger.error("mplfinance not installed. Run: pip install mplfinance")
            return None

        if df is None or df.empty:
            logger.warning("No data provided for regime chart")
            return None

        # Ensure DataFrame has DatetimeIndex for mplfinance
        df = df.copy()
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
        elif not isinstance(df.index, pd.DatetimeIndex):
            logger.warning("DataFrame needs timestamp column or DatetimeIndex")
            return None

        # Validate required columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        # Handle case-insensitive column names
        col_map = {c.lower(): c for c in df.columns}
        for req in required_cols:
            if req not in col_map:
                logger.warning(f"Missing required column: {req}")
                return None

        # Normalize column names to lowercase
        df.columns = df.columns.str.lower()

        # Build addplot list for overlays
        addplots = []

        # === Main Panel (0): Bollinger Bands ===
        if 'bb_upper' in df.columns and 'bb_lower' in df.columns:
            addplots.append(mpf.make_addplot(
                df['bb_upper'], panel=0, color='gray', width=0.8,
                linestyle='--', alpha=0.7
            ))
            addplots.append(mpf.make_addplot(
                df['bb_lower'], panel=0, color='gray', width=0.8,
                linestyle='--', alpha=0.7
            ))
            # Fill between BB (using middle as reference)
            if 'bb_middle' in df.columns:
                addplots.append(mpf.make_addplot(
                    df['bb_middle'], panel=0, color='gray', width=0.5,
                    linestyle=':', alpha=0.5
                ))

        # Add trade markers if provided
        if trades:
            buy_signals = self._create_trade_markers(df, trades, 'buy')
            sell_signals = self._create_trade_markers(df, trades, 'sell')

            if buy_signals is not None and not buy_signals.isna().all():
                addplots.append(mpf.make_addplot(
                    buy_signals, panel=0, type='scatter',
                    marker='^', markersize=100, color='#4CAF50'
                ))
            if sell_signals is not None and not sell_signals.isna().all():
                addplots.append(mpf.make_addplot(
                    sell_signals, panel=0, type='scatter',
                    marker='v', markersize=100, color='#F44336'
                ))

        # Add equity curve overlay (cumulative return %)
        has_equity = False
        if equity_curve and len(equity_curve) > 0:
            try:
                equity_df = pd.DataFrame(equity_curve)
                equity_df['date'] = pd.to_datetime(equity_df['date']).dt.date

                # Calculate cumulative return percentage
                initial_equity = equity_df['equity'].iloc[0]
                if initial_equity > 0:
                    equity_df['return_pct'] = ((equity_df['equity'] / initial_equity) - 1) * 100

                    # Create date-to-return mapping
                    date_to_return = dict(zip(equity_df['date'], equity_df['return_pct']))

                    # Map each price bar's date to the corresponding return %
                    # Handle both datetime index and timestamp column
                    if isinstance(df.index, pd.DatetimeIndex):
                        price_dates = df.index.date
                    else:
                        price_dates = pd.to_datetime(df.index).date

                    aligned_returns = pd.Series(
                        [date_to_return.get(d, np.nan) for d in price_dates],
                        index=df.index
                    )
                    # Forward fill any missing values
                    aligned_returns = aligned_returns.ffill().fillna(0)

                    # Add as secondary y-axis overlay on main panel
                    addplots.append(mpf.make_addplot(
                        aligned_returns, panel=0, color='#E91E63', width=1.5,
                        linestyle='-', secondary_y=True, ylabel='Return %'
                    ))
                    has_equity = True
            except Exception as e:
                logger.warning(f"Failed to add equity overlay: {e}")

        # Determine panel configuration
        has_mfi_adx = 'mfi' in df.columns or 'adx' in df.columns

        # === Panel 1: MFI + ADX (if available) ===
        if has_mfi_adx:
            if 'mfi' in df.columns:
                addplots.append(mpf.make_addplot(
                    df['mfi'], panel=1, color='#4CAF50', width=1.2,
                    ylabel='MFI/ADX', ylim=(0, 100)
                ))
                # MFI threshold lines (52/48)
                mfi_upper = pd.Series(52, index=df.index)
                mfi_lower = pd.Series(48, index=df.index)
                addplots.append(mpf.make_addplot(
                    mfi_upper, panel=1, color='green', width=0.5,
                    linestyle='--', alpha=0.5
                ))
                addplots.append(mpf.make_addplot(
                    mfi_lower, panel=1, color='red', width=0.5,
                    linestyle='--', alpha=0.5
                ))

            if 'adx' in df.columns:
                addplots.append(mpf.make_addplot(
                    df['adx'], panel=1, color='#FF9800', width=1.2,
                    secondary_y=False
                ))
                # ADX threshold line (20)
                adx_threshold = pd.Series(20, index=df.index)
                addplots.append(mpf.make_addplot(
                    adx_threshold, panel=1, color='orange', width=0.5,
                    linestyle='--', alpha=0.5
                ))

            # === Panel 2: Volume (manual) ===
            # Add volume as manual addplot to get 3-panel layout
            colors = ['#81C784' if c >= o else '#EF5350'
                      for c, o in zip(df['close'], df['open'])]
            addplots.append(mpf.make_addplot(
                df['volume'], panel=2, type='bar', color=colors,
                ylabel='Volume'
            ))
            panel_ratios = (7, 1.5, 1.5)  # Main, MFI/ADX, Volume
            use_volume = False  # Disable built-in volume
        else:
            # 2-panel layout: Main + Volume
            panel_ratios = (8, 2)
            use_volume = True  # Use built-in volume

        # Create custom style
        mc = mpf.make_marketcolors(
            up='#4CAF50', down='#F44336',
            edge='inherit',
            wick='inherit',
            volume={'up': '#81C784', 'down': '#EF5350'}
        )
        style = mpf.make_mpf_style(
            base_mpf_style='charles',
            marketcolors=mc,
            rc={
                'font.size': 7,
                'axes.titlesize': 8,
                'axes.labelsize': 7,
                'xtick.labelsize': 6,
                'ytick.labelsize': 6,
            }
        )

        # Generate output path
        chart_format = self.config.format.lower()
        if chart_format not in ALLOWED_FORMATS:
            chart_format = "png"

        if output_path is None:
            output_path = f"regime_chart.{chart_format}"

        try:
            safe_path = _validate_output_path(output_path)
        except ValueError as e:
            logger.error(f"Invalid output path: {e}")
            return None

        # Create the chart
        try:
            fig, axes = mpf.plot(
                df,
                type='candle',
                style=style,
                addplot=addplots if addplots else None,
                volume=use_volume,
                panel_ratios=panel_ratios,
                title=title,
                figsize=(self.config.width, self.config.height),
                returnfig=True,
                warn_too_much_data=5000,
            )

            # Add regime background coloring to volume panel
            if 'regime' in df.columns:
                self._add_regime_background(fig, axes, df)

            # Add legend
            self._add_regime_legend(fig)

            # Save
            fig.savefig(str(safe_path), dpi=self.config.dpi, format=chart_format,
                       bbox_inches='tight', facecolor='white')
            plt.close(fig)

            logger.info(f"Regime chart saved to: {safe_path}")
            return str(safe_path)

        except Exception as e:
            logger.error(f"Failed to create regime chart: {e}")
            import traceback
            traceback.print_exc()
            return None

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

        for trade in trades:
            trade_action = trade.get('action', '').lower()
            if action == 'buy' and trade_action in ('buy', 'long', 'entry'):
                ts = pd.to_datetime(trade.get('timestamp'))
                if ts in df.index:
                    # Place marker below candle for buy
                    markers.loc[ts] = df.loc[ts, 'low'] * 0.995
            elif action == 'sell' and trade_action in ('sell', 'short', 'exit', 'cover'):
                ts = pd.to_datetime(trade.get('timestamp'))
                if ts in df.index:
                    # Place marker above candle for sell
                    markers.loc[ts] = df.loc[ts, 'high'] * 1.005

        return markers if not markers.isna().all() else None

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
