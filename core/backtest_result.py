"""BacktestResult dataclass for enhanced backtest results with benchmark data."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd


@dataclass
class Trade:
    """Individual trade record."""

    entry_time: datetime
    entry_price: float
    quantity: float
    side: str  # 'buy' or 'sell'
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    profit_loss: Optional[float] = None
    profit_loss_pct: Optional[float] = None
    reason: str = ""


@dataclass
class BacktestResult:
    """Complete backtest result with benchmark comparison.

    This dataclass contains all metrics and time series data from a backtest run,
    including comparison against a buy-and-hold benchmark.

    Attributes:
        strategy_name: Strategy identifier (e.g., "v35_long")
        symbol: Trading symbol (e.g., "BTC", "ETH")
        start_date: Backtest start timestamp
        end_date: Backtest end timestamp
        initial_capital: Starting capital
        final_capital: Ending capital
        total_return_pct: Strategy return percentage
        total_trades: Total number of closed trades
        winning_trades: Number of profitable trades
        losing_trades: Number of losing trades
        win_rate: Win rate (0.0 to 1.0)
        sharpe_ratio: Annualized Sharpe ratio
        max_drawdown_pct: Maximum peak-to-trough decline percentage
        profit_factor: Gross profit / gross loss
        equity_curve: Time series of portfolio value
        trades: List of individual trade records
        benchmark_curve: Time series of buy-and-hold value
        benchmark_return_pct: Buy-and-hold return percentage
        params: Strategy parameters for logging
    """

    # Identification
    strategy_name: str
    symbol: str
    start_date: datetime
    end_date: datetime

    # Capital tracking
    initial_capital: float
    final_capital: float
    total_return_pct: float

    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float  # 0.0 to 1.0

    # Risk metrics
    sharpe_ratio: float
    max_drawdown_pct: float
    profit_factor: float  # gross_profit / gross_loss

    # Time series data
    equity_curve: pd.DataFrame  # timestamp, cash, position_value, total_equity
    trades: List[Trade] = field(default_factory=list)

    # Benchmark data
    benchmark_curve: Optional[pd.Series] = None  # timestamp -> benchmark_equity
    benchmark_return_pct: float = 0.0

    # Strategy parameters (for MLflow logging)
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for legacy compatibility."""
        return {
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_capital": self.initial_capital,
            "final_capital": self.final_capital,
            "total_return": self.total_return_pct,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown_pct": self.max_drawdown_pct,
            "profit_factor": self.profit_factor,
            "equity_curve": self.equity_curve,
            "trades": self.trades,
            "benchmark_curve": self.benchmark_curve,
            "benchmark_return_pct": self.benchmark_return_pct,
            "params": self.params,
        }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        strategy_name: str = "unknown",
        symbol: str = "unknown",
        params: Optional[Dict[str, Any]] = None,
    ) -> "BacktestResult":
        """Create BacktestResult from legacy results dictionary.

        Args:
            data: Legacy results dictionary from Backtester._generate_results()
            strategy_name: Strategy name to attach
            symbol: Symbol to attach
            params: Strategy parameters to attach

        Returns:
            BacktestResult instance
        """
        equity_curve = data.get("equity_curve", pd.DataFrame())

        # Extract dates from equity curve if available
        if not equity_curve.empty and "timestamp" in equity_curve.columns:
            start_date = equity_curve["timestamp"].iloc[0]
            end_date = equity_curve["timestamp"].iloc[-1]
        else:
            start_date = datetime.now()
            end_date = datetime.now()

        # Default benchmark values (will be populated by calculate_benchmark)
        benchmark_curve = data.get("benchmark_curve")
        benchmark_return_pct = data.get("benchmark_return_pct", 0.0)

        return cls(
            strategy_name=strategy_name,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=data.get("initial_capital", 0.0),
            final_capital=data.get("final_capital", 0.0),
            total_return_pct=data.get("total_return", 0.0),
            total_trades=data.get("total_trades", 0),
            winning_trades=data.get("winning_trades", 0),
            losing_trades=data.get("losing_trades", 0),
            win_rate=data.get("win_rate", 0.0),
            sharpe_ratio=data.get("sharpe_ratio", 0.0),
            max_drawdown_pct=data.get("max_drawdown_pct", 0.0),
            profit_factor=data.get("profit_factor", 0.0),
            equity_curve=equity_curve,
            trades=data.get("trades", []),
            benchmark_curve=benchmark_curve,
            benchmark_return_pct=benchmark_return_pct,
            params=params or {},
        )
