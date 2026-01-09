"""
Backtest runner service for executing backtests via web dashboard.
"""

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
    # These match the strategies defined in the trading system
    return [
        {
            'id': 'v35_long',
            'name': 'V35 Long (Upbit)',
            'description': 'Momentum-based long strategy for bull markets',
            'exchange': 'upbit',
            'default_params': {}
        },
        {
            'id': 'sideways_v2',
            'name': 'Sideways V2 (Upbit)',
            'description': 'Range-bound trading strategy for sideways markets',
            'exchange': 'upbit',
            'default_params': {}
        },
        {
            'id': 'short_v1',
            'name': 'Short V1 (Binance)',
            'description': 'Futures short strategy for bear markets',
            'exchange': 'binance',
            'default_params': {}
        },
        {
            'id': 'h4_conservative',
            'name': 'H4 Conservative',
            'description': '4-hour timeframe conservative strategy',
            'exchange': 'upbit',
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

            # Load strategy config (safe: strategy_id validated above)
            strategy_config_path = f'config/strategies/{strategy_id}.json'

            # Determine exchange from strategy
            exchange = strategy_info['exchange'] if strategy_info else 'upbit'

            # Initialize backtester
            backtester = Backtester(
                strategy_name=strategy_id,
                config_path=strategy_config_path
            )

            if job._cancelled:
                return

            job.progress = 30

            # Run backtest
            results = backtester.run(
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital
            )

            if job._cancelled:
                return

            job.progress = 90

            # Format results
            job.result = {
                'strategy': strategy_id,
                'start_date': start_date,
                'end_date': end_date,
                'initial_capital': initial_capital,
                'final_capital': results.get('final_capital', initial_capital),
                'total_return': results.get('total_return', 0),
                'total_return_pct': results.get('total_return_pct', 0),
                'total_trades': results.get('total_trades', 0),
                'winning_trades': results.get('winning_trades', 0),
                'losing_trades': results.get('losing_trades', 0),
                'win_rate': results.get('win_rate', 0),
                'profit_factor': results.get('profit_factor', 0),
                'max_drawdown': results.get('max_drawdown', 0),
                'max_drawdown_pct': results.get('max_drawdown_pct', 0),
                'sharpe_ratio': results.get('sharpe_ratio', 0),
                'equity_curve': results.get('equity_curve', []),
                'trades': results.get('trades', [])[:100]  # Limit trades for response size
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
