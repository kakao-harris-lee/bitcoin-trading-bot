"""Metrics calculation functions for backtest results.

This module provides functions to calculate key performance metrics:
- Benchmark (buy-and-hold) returns
- Sharpe ratio (annualized)
- Maximum drawdown
"""

import logging
from typing import Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Standard trading days per year for annualized calculations
# See also: trading.config.constants.TimePeriods.TRADING_DAYS_PER_YEAR
TRADING_DAYS_PER_YEAR = 252


def calculate_benchmark(
    price_data: pd.DataFrame,
    initial_capital: float,
    price_column: str = "close",
) -> Tuple[pd.Series, float]:
    """Calculate buy-and-hold benchmark equity curve and return.

    Simulates buying at the first price and holding until the end.

    Args:
        price_data: DataFrame with timestamp and price columns
        initial_capital: Starting capital
        price_column: Column name for price (default: "close")

    Returns:
        Tuple of:
        - pd.Series: Benchmark equity curve indexed by timestamp
        - float: Total benchmark return percentage

    Example:
        >>> benchmark_curve, benchmark_return = calculate_benchmark(df, 10000)
        >>> print(f"Buy-and-hold return: {benchmark_return:.2f}%")
    """
    if price_data.empty:
        return pd.Series(dtype=float), 0.0

    # Validate required columns exist
    if price_column not in price_data.columns:
        logger.warning(f"Column '{price_column}' not found in price data")
        return pd.Series(dtype=float), 0.0
    if "timestamp" not in price_data.columns:
        logger.warning("Column 'timestamp' not found in price data")
        return pd.Series(dtype=float), 0.0

    prices = price_data[price_column].values
    timestamps = price_data["timestamp"].values

    # Buy at first price
    first_price = prices[0]
    if first_price <= 0:
        return pd.Series(dtype=float), 0.0

    # Calculate position size (how many units we can buy)
    position_size = initial_capital / first_price

    # Calculate equity at each timestamp
    equity_values = position_size * prices

    # Create Series with timestamp index
    benchmark_curve = pd.Series(equity_values, index=timestamps, name="benchmark_equity")

    # Calculate return
    final_equity = equity_values[-1]
    benchmark_return_pct = ((final_equity - initial_capital) / initial_capital) * 100

    return benchmark_curve, benchmark_return_pct


def calculate_sharpe_ratio(
    equity_curve: pd.DataFrame,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365 * 24,  # Hourly data by default
    equity_column: str = "total_equity",
) -> float:
    """Calculate annualized Sharpe ratio from equity curve.

    The Sharpe ratio measures risk-adjusted return:
    Sharpe = (mean_return - risk_free_rate) / std_return * sqrt(periods_per_year)

    Args:
        equity_curve: DataFrame with equity values over time
        risk_free_rate: Annual risk-free rate (default: 0.0)
        periods_per_year: Number of periods in a year (default: 8760 for hourly)
        equity_column: Column name for equity (default: "total_equity")

    Returns:
        Annualized Sharpe ratio. Returns 0.0 if insufficient data.

    Example:
        >>> sharpe = calculate_sharpe_ratio(equity_df, periods_per_year=365*24)
        >>> print(f"Sharpe Ratio: {sharpe:.2f}")
    """
    if equity_curve.empty or len(equity_curve) < 2:
        return 0.0

    # Validate required column exists
    if equity_column not in equity_curve.columns:
        logger.warning(f"Column '{equity_column}' not found in equity curve")
        return 0.0

    equity = equity_curve[equity_column].values

    # Calculate period returns
    returns = np.diff(equity) / equity[:-1]

    if len(returns) < 2:
        return 0.0

    # Calculate mean and std of returns
    mean_return = np.mean(returns)
    std_return = np.std(returns, ddof=1)  # Use sample std

    if std_return == 0:
        return 0.0

    # Convert risk-free rate to per-period
    risk_free_per_period = risk_free_rate / periods_per_year

    # Calculate and annualize Sharpe ratio
    sharpe = (mean_return - risk_free_per_period) / std_return * np.sqrt(periods_per_year)

    return float(sharpe)


def calculate_max_drawdown(
    equity_curve: pd.DataFrame,
    equity_column: str = "total_equity",
) -> float:
    """Calculate maximum drawdown percentage from equity curve.

    Maximum drawdown is the largest peak-to-trough decline as a percentage.

    Args:
        equity_curve: DataFrame with equity values over time
        equity_column: Column name for equity (default: "total_equity")

    Returns:
        Maximum drawdown as a positive percentage (e.g., 15.5 for 15.5% drawdown).
        Returns 0.0 if insufficient data.

    Example:
        >>> max_dd = calculate_max_drawdown(equity_df)
        >>> print(f"Max Drawdown: {max_dd:.2f}%")
    """
    if equity_curve.empty or len(equity_curve) < 2:
        return 0.0

    # Validate required column exists
    if equity_column not in equity_curve.columns:
        logger.warning(f"Column '{equity_column}' not found in equity curve")
        return 0.0

    equity = equity_curve[equity_column].values

    # Calculate running maximum
    running_max = np.maximum.accumulate(equity)

    # Calculate drawdown at each point
    drawdowns = (running_max - equity) / running_max * 100

    # Return max drawdown as positive percentage
    max_drawdown = np.max(drawdowns)

    return float(max_drawdown)


def calculate_profit_factor(
    winning_profit: float,
    losing_loss: float,
) -> float:
    """Calculate profit factor from gross profits and losses.

    Profit factor = gross_profit / abs(gross_loss)

    Args:
        winning_profit: Total profit from winning trades (positive)
        losing_loss: Total loss from losing trades (negative or positive)

    Returns:
        Profit factor. Returns 0.0 if no losing trades.
    """
    abs_loss = abs(losing_loss)
    if abs_loss == 0:
        return float("inf") if winning_profit > 0 else 0.0
    return winning_profit / abs_loss


def calculate_cagr(equity_curve: pd.DataFrame, years: float) -> float:
    """Calculate Compound Annual Growth Rate.

    Args:
        equity_curve: DataFrame with 'total_equity' column
        years: Number of years in the backtest period

    Returns:
        CAGR as percentage (e.g., 15.5 for 15.5%)
    """
    if years <= 0:
        return 0.0

    if equity_curve.empty or 'total_equity' not in equity_curve.columns:
        return 0.0

    start = equity_curve['total_equity'].iloc[0]
    end = equity_curve['total_equity'].iloc[-1]

    if start <= 0:
        return 0.0

    return (pow(end / start, 1 / years) - 1) * 100


def calculate_sortino_ratio(equity_curve: pd.DataFrame, risk_free: float = 0.0) -> float:
    """Calculate Sortino ratio (downside risk only).

    Args:
        equity_curve: DataFrame with 'total_equity' column
        risk_free: Annual risk-free rate (default 0)

    Returns:
        Sortino ratio
    """
    if equity_curve.empty or 'total_equity' not in equity_curve.columns:
        return 0.0

    returns = equity_curve['total_equity'].pct_change().dropna()

    if len(returns) < 2:
        return 0.0

    excess = returns - risk_free / 252
    downside_returns = returns[returns < 0]

    if len(downside_returns) == 0:
        return 0.0

    downside = downside_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)

    if downside == 0 or np.isnan(downside):
        return 0.0

    sortino = (returns.mean() * 252 - risk_free) / downside

    # Return 0 if result is NaN or infinite
    if np.isnan(sortino) or np.isinf(sortino):
        return 0.0

    return float(sortino)


def calculate_calmar_ratio(cagr: float, max_drawdown: float) -> float:
    """Calculate Calmar ratio (CAGR / MDD).

    Args:
        cagr: Compound Annual Growth Rate (%)
        max_drawdown: Maximum drawdown (positive percentage)

    Returns:
        Calmar ratio
    """
    if max_drawdown == 0:
        return 0.0
    return cagr / abs(max_drawdown)
