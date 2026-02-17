"""Backtest CSV Logger.

Logs candle-by-candle state during backtesting for analysis.
Records: price, position, portfolio, risk metrics, signals, regime, and indicators.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class BacktestLogger:
    """Logs backtest state to CSV file for analysis.

    Creates one CSV file per backtest run with all state recorded at each candle.

    Usage:
        logger = BacktestLogger("short_v1", "BTC")
        for candle in candles:
            logger.log_candle(state_dict)
        filepath = logger.flush()
    """

    # Standard columns (always present)
    STANDARD_COLUMNS = [
        # Time/Price
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        # Position
        "position",
        "position_qty",
        "entry_price",
        # Portfolio
        "portfolio_value",
        "cash",
        "unrealized_pnl",
        "realized_pnl",
        "cumulative_pnl",
        # Risk
        "drawdown",
        "drawdown_pct",
        "high_water_mark",
        # Signal
        "signal",
        "signal_reason",
        # Regime
        "regime",
        "trend",
    ]

    # Indicator columns (optional, strategy-dependent)
    INDICATOR_COLUMNS = [
        "mfi",
        "adx",
        "rsi",
        "bb_upper",
        "bb_lower",
        "bb_middle",
        "ema_120",
        "ema_200",
        "atr",
        "macd",
        "macd_signal",
        "stoch_k",
        "stoch_d",
        "rf_confidence",
        "rf_direction",
        "mlp_prediction",
        "mlp_confidence",
    ]

    def __init__(
        self,
        strategy_name: str,
        symbol: str,
        output_dir: str = "backtest_logs",
        include_indicators: bool = True,
    ):
        """Initialize the logger.

        Args:
            strategy_name: Name of the strategy being tested.
            symbol: Trading symbol (e.g., "BTC", "ETH").
            output_dir: Directory to save CSV files.
            include_indicators: Whether to include indicator columns.
        """
        self.strategy_name = strategy_name
        self.symbol = symbol
        self.output_dir = Path(output_dir)
        self.include_indicators = include_indicators

        # Generate unique filename with timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.filename = f"{strategy_name}_{symbol}_{timestamp}.csv"
        self.filepath = self.output_dir / self.filename

        # Buffer for rows (flushed at end)
        self._rows: List[Dict[str, Any]] = []

        # Track columns dynamically
        self._columns = list(self.STANDARD_COLUMNS)
        if include_indicators:
            self._columns.extend(self.INDICATOR_COLUMNS)

        # Track extra columns discovered during logging
        self._extra_columns: set = set()

    def log_candle(self, state: Dict[str, Any]) -> None:
        """Log state for a single candle.

        Args:
            state: Dictionary containing state values. Keys should match
                   STANDARD_COLUMNS and optionally INDICATOR_COLUMNS.
                   Extra keys are preserved and added to output.
        """
        # Track any extra columns
        for key in state.keys():
            if key not in self._columns and key not in self._extra_columns:
                self._extra_columns.add(key)

        self._rows.append(state.copy())

    def flush(self) -> str:
        """Write buffered rows to CSV file.

        Returns:
            Path to the created CSV file.
        """
        if not self._rows:
            return str(self.filepath)

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Build final column list (standard + extra)
        all_columns = self._columns + sorted(self._extra_columns)

        with open(self.filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=all_columns,
                extrasaction="ignore",
            )
            writer.writeheader()

            for row in self._rows:
                # Fill missing columns with empty string
                filled_row = {col: row.get(col, "") for col in all_columns}
                writer.writerow(filled_row)

        return str(self.filepath)

    def get_filepath(self) -> str:
        """Get the filepath where CSV will be saved.

        Returns:
            Filepath string.
        """
        return str(self.filepath)

    def get_row_count(self) -> int:
        """Get number of logged rows.

        Returns:
            Number of rows in buffer.
        """
        return len(self._rows)

    def clear(self) -> None:
        """Clear the buffer without writing."""
        self._rows.clear()
        self._extra_columns.clear()

    @classmethod
    def list_logs(cls, output_dir: str = "backtest_logs") -> List[Dict[str, str]]:
        """List available CSV log files.

        Args:
            output_dir: Directory to search.

        Returns:
            List of dicts with filename, filepath, size, and modified time.
        """
        log_dir = Path(output_dir)
        if not log_dir.exists():
            return []

        logs = []
        for f in sorted(log_dir.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True):
            stat = f.stat()
            logs.append({
                "filename": f.name,
                "filepath": str(f),
                "size_kb": round(stat.st_size / 1024, 2),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })

        return logs


def build_candle_state(
    row: Dict[str, Any],
    position: Optional[str],
    position_qty: float,
    entry_price: float,
    portfolio_value: float,
    cash: float,
    unrealized_pnl: float,
    realized_pnl: float,
    cumulative_pnl: float,
    drawdown: float,
    drawdown_pct: float,
    high_water_mark: float,
    signal: str,
    signal_reason: str,
    regime: str,
    trend: str,
    **extra_indicators,
) -> Dict[str, Any]:
    """Build state dictionary for logging.

    Helper function to construct the state dict from backtest loop variables.

    Args:
        row: DataFrame row with OHLCV and indicator data.
        position: Position type ("long", "short", or "none").
        position_qty: Position quantity.
        entry_price: Entry price if in position.
        portfolio_value: Total portfolio value.
        cash: Available cash.
        unrealized_pnl: Unrealized profit/loss.
        realized_pnl: Realized profit/loss for current trade.
        cumulative_pnl: Cumulative profit/loss.
        drawdown: Current drawdown in absolute terms.
        drawdown_pct: Current drawdown percentage.
        high_water_mark: Highest portfolio value seen.
        signal: Signal type ("buy", "sell", "hold").
        signal_reason: Reason for signal.
        regime: Market regime classification.
        trend: Market trend direction.
        **extra_indicators: Additional indicator values.

    Returns:
        State dictionary ready for log_candle().
    """
    # Handle timestamp conversion
    ts = row.get("timestamp", "")
    if hasattr(ts, "isoformat"):
        ts = ts.isoformat()
    elif hasattr(ts, "timestamp"):
        ts = datetime.fromtimestamp(ts.timestamp()).isoformat()

    state = {
        # Time/Price
        "timestamp": ts,
        "open": row.get("open", 0.0),
        "high": row.get("high", 0.0),
        "low": row.get("low", 0.0),
        "close": row.get("close", 0.0),
        "volume": row.get("volume", 0.0),
        # Position
        "position": position or "none",
        "position_qty": position_qty,
        "entry_price": entry_price,
        # Portfolio
        "portfolio_value": portfolio_value,
        "cash": cash,
        "unrealized_pnl": unrealized_pnl,
        "realized_pnl": realized_pnl,
        "cumulative_pnl": cumulative_pnl,
        # Risk
        "drawdown": drawdown,
        "drawdown_pct": drawdown_pct,
        "high_water_mark": high_water_mark,
        # Signal
        "signal": signal,
        "signal_reason": signal_reason,
        # Regime
        "regime": regime,
        "trend": trend,
        # Standard indicators from row
        "mfi": row.get("mfi", ""),
        "adx": row.get("adx", ""),
        "rsi": row.get("rsi", ""),
        "bb_upper": row.get("bb_upper", ""),
        "bb_lower": row.get("bb_lower", ""),
        "bb_middle": row.get("bb_middle", ""),
        "ema_120": row.get("ema_120", ""),
        "ema_200": row.get("ema_200", ""),
        "atr": row.get("atr", ""),
        "macd": row.get("macd", ""),
        "macd_signal": row.get("macd_signal", ""),
        "stoch_k": row.get("stoch_k", ""),
        "stoch_d": row.get("stoch_d", ""),
    }

    # Add extra indicators
    state.update(extra_indicators)

    return state
