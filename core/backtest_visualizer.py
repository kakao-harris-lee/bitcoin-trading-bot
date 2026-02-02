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

        # Resample to daily if data is too dense (> 1000 points)
        if len(df) > 1000:
            logger.info(f"Resampling {len(df)} data points to daily for better visibility")
            # OHLCV aggregation rules
            ohlcv_agg = {
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum',
            }
            # Indicator aggregation (use last value of day)
            indicator_cols = ['mfi', 'adx', 'bb_upper', 'bb_lower', 'bb_middle',
                              'ema_200', 'macd', 'macd_signal', 'regime']
            indicator_agg = {col: 'last' for col in indicator_cols if col in df.columns}

            agg_dict = {**ohlcv_agg, **indicator_agg}
            # Only include columns that exist
            agg_dict = {k: v for k, v in agg_dict.items() if k in df.columns}

            df = df.resample('D').agg(agg_dict).dropna(subset=['close'])

            # Also aggregate trades to daily level
            if trades:
                daily_trades = {}
                for t in trades:
                    ts = pd.to_datetime(t.get('timestamp'))
                    day = ts.normalize()  # Start of day
                    action = t.get('action', '').lower()
                    price = t.get('price', 0)
                    # Keep first buy/sell of each day
                    key = (day, action)
                    if key not in daily_trades:
                        daily_trades[key] = {'timestamp': day, 'action': action, 'price': price}
                trades = list(daily_trades.values())

            logger.info(f"Resampled to {len(df)} daily bars")

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

        # === Main Panel (0): Bollinger Bands Overlay ===
        has_bb = 'bb_upper' in df.columns and 'bb_lower' in df.columns
        if has_bb:
            bb_upper_valid = df['bb_upper'].notna().sum()
            bb_lower_valid = df['bb_lower'].notna().sum()
            logger.info(f"BB columns found: upper={bb_upper_valid} valid, lower={bb_lower_valid} valid")

            if bb_upper_valid > 0 and bb_lower_valid > 0:
                # Fill NaN with forward fill for continuous lines
                bb_upper = df['bb_upper'].ffill().bfill()
                bb_lower = df['bb_lower'].ffill().bfill()

                # Upper band - blue dashed line
                addplots.append(mpf.make_addplot(
                    bb_upper, panel=0, color='#2196F3', width=1.2,
                    linestyle='--', alpha=0.9
                ))
                # Lower band - blue dashed line
                addplots.append(mpf.make_addplot(
                    bb_lower, panel=0, color='#2196F3', width=1.2,
                    linestyle='--', alpha=0.9
                ))
                # Middle band (SMA) - solid blue line
                if 'bb_middle' in df.columns:
                    bb_middle = df['bb_middle'].ffill().bfill()
                    addplots.append(mpf.make_addplot(
                        bb_middle, panel=0, color='#1976D2', width=1.5,
                        linestyle='-', alpha=0.9
                    ))
                logger.info("Bollinger Bands added to chart")
            else:
                logger.warning("BB columns exist but have no valid data")
        else:
            logger.info(f"BB columns not found. Available: {list(df.columns)}")

        # Add trade markers if provided
        # Marker size 175 (reduced 30% from 250) with edge color for visibility
        if trades:
            buy_signals = self._create_trade_markers(df, trades, 'buy')
            sell_signals = self._create_trade_markers(df, trades, 'sell')

            if buy_signals is not None and not buy_signals.isna().all():
                addplots.append(mpf.make_addplot(
                    buy_signals, panel=0, type='scatter',
                    marker='^', markersize=175, color='#00E676',
                    edgecolors='#1B5E20', linewidths=1.2
                ))
                logger.info(f"Buy markers: {buy_signals.notna().sum()} signals")
            if sell_signals is not None and not sell_signals.isna().all():
                addplots.append(mpf.make_addplot(
                    sell_signals, panel=0, type='scatter',
                    marker='v', markersize=175, color='#FF5252',
                    edgecolors='#B71C1C', linewidths=1.2
                ))
                logger.info(f"Sell markers: {sell_signals.notna().sum()} signals")

        # Add equity curve overlay (cumulative return %)
        has_equity = False
        if equity_curve and len(equity_curve) > 0:
            try:
                equity_df = pd.DataFrame(equity_curve)
                equity_df['date'] = pd.to_datetime(equity_df['date']).dt.date

                # Aggregate to daily: take last equity value of each day
                daily_equity = equity_df.groupby('date')['equity'].last().reset_index()

                # Calculate cumulative return percentage
                initial_equity = daily_equity['equity'].iloc[0]
                if initial_equity > 0:
                    daily_equity['return_pct'] = ((daily_equity['equity'] / initial_equity) - 1) * 100

                    # Create date-to-return mapping
                    date_to_return = dict(zip(daily_equity['date'], daily_equity['return_pct']))

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

        # Panel configuration: Main (with BB overlay) + Volume
        # MFI/ADX panel removed for cleaner visualization
        panel_ratios = (8, 2)
        use_volume = True  # Use built-in volume panel

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

        # Build date-to-index lookup for flexible timestamp matching
        # This handles daily resampling where exact timestamps don't match
        date_to_idx = {}
        for idx in df.index:
            dt = pd.to_datetime(idx)
            date_key = dt.date()
            if date_key not in date_to_idx:
                date_to_idx[date_key] = idx

        matched = 0
        unmatched = 0

        for trade in trades:
            trade_action = trade.get('action', '').lower()
            is_buy = action == 'buy' and trade_action in ('buy', 'long', 'entry')
            is_sell = action == 'sell' and trade_action in ('sell', 'short', 'exit', 'cover')

            if is_buy or is_sell:
                ts = pd.to_datetime(trade.get('timestamp'))

                # Try exact match first
                if ts in df.index:
                    idx = ts
                else:
                    # Fall back to date-based matching (for resampled data)
                    date_key = ts.date()
                    idx = date_to_idx.get(date_key)

                if idx is not None and idx in df.index:
                    if is_buy:
                        markers.loc[idx] = df.loc[idx, 'low'] * 0.995
                    else:
                        markers.loc[idx] = df.loc[idx, 'high'] * 1.005
                    matched += 1
                else:
                    unmatched += 1

        if unmatched > 0:
            logger.debug(f"Trade markers: {matched} matched, {unmatched} unmatched for {action}")

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

        # Ensure timestamp column
        df = df.copy()
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        elif isinstance(df.index, pd.DatetimeIndex):
            df['timestamp'] = df.index

        # Get year range
        years = df['timestamp'].dt.year.unique()
        years = sorted(years)

        if len(years) <= 1:
            # Only one year, use regular chart
            chart_path = self.create_regime_chart(
                df, trades, equity_curve,
                output_path=f"{output_dir or '.'}/regime_chart.png",
                title=title_prefix
            )
            return [chart_path] if chart_path else []

        saved_paths = []
        output_dir = Path(output_dir) if output_dir else Path.cwd()
        output_dir.mkdir(parents=True, exist_ok=True)

        for year in years:
            # Filter data for this year
            year_mask = df['timestamp'].dt.year == year
            year_df = df[year_mask].copy()

            if year_df.empty:
                continue

            # Filter trades for this year
            year_trades = None
            if trades:
                year_trades = []
                for t in trades:
                    ts = pd.to_datetime(t.get('timestamp'))
                    if ts.year == year:
                        year_trades.append(t)

            # Filter equity curve for this year
            year_equity = None
            if equity_curve:
                year_equity = []
                for e in equity_curve:
                    date = pd.to_datetime(e.get('date'))
                    if date.year == year:
                        year_equity.append(e)

            # Generate chart for this year
            output_path = output_dir / f"regime_{year}.png"
            chart_path = self.create_regime_chart(
                year_df,
                trades=year_trades,
                equity_curve=year_equity,
                output_path=str(output_path),
                title=f"{title_prefix} - {year}"
            )

            if chart_path:
                saved_paths.append(chart_path)
                logger.info(f"Generated yearly chart: {chart_path}")

        return saved_paths

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
