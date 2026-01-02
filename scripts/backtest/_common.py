#!/usr/bin/env python3
"""
Common utilities for per-strategy backtesting.

Provides shared functionality:
- Data loading
- Metrics calculation
- Output formatting
- CLI argument parsing
- ShortMarginBacktester for short strategy backtesting
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# Project root setup
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.data_loader import DataLoader

# Annualization factors for different timeframes
PERIODS_PER_YEAR = {
    "day": 252,
    "minute240": 252 * 6,  # 6 candles per day
    "minute60": 252 * 24,  # 24 candles per day
    "minute30": 252 * 48,
    "minute15": 252 * 96,
    "minute5": 252 * 288,
    "minute1": 252 * 1440,
}


def load_data(
    db_path: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Load OHLCV data from database.

    Args:
        db_path: Path to SQLite database
        timeframe: Candle timeframe (day, minute240, etc.)
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        DataFrame with OHLCV data
    """
    with DataLoader(db_path) as loader:
        df = loader.load_timeframe(timeframe, start_date, end_date)
    return df


def compute_metrics(
    equity_curve: Optional[pd.DataFrame],
    timeframe: str = "day",
) -> Dict[str, float]:
    """Compute backtest metrics from equity curve.

    Args:
        equity_curve: DataFrame with 'timestamp' and 'total_equity' columns
        timeframe: Candle timeframe for correct Sharpe ratio annualization

    Returns:
        Dict with: total_return, cagr, mdd, sharpe
    """
    # Handle None or empty DataFrame
    if equity_curve is None or equity_curve.empty or len(equity_curve) < 2:
        return {
            "total_return": 0.0,
            "cagr": 0.0,
            "mdd": 0.0,
            "sharpe": 0.0,
        }

    eq = equity_curve.copy()
    eq = eq.sort_values("timestamp")

    initial = float(eq["total_equity"].iloc[0])
    final = float(eq["total_equity"].iloc[-1])

    # Total return
    total_return = ((final - initial) / initial) * 100 if initial > 0 else 0.0

    # CAGR (handle negative final equity)
    start = pd.Timestamp(eq["timestamp"].iloc[0])
    end = pd.Timestamp(eq["timestamp"].iloc[-1])
    years = (end - start).days / 365.25
    cagr = 0.0
    if years > 0 and initial > 0 and final > 0:
        cagr = ((final / initial) ** (1 / years) - 1) * 100
    elif years > 0 and initial > 0 and final <= 0:
        cagr = -100.0  # Total loss

    # Max Drawdown (with zero protection)
    peak = eq["total_equity"].cummax()
    with np.errstate(divide='ignore', invalid='ignore'):
        drawdown = np.where(peak > 0, (eq["total_equity"] - peak) / peak, 0.0)
    mdd = float(np.nanmin(drawdown) * 100) if len(drawdown) > 0 else 0.0

    # Sharpe Ratio (annualized with correct period)
    returns = eq["total_equity"].pct_change().dropna()
    sharpe = 0.0
    periods_per_year = PERIODS_PER_YEAR.get(timeframe, 252)
    if len(returns) > 5 and returns.std() != 0:
        sharpe = float((returns.mean() / returns.std()) * np.sqrt(periods_per_year))

    return {
        "total_return": total_return,
        "cagr": cagr,
        "mdd": mdd,
        "sharpe": sharpe,
    }


def compute_trade_stats(results: Dict) -> Dict[str, float]:
    """Extract trade statistics from backtest results.

    Args:
        results: Backtester results dictionary

    Returns:
        Dict with: total_trades, win_rate, profit_factor, avg_profit, avg_loss
    """
    return {
        "total_trades": results.get("total_trades", 0),
        "win_rate": results.get("win_rate", 0.0),
        "profit_factor": results.get("profit_factor", 0.0),
        "avg_profit": results.get("avg_profit", 0.0),
        "avg_loss": results.get("avg_loss", 0.0),
    }


def print_summary(
    strategy_name: str,
    results: Dict,
    metrics: Dict[str, float],
    verbose: bool = True,
) -> None:
    """Print backtest summary.

    Args:
        strategy_name: Name of the strategy
        results: Backtester results
        metrics: Computed metrics
        verbose: Whether to print detailed output
    """
    print("\n" + "=" * 60)
    print(f"Backtest: {strategy_name.upper()}")
    print("=" * 60)
    print(f"Initial Capital: {results.get('initial_capital', 0):,.0f}")
    print(f"Final Capital:   {results.get('final_capital', 0):,.0f}")
    print(f"Total Return:    {results.get('total_return', 0):+.2f}%")
    print(f"CAGR:            {metrics.get('cagr', 0):+.2f}%")
    print(f"MDD:             {metrics.get('mdd', 0):.2f}%")
    print(f"Sharpe:          {metrics.get('sharpe', 0):+.2f}")

    if verbose and results.get("total_trades", 0) > 0:
        print("-" * 40)
        print(f"Total Trades:    {results.get('total_trades', 0)}")
        print(f"Win Rate:        {results.get('win_rate', 0) * 100:.1f}%")
        print(f"Profit Factor:   {results.get('profit_factor', 0):.2f}")
        print(f"Avg Profit:      {results.get('avg_profit', 0):,.0f}")
        print(f"Avg Loss:        {results.get('avg_loss', 0):,.0f}")


def print_yearly_table(equity_curve: Optional[pd.DataFrame]) -> None:
    """Print year-by-year breakdown table.

    Args:
        equity_curve: DataFrame with 'timestamp' and 'total_equity' columns
    """
    # Handle None or empty DataFrame
    if equity_curve is None or equity_curve.empty:
        print("(no data)")
        return

    df = equity_curve.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["year"] = df["timestamp"].dt.year

    print("\n" + "=" * 50)
    print("Year-by-Year Breakdown")
    print("=" * 50)
    print(f"{'YEAR':<6} {'RET%':>10} {'MDD%':>10}")
    print("-" * 30)

    for year, grp in df.groupby("year"):
        if len(grp) < 2:
            continue

        start_eq = float(grp["total_equity"].iloc[0])
        end_eq = float(grp["total_equity"].iloc[-1])
        ret = ((end_eq - start_eq) / start_eq) * 100 if start_eq > 0 else 0.0

        peak = grp["total_equity"].cummax()
        with np.errstate(divide='ignore', invalid='ignore'):
            dd = np.where(peak > 0, (grp["total_equity"] - peak) / peak, 0.0)
        mdd = float(np.nanmin(dd) * 100) if len(dd) > 0 else 0.0

        print(f"{int(year):<6} {ret:>10.2f} {mdd:>10.2f}")


def create_parser(
    strategy_name: str,
    default_timeframe: str = "day",
    default_capital: float = 10_000_000,
) -> argparse.ArgumentParser:
    """Create CLI argument parser.

    Args:
        strategy_name: Name of the strategy
        default_timeframe: Default candle timeframe
        default_capital: Default initial capital

    Returns:
        Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(
        description=f"Backtest for {strategy_name} strategy"
    )

    parser.add_argument(
        "--start-date",
        default="2020-01-01",
        help="Backtest start date (default: 2020-01-01)",
    )
    parser.add_argument(
        "--end-date",
        default="2024-12-31",
        help="Backtest end date (default: 2024-12-31)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=default_capital,
        help=f"Initial capital (default: {default_capital:,.0f})",
    )
    parser.add_argument(
        "--timeframe",
        default=default_timeframe,
        help=f"Candle timeframe (default: {default_timeframe})",
    )
    parser.add_argument(
        "--by-year",
        action="store_true",
        help="Show year-by-year breakdown",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Database path (default: data/upbit_bitcoin.db)",
    )

    return parser


def get_db_path(args_db_path: Optional[str] = None) -> str:
    """Get database path.

    Args:
        args_db_path: User-provided path or None

    Returns:
        Resolved database path
    """
    if args_db_path:
        return args_db_path
    return str(PROJECT_ROOT / "data" / "upbit_bitcoin.db")


class ShortMarginBacktester:
    """Margin-style backtester for short positions.

    Configurable for different currencies and action naming conventions.

    Args:
        initial_capital: Starting capital
        fee_rate: Trading fee rate (default: 0.05%)
        slippage: Slippage rate (default: 0.02%)
        min_order_amount: Minimum order amount (10 for USDT, 10000 for KRW)
        action_open: Action name to open short (default: "short")
        action_close: Action name to close short (default: "close_short")
    """

    def __init__(
        self,
        initial_capital: float = 10_000,
        fee_rate: float = 0.0005,
        slippage: float = 0.0002,
        min_order_amount: float = 10,
        action_open: str = "short",
        action_close: str = "close_short",
    ):
        self.initial_capital = float(initial_capital)
        self.fee_rate = float(fee_rate)
        self.slippage = float(slippage)
        self.min_order_amount = float(min_order_amount)
        self.action_open = action_open
        self.action_close = action_close

        self.cash = self.initial_capital
        self.in_short = False
        self.entry_price = 0.0
        self.entry_fee = 0.0
        self.size = 0.0
        self.margin = 0.0
        self.equity_curve: List[Dict] = []
        self.trades: List[Dict] = []

    def reset(self):
        """Reset backtester state."""
        self.cash = self.initial_capital
        self.in_short = False
        self.entry_price = 0.0
        self.entry_fee = 0.0
        self.size = 0.0
        self.margin = 0.0
        self.equity_curve = []
        self.trades = []

    def _equity(self, price: float) -> float:
        """Calculate current equity including unrealized P&L."""
        if not self.in_short:
            return self.cash
        current_exec = price * (1 + self.slippage)
        unrealized = (self.entry_price - current_exec) * self.size
        return self.cash + self.margin + unrealized

    def run(self, df: pd.DataFrame, strategy_func, params: Dict = None) -> Dict:
        """Run backtest on DataFrame.

        Args:
            df: OHLCV DataFrame with 'timestamp' and 'close' columns
            strategy_func: Callable that returns signal dict
            params: Additional parameters for strategy

        Returns:
            Results dictionary with metrics and equity curve
        """
        self.reset()
        params = params or {}

        if df.empty:
            return self._generate_results()

        for i in range(len(df)):
            row = df.iloc[i]
            ts = row["timestamp"]
            price = float(row["close"]) if not pd.isna(row["close"]) else 0.0

            if price <= 0:
                continue

            sig = strategy_func(df, i, params)
            if sig is None:
                sig = {"action": "hold"}

            action = sig.get("action", "hold")
            fraction = min(1.0, max(0.0, float(sig.get("fraction", 1.0))))

            if action == self.action_open:
                self._open_short(ts, price, fraction)
            elif action == self.action_close:
                self._close_short(ts, price)

            self.equity_curve.append({
                "timestamp": ts,
                "cash": self.cash,
                "margin": self.margin,
                "total_equity": self._equity(price),
            })

        # Force close at end
        if self.in_short and len(df) > 0:
            last = df.iloc[-1]
            self._close_short(last["timestamp"], float(last["close"]))

        return self._generate_results()

    def _open_short(self, ts, price: float, fraction: float):
        """Open a short position."""
        if self.in_short:
            return

        margin = self.cash * fraction
        if margin < self.min_order_amount:
            return

        entry_exec = price * (1 - self.slippage)
        size = margin / entry_exec
        entry_fee = (size * entry_exec) * self.fee_rate
        total_cost = margin + entry_fee

        if total_cost > self.cash:
            return

        self.cash -= total_cost
        self.margin = margin
        self.size = size
        self.entry_price = entry_exec
        self.entry_fee = entry_fee
        self.in_short = True

        self.trades.append({
            "entry_time": ts,
            "entry_price": entry_exec,
            "entry_fee": entry_fee,
            "size": size,
            "margin": margin,
            "exit_time": None,
            "exit_price": None,
            "pnl": None,
        })

    def _close_short(self, ts, price: float):
        """Close the short position."""
        if not self.in_short:
            return

        exit_exec = price * (1 + self.slippage)
        exit_fee = (self.size * exit_exec) * self.fee_rate
        pnl = (self.entry_price - exit_exec) * self.size
        # Include both entry and exit fees in PnL
        total_pnl = pnl - exit_fee - self.entry_fee
        self.cash += self.margin + pnl - exit_fee

        for t in self.trades:
            if t.get("exit_time") is None:
                t["exit_time"] = ts
                t["exit_price"] = exit_exec
                t["pnl"] = total_pnl
                break

        self.in_short = False
        self.entry_price = 0.0
        self.entry_fee = 0.0
        self.size = 0.0
        self.margin = 0.0

    def _generate_results(self) -> Dict:
        """Generate results dictionary from backtest."""
        eq = pd.DataFrame(self.equity_curve) if self.equity_curve else pd.DataFrame()
        final_equity = float(eq["total_equity"].iloc[-1]) if not eq.empty else self.cash
        total_return = ((final_equity - self.initial_capital) / self.initial_capital) * 100 if self.initial_capital > 0 else 0.0

        closed_trades = [t for t in self.trades if t.get("exit_time") is not None]
        wins = [t for t in closed_trades if t.get("pnl", 0) > 0]
        losses = [t for t in closed_trades if t.get("pnl", 0) <= 0]

        win_rate = len(wins) / len(closed_trades) if closed_trades else 0.0
        avg_profit = float(np.mean([t["pnl"] for t in wins])) if wins else 0.0
        avg_loss = float(abs(np.mean([t["pnl"] for t in losses]))) if losses else 0.0

        # Fix profit_factor edge case
        total_profit = sum(t["pnl"] for t in wins) if wins else 0.0
        total_loss = abs(sum(t["pnl"] for t in losses)) if losses else 0.0

        if total_loss > 0:
            profit_factor = total_profit / total_loss
        elif total_profit > 0:
            profit_factor = float('inf')
        else:
            profit_factor = 0.0

        return {
            "initial_capital": self.initial_capital,
            "final_capital": final_equity,
            "total_return": total_return,
            "total_trades": len(closed_trades),
            "win_rate": win_rate,
            "avg_profit": avg_profit,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "equity_curve": eq,
            "trades": closed_trades,
        }
