"""
Backtest runner service for executing backtests via web dashboard.
"""

import sys
from pathlib import Path

# Add project root to path for imports (core, scripts, etc.)
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import threading
import uuid
from datetime import datetime
from typing import Optional
import traceback

# Job storage (in-memory for now)
_backtest_jobs: dict = {}
_jobs_lock = threading.Lock()

# Rate limiting
MAX_CONCURRENT_JOBS = 3


class BacktestJob:
    """Represents a backtest job."""

    def __init__(self, job_id: str, config: dict):
        self.job_id = job_id
        self.config = config
        self.status = 'pending'  # pending, running, completed, failed, cancelled
        self.progress = 0
        self.result = None
        self.error = None
        self.created_at = datetime.now().isoformat()
        self.started_at = None
        self.completed_at = None
        self._thread: Optional[threading.Thread] = None
        self._cancelled = False

    def to_dict(self) -> dict:
        return {
            'job_id': self.job_id,
            'config': self.config,
            'status': self.status,
            'progress': self.progress,
            'result': self.result,
            'error': self.error,
            'created_at': self.created_at,
            'started_at': self.started_at,
            'completed_at': self.completed_at
        }


def get_available_strategies() -> list:
    """Get list of available strategies for backtesting."""
    # These match the strategies defined in the trading system (Binance-only)
    return [
        {
            'id': 'v35_long',
            'name': 'V35 Long (Binance)',
            'description': 'Momentum-based long strategy for bull markets',
            'exchange': 'binance',
            'default_params': {}
        },
        {
            'id': 'short_v1',
            'name': 'Short V1 (Binance)',
            'description': 'Futures short strategy for bear markets',
            'exchange': 'binance',
            'default_params': {}
        }
    ]


def create_backtest_job(config: dict) -> BacktestJob:
    """Create a new backtest job."""
    job_id = str(uuid.uuid4())[:8]
    job = BacktestJob(job_id, config)

    with _jobs_lock:
        _backtest_jobs[job_id] = job

    return job


def get_job(job_id: str) -> Optional[BacktestJob]:
    """Get a backtest job by ID."""
    with _jobs_lock:
        return _backtest_jobs.get(job_id)


def cancel_job(job_id: str) -> bool:
    """Cancel a running backtest job."""
    with _jobs_lock:
        job = _backtest_jobs.get(job_id)
        if job and job.status in ('pending', 'running'):
            job._cancelled = True
            job.status = 'cancelled'
            job.completed_at = datetime.now().isoformat()
            return True
    return False


def run_backtest(job: BacktestJob) -> None:
    """Run the backtest in a background thread."""
    def _run():
        try:
            job.status = 'running'
            job.started_at = datetime.now().isoformat()
            job.progress = 0

            # Import here to avoid circular imports
            from core.backtester import Backtester
            from core.data_loader import DataLoader
            from trading.strategy.v35_long import V35LongStrategy
            from trading.strategy.short_v1 import ShortV1Strategy

            # Strategy adapters to wrap strategy classes for Backtester interface
            class V35StrategyAdapter:
                """Adapter to make V35LongStrategy work with Backtester."""
                def __init__(self, config=None):
                    self.strategy = V35LongStrategy(config or {})
                    self._indicators_added = False

                def __call__(self, df, i, params):
                    if not self._indicators_added:
                        self.strategy.add_indicators(df)
                        self._indicators_added = True
                    signal = self.strategy.generate_signal(df, i)
                    if signal:
                        action = signal.get('action', 'hold')
                        if action in ('buy', 'sell'):
                            return {'action': action, 'fraction': signal.get('fraction', 1.0)}
                    return {'action': 'hold', 'fraction': 0}

            class ShortV1StrategyAdapter:
                """Adapter to make ShortV1Strategy work with Backtester."""
                def __init__(self, config=None):
                    self.strategy = ShortV1Strategy(strategy_config=config)
                    self._indicators_added = False

                def __call__(self, df, i, params):
                    if not self._indicators_added:
                        df = self.strategy.add_indicators(df)
                        self._indicators_added = True
                    signal = self.strategy.generate_signal(df, i)
                    if signal:
                        action = signal.get('action', 'hold')
                        # Map short actions to backtester actions
                        if action == 'open_short':
                            return {'action': 'sell', 'fraction': signal.get('fraction', 1.0)}
                        elif action in ('close_short', 'partial_close'):
                            return {'action': 'buy', 'fraction': signal.get('fraction', 1.0)}
                    return {'action': 'hold', 'fraction': 0}

            config = job.config
            strategy_id = config.get('strategy', 'v35_long')
            start_date = config.get('start_date', '2024-01-01')
            end_date = config.get('end_date', '2024-12-31')
            initial_capital = config.get('initial_capital', 10000000)

            # SECURITY: Re-validate strategy_id in worker thread to prevent path traversal
            strategies = get_available_strategies()
            valid_ids = [s['id'] for s in strategies]
            if strategy_id not in valid_ids:
                raise ValueError(f"Invalid strategy: {strategy_id}")

            strategy_info = next((s for s in strategies if s['id'] == strategy_id), None)

            # Check cancellation
            if job._cancelled:
                return

            job.progress = 10

            # Determine exchange from strategy
            exchange = strategy_info['exchange'] if strategy_info else 'binance'

            # Create strategy adapter based on strategy_id
            # Load optimized configs where available
            import json
            from pathlib import Path
            config_dir = Path('config/strategies')

            if strategy_id == 'v35_long':
                # Load optimized v35 config
                v35_config = None
                config_path = config_dir / 'v35_long.json'
                if config_path.exists():
                    with open(config_path) as f:
                        raw = json.load(f)
                    # Flatten nested config structure
                    v35_config = {}
                    v35_config.update(raw.get('market_classifier', {}))
                    v35_config.update(raw.get('entry_conditions', {}))
                    v35_config.update(raw.get('exit_conditions', {}))
                    v35_config.update(raw.get('position_sizing', {}))
                    v35_config.update(raw.get('sideways_strategies', {}))
                strategy_func = V35StrategyAdapter(config=v35_config)
                timeframe = 'day'
            elif strategy_id == 'short_v1':
                strategy_func = ShortV1StrategyAdapter()
                timeframe = 'minute240'
            else:
                raise ValueError(f"Unknown strategy adapter for: {strategy_id}")

            if job._cancelled:
                return

            job.progress = 20

            # Load data
            with DataLoader(exchange=exchange) as loader:
                df = loader.load_timeframe(timeframe, start_date, end_date)

            if df.empty:
                raise ValueError(f"No data available for {start_date} to {end_date}")

            job.progress = 30

            # Initialize backtester with fee and slippage
            backtester = Backtester(
                initial_capital=initial_capital,
                fee_rate=0.0005,   # 0.05%
                slippage=0.0002    # 0.02%
            )

            if job._cancelled:
                return

            job.progress = 40

            # Run backtest
            results = backtester.run(df, strategy_func, {})

            if job._cancelled:
                return

            job.progress = 90

            # Convert equity_curve DataFrame to list for JSON serialization
            equity_curve = results.get('equity_curve')
            equity_curve_list = []
            max_drawdown_pct = 0
            sharpe_ratio = 0

            if equity_curve is not None and not equity_curve.empty:
                import numpy as np

                # Convert DataFrame to list with frontend-expected field names
                for _, row in equity_curve.iterrows():
                    ts = row.get('timestamp')
                    date_str = str(ts)[:10] if ts else ''
                    equity_curve_list.append({
                        'date': date_str,
                        'equity': row.get('total_equity', 0)
                    })

                # Calculate max drawdown
                eq = equity_curve['total_equity']
                peak = eq.cummax()
                dd = (eq - peak) / peak
                max_drawdown_pct = float(dd.min() * 100) if not dd.empty else 0

                # Calculate Sharpe ratio (annualized)
                rets = eq.pct_change().dropna()
                if len(rets) > 5 and rets.std() != 0:
                    sharpe_ratio = float((rets.mean() / rets.std()) * np.sqrt(252))

            # Convert Trade objects to dicts with frontend-expected field names
            trades_raw = results.get('trades', [])
            trades_list = []
            for t in trades_raw[:100]:  # Limit trades for response size
                if hasattr(t, 'exit_time') and t.exit_time:
                    # Closed trade - show as SELL with profit
                    trade_dict = {
                        'timestamp': str(t.exit_time) if t.exit_time else None,
                        'action': 'SELL',
                        'price': t.exit_price,
                        'profit': round(t.profit_loss, 0) if t.profit_loss else 0,
                    }
                    trades_list.append(trade_dict)
                elif hasattr(t, 'entry_time'):
                    # Entry trade
                    trade_dict = {
                        'timestamp': str(t.entry_time) if t.entry_time else None,
                        'action': 'BUY',
                        'price': t.entry_price,
                        'profit': None,
                    }
                    trades_list.append(trade_dict)
                elif isinstance(t, dict):
                    # Already a dict, transform field names
                    trade_dict = {
                        'timestamp': t.get('exit_time') or t.get('entry_time') or t.get('timestamp'),
                        'action': 'SELL' if t.get('exit_time') else 'BUY',
                        'price': t.get('exit_price') or t.get('entry_price') or t.get('price'),
                        'profit': round(t.get('profit_loss', 0) or t.get('pnl', 0) or 0, 0) if t.get('exit_time') else None,
                    }
                    trades_list.append(trade_dict)

            total_return_pct = results.get('total_return', 0)

            # Format results with rounded numbers
            job.result = {
                'strategy': strategy_id,
                'start_date': start_date,
                'end_date': end_date,
                'initial_capital': initial_capital,
                'final_capital': round(results.get('final_capital', initial_capital), 0),
                'total_return': round(results.get('final_capital', initial_capital) - initial_capital, 0),
                'total_return_pct': round(total_return_pct, 2),
                'total_trades': results.get('total_trades', 0),
                'winning_trades': results.get('winning_trades', 0),
                'losing_trades': results.get('losing_trades', 0),
                'win_rate': round(results.get('win_rate', 0) * 100, 2),
                'profit_factor': round(results.get('profit_factor', 0), 2),
                'max_drawdown': round(max_drawdown_pct, 2),
                'max_drawdown_pct': round(max_drawdown_pct, 2),
                'sharpe_ratio': round(sharpe_ratio, 2),
                'equity_curve': equity_curve_list,
                'trades': trades_list
            }

            job.status = 'completed'
            job.progress = 100
            job.completed_at = datetime.now().isoformat()

        except Exception as e:
            job.status = 'failed'
            job.error = str(e)
            job.completed_at = datetime.now().isoformat()
            traceback.print_exc()

    job._thread = threading.Thread(target=_run, daemon=True)
    job._thread.start()


def get_running_job_count() -> int:
    """Count currently running jobs."""
    with _jobs_lock:
        return sum(1 for job in _backtest_jobs.values() if job.status in ('pending', 'running'))


def start_backtest(config: dict) -> BacktestJob:
    """Create and start a backtest job."""
    # Rate limiting: check concurrent job count
    if get_running_job_count() >= MAX_CONCURRENT_JOBS:
        raise RuntimeError(f"Too many concurrent jobs. Maximum is {MAX_CONCURRENT_JOBS}.")

    job = create_backtest_job(config)
    run_backtest(job)
    return job


def cleanup_old_jobs(max_age_hours: int = 24) -> int:
    """Remove jobs older than max_age_hours."""
    from datetime import timedelta

    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    removed = 0

    with _jobs_lock:
        to_remove = []
        for job_id, job in _backtest_jobs.items():
            created = datetime.fromisoformat(job.created_at)
            if created < cutoff and job.status in ('completed', 'failed', 'cancelled'):
                to_remove.append(job_id)

        for job_id in to_remove:
            del _backtest_jobs[job_id]
            removed += 1

    return removed
