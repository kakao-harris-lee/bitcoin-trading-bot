"""
Analytics service for calculating trading performance metrics.
"""

from datetime import datetime, timedelta


def calculate_metrics(trades: list, period: str = '30d') -> dict:
    """
    Calculate performance metrics from a list of trades.

    Args:
        trades: List of trade dictionaries with profit, profit_pct, timestamp, action
        period: '7d', '30d', '90d', or 'all'

    Returns:
        Dictionary with calculated metrics
    """
    trades = _filter_trades_by_period(trades, period)

    if not trades:
        return _empty_metrics(period)

    total_trades = len(trades)
    sell_trades = _extract_closed_sell_trades(trades)
    if not sell_trades:
        return _empty_metrics(period)

    stats = _calculate_trade_stats(sell_trades)
    profit_pcts = _extract_profit_pcts(sell_trades)
    total_return = sum(profit_pcts) if profit_pcts else 0
    start_date, end_date = _extract_date_range(trades)
    max_drawdown, max_drawdown_pct = _calculate_max_drawdown(sell_trades)
    sharpe_ratio = _calculate_sharpe(profit_pcts)
    by_strategy = _group_by_strategy(sell_trades)

    return {
        'period': period,
        'start_date': start_date,
        'end_date': end_date,
        'total_return': total_return,
        'total_return_krw': stats['total_profit'],
        'win_rate': stats['win_rate'],
        'total_trades': total_trades,
        'closed_trades': stats['closed_trades'],
        'winning_trades': stats['winning_trades'],
        'losing_trades': stats['losing_trades'],
        'profit_factor': stats['profit_factor'],
        'avg_trade': stats['avg_trade'],
        'avg_win': stats['avg_win'],
        'avg_loss': stats['avg_loss'],
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown_pct,
        'max_drawdown_krw': max_drawdown,
        'by_strategy': by_strategy
    }


def _filter_trades_by_period(trades: list, period: str) -> list:
    if period == 'all':
        return trades
    days = int(period.replace('d', ''))
    cutoff = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff.isoformat()
    return [t for t in trades if t.get('timestamp', '') >= cutoff_str]


def _extract_closed_sell_trades(trades: list) -> list:
    return [
        t for t in trades
        if t.get('action', '').upper() == 'SELL' and t.get('profit') is not None
    ]


def _calculate_trade_stats(sell_trades: list) -> dict:
    wins, losses = _split_wins_losses(sell_trades)
    winning_trades = len(wins)
    losing_trades = len(losses)
    closed_trades = len(sell_trades)
    total_profit = sum(t.get('profit', 0) for t in sell_trades)
    total_wins = sum(t.get('profit', 0) for t in wins)
    total_losses = abs(sum(t.get('profit', 0) for t in losses))
    win_rate = _safe_pct_ratio(winning_trades, closed_trades)
    profit_factor = _compute_profit_factor(total_wins, total_losses)
    return {
        'closed_trades': closed_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': win_rate,
        'total_profit': total_profit,
        'avg_trade': _safe_div(total_profit, closed_trades),
        'avg_win': _safe_div(total_wins, winning_trades),
        'avg_loss': _safe_div(total_losses, losing_trades),
        'profit_factor': _format_profit_factor(profit_factor),
    }


def _split_wins_losses(sell_trades: list) -> tuple[list, list]:
    wins = [t for t in sell_trades if t.get('profit', 0) > 0]
    losses = [t for t in sell_trades if t.get('profit', 0) <= 0]
    return wins, losses


def _safe_div(numerator: float, denominator: int) -> float:
    if denominator <= 0:
        return 0
    return numerator / denominator


def _safe_pct_ratio(numerator: int, denominator: int) -> float:
    return _safe_div(numerator * 100, denominator)


def _compute_profit_factor(total_wins: float, total_losses: float) -> float:
    if total_losses > 0:
        return total_wins / total_losses
    if total_wins > 0:
        return float('inf')
    return 0


def _format_profit_factor(profit_factor: float) -> float | int:
    if profit_factor == float('inf'):
        return 999
    return round(profit_factor, 2)


def _extract_profit_pcts(sell_trades: list) -> list:
    return [t.get('profit_pct', 0) for t in sell_trades if t.get('profit_pct') is not None]


def _extract_date_range(trades: list) -> tuple[str, str]:
    timestamps = [t.get('timestamp', '') for t in trades if t.get('timestamp')]
    if not timestamps:
        return '', ''
    return min(timestamps)[:10], max(timestamps)[:10]


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
    except (statistics.StatisticsError, ValueError, TypeError):
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
