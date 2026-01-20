"""
Backtest runner service for executing backtests via web dashboard.

Uses the same backtest logic as scripts/backtest_short.py for consistency.
Integrates with MLflow visualization for chart generation and experiment tracking.
"""

import sys
from pathlib import Path
import logging

# Add project root to path for imports (core, scripts, etc.)
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import threading
import uuid
from datetime import datetime
from typing import Optional
import traceback
import pandas as pd

# MLflow visualization imports
from core.backtest_visualizer import BacktestVisualizer
from core.mlflow_tracker import MLflowTracker
from core.metrics import calculate_benchmark

# Database persistence
from web.services import backtest_db
from trading.strategies.components.strategy_factory import StrategyFactory, STRATEGY_REGISTRY
from core.component_adapter import ComponentStrategyAdapter
from trading.indicators import add_all_indicators

logger = logging.getLogger(__name__)

# Job storage (in-memory for now)
_backtest_jobs: dict = {}
_jobs_lock = threading.Lock()

# Rate limiting
MAX_CONCURRENT_JOBS = 3

# Chart output directory
CHART_OUTPUT_DIR = PROJECT_ROOT / "web" / "static" / "charts"
CHART_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Initialize visualization components
_visualizer = BacktestVisualizer()
_mlflow_tracker = MLflowTracker()


def _generate_visualization(
    results: dict,
    price_data: pd.DataFrame,
    strategy_id: str,
    job_id: str
) -> dict:
    """Generate benchmark chart and log to MLflow.

    Args:
        results: Backtest results dict
        price_data: Original price DataFrame for benchmark calculation
        strategy_id: Strategy identifier
        job_id: Job ID for unique chart filename

    Returns:
        Updated results dict with chart_path, benchmark_curve, and mlflow_run_id
    """
    try:
        initial_capital = results.get('initial_capital', 10000000)

        # Calculate benchmark (buy-and-hold)
        if not price_data.empty and 'close' in price_data.columns:
            # Ensure timestamp column exists
            if 'timestamp' not in price_data.columns:
                price_data = price_data.copy()
                price_data['timestamp'] = price_data.index

            benchmark_curve, benchmark_return_pct = calculate_benchmark(
                price_data, initial_capital
            )
            results['benchmark_return_pct'] = round(benchmark_return_pct, 2)

            # Convert benchmark to list format for frontend
            if benchmark_curve is not None and len(benchmark_curve) > 0:
                benchmark_list = []
                for ts, equity in benchmark_curve.items():
                    benchmark_list.append({
                        'date': str(ts)[:10],
                        'equity': equity
                    })
                results['benchmark_curve'] = benchmark_list

        # Create equity curve DataFrame for visualization
        equity_data = results.get('equity_curve', [])
        if equity_data:
            equity_df = pd.DataFrame(equity_data)
            equity_df['timestamp'] = pd.to_datetime(equity_df['date'])
            equity_df['total_equity'] = equity_df['equity']

            # Generate chart
            chart_filename = f"backtest_{strategy_id}_{job_id}.png"
            chart_path = CHART_OUTPUT_DIR / chart_filename

            # Build chart data structure for visualizer
            chart_result = {
                'equity_curve': equity_df,
                'benchmark_curve': benchmark_curve if 'benchmark_curve' in dir() else None,
                'strategy_name': strategy_id,
                'symbol': 'BTC',
                'total_return': results.get('total_return_pct', 0),
                'benchmark_return_pct': results.get('benchmark_return_pct', 0)
            }

            saved_path = _visualizer.create_chart(
                chart_result,
                output_path=str(chart_path),
                title=f"{strategy_id} Backtest"
            )

            if saved_path:
                # Store relative path for web serving
                results['chart_path'] = f"/static/charts/{chart_filename}"
                logger.info(f"Generated chart: {saved_path}")

        # Log to MLflow
        mlflow_result = {
            'strategy_name': strategy_id,
            'symbol': 'BTC',
            'total_return': results.get('total_return_pct', 0),
            'sharpe_ratio': results.get('sharpe_ratio', 0),
            'max_drawdown_pct': results.get('max_drawdown_pct', 0),
            'win_rate': results.get('win_rate', 0),
            'total_trades': results.get('total_trades', 0),
            'profit_factor': results.get('profit_factor', 0),
            'benchmark_return_pct': results.get('benchmark_return_pct', 0),
            'params': {
                'start_date': results.get('start_date'),
                'end_date': results.get('end_date'),
                'initial_capital': initial_capital,
                'leverage': results.get('leverage', 1)
            }
        }

        chart_artifact = str(chart_path) if results.get('chart_path') else None
        run_id = _mlflow_tracker.log_run(mlflow_result, chart_path=chart_artifact)

        if run_id:
            results['mlflow_run_id'] = run_id
            results['mlflow_url'] = _mlflow_tracker.get_run_url(run_id)
            logger.info(f"Logged to MLflow: run_id={run_id}")

    except Exception as e:
        logger.warning(f"Visualization/MLflow logging failed: {e}")
        traceback.print_exc()

    return results


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
    """Get list of available strategies dynamically from StrategyFactory."""
    strategies = []

    # 1. Get strategies from Factory Registry
    try:
        factory_strategies = STRATEGY_REGISTRY.keys()

        for name in factory_strategies:
            spec = STRATEGY_REGISTRY[name]
            strategies.append({
                'id': name,
                'name': name.replace('_', ' ').title(),
                'description': f"{spec.market.title()} strategy ({name})",
                'exchange': 'binance',  # System is Binance-only since PR #21
                'default_params': {}
            })
    except Exception as e:
        print(f"Error loading factory strategies: {e}")
        # Fallback if registry fails

    # 2. Add legacy hardcoded/baseline strategies if needed
    # Keeping short_v1_baseline for backward compatibility if it's not in factory
    existing_ids = [s['id'] for s in strategies]

    if 'short_v1_baseline' not in existing_ids:
        strategies.append({
            'id': 'short_v1_baseline',
            'name': 'Short V1 Baseline (Binance)',
            'description': 'Simple short strategy with fixed SL/TP',
            'exchange': 'binance',
            'default_params': {}
        })

    return strategies


def create_backtest_job(config: dict) -> BacktestJob:
    """Create a new backtest job."""
    job_id = str(uuid.uuid4())[:8]
    job = BacktestJob(job_id, config)

    with _jobs_lock:
        _backtest_jobs[job_id] = job

    # Save to database
    backtest_db.save_backtest(
        job_id=job_id,
        config=config,
        status='pending',
        created_at=job.created_at
    )

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

            # Persist cancellation so history is accurate even if polling stops.
            try:
                backtest_db.save_backtest(
                    job_id=job.job_id,
                    config=job.config,
                    status='cancelled',
                    created_at=job.created_at,
                    completed_at=job.completed_at,
                    result=None,
                    error=None,
                )
            except Exception:
                traceback.print_exc()
            return True
    return False


def run_backtest(job: BacktestJob) -> None:
    """Run the backtest in a background thread."""
    def _run():
        try:
            job.status = 'running'
            job.started_at = datetime.now().isoformat()
            job.progress = 0

            config = job.config
            strategy_id = config.get('strategy', 'v35_long')
            start_date = config.get('start_date', '2024-01-01')
            end_date = config.get('end_date', '2024-12-31')
            initial_capital = config.get('initial_capital', 10000)

            # SECURITY: Validate strategy_id
            strategies = get_available_strategies()
            valid_ids = [s['id'] for s in strategies]
            if strategy_id not in valid_ids:
                raise ValueError(f"Invalid strategy: {strategy_id}")

            if job._cancelled:
                job.status = 'cancelled'
                job.completed_at = datetime.now().isoformat()
                backtest_db.save_backtest(
                    job_id=job.job_id,
                    config=job.config,
                    status='cancelled',
                    created_at=job.created_at,
                    completed_at=job.completed_at,
                    result=None,
                    error=None,
                )
                return

            job.progress = 10

            # Route to appropriate backtester
            # 1. Use Generic Backtester for all Factory Strategies
            if strategy_id in STRATEGY_REGISTRY:
                results, price_data = _run_generic_backtest(
                    strategy_id, start_date, end_date, initial_capital, job
                )
            # 2. Use specific legacy backtester for baseline (unregistered) strategies
            elif strategy_id in ('short_v1_baseline',):
                results, price_data = _run_short_backtest(
                    strategy_id, start_date, end_date, initial_capital, job
                )
            else:
                raise ValueError(
                    f"No backtest runner available for strategy '{strategy_id}'. "
                    "This is unexpected because strategy_id was validated earlier."
                )

            if job._cancelled:
                job.status = 'cancelled'
                job.completed_at = datetime.now().isoformat()
                backtest_db.save_backtest(
                    job_id=job.job_id,
                    config=job.config,
                    status='cancelled',
                    created_at=job.created_at,
                    completed_at=job.completed_at,
                    result=None,
                    error=None,
                )
                return

            job.progress = 90

            # Generate visualization and log to MLflow
            results = _generate_visualization(
                results, price_data, strategy_id, job.job_id
            )

            job.result = results
            job.status = 'completed'
            job.progress = 100
            job.completed_at = datetime.now().isoformat()

            # Save to database
            backtest_db.save_backtest(
                job_id=job.job_id,
                config=job.config,
                status='completed',
                created_at=job.created_at,
                completed_at=job.completed_at,
                result=results
            )

        except Exception as e:
            job.status = 'failed'
            job.error = str(e)
            job.completed_at = datetime.now().isoformat()
            traceback.print_exc()

            # Save to database
            backtest_db.save_backtest(
                job_id=job.job_id,
                config=job.config,
                status='failed',
                created_at=job.created_at,
                completed_at=job.completed_at,
                error=str(e)
            )

    job._thread = threading.Thread(target=_run, daemon=True)
    job._thread.start()


def _run_generic_backtest(
    strategy_id: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    job: BacktestJob
) -> dict:
    """
    Run any strategy using ComponentStrategyAdapter and generic loop.
    Supports both Spot (Long-only) and Futures (Long/Short).
    """
    import numpy as np
    from typing import Dict, List
    from core.data_loader import DataLoader

    # Check if strategy exists in registry
    if strategy_id not in STRATEGY_REGISTRY:
        raise ValueError(f"Strategy {strategy_id} not found in StrategyFactory Registry")

    # 1. Initialize Factory and Adapter
    factory = StrategyFactory(redis=None)

    # Get market type (spot/futures)
    spec = STRATEGY_REGISTRY[strategy_id]
    market_type = spec.market

    # Config parameters
    config = {}

    # Create Adapter
    adapter = ComponentStrategyAdapter(factory, strategy_id, config)

    # 2. Set environment based on Market
    # Note: System is Binance-only since PR #21
    exchange_name = "binance"

    if market_type == 'futures':
        leverage = 3.0
        fee_rate = 0.0004  # 0.04%
        slippage = 0.0002  # 0.02%
        timeframe = spec.timeframe
    else:
        # Spot
        leverage = 1.0
        fee_rate = 0.0005  # 0.05%
        slippage = 0.0000
        timeframe = spec.timeframe

    with DataLoader(exchange=exchange_name) as loader:
        df = loader.load_timeframe(timeframe, start_date, end_date)

    if df.empty:
        raise ValueError(f"No data available for {start_date} to {end_date}")

    job.progress = 20

    # 4. Pre-calculate indicators (optimization)
    # Adapter calculates indicators internally usually?
    # ComponentStrategyAdapter.check_entry calls market_data construction which expects indicators in row
    # So yes, we must add indicators to DF first.
    add_all_indicators(df)
    job.progress = 30

    # 5. Backtest Loop
    capital = initial_capital
    position_size = 0.0
    entry_price = 0.0
    trades: List[Dict] = []
    equity_curve: List[float] = []

    adapter.symbol = "BTC"

    for i in range(len(df)):
        if job._cancelled:
            return {}

        # Execute Strategy Logic via Adapter
        signal = adapter(df, i)
        row = df.iloc[i]

        action = signal.get('action', 'hold')
        reason = signal.get('reason', '')
        timestamp = str(row.get('timestamp', row.name))

        # --- Current Value Calculation ---
        current_equity = capital
        if position_size > 0:
            current_price = row['close']
            if adapter.current_position and adapter.current_position.side == 'short':
                # Short PnL
                pnl_ratio = (entry_price - current_price) / entry_price
                unrealized_pnl = position_size * pnl_ratio
                current_equity += (position_size / leverage) + unrealized_pnl
            else:
                # Long PnL
                pnl_ratio = (current_price - entry_price) / entry_price
                unrealized_pnl = position_size * pnl_ratio
                current_equity += (position_size / leverage) + unrealized_pnl

        equity_curve.append({'date': timestamp[:10], 'equity': current_equity})

        # --- Execution Logic ---

        # OPEN LONG
        if action == 'buy' and position_size == 0:
            fraction = signal.get('fraction', 1.0)
            margin = capital * fraction
            effective_pos_size = margin * leverage
            fee = effective_pos_size * fee_rate

            if capital >= (margin + fee):
                capital -= (margin + fee)
                position_size = effective_pos_size
                entry_price = row['close'] * (1 + slippage)
                trades.append({
                    'type': 'buy',
                    'time': timestamp,
                    'price': entry_price,
                    'size': position_size,
                    'reason': reason
                })

        # OPEN SHORT
        elif action == 'open_short' and position_size == 0:
            fraction = signal.get('fraction', 0.3)
            margin = capital * fraction
            effective_pos_size = margin * leverage
            fee = effective_pos_size * fee_rate

            if capital >= (margin + fee):
                capital -= (margin + fee)
                position_size = effective_pos_size
                entry_price = row['close'] * (1 - slippage)
                trades.append({
                    'type': 'open_short',
                    'time': timestamp,
                    'price': entry_price,
                    'size': position_size,
                    'reason': reason
                })

        # CLOSE LONG (SELL)
        elif action == 'sell' and position_size > 0:
            exit_price = row['close'] * (1 - slippage)
            pnl_ratio = (exit_price - entry_price) / entry_price
            pnl = position_size * pnl_ratio
            margin_return = position_size / leverage
            fee = position_size * fee_rate

            capital += margin_return + pnl - fee

            trades.append({
                'type': 'sell',
                'time': timestamp,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'size': position_size,
                'pnl': pnl,
                'pnl_pct': pnl_ratio * 100 * leverage,
                'reason': reason
            })
            position_size = 0.0
            entry_price = 0.0

        # CLOSE SHORT
        elif action == 'close_short' and position_size > 0:
             exit_price = row['close'] * (1 + slippage)
             pnl_ratio = (entry_price - exit_price) / entry_price
             pnl = position_size * pnl_ratio
             margin_return = position_size / leverage
             fee = position_size * fee_rate

             capital += margin_return + pnl - fee

             trades.append({
                'type': 'close_short',
                'time': timestamp,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'size': position_size,
                'pnl': pnl,
                'pnl_pct': pnl_ratio * 100 * leverage,
                'reason': reason
             })
             position_size = 0.0
             entry_price = 0.0

    job.progress = 80

    # Force close at end
    if position_size > 0:
        last_price = df.iloc[-1]['close']
        if adapter.current_position and adapter.current_position.side == 'short':
             pnl_ratio = (entry_price - last_price) / entry_price
        else:
             pnl_ratio = (last_price - entry_price) / entry_price
        pnl = position_size * pnl_ratio
        capital += (position_size / leverage) + pnl

    # --- Metrics ---
    final_capital = capital
    total_return_pct = (final_capital - initial_capital) / initial_capital * 100

    close_trades = [t for t in trades if t['type'] in ('sell', 'close_short', 'partial_close')]
    profits = [t['pnl'] for t in close_trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]

    win_rate = len(wins) / len(close_trades) * 100 if close_trades else 0
    profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 0

    # MDD
    equity_values = [e['equity'] for e in equity_curve]
    equity_series = pd.Series(equity_values)
    returns = equity_series.pct_change().dropna()
    sharpe_ratio = float(returns.mean() / returns.std() * np.sqrt(252)) if len(returns) > 0 and returns.std() > 0 else 0

    peak = equity_series.cummax()
    drawdown = (equity_series - peak) / peak * 100
    mdd = float(drawdown.min())

    # Format for Frontend
    trades_list = []
    for t in close_trades[:100]:
        action_label = 'COVER' if t['type'] == 'close_short' else 'SELL'
        entry_action = 'SHORT' if t['type'] == 'close_short' else 'BUY'
        trades_list.append({
            'timestamp': t.get('entry_time') or t.get('time'),  # Using exit time if entry_time missing
            'symbol': 'BTC',
            'action': entry_action,
            'price': t.get('entry_price'),
            'profit': None
        })
        trades_list.append({
            'timestamp': t.get('time'),
            'symbol': 'BTC',
            'action': action_label,
            'price': t.get('exit_price'),
            'profit': round(t.get('pnl', 0), 0)
        })

    return {
        'strategy': strategy_id,
        'preset': 'generic',
        'start_date': start_date,
        'end_date': end_date,
        'initial_capital': initial_capital,
        'final_capital': round(final_capital, 0),
        'total_return': round(final_capital - initial_capital, 0),
        'total_return_pct': round(total_return_pct, 2),
        'leverage': leverage,
        'total_trades': len(close_trades),
        'winning_trades': len(wins),
        'losing_trades': len(losses),
        'win_rate': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'max_drawdown': round(mdd, 2),
        'max_drawdown_pct': round(mdd, 2),
        'sharpe_ratio': round(sharpe_ratio, 2),
        'equity_curve': equity_curve,
        'trades': trades_list
    }, df


def _run_short_backtest(
    strategy_id: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    job: BacktestJob
) -> dict:
    """
    Run short strategy backtest using the same logic as scripts/backtest_short.py.
    This ensures dashboard and script produce identical results.
    """
    import numpy as np
    import pandas as pd
    from typing import Dict, List

    from core.data_loader import DataLoader

    # Determine preset based on strategy_id
    preset = 'baseline' if strategy_id == 'short_v1_baseline' else 'enhanced'
    leverage = 3
    timeframe = 'minute240'

    job.progress = 20

    # Load data
    with DataLoader(exchange='binance') as loader:
        df = loader.load_timeframe(timeframe, start_date, end_date)

    if df.empty:
        raise ValueError(f"No data available for {start_date} to {end_date}")

    job.progress = 30

    # Import strategy classes (same as script)
    if preset == 'enhanced':
        from trading.strategies.components.strategy_factory import StrategyFactory
        from core.component_adapter import ComponentStrategyAdapter
        from trading.indicators import add_all_indicators, technical as ta

        class EnhancedShortStrategyAdapter:
            def __init__(self, config=None):
                self.config = config or {}
                self.factory = StrategyFactory(redis=None)
                self.adapter = ComponentStrategyAdapter(self.factory, "short_v1", self.config)
                self._indicators_added = False
                self._cached_df = None

            def execute(self, df, i):
                if i < 200:
                    return {'action': 'hold', 'reason': 'WARMUP'}

                if not self._indicators_added:
                    self._cached_df = df.copy()
                    add_all_indicators(self._cached_df)

                    close = self._cached_df['close']
                    high = self._cached_df['high']
                    low = self._cached_df['low']

                    ema_fast = self.config.get('ema_fast', 68)
                    ema_slow = self.config.get('ema_slow', 128)
                    self._cached_df[f'ema_{ema_fast}'] = ta.ema(close, period=ema_fast)
                    self._cached_df[f'ema_{ema_slow}'] = ta.ema(close, period=ema_slow)

                    adx_period = self.config.get('adx_period', 14)
                    if adx_period != 14:
                        self._cached_df['adx'], self._cached_df['plus_di'], self._cached_df['minus_di'] = ta.adx(high, low, close, period=adx_period)

                    self._cached_df['adx_slope'] = self._cached_df['adx'].diff()
                    self._indicators_added = True

                return self.adapter(self._cached_df, i)

        strategy = EnhancedShortStrategyAdapter()
    else:
        # Baseline strategy (simple fixed SL/TP)
        class BasicShortStrategy:
            def __init__(self, config=None):
                self.config = config or {
                    'ema_fast': 50, 'ema_slow': 200, 'adx_threshold': 25,
                    'stop_loss_pct': 2.0, 'take_profit_pct': 5.0, 'position_size': 0.3
                }
                self.in_position = False
                self.entry_price = 0.0
                self._cached_df = None

            def _add_indicators(self, df):
                df = df.copy()
                df['ema_fast'] = df['close'].ewm(span=self.config['ema_fast'], adjust=False).mean()
                df['ema_slow'] = df['close'].ewm(span=self.config['ema_slow'], adjust=False).mean()
                df['death_cross'] = (df['ema_fast'] < df['ema_slow']) & (df['ema_fast'].shift(1) >= df['ema_slow'].shift(1))
                df['golden_cross'] = (df['ema_fast'] > df['ema_slow']) & (df['ema_fast'].shift(1) <= df['ema_slow'].shift(1))
                df['tr'] = np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))
                df['atr'] = df['tr'].rolling(window=14).mean()
                plus_dm = df['high'].diff()
                minus_dm = -df['low'].diff()
                plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
                minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
                plus_di = 100 * (plus_dm.rolling(14).mean() / df['atr'])
                minus_di = 100 * (minus_dm.rolling(14).mean() / df['atr'])
                dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
                df['adx'] = dx.rolling(14).mean()
                df['plus_di'] = plus_di
                df['minus_di'] = minus_di
                return df

            def execute(self, df, i):
                if i < 200:
                    return {'action': 'hold', 'reason': 'WARMUP'}
                if self._cached_df is None or len(df) != len(self._cached_df):
                    self._cached_df = self._add_indicators(df)
                row = self._cached_df.iloc[i]
                if self.in_position:
                    pnl_pct = (self.entry_price - row['close']) / self.entry_price * 100
                    if pnl_pct <= -self.config['stop_loss_pct']:
                        self.in_position = False
                        return {'action': 'close_short', 'fraction': 1.0, 'reason': f'STOP_LOSS: {pnl_pct:+.2f}%'}
                    if pnl_pct >= self.config['take_profit_pct']:
                        self.in_position = False
                        return {'action': 'close_short', 'fraction': 1.0, 'reason': f'TAKE_PROFIT: {pnl_pct:+.2f}%'}
                    if row.get('golden_cross', False):
                        self.in_position = False
                        return {'action': 'close_short', 'fraction': 1.0, 'reason': f'GOLDEN_CROSS: {pnl_pct:+.2f}%'}
                    return {'action': 'hold', 'reason': 'IN_POSITION'}
                if row.get('death_cross', False):
                    adx = row.get('adx', 0)
                    plus_di = row.get('plus_di', 0)
                    minus_di = row.get('minus_di', 0)
                    if adx >= self.config['adx_threshold'] and minus_di > plus_di:
                        self.in_position = True
                        self.entry_price = row['close']
                        return {'action': 'open_short', 'fraction': self.config.get('position_size', 0.3), 'reason': f'DEATH_CROSS: ADX={adx:.1f}'}
                return {'action': 'hold', 'reason': 'NO_SIGNAL'}

        strategy = BasicShortStrategy()

    job.progress = 40

    # Run backtest using ShortBacktester logic (same as script)
    fee_rate = 0.0004
    slippage = 0.0002

    capital = initial_capital
    position_size = 0.0
    entry_price = 0.0
    initial_position_size = 0.0
    trades: List[Dict] = []
    equity_curve: List[float] = []

    for i in range(len(df)):
        if job._cancelled:
            return {}

        signal = strategy.execute(df, i)
        row = df.iloc[i]
        action = signal.get('action', 'hold')

        # Open Short
        if action == 'open_short' and position_size == 0:
            fraction = signal.get('fraction', 0.3)
            margin = capital * fraction
            position_size = margin * leverage
            initial_position_size = position_size
            entry_price = row['close'] * (1 - slippage)
            fee = position_size * fee_rate
            capital -= margin + fee
            trades.append({
                'type': 'open_short',
                'time': str(row.get('timestamp', row.name)),
                'price': entry_price,
                'size': position_size,
                'reason': signal.get('reason', '')
            })

        # Partial Close
        elif action == 'partial_close' and position_size > 0:
            close_fraction = signal.get('fraction', 0.5)
            close_size = initial_position_size * close_fraction
            exit_price = row['close'] * (1 + slippage)
            pnl_ratio = (entry_price - exit_price) / entry_price
            pnl = close_size * pnl_ratio
            fee = close_size * fee_rate
            margin_return = close_size / leverage
            capital += margin_return + pnl - fee
            position_size -= close_size
            trades.append({
                'type': 'partial_close',
                'time': str(row.get('timestamp', row.name)),
                'entry_price': entry_price,
                'exit_price': exit_price,
                'size': close_size,
                'pnl': pnl,
                'pnl_pct': pnl_ratio * 100 * leverage,
                'reason': signal.get('reason', '')
            })

        # Close Short
        elif action == 'close_short' and position_size > 0:
            exit_price = row['close'] * (1 + slippage)
            pnl_ratio = (entry_price - exit_price) / entry_price
            pnl = position_size * pnl_ratio
            fee = position_size * fee_rate
            margin_return = position_size / leverage
            capital += margin_return + pnl - fee
            trades.append({
                'type': 'close_short',
                'time': str(row.get('timestamp', row.name)),
                'entry_price': entry_price,
                'exit_price': exit_price,
                'size': position_size,
                'pnl': pnl,
                'pnl_pct': pnl_ratio * 100 * leverage,
                'reason': signal.get('reason', '')
            })
            position_size = 0.0
            entry_price = 0.0
            initial_position_size = 0.0

        # Equity calculation
        if position_size > 0:
            unrealized_pnl_ratio = (entry_price - row['close']) / entry_price
            unrealized_pnl = position_size * unrealized_pnl_ratio
            current_equity = capital + (position_size / leverage) + unrealized_pnl
        else:
            current_equity = capital

        equity_curve.append({'date': str(row.get('timestamp', row.name))[:10], 'equity': current_equity})

    job.progress = 80

    # Close remaining position
    if position_size > 0:
        last_price = df.iloc[-1]['close']
        pnl_ratio = (entry_price - last_price) / entry_price
        pnl = position_size * pnl_ratio
        capital += (position_size / leverage) + pnl

    # Calculate metrics
    final_capital = capital
    total_return_pct = (final_capital - initial_capital) / initial_capital * 100

    close_trades = [t for t in trades if t['type'] in ('close_short', 'partial_close')]
    profits = [t['pnl'] for t in close_trades] if close_trades else []
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]

    win_rate = len(wins) / len(close_trades) * 100 if close_trades else 0
    profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 0

    equity_values = [e['equity'] for e in equity_curve]
    equity_series = pd.Series(equity_values)
    returns = equity_series.pct_change().dropna()
    sharpe = float(returns.mean() / returns.std() * np.sqrt(252)) if len(returns) > 0 and returns.std() > 0 else 0

    peak = equity_series.cummax()
    drawdown = (equity_series - peak) / peak * 100
    mdd = float(drawdown.min())

    # Format trades for frontend - show both entry and exit
    trades_list = []
    for t in close_trades[:50]:  # Limit to 50 round-trips
        # Add entry
        if t.get('entry_price'):
            trades_list.append({
                'timestamp': t.get('entry_time', t.get('time')),
                'symbol': 'BTC',
                'action': 'SHORT',
                'price': t.get('entry_price', 0),
                'profit': None,
            })
        # Add exit
        trades_list.append({
            'timestamp': t.get('time'),
            'symbol': 'BTC',
            'action': 'COVER' if t['type'] == 'close_short' else 'PARTIAL',
            'price': t.get('exit_price', 0),
            'profit': round(t.get('pnl', 0), 0)
        })

    results = {
        'strategy': strategy_id,
        'preset': preset,
        'start_date': start_date,
        'end_date': end_date,
        'initial_capital': initial_capital,
        'final_capital': round(final_capital, 0),
        'total_return': round(final_capital - initial_capital, 0),
        'total_return_pct': round(total_return_pct, 2),
        'leverage': leverage,
        'total_trades': len(close_trades),
        'winning_trades': len(wins),
        'losing_trades': len(losses),
        'win_rate': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'max_drawdown': round(mdd, 2),
        'max_drawdown_pct': round(mdd, 2),
        'sharpe_ratio': round(sharpe, 2),
        'equity_curve': equity_curve,
        'trades': trades_list
    }
    return results, df





def get_running_job_count() -> int:
    """Count currently running jobs."""
    with _jobs_lock:
        return sum(1 for job in _backtest_jobs.values() if job.status in ('pending', 'running'))


def start_backtest(config: dict) -> BacktestJob:
    """Create and start a backtest job."""
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


def get_all_jobs(limit: int = 50) -> list:
    """Get all backtest jobs sorted by creation time (newest first).

    Merges in-memory running jobs with database history.
    In-memory jobs take precedence for active (pending/running) jobs.

    Returns:
        List of job dictionaries with summary info (excludes large data like trades/equity_curve).
    """
    jobs_by_id = {}

    # First, load history from database
    db_history = backtest_db.get_history(limit=limit)
    for db_job in db_history:
        jobs_by_id[db_job['job_id']] = db_job

    # Then, overlay in-memory jobs (for real-time progress on running jobs)
    with _jobs_lock:
        for job in _backtest_jobs.values():
            # Create summary without large data fields
            summary = {
                'job_id': job.job_id,
                'config': job.config,
                'status': job.status,
                'progress': job.progress,
                'created_at': job.created_at,
                'completed_at': job.completed_at,
                'error': job.error,
            }
            # Add key metrics from result if available
            if job.result:
                summary['metrics'] = {
                    'total_return_pct': job.result.get('total_return_pct', 0),
                    'win_rate': job.result.get('win_rate', 0),
                    'total_trades': job.result.get('total_trades', 0),
                    'sharpe_ratio': job.result.get('sharpe_ratio', 0),
                    'max_drawdown_pct': job.result.get('max_drawdown_pct', 0),
                }
            # In-memory jobs override DB entries (for real-time updates)
            jobs_by_id[job.job_id] = summary

    # Convert to list and sort by created_at descending (newest first)
    jobs = list(jobs_by_id.values())
    jobs.sort(key=lambda x: x['created_at'], reverse=True)
    return jobs
