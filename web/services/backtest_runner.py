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
from trading.config.constants import FeeRates, TimePeriods

logger = logging.getLogger(__name__)


def add_rf_predictions(df: pd.DataFrame, config: dict) -> None:
    """Pre-compute RF predictions for entire DataFrame (adds columns in-place).

    Scales the ENTIRE DataFrame once, then runs LSTM+RF predictions using slices.
    This avoids the O(n*window) scaling overhead of per-prediction scaling.

    Args:
        df: DataFrame with OHLCV and indicators.
        config: Strategy config with lstm_model_path, rf_model_path.
    """
    # Initialize columns with defaults
    df['rf_confidence'] = 0.0
    df['rf_direction'] = 'SIDEWAYS'
    df['rf_signal'] = 'HOLD'

    try:
        from trading.strategies.components.rf_probability_service import RFProbabilityService

        service = RFProbabilityService.get_instance(
            lstm_path=config.get('lstm_model_path', 'lstm_trainer/models/hybrid_lstm.pth'),
            rf_path=config.get('rf_model_path', 'lstm_trainer/models/noise_filter_rf.pkl'),
        )

        if not service.is_available():
            logger.warning("RF model not available, skipping predictions")
            return

        logger.info(f"Pre-computing RF predictions for {len(df):,} rows...")

        # === STEP 1: Scale entire DataFrame ONCE ===
        from lstm_trainer.src.live_scaler import LiveScaler

        feature_cols = getattr(service._predictor, "scaled_columns", None)
        scaler = LiveScaler(rolling_window=TimePeriods.RF_HISTORY_WINDOW, feature_columns=feature_cols) if feature_cols else LiveScaler(rolling_window=TimePeriods.RF_HISTORY_WINDOW)

        # Convert to history format
        col_map = {c: c.lower() for c in df.columns}
        df_norm = df.rename(columns=col_map)
        cols = ['open', 'high', 'low', 'close']
        available_cols = [c for c in cols if c in df_norm.columns]
        full_history = df_norm[available_cols].to_dict('records')
        if 'volume' in df_norm.columns:
            vol_values = df_norm['volume'].tolist()
            for idx, h in enumerate(full_history):
                h['volume'] = float(vol_values[idx])

        # Scale entire history once (this is the key optimization)
        logger.info("Scaling entire dataset...")
        full_scaled_df = scaler.prepare_sequence(full_history)
        if full_scaled_df is None:
            logger.warning("Failed to scale data")
            return
        logger.info(f"Scaled data shape: {full_scaled_df.shape}")

        # === STEP 2: Run predictions using slices of pre-scaled data ===
        min_history = TimePeriods.MIN_HISTORY_REQUIRED
        sample_interval = 6  # Predict every 6 candles

        last_result = {'confidence': 0.0, 'direction': 'SIDEWAYS', 'signal': 'HOLD'}
        processed = 0

        for i in range(min_history, len(df), sample_interval):
            try:
                # Slice from pre-scaled data (no re-scaling!)
                scaled_slice = full_scaled_df.iloc[max(0, i-60):i+1]

                if len(scaled_slice) < min_history:
                    continue

                row = df.iloc[i]
                close = float(row.get('close', 0))
                atr = float(row.get('atr', 0))
                volatility = atr / close if close > 0 else 0.0

                market_context = {
                    "mfi": float(row.get('mfi', 50.0)),
                    "adx": float(row.get('adx', 20.0)),
                    "volatility": volatility,
                    "regime": str(row.get('regime', 'SIDEWAYS_FLAT')),
                    "breakout_signal": int(row.get('breakout_signal', 0)),
                }

                result = service._predictor.predict(scaled_slice, market_context)
                last_result = {
                    'confidence': result.get('confidence', 0.0),
                    'direction': result.get('direction', 'SIDEWAYS'),
                    'signal': result.get('signal', 'HOLD'),
                }
                processed += 1

            except Exception as e:
                logger.debug(f"RF prediction failed at {i}: {e}")

            # Fill this sample and gap with result
            end_idx = min(i + sample_interval, len(df))
            df.loc[df.index[i:end_idx], 'rf_confidence'] = last_result['confidence']
            df.loc[df.index[i:end_idx], 'rf_direction'] = last_result['direction']
            df.loc[df.index[i:end_idx], 'rf_signal'] = last_result['signal']

        logger.info(f"RF predictions complete: {processed} inferences for {len(df):,} rows")

    except ImportError as e:
        logger.warning(f"RF dependencies not available: {e}")
    except Exception as e:
        logger.error(f"RF prediction failed: {e}")

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


def _is_tuned_strategy(strategy_id: str) -> bool:
    """Check if a strategy is a tuned strategy from allocation.json with regime_routing."""
    import json
    allocation_path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
    if not allocation_path.exists():
        return False
    try:
        with open(allocation_path, 'r') as f:
            allocation = json.load(f)
        strategy_config = allocation.get('strategies', {}).get(strategy_id, {})
        return 'regime_routing' in strategy_config
    except Exception:
        return False


def _has_base_strategy(strategy_id: str) -> bool:
    """Check if a strategy in allocation.json has a valid base strategy in registry."""
    import json
    allocation_path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
    if not allocation_path.exists():
        return False
    try:
        with open(allocation_path, 'r') as f:
            allocation = json.load(f)
        if strategy_id not in allocation.get('strategies', {}):
            return False
        strategy_config = allocation['strategies'][strategy_id]
        # Check explicit base_strategy field
        base_strategy = strategy_config.get('base_strategy')
        if base_strategy and base_strategy in STRATEGY_REGISTRY:
            return True
        # Try to infer base strategy from name prefix
        for reg_name in STRATEGY_REGISTRY.keys():
            if strategy_id.startswith(reg_name) and strategy_id != reg_name:
                return True
        return False
    except Exception:
        return False


def _generate_visualization(
    results: dict,
    price_data: pd.DataFrame,
    strategy_id: str,
    job_id: str
) -> dict:
    """Generate benchmark chart, regime chart, and log to MLflow.

    Args:
        results: Backtest results dict
        price_data: Original price DataFrame for benchmark calculation
        strategy_id: Strategy identifier
        job_id: Job ID for unique chart filename

    Returns:
        Updated results dict with chart_path, regime_chart_path, benchmark_curve, and mlflow_run_id
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

            # Generate equity chart
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

        # Generate regime chart (mplfinance-based with indicators)
        if not price_data.empty and 'close' in price_data.columns:
            try:
                regime_filename = f"regime_{strategy_id}_{job_id}.png"
                regime_path = CHART_OUTPUT_DIR / regime_filename

                # Convert trades to marker format for regime chart
                trades_for_chart = []
                raw_trades = results.get('trades', [])
                for t in raw_trades:
                    action = t.get('action', '').upper()
                    if action in ('BUY', 'LONG', 'ENTRY'):
                        trades_for_chart.append({
                            'timestamp': t.get('timestamp'),
                            'action': 'buy',
                            'price': t.get('price')
                        })
                    elif action in ('SELL', 'SHORT', 'EXIT', 'COVER'):
                        trades_for_chart.append({
                            'timestamp': t.get('timestamp'),
                            'action': 'sell',
                            'price': t.get('price')
                        })

                saved_regime_path = _visualizer.create_regime_chart(
                    price_data,
                    trades=trades_for_chart if trades_for_chart else None,
                    equity_curve=results.get('equity_curve'),
                    output_path=str(regime_path),
                    title=f"{strategy_id} Regime Analysis"
                )

                if saved_regime_path:
                    results['regime_chart_path'] = f"/static/charts/{regime_filename}"
                    logger.info(f"Generated regime chart: {saved_regime_path}")

                # Generate yearly charts for multi-year backtests (better trade visibility)
                if 'timestamp' in price_data.columns:
                    years = price_data['timestamp'].dt.year.nunique()
                elif isinstance(price_data.index, pd.DatetimeIndex):
                    years = price_data.index.year.nunique()
                else:
                    years = 1

                if years >= 2:
                    yearly_dir = CHART_OUTPUT_DIR / f"yearly_{strategy_id}_{job_id}"
                    yearly_paths = _visualizer.create_yearly_regime_charts(
                        price_data,
                        trades=trades_for_chart,
                        equity_curve=results.get('equity_curve'),
                        output_dir=str(yearly_dir),
                        title_prefix=f"{strategy_id}"
                    )
                    if yearly_paths:
                        results['yearly_chart_paths'] = [
                            f"/static/charts/yearly_{strategy_id}_{job_id}/{Path(p).name}"
                            for p in yearly_paths
                        ]
                        logger.info(f"Generated {len(yearly_paths)} yearly charts")
            except Exception as e:
                logger.warning(f"Regime chart generation failed: {e}")

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
    """Get list of available strategies dynamically from StrategyFactory and allocation.json."""
    import json

    strategies = []
    existing_ids = set()

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
            existing_ids.add(name)
    except Exception as e:
        print(f"Error loading factory strategies: {e}")
        # Fallback if registry fails

    # 2. Get tuned strategies from allocation.json
    try:
        allocation_path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
        if allocation_path.exists():
            with open(allocation_path, 'r') as f:
                allocation = json.load(f)

            for name, config in allocation.get('strategies', {}).items():
                if name not in existing_ids:
                    # This is a tuned/custom strategy not in registry
                    is_tuned = 'tuned_config' in config or 'regime_routing' in config
                    strategies.append({
                        'id': name,
                        'name': name.replace('_', ' ').title(),
                        'description': f"{'Tuned' if is_tuned else 'Custom'} {config.get('market', 'futures').title()} strategy",
                        'exchange': 'binance',
                        'default_params': {},
                        'is_tuned': is_tuned
                    })
                    existing_ids.add(name)
    except Exception as e:
        print(f"Error loading allocation.json strategies: {e}")

    # 3. Add legacy hardcoded/baseline strategies if needed
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
            strategy_id = config.get('strategy_id') or config.get('strategy', 'v35_long')
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
            # 1. Use Generic Backtester for:
            #    - Factory Strategies (in STRATEGY_REGISTRY)
            #    - Tuned strategies (with regime_routing in allocation.json)
            #    - Derived strategies (with base_strategy in allocation.json)
            if strategy_id in STRATEGY_REGISTRY or _is_tuned_strategy(strategy_id) or _has_base_strategy(strategy_id):
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


def _run_tuned_strategy_backtest(
    strategy_id: str,
    tuned_config: dict,
    df: 'pd.DataFrame',
    initial_capital: float,
    leverage: float,
    fee_rate: float,
    slippage: float,
    job: BacktestJob
) -> tuple:
    """
    Run backtest for tuned strategies with regime_routing config.

    Uses regime-based component routing similar to Quant Lab optimization.
    """
    import numpy as np
    import pandas as pd
    from typing import Dict, List
    from types import MappingProxyType

    from trading.strategies.components.registry import (
        get_entry_class, get_exit_class,
        get_entry_params_class, get_exit_params_class,
        build_params_from_config
    )
    from trading.strategies.components.models import (
        MarketData, Position, TradingContext, build_market_context
    )

    regime_routing = tuned_config.get('regime_routing', {})

    # Build regime strategies from config
    regime_strategies = {}
    for regime, regime_config in regime_routing.items():
        entry_name = regime_config.get('entry')
        exit_name = regime_config.get('exit')

        if entry_name == 'None' or not entry_name:
            regime_strategies[regime] = None
            continue

        try:
            entry_cls = get_entry_class(entry_name + 'Strategy')
            exit_cls = get_exit_class(exit_name + 'Strategy')

            entry_params_cls = get_entry_params_class(entry_name + 'Strategy')
            exit_params_cls = get_exit_params_class(exit_name + 'Strategy')

            entry_params = regime_config.get('entry_params', {})
            exit_params = regime_config.get('exit_params', {})

            entry_params_obj = build_params_from_config(entry_params_cls, entry_params) if entry_params_cls else None
            exit_params_obj = build_params_from_config(exit_params_cls, exit_params) if exit_params_cls else None

            regime_strategies[regime] = {
                'entry': entry_cls(entry_params_obj),
                'exit': exit_cls(exit_params_obj),
            }
        except Exception as e:
            logger.warning(f"Failed to create components for {regime}: {e}")
            regime_strategies[regime] = None

    # Backtest loop
    capital = initial_capital
    position_size = 0.0
    entry_price = 0.0
    current_position_data = None
    trades: List[Dict] = []
    equity_curve: List[float] = []

    for i in range(len(df)):
        if job._cancelled:
            return {}, df

        if i < TimePeriods.BACKTEST_WARMUP:  # Warmup period
            row = df.iloc[i]
            equity_curve.append({'date': str(row.get('timestamp', row.name))[:10], 'equity': capital})
            continue

        row = df.iloc[i]
        timestamp = str(row.get('timestamp', row.name))

        # Determine current regime
        # Includes drawdown-based BEAR detection (15% from 30-day high = BEAR override)
        # Use 30-day high for better crash detection (falls back to 20-period if not available)
        high_30d = row.get('high_30d', 0.0)
        recent_high = high_30d if high_30d > 0 else row.get('prev_high_20', 0.0)
        context = build_market_context(
            mfi=row.get('mfi', 50.0),
            adx=row.get('adx', 20.0),
            atr=row.get('atr', 0.0),
            close=row['close'],
            volume=row.get('volume', 0.0),
            avg_volume=row.get('avg_volume_20', 0.0),
            recent_high=recent_high,
        )
        current_regime = context.regime

        # Get strategy components for current regime
        strategy_components = regime_strategies.get(current_regime)

        # Calculate current equity
        current_equity = capital
        if position_size > 0 and current_position_data:
            pnl_ratio = (row['close'] - entry_price) / entry_price
            unrealized_pnl = position_size * pnl_ratio
            current_equity += (position_size / leverage) + unrealized_pnl

        equity_curve.append({'date': timestamp[:10], 'equity': current_equity})

        # No trading in this regime
        if strategy_components is None:
            if position_size > 0:
                # Close position when entering no-trade regime
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
                    'reason': f'Regime changed to {current_regime} (no trading)'
                })
                position_size = 0.0
                entry_price = 0.0
                current_position_data = None
            continue

        entry_strategy = strategy_components['entry']
        exit_strategy = strategy_components['exit']

        # Build MarketData
        market_data = MarketData(
            symbol='BTC',
            close=row['close'],
            timestamp=int(row['timestamp'].timestamp() * 1000) if hasattr(row.get('timestamp'), 'timestamp') else 0,
            mfi=row.get('mfi', 50.0),
            adx=row.get('adx', 20.0),
            rsi=row.get('rsi', 50.0),
            atr=row.get('atr', 0.0),
            macd=row.get('macd', 0.0),
            macd_signal=row.get('macd_signal', 0.0),
            stoch_k=row.get('stoch_k', 50.0),
            stoch_d=row.get('stoch_d', 50.0),
            bb_upper=row.get('bb_upper', 0.0),
            bb_lower=row.get('bb_lower', 0.0),
            bb_middle=row.get('bb_middle', 0.0),
            volume=row.get('volume', 0.0),
            avg_volume_20=row.get('avg_volume_20', 0.0),
            prev_high_20=row.get('prev_high_20', 0.0),
            prev_low_20=row.get('prev_low_20', 0.0),
        )

        # Check exit if we have a position
        if position_size > 0 and current_position_data:
            pos = Position(
                symbol='BTC',
                entry_price=entry_price,
                quantity=current_position_data['quantity'],
                strategy=strategy_id,
                market='futures',
                timestamp=current_position_data['timestamp'],
            )

            exit_trading_ctx = TradingContext(
                symbol='BTC',
                timestamp=market_data.timestamp,
                market=market_data,
                regime=context,
                positions=MappingProxyType({strategy_id: pos}),
            )

            signal = exit_strategy.check_exit(exit_trading_ctx, pos)
            if signal:
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
                    'reason': signal.reason
                })
                position_size = 0.0
                entry_price = 0.0
                current_position_data = None
            continue

        # Check entry if no position
        trading_ctx = TradingContext(
            symbol='BTC',
            timestamp=market_data.timestamp,
            market=market_data,
            regime=context,
            positions=MappingProxyType({}),
        )

        signal = entry_strategy.check_entry(trading_ctx)
        if signal:
            fraction = 0.3  # Default position size
            margin = capital * fraction
            effective_pos_size = margin * leverage
            fee = effective_pos_size * fee_rate

            if capital >= (margin + fee):
                capital -= (margin + fee)
                position_size = effective_pos_size
                entry_price = row['close'] * (1 + slippage)
                current_position_data = {
                    'quantity': signal.quantity,
                    'timestamp': market_data.timestamp,
                }
                trades.append({
                    'type': 'buy',
                    'time': timestamp,
                    'price': entry_price,
                    'size': position_size,
                    'reason': signal.reason
                })

    job.progress = 80

    # Force close at end
    if position_size > 0:
        last_price = df.iloc[-1]['close']
        pnl_ratio = (last_price - entry_price) / entry_price
        pnl = position_size * pnl_ratio
        capital += (position_size / leverage) + pnl

    # Calculate metrics
    final_capital = capital
    total_return_pct = (final_capital - initial_capital) / initial_capital * 100

    close_trades = [t for t in trades if t['type'] == 'sell']
    profits = [t['pnl'] for t in close_trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]

    win_rate = len(wins) / len(close_trades) * 100 if close_trades else 0
    profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 0

    equity_values = [e['equity'] for e in equity_curve]
    equity_series = pd.Series(equity_values)
    returns = equity_series.pct_change().dropna()

    import numpy as np
    sharpe_ratio = float(returns.mean() / returns.std() * np.sqrt(TimePeriods.TRADING_DAYS_PER_YEAR)) if len(returns) > 0 and returns.std() > 0 else 0

    peak = equity_series.cummax()
    drawdown = (equity_series - peak) / peak * 100
    mdd = float(drawdown.min())

    # Format trades for frontend
    trades_list = []
    for t in close_trades[:100]:
        trades_list.append({
            'timestamp': t.get('time'),
            'symbol': 'BTC',
            'action': 'BUY',
            'price': t.get('entry_price'),
            'profit': None
        })
        trades_list.append({
            'timestamp': t.get('time'),
            'symbol': 'BTC',
            'action': 'SELL',
            'price': t.get('exit_price'),
            'profit': round(t.get('pnl', 0), 0)
        })

    start_date = str(df.iloc[0].get('timestamp', df.index[0]))[:10]
    end_date = str(df.iloc[-1].get('timestamp', df.index[-1]))[:10]

    return {
        'strategy': strategy_id,
        'preset': 'tuned',
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
    Also supports tuned strategies from allocation.json with regime_routing.
    """
    import json
    import numpy as np
    from typing import Dict, List
    from core.data_loader import DataLoader

    # Check if strategy exists in registry or allocation.json
    is_tuned_strategy = False
    tuned_config = None
    base_strategy_id = strategy_id  # Default to same name

    if strategy_id not in STRATEGY_REGISTRY:
        # Check if it's a strategy in allocation.json
        allocation_path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
        if allocation_path.exists():
            with open(allocation_path, 'r') as f:
                allocation = json.load(f)
            if strategy_id in allocation.get('strategies', {}):
                strategy_config = allocation['strategies'][strategy_id]
                if 'regime_routing' in strategy_config:
                    is_tuned_strategy = True
                    tuned_config = strategy_config
                else:
                    # Try to find a base strategy in registry
                    # e.g., 'mlp_direction_optimized' -> 'mlp_direction'
                    base_strategy = strategy_config.get('base_strategy')
                    if not base_strategy:
                        # Infer base strategy by finding registry entry that matches prefix
                        for reg_name in STRATEGY_REGISTRY.keys():
                            if strategy_id.startswith(reg_name):
                                base_strategy = reg_name
                                break
                    if base_strategy and base_strategy in STRATEGY_REGISTRY:
                        base_strategy_id = base_strategy
                        logger.info(f"Using base strategy '{base_strategy}' for '{strategy_id}'")
                    else:
                        raise ValueError(f"Strategy {strategy_id} has no regime_routing and no valid base_strategy")
            else:
                raise ValueError(f"Strategy {strategy_id} not found in registry or allocation.json")
        else:
            raise ValueError(f"Strategy {strategy_id} not found in StrategyFactory Registry")

    # 1. Initialize Factory
    factory = StrategyFactory(redis=None)

    # 2. Set environment based on Market
    exchange_name = "binance"

    if is_tuned_strategy:
        # Use tuned config from allocation.json
        market_type = tuned_config.get('market', 'futures')
        leverage = float(tuned_config.get('leverage', 3))
        timeframe = 'minute60'  # Default for tuned strategies
    else:
        # Use registry spec (use base_strategy_id for registry lookup)
        spec = STRATEGY_REGISTRY[base_strategy_id]
        market_type = spec.market
        leverage = 3.0 if market_type == 'futures' else 1.0
        timeframe = spec.timeframe

    if market_type == 'futures':
        fee_rate = FeeRates.FUTURES
        slippage = FeeRates.FUTURES_SLIPPAGE
    else:
        fee_rate = FeeRates.SPOT
        slippage = FeeRates.SPOT_SLIPPAGE

    # Map timeframe aliases to database table names
    timeframe_map = {
        'hour1': 'minute60',
        'hour4': 'minute240',
        '1h': 'minute60',
        '4h': 'minute240',
        '1d': 'day',
    }
    db_timeframe = timeframe_map.get(timeframe, timeframe)

    with DataLoader(exchange=exchange_name) as loader:
        df = loader.load_timeframe(db_timeframe, start_date, end_date)

    if df.empty:
        raise ValueError(f"No data available for {start_date} to {end_date}")

    job.progress = 20

    # Pre-calculate indicators
    add_all_indicators(df)
    job.progress = 30

    # Route to appropriate backtest implementation
    if is_tuned_strategy:
        return _run_tuned_strategy_backtest(
            strategy_id, tuned_config, df, initial_capital, leverage, fee_rate, slippage, job
        )

    # Regular strategy: use ComponentStrategyAdapter
    # Load strategy config from allocation.json for regime_version and other params
    allocation_path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
    config = {}
    if allocation_path.exists():
        with open(allocation_path, 'r') as f:
            allocation = json.load(f)
        strategy_config = allocation.get('strategies', {}).get(strategy_id, {})

        # CRITICAL: Pass ALL strategy config params to adapter
        # This ensures strategy-specific parameters (mfi_bull_strong, position_size_bull_strong,
        # stop_loss_pct, take_profit_pct, etc.) are correctly passed to Entry/Exit components.
        # Start with full strategy_config, then apply adapter-specific defaults.
        config = dict(strategy_config)  # Copy all strategy params

        # Apply adapter-specific defaults for params not in strategy_config
        adapter_defaults = {
            'regime_version': 'v1',
            'position_size': 0.5,
            'position_pct': 0.3,
            'dynamic_sizing': False,
            'core_hold_pct': 0.0,
            'core_exit_on_ema200': False,
            'core_ema_hours': 0,
            'core_ema_timeframe': '',
            'core_ema_span': 0,
            'core_reentry_on_ema200': True,
            'core_fee_rate': fee_rate,
            'core_slippage': slippage,
            'core_drawdown_exit_pct': 0.0,
            'core_drawdown_reentry_pct': 0.0,
            'use_breakout_filter': True,
            'bbw_block_threshold': 25,
            'bbw_confirm_threshold': 50,
            'volume_block_ratio': 0.8,
            'volume_boost_ratio': 1.2,
            'mtf_enabled': True,
            'stop_loss_cooldown': 24,
            'trailing_enabled': False,
            'trailing_activation': 3.0,
            'trailing_distance': 2.0,
            'atr_stop_enabled': False,
            'atr_stop_multiplier': 2.0,
            'atr_stop_min_pct': 1.5,
            'atr_stop_max_pct': 4.0,
            'dynamic_leverage': False,
            'leverage_bull_strong': 3.0,
            'leverage_bull_moderate': 2.0,
            'leverage_sideways': 1.0,
            'leverage_bear': 0.0,
            'cash_in_bear': False,
            'cash_below_ema200': False,
            'max_consecutive_losses': 3,
            'loss_pause_candles': 48,
            'drawdown_enabled': True,
            'drawdown_warning_pct': 8.0,
            'drawdown_reduce_pct': 10.0,
            'drawdown_exit_pct': 12.0,
            'drawdown_leverage_reduction': 0.5,
            'drawdown_partial_exit_fraction': 0.5,
            'v2_exit_on_filter': False,
            'bull_prob_threshold': 0.0,
            'panic_sell_below_ma120': False,
            'prob_leverage_enabled': False,
            'prob_leverage_max': 3.0,
            'prob_leverage_high': 2.5,
            'prob_leverage_mid': 2.0,
            'prob_leverage_low': 1.0,
            'prob_leverage_min': 0.5,
            'use_rf_probability': False,
            'lstm_model_path': 'lstm_trainer/models/hybrid_lstm.pth',
            'rf_model_path': 'lstm_trainer/models/noise_filter_rf.pkl',
            'dynamic_position_sizing': False,
            'position_size_high': 0.30,
            'position_size_mid': 0.15,
            'position_size_low': 0.05,
            'position_conf_low': 0.50,
            'position_conf_high': 0.70,
        }
        # Apply defaults only for missing keys
        for key, default_val in adapter_defaults.items():
            if key not in config:
                config[key] = default_val

        # Also merge defaults from allocation if present
        defaults = allocation.get('defaults', {}).get('regime_v2', {})
        for key in ['bbw_block_threshold', 'bbw_confirm_threshold', 'volume_block_ratio', 'volume_boost_ratio', 'mtf_enabled']:
            if key not in strategy_config and key in defaults:
                config[key] = defaults[key]

    # Pre-compute RF predictions as DataFrame columns (if RF is enabled)
    if config.get('use_rf_probability', False):
        add_rf_predictions(df, config)
        job.progress = 40

    # Use base_strategy_id for adapter (e.g., 'mlp_direction' for 'mlp_direction_optimized')
    adapter = ComponentStrategyAdapter(factory, base_strategy_id, config)

    # 5. Backtest Loop
    core_hold_pct = float(config.get("core_hold_pct", 0.0))
    core_hold_pct = max(min(core_hold_pct, 0.95), 0.0)
    core_exit_on_ema200 = bool(config.get("core_exit_on_ema200", False))
    core_ema_hours = int(config.get("core_ema_hours", 0))
    core_ema_timeframe = str(config.get("core_ema_timeframe", "")).lower()
    core_ema_span = int(config.get("core_ema_span", 0))
    core_reentry_on_ema200 = bool(config.get("core_reentry_on_ema200", True))
    core_fee_rate = float(config.get("core_fee_rate", fee_rate))
    core_slippage = float(config.get("core_slippage", slippage))
    core_drawdown_exit_pct = float(config.get("core_drawdown_exit_pct", 0.0))
    core_drawdown_reentry_pct = float(config.get("core_drawdown_reentry_pct", 0.0))

    core_cash = initial_capital * core_hold_pct
    capital = initial_capital - core_cash
    core_qty = 0.0
    core_active = False
    core_peak_price = 0.0

    if core_hold_pct > 0:
        if core_ema_timeframe in ("day", "daily"):
            core_span = core_ema_span if core_ema_span > 0 else 200
            with DataLoader(exchange=exchange_name) as core_loader:
                day_df = core_loader.load_timeframe("day", start_date, end_date)
            if not day_df.empty:
                day_df = day_df.copy()
                day_df["date"] = day_df["timestamp"].dt.date
                day_df["core_ema"] = day_df["close"].ewm(span=core_span, adjust=False).mean()
                df = df.copy()
                df["date"] = df["timestamp"].dt.date
                df = df.merge(day_df[["date", "core_ema"]], on="date", how="left")
                df.drop(columns=["date"], inplace=True)
                df["core_ema"] = df["core_ema"].ffill()
        elif core_ema_hours > 0:
            df = df.copy()
            df["core_ema"] = df["close"].ewm(span=core_ema_hours, adjust=False).mean()

    if core_hold_pct > 0 and not df.empty:
        first_row = df.iloc[0]
        ema_200 = float(first_row.get("ema_200", 0.0) or 0.0)
        core_ema = float(first_row.get("core_ema", 0.0) or 0.0)
        price = float(first_row["close"])
        can_enter = True
        if core_ema > 0 and price < core_ema:
            can_enter = False
        elif core_exit_on_ema200 and ema_200 > 0 and price < ema_200:
            can_enter = False

        if can_enter and core_cash > 0:
            entry_price = price * (1 + core_slippage)
            core_qty = core_cash / (entry_price * (1 + core_fee_rate))
            cost = core_qty * entry_price * (1 + core_fee_rate)
            core_cash -= cost
            core_active = core_qty > 0
            core_peak_price = price

    position_size = 0.0
    entry_price = 0.0
    entry_timestamp = None  # Track when position was opened for chart markers
    position_leverage = leverage  # Track leverage used for current position
    trades: List[Dict] = []
    equity_curve: List[float] = []

    adapter.symbol = "BTC"

    for i in range(len(df)):
        if job._cancelled:
            return {}, df

        row = df.iloc[i]
        timestamp = str(row.get('timestamp', row.name))

        # Core hold management (EMA200 filter)
        if core_hold_pct > 0:
            ema_200 = float(row.get("ema_200", 0.0) or 0.0)
            core_ema = float(row.get("core_ema", 0.0) or 0.0)
            price = float(row["close"])

            if core_active:
                if price > core_peak_price:
                    core_peak_price = price

                core_drawdown_pct = 0.0
                if core_peak_price > 0:
                    core_drawdown_pct = (core_peak_price - price) / core_peak_price * 100

                exit_on_core_ema = core_ema > 0 and price < core_ema
                exit_on_ema200 = core_exit_on_ema200 and ema_200 > 0 and price < ema_200
                exit_on_drawdown = core_drawdown_exit_pct > 0 and core_drawdown_pct >= core_drawdown_exit_pct

                if exit_on_drawdown or exit_on_core_ema or exit_on_ema200:
                    exit_price = price * (1 - core_slippage)
                    proceeds = core_qty * exit_price * (1 - core_fee_rate)
                    core_cash += proceeds
                    core_qty = 0.0
                    core_active = False

            elif (not core_active) and core_reentry_on_ema200:
                can_reenter = True
                if core_ema > 0 and price < core_ema:
                    can_reenter = False
                elif core_exit_on_ema200 and ema_200 > 0 and price < ema_200:
                    can_reenter = False
                if core_drawdown_reentry_pct > 0:
                    if core_peak_price > 0:
                        drawdown_pct = (core_peak_price - price) / core_peak_price * 100
                        if drawdown_pct > core_drawdown_reentry_pct:
                            can_reenter = False
                if can_reenter and core_cash > 0:
                    entry_price = price * (1 + core_slippage)
                    core_qty = core_cash / (entry_price * (1 + core_fee_rate))
                    cost = core_qty * entry_price * (1 + core_fee_rate)
                    core_cash -= cost
                    core_active = core_qty > 0
                    core_peak_price = price

        # --- Calculate Current Equity BEFORE strategy call ---
        # This enables portfolio-level drawdown protection in the adapter
        current_equity = capital
        if position_size > 0:
            current_price = row['close']
            if adapter.current_position and adapter.current_position.side == 'short':
                # Short PnL
                pnl_ratio = (entry_price - current_price) / entry_price
                unrealized_pnl = position_size * pnl_ratio
                current_equity += (position_size / position_leverage) + unrealized_pnl
            else:
                # Long PnL
                pnl_ratio = (current_price - entry_price) / entry_price
                unrealized_pnl = position_size * pnl_ratio
                current_equity += (position_size / position_leverage) + unrealized_pnl

        if core_hold_pct > 0:
            current_equity += core_cash + (core_qty * row['close'])

        # Update adapter with current equity for drawdown protection
        adapter.update_equity(current_equity)

        # Execute Strategy Logic via Adapter (now with drawdown awareness)
        signal = adapter(df, i)

        action = signal.get('action', 'hold')
        reason = signal.get('reason', '')

        equity_curve.append({'date': timestamp[:10], 'equity': current_equity})

        # --- Execution Logic ---

        # OPEN LONG
        if action == 'buy' and position_size == 0:
            fraction = signal.get('fraction', 1.0)
            # Use dynamic leverage from signal if provided, else use fixed leverage
            effective_leverage = signal.get('leverage', leverage)
            # Account for fees when calculating margin to avoid silent skips
            # margin + fee <= capital * fraction, where fee = margin * effective_leverage * fee_rate
            # margin * (1 + effective_leverage * fee_rate) <= capital * fraction
            max_margin = capital * fraction / (1 + effective_leverage * fee_rate)
            margin = max_margin
            effective_pos_size = margin * effective_leverage
            fee = effective_pos_size * fee_rate

            if capital >= (margin + fee):
                capital -= (margin + fee)
                position_size = effective_pos_size
                position_leverage = effective_leverage  # Track leverage for this position
                entry_price = row['close'] * (1 + slippage)
                entry_timestamp = timestamp  # Track entry time for chart markers
                trades.append({
                    'type': 'buy',
                    'time': timestamp,
                    'price': entry_price,
                    'size': position_size,
                    'reason': reason,
                    'leverage': effective_leverage,
                })

        # OPEN SHORT
        elif action == 'open_short' and position_size == 0:
            fraction = signal.get('fraction', 0.3)
            # Use dynamic leverage from signal if provided, else use fixed leverage
            effective_leverage = signal.get('leverage', leverage)
            # Account for fees when calculating margin
            max_margin = capital * fraction / (1 + effective_leverage * fee_rate)
            margin = max_margin
            effective_pos_size = margin * effective_leverage
            fee = effective_pos_size * fee_rate

            if capital >= (margin + fee):
                capital -= (margin + fee)
                position_size = effective_pos_size
                position_leverage = effective_leverage  # Track leverage for this position
                entry_price = row['close'] * (1 - slippage)
                entry_timestamp = timestamp  # Track entry time for chart markers
                trades.append({
                    'type': 'open_short',
                    'time': timestamp,
                    'price': entry_price,
                    'size': position_size,
                    'reason': reason,
                    'leverage': effective_leverage,
                })

        # CLOSE LONG (SELL) - supports partial exits via fraction
        elif action == 'sell' and position_size > 0:
            exit_fraction = signal.get('fraction', 1.0)
            exit_size = position_size * exit_fraction

            exit_price = row['close'] * (1 - slippage)
            pnl_ratio = (exit_price - entry_price) / entry_price
            pnl = exit_size * pnl_ratio
            margin_return = exit_size / position_leverage
            fee = exit_size * fee_rate

            capital += margin_return + pnl - fee

            trades.append({
                'type': 'sell',
                'time': timestamp,
                'entry_time': entry_timestamp,  # Track when position was opened
                'entry_price': entry_price,
                'exit_price': exit_price,
                'size': exit_size,
                'pnl': pnl,
                'pnl_pct': pnl_ratio * 100 * position_leverage,
                'reason': reason,
                'leverage': position_leverage,
            })

            # Update position for partial exit or clear for full exit
            if exit_fraction >= 1.0:
                position_size = 0.0
                entry_timestamp = None  # Reset entry timestamp
                entry_price = 0.0
            else:
                position_size -= exit_size  # Keep remaining position

        # CLOSE SHORT - supports partial exits via fraction
        elif action == 'close_short' and position_size > 0:
             exit_fraction = signal.get('fraction', 1.0)
             exit_size = position_size * exit_fraction

             exit_price = row['close'] * (1 + slippage)
             pnl_ratio = (entry_price - exit_price) / entry_price
             pnl = exit_size * pnl_ratio
             margin_return = exit_size / position_leverage
             fee = exit_size * fee_rate

             capital += margin_return + pnl - fee

             trades.append({
                'type': 'close_short',
                'time': timestamp,
                'entry_time': entry_timestamp,  # Track when position was opened
                'entry_price': entry_price,
                'exit_price': exit_price,
                'size': exit_size,
                'pnl': pnl,
                'pnl_pct': pnl_ratio * 100 * position_leverage,
                'reason': reason,
                'leverage': position_leverage,
             })

             # Update position for partial exit or clear for full exit
             if exit_fraction >= 1.0:
                 position_size = 0.0
                 entry_price = 0.0
                 entry_timestamp = None  # Reset entry timestamp
             else:
                 position_size -= exit_size  # Keep remaining position

    job.progress = 80

    # Force close at end
    if position_size > 0:
        last_price = df.iloc[-1]['close']
        if adapter.current_position and adapter.current_position.side == 'short':
             pnl_ratio = (entry_price - last_price) / entry_price
        else:
             pnl_ratio = (last_price - entry_price) / entry_price
        pnl = position_size * pnl_ratio
        capital += (position_size / position_leverage) + pnl

    # Final capital includes core hold value
    if core_hold_pct > 0:
        last_price = df.iloc[-1]['close']
        capital += core_cash + (core_qty * last_price)

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
    sharpe_ratio = float(returns.mean() / returns.std() * np.sqrt(TimePeriods.TRADING_DAYS_PER_YEAR)) if len(returns) > 0 and returns.std() > 0 else 0

    peak = equity_series.cummax()
    drawdown = (equity_series - peak) / peak * 100
    mdd = float(drawdown.min())

    # Format for Frontend - sample trades evenly across time period for chart markers
    trades_list = []
    max_trades = 150  # Maximum round-trips to display
    if len(close_trades) <= max_trades:
        sampled_trades = close_trades
    else:
        # Sample evenly across the trade list to cover all time periods
        step = len(close_trades) / max_trades
        indices = [int(i * step) for i in range(max_trades)]
        sampled_trades = [close_trades[i] for i in indices]

    for t in sampled_trades:
        action_label = 'COVER' if t['type'] == 'close_short' else 'SELL'
        entry_action = 'SHORT' if t['type'] == 'close_short' else 'BUY'
        trades_list.append({
            'timestamp': t.get('entry_time') or t.get('time'),  # Use entry_time for BUY markers
            'symbol': 'BTC',
            'action': entry_action,
            'price': t.get('entry_price'),
            'profit': None
        })
        trades_list.append({
            'timestamp': t.get('time'),  # Use exit time for SELL markers
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
    fee_rate = FeeRates.FUTURES
    slippage = FeeRates.FUTURES_SLIPPAGE

    capital = initial_capital
    position_size = 0.0
    entry_price = 0.0
    initial_position_size = 0.0
    trades: List[Dict] = []
    equity_curve: List[float] = []

    for i in range(len(df)):
        if job._cancelled:
            return {}, df

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
    sharpe = float(returns.mean() / returns.std() * np.sqrt(TimePeriods.TRADING_DAYS_PER_YEAR)) if len(returns) > 0 and returns.std() > 0 else 0

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
