"""
Analytics service for calculating trading performance metrics.
"""

from datetime import datetime, timedelta
from typing import Optional


def calculate_metrics(trades: list, period: str = '30d') -> dict:
    """
    Calculate performance metrics from a list of trades.

    Args:
        trades: List of trade dictionaries with profit, profit_pct, timestamp, action
        period: '7d', '30d', '90d', or 'all'

    Returns:
        Dictionary with calculated metrics
    """
    # Filter trades by period
    now = datetime.now()

    if period != 'all':
        days = int(period.replace('d', ''))
        cutoff = now - timedelta(days=days)
        cutoff_str = cutoff.isoformat()
        trades = [t for t in trades if t.get('timestamp', '') >= cutoff_str]

    if not trades:
        return _empty_metrics(period)

    # Calculate basic stats
    total_trades = len(trades)
    sell_trades = [t for t in trades if t.get('action', '').upper() == 'SELL' and t.get('profit') is not None]

    if not sell_trades:
        return _empty_metrics(period)

    wins = [t for t in sell_trades if t.get('profit', 0) > 0]
    losses = [t for t in sell_trades if t.get('profit', 0) <= 0]

    winning_trades = len(wins)
    losing_trades = len(losses)
    closed_trades = len(sell_trades)

    win_rate = (winning_trades / closed_trades * 100) if closed_trades > 0 else 0

    # Calculate P&L
    total_profit = sum(t.get('profit', 0) for t in sell_trades)
    total_wins = sum(t.get('profit', 0) for t in wins)
    total_losses = abs(sum(t.get('profit', 0) for t in losses))

    profit_factor = (total_wins / total_losses) if total_losses > 0 else float('inf') if total_wins > 0 else 0

    avg_trade = total_profit / closed_trades if closed_trades > 0 else 0
    avg_win = total_wins / winning_trades if winning_trades > 0 else 0
    avg_loss = total_losses / losing_trades if losing_trades > 0 else 0

    # Calculate return percentage
    profit_pcts = [t.get('profit_pct', 0) for t in sell_trades if t.get('profit_pct') is not None]
    total_return = sum(profit_pcts) if profit_pcts else 0

    # Get date range
    timestamps = [t.get('timestamp', '') for t in trades if t.get('timestamp')]
    start_date = min(timestamps)[:10] if timestamps else ''
    end_date = max(timestamps)[:10] if timestamps else ''

    # Calculate max drawdown (simplified)
    max_drawdown, max_drawdown_pct = _calculate_max_drawdown(sell_trades)

    # Calculate Sharpe ratio (simplified - using profit_pct as returns)
    sharpe_ratio = _calculate_sharpe(profit_pcts)

    # Group by strategy
    by_strategy = _group_by_strategy(sell_trades)

    return {
        'period': period,
        'start_date': start_date,
        'end_date': end_date,
        'total_return': total_return,
        'total_return_krw': total_profit,
        'win_rate': win_rate,
        'total_trades': total_trades,
        'closed_trades': closed_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 999,
        'avg_trade': avg_trade,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown_pct,
        'max_drawdown_krw': max_drawdown,
        'by_strategy': by_strategy
    }


def calculate_equity_curve(trades: list, period: str = '30d', initial_capital: float = 10000000) -> dict:
    """
    Generate equity curve data points from trades.

    Args:
        trades: List of trade dictionaries
        period: '7d', '30d', '90d', or 'all'
        initial_capital: Starting capital for the curve

    Returns:
        Dictionary with equity curve data
    """
    # Filter trades by period
    now = datetime.now()

    if period != 'all':
        days = int(period.replace('d', ''))
        cutoff = now - timedelta(days=days)
        cutoff_str = cutoff.isoformat()
        trades = [t for t in trades if t.get('timestamp', '') >= cutoff_str]

    # Sort by timestamp
    trades = sorted(trades, key=lambda x: x.get('timestamp', ''))

    # Only consider SELL trades with profit
    sell_trades = [t for t in trades if t.get('action', '').upper() == 'SELL' and t.get('profit') is not None]

    if not sell_trades:
        return {
            'period': period,
            'points': [],
            'peak_equity': initial_capital,
            'min_equity': initial_capital
        }

    # Build equity curve
    equity = initial_capital
    peak_equity = initial_capital
    min_equity = initial_capital
    points = []

    # Add starting point
    points.append({
        'timestamp': sell_trades[0].get('timestamp', ''),
        'equity': initial_capital,
        'drawdown': 0,
        'drawdown_pct': 0
    })

    for trade in sell_trades:
        profit = trade.get('profit', 0)
        equity += profit

        peak_equity = max(peak_equity, equity)
        min_equity = min(min_equity, equity)

        drawdown = peak_equity - equity
        drawdown_pct = (drawdown / peak_equity * 100) if peak_equity > 0 else 0

        points.append({
            'timestamp': trade.get('timestamp', ''),
            'equity': equity,
            'drawdown': drawdown,
            'drawdown_pct': drawdown_pct
        })

    return {
        'period': period,
        'points': points,
        'peak_equity': peak_equity,
        'min_equity': min_equity
    }


def _empty_metrics(period: str) -> dict:
    """Return empty metrics structure."""
    return {
        'period': period,
        'start_date': '',
        'end_date': '',
        'total_return': 0,
        'total_return_krw': 0,
        'win_rate': 0,
        'total_trades': 0,
        'closed_trades': 0,
        'winning_trades': 0,
        'losing_trades': 0,
        'profit_factor': 0,
        'avg_trade': 0,
        'avg_win': 0,
        'avg_loss': 0,
        'sharpe_ratio': 0,
        'max_drawdown': 0,
        'max_drawdown_krw': 0,
        'by_strategy': {}
    }


def _calculate_max_drawdown(trades: list) -> tuple:
    """Calculate maximum drawdown from trades."""
    if not trades:
        return 0, 0

    equity = 0
    peak = 0
    max_dd = 0
    max_dd_pct = 0

    for trade in sorted(trades, key=lambda x: x.get('timestamp', '')):
        profit = trade.get('profit', 0)
        equity += profit
        peak = max(peak, equity)

        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = (dd / peak * 100) if peak > 0 else 0

    return max_dd, max_dd_pct


def _calculate_sharpe(returns: list, risk_free_rate: float = 0.02) -> float:
    """Calculate simplified Sharpe ratio."""
    if len(returns) < 2:
        return 0

    import statistics

    try:
        mean_return = statistics.mean(returns)
        std_return = statistics.stdev(returns)

        if std_return == 0:
            return 0

        # Annualized (assuming daily returns)
        sharpe = (mean_return - risk_free_rate / 365) / std_return * (365 ** 0.5)
        return round(sharpe, 2)
    except Exception:
        return 0


def _group_by_strategy(trades: list) -> dict:
    """Group trade statistics by strategy."""
    strategies = {}

    for trade in trades:
        strategy = trade.get('strategy', 'unknown')
        if strategy not in strategies:
            strategies[strategy] = {
                'total_trades': 0,
                'wins': 0,
                'total_profit': 0,
                'total_wins': 0,
                'total_losses': 0
            }

        s = strategies[strategy]
        s['total_trades'] += 1
        profit = trade.get('profit', 0)
        s['total_profit'] += profit

        if profit > 0:
            s['wins'] += 1
            s['total_wins'] += profit
        else:
            s['total_losses'] += abs(profit)

    # Calculate final metrics per strategy
    result = {}
    for strategy, stats in strategies.items():
        win_rate = (stats['wins'] / stats['total_trades'] * 100) if stats['total_trades'] > 0 else 0
        profit_factor = (stats['total_wins'] / stats['total_losses']) if stats['total_losses'] > 0 else 0

        result[strategy] = {
            'total_trades': stats['total_trades'],
            'win_rate': round(win_rate, 1),
            'total_return': stats['total_profit'],
            'profit_factor': round(profit_factor, 2)
        }

    return result
