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
    """Get list of available strategies for backtesting."""
    return [
        {
            'id': 'v35_long',
            'name': 'V35 Long (Binance)',
            'description': 'Momentum-based long strategy for bull markets',
            'exchange': 'binance',
            'default_params': {}
        },
        {
            'id': 'sideways_v2',
            'name': 'Sideways V2 (Binance)',
            'description': 'Mean-reversion strategy for sideways markets',
            'exchange': 'binance',
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
            'id': 'short_v1_baseline',
            'name': 'Short V1 Baseline (Binance)',
            'description': 'Simple short strategy with fixed SL/TP',
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

            config = job.config
            strategy_id = config.get('strategy', 'v35_long')
            start_date = config.get('start_date', '2024-01-01')
            end_date = config.get('end_date', '2024-12-31')
            initial_capital = config.get('initial_capital', 10000000)

            # SECURITY: Validate strategy_id
            strategies = get_available_strategies()
            valid_ids = [s['id'] for s in strategies]
            if strategy_id not in valid_ids:
                raise ValueError(f"Invalid strategy: {strategy_id}")

            if job._cancelled:
                return

            job.progress = 10

            # Route to appropriate backtester
            if strategy_id in ('short_v1', 'short_v1_baseline'):
                results, price_data = _run_short_backtest(
                    strategy_id, start_date, end_date, initial_capital, job
                )
            else:
                results, price_data = _run_long_backtest(
                    strategy_id, start_date, end_date, initial_capital, job
                )

            if job._cancelled:
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

        except Exception as e:
            job.status = 'failed'
            job.error = str(e)
            job.completed_at = datetime.now().isoformat()
            traceback.print_exc()

    job._thread = threading.Thread(target=_run, daemon=True)
    job._thread.start()


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
        from trading.strategy.short_v1 import ShortV1Strategy

        class EnhancedShortStrategyAdapter:
            def __init__(self, config=None):
                self.strategy = ShortV1Strategy(strategy_config=config)
                self._indicators_added = False
                self._cached_df = None

            def execute(self, df, i):
                if i < 200:
                    return {'action': 'hold', 'reason': 'WARMUP'}
                if not self._indicators_added:
                    self._cached_df = self.strategy.add_indicators(df.copy())
                    self._indicators_added = True
                signal = self.strategy.generate_signal(self._cached_df, i)
                if signal is None:
                    return {'action': 'hold', 'reason': 'NO_SIGNAL'}
                action = signal.get('action', 'hold')
                if action == 'open_short':
                    return {'action': 'open_short', 'fraction': signal.get('fraction', 0.3), 'reason': signal.get('reason', '')}
                elif action == 'close_short':
                    return {'action': 'close_short', 'fraction': signal.get('fraction', 1.0), 'reason': signal.get('reason', '')}
                elif action == 'partial_close':
                    return {'action': 'partial_close', 'fraction': signal.get('fraction', 0.5), 'reason': signal.get('reason', '')}
                return {'action': 'hold', 'reason': 'NO_SIGNAL'}

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

    # Format trades for frontend
    trades_list = []
    for t in close_trades[:100]:
        trades_list.append({
            'timestamp': t.get('time'),
            'action': 'SELL' if t['type'] == 'close_short' else 'PARTIAL',
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


def _run_long_backtest(
    strategy_id: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    job: BacktestJob
) -> dict:
    """Run long strategy backtest using core/backtester.py (spot trading)."""
    import numpy as np
    from core.backtester import Backtester
    from core.data_loader import DataLoader
    from trading.strategy.v35_long import V35LongStrategy

    class V35StrategyAdapter:
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

    class SidewaysV2StrategyAdapter:
        """Mean-reversion strategy for sideways markets (48 < MFI < 52, ADX < 20)."""
        def __init__(self, config=None):
            self.config = config or {}
            self._indicators_added = False
            self.in_position = False
            self.entry_price = 0.0
            # Thresholds from sideways_v2_task.py
            self.mfi_bull = 52
            self.mfi_bear = 48
            self.adx_trend = 20
            self.rsi_oversold = 35
            self.rsi_mean = 50
            self.take_profit_pct = 1.5
            self.stop_loss_pct = 1.0

        def _add_indicators(self, df):
            """Add MFI, ADX, and RSI indicators."""
            # RSI
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss.replace(0, np.inf)
            df['rsi'] = 100 - (100 / (1 + rs))

            # MFI (Money Flow Index)
            typical_price = (df['high'] + df['low'] + df['close']) / 3
            raw_money_flow = typical_price * df['volume']
            pos_flow = raw_money_flow.where(typical_price > typical_price.shift(1), 0)
            neg_flow = raw_money_flow.where(typical_price < typical_price.shift(1), 0)
            pos_mf = pos_flow.rolling(window=14).sum()
            neg_mf = neg_flow.rolling(window=14).sum()
            mf_ratio = pos_mf / neg_mf.replace(0, np.inf)
            df['mfi'] = 100 - (100 / (1 + mf_ratio))

            # ADX
            tr = np.maximum(
                df['high'] - df['low'],
                np.maximum(
                    abs(df['high'] - df['close'].shift(1)),
                    abs(df['low'] - df['close'].shift(1))
                )
            )
            atr = tr.rolling(window=14).mean()
            plus_dm = df['high'].diff()
            minus_dm = -df['low'].diff()
            plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
            minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
            plus_di = 100 * (plus_dm.rolling(14).mean() / atr)
            minus_di = 100 * (minus_dm.rolling(14).mean() / atr)
            dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
            df['adx'] = dx.rolling(14).mean()

            return df

        def _is_sideways(self, mfi: float, adx: float) -> bool:
            """Check if market is in sideways regime."""
            return self.mfi_bear < mfi < self.mfi_bull and adx < self.adx_trend

        def __call__(self, df, i, params):
            if i < 100:
                return {'action': 'hold', 'fraction': 0}

            if not self._indicators_added:
                df = self._add_indicators(df)
                self._indicators_added = True

            row = df.iloc[i]
            mfi = row.get('mfi', 50)
            adx = row.get('adx', 25)
            rsi = row.get('rsi', 50)
            price = row['close']

            if self.in_position:
                # Check exit conditions
                pnl_pct = ((price - self.entry_price) / self.entry_price) * 100

                # Take profit
                if pnl_pct >= self.take_profit_pct:
                    self.in_position = False
                    return {'action': 'sell', 'fraction': 1.0}

                # Stop loss
                if pnl_pct <= -self.stop_loss_pct:
                    self.in_position = False
                    return {'action': 'sell', 'fraction': 1.0}

                # RSI mean reversion complete
                if rsi >= self.rsi_mean:
                    self.in_position = False
                    return {'action': 'sell', 'fraction': 1.0}

                return {'action': 'hold', 'fraction': 0}

            # Entry: sideways regime + oversold RSI
            if self._is_sideways(mfi, adx) and rsi <= self.rsi_oversold:
                self.in_position = True
                self.entry_price = price
                return {'action': 'buy', 'fraction': 1.0}

            return {'action': 'hold', 'fraction': 0}

    job.progress = 20

    # Load data
    with DataLoader(exchange='binance') as loader:
        df = loader.load_timeframe('day', start_date, end_date)

    if df.empty:
        raise ValueError(f"No data available for {start_date} to {end_date}")

    job.progress = 30

    # Select strategy adapter based on strategy_id
    import json
    if strategy_id == 'sideways_v2':
        strategy_func = SidewaysV2StrategyAdapter()
    else:
        # Load config if available for v35_long
        config_path = Path('config/strategies/v35_long.json')
        v35_config = None
        if config_path.exists():
            with open(config_path) as f:
                raw = json.load(f)
            v35_config = {}
            v35_config.update(raw.get('market_classifier', {}))
            v35_config.update(raw.get('entry_conditions', {}))
            v35_config.update(raw.get('exit_conditions', {}))
            v35_config.update(raw.get('position_sizing', {}))
        strategy_func = V35StrategyAdapter(config=v35_config)

    job.progress = 40

    # Run backtest
    backtester = Backtester(
        initial_capital=initial_capital,
        fee_rate=0.0005,
        slippage=0.0002
    )
    results = backtester.run(df, strategy_func, {})

    job.progress = 80

    # Process results
    equity_curve = results.get('equity_curve')
    equity_curve_list = []
    max_drawdown_pct = 0
    sharpe_ratio = 0

    if equity_curve is not None and not equity_curve.empty:
        for _, row in equity_curve.iterrows():
            ts = row.get('timestamp')
            date_str = str(ts)[:10] if ts else ''
            equity_curve_list.append({'date': date_str, 'equity': row.get('total_equity', 0)})

        eq = equity_curve['total_equity']
        peak = eq.cummax()
        dd = (eq - peak) / peak
        max_drawdown_pct = float(dd.min() * 100) if not dd.empty else 0

        rets = eq.pct_change().dropna()
        if len(rets) > 5 and rets.std() != 0:
            sharpe_ratio = float((rets.mean() / rets.std()) * np.sqrt(252))

    # Format trades
    trades_raw = results.get('trades', [])
    trades_list = []
    for t in trades_raw[:100]:
        if hasattr(t, 'exit_time') and t.exit_time:
            trades_list.append({
                'timestamp': str(t.exit_time),
                'action': 'SELL',
                'price': t.exit_price,
                'profit': round(t.profit_loss, 0) if t.profit_loss else 0,
            })

    result_dict = {
        'strategy': strategy_id,
        'start_date': start_date,
        'end_date': end_date,
        'initial_capital': initial_capital,
        'final_capital': round(results.get('final_capital', initial_capital), 0),
        'total_return': round(results.get('final_capital', initial_capital) - initial_capital, 0),
        'total_return_pct': round(results.get('total_return', 0), 2),
        'leverage': 1,
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
    return result_dict, df


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
