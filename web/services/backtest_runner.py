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
from trading.strategies.components.config_schema import has_new_config_format
from core.component_adapter import ComponentStrategyAdapter
from trading.indicators import add_all_indicators
from trading.config.constants import FeeRates, TimePeriods

logger = logging.getLogger(__name__)

# Symbol to database path mapping
SYMBOL_DB_MAPPING = {
    "BTC": PROJECT_ROOT / "data" / "binance_bitcoin.db",
    "ETH": PROJECT_ROOT / "data" / "binance_ethereum.db",
    "SOL": PROJECT_ROOT / "data" / "binance_solana.db",
    "BNB": PROJECT_ROOT / "data" / "binance_bnb.db",
}


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

_ADAPTER_DEFAULTS = {
    'regime_version': 'v1',
    'position_size': 0.01,
    'position_pct': 0.3,
    'dynamic_sizing': False,
    'core_hold_pct': 0.0,
    'core_exit_on_ema200': False,
    'core_ema_hours': 0,
    'core_ema_timeframe': '',
    'core_ema_span': 0,
    'core_reentry_on_ema200': True,
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
}


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


def _is_new_config_strategy(strategy_id: str) -> bool:
    """Check if a strategy in allocation.json uses new config format (entry.class/exit.class)."""
    import json
    allocation_path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
    if not allocation_path.exists():
        return False
    try:
        with open(allocation_path, 'r') as f:
            allocation = json.load(f)
        strategy_config = allocation.get('strategies', {}).get(strategy_id, {})
        return has_new_config_format(strategy_config)
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
        benchmark_curve = _add_benchmark_to_results(results, price_data, initial_capital)
        chart_path = _generate_equity_chart(results, strategy_id, job_id, benchmark_curve)
        _generate_regime_charts(results, price_data, strategy_id, job_id)
        _log_results_to_mlflow(results, strategy_id, initial_capital, chart_path)

    except Exception as e:
        logger.warning(f"Visualization/MLflow logging failed: {e}")
        traceback.print_exc()

    return results


def _add_benchmark_to_results(
    results: dict,
    price_data: pd.DataFrame,
    initial_capital: float,
):
    """Calculate benchmark curve and append frontend-friendly benchmark data."""
    if price_data.empty or 'close' not in price_data.columns:
        return None

    if 'timestamp' not in price_data.columns:
        price_data = price_data.copy()
        price_data['timestamp'] = price_data.index

    benchmark_curve, benchmark_return_pct = calculate_benchmark(price_data, initial_capital)
    results['benchmark_return_pct'] = round(benchmark_return_pct, 2)

    if benchmark_curve is not None and len(benchmark_curve) > 0:
        results['benchmark_curve'] = [
            {'date': str(ts)[:10], 'equity': equity}
            for ts, equity in benchmark_curve.items()
        ]
    return benchmark_curve


def _generate_equity_chart(
    results: dict,
    strategy_id: str,
    job_id: str,
    benchmark_curve,
):
    """Generate equity chart and attach relative chart path to results."""
    equity_data = results.get('equity_curve', [])
    if not equity_data:
        return None

    equity_df = pd.DataFrame(equity_data)
    equity_df['timestamp'] = pd.to_datetime(equity_df['date'])
    equity_df['total_equity'] = equity_df['equity']

    chart_filename = f"backtest_{strategy_id}_{job_id}.png"
    chart_path = CHART_OUTPUT_DIR / chart_filename
    chart_result = {
        'equity_curve': equity_df,
        'benchmark_curve': benchmark_curve,
        'strategy_name': strategy_id,
        'symbol': 'BTC',
        'total_return': results.get('total_return_pct', 0),
        'benchmark_return_pct': results.get('benchmark_return_pct', 0),
    }

    saved_path = _visualizer.create_chart(
        chart_result,
        output_path=str(chart_path),
        title=f"{strategy_id} Backtest",
    )
    if saved_path:
        results['chart_path'] = f"/static/charts/{chart_filename}"
        logger.info(f"Generated chart: {saved_path}")
        return chart_path
    return None


def _generate_regime_charts(
    results: dict,
    price_data: pd.DataFrame,
    strategy_id: str,
    job_id: str,
) -> None:
    """Generate regime and yearly regime charts."""
    if price_data.empty or 'close' not in price_data.columns:
        return
    try:
        regime_filename = f"regime_{strategy_id}_{job_id}.png"
        regime_path = CHART_OUTPUT_DIR / regime_filename
        trades_for_chart = _convert_trades_for_regime_chart(results.get('trades', []))

        saved_regime_path = _visualizer.create_regime_chart(
            price_data,
            trades=trades_for_chart if trades_for_chart else None,
            equity_curve=results.get('equity_curve'),
            output_path=str(regime_path),
            title=f"{strategy_id} Regime Analysis",
        )
        if saved_regime_path:
            results['regime_chart_path'] = f"/static/charts/{regime_filename}"
            logger.info(f"Generated regime chart: {saved_regime_path}")

        years = _count_years(price_data)
        if years >= 2:
            yearly_dir = CHART_OUTPUT_DIR / f"yearly_{strategy_id}_{job_id}"
            yearly_paths = _visualizer.create_yearly_regime_charts(
                price_data,
                trades=trades_for_chart,
                equity_curve=results.get('equity_curve'),
                output_dir=str(yearly_dir),
                title_prefix=f"{strategy_id}",
            )
            if yearly_paths:
                results['yearly_chart_paths'] = [
                    f"/static/charts/yearly_{strategy_id}_{job_id}/{Path(p).name}"
                    for p in yearly_paths
                ]
                logger.info(f"Generated {len(yearly_paths)} yearly charts")
    except Exception as e:
        logger.warning(f"Regime chart generation failed: {e}")


def _convert_trades_for_regime_chart(raw_trades: list[dict]) -> list[dict]:
    """Convert frontend trade actions to regime chart buy/sell markers."""
    converted = []
    for trade in raw_trades:
        action = trade.get('action', '').upper()
        if action in ('BUY', 'LONG', 'ENTRY'):
            converted.append({'timestamp': trade.get('timestamp'), 'action': 'buy', 'price': trade.get('price')})
        elif action in ('SELL', 'SHORT', 'EXIT', 'COVER'):
            converted.append({'timestamp': trade.get('timestamp'), 'action': 'sell', 'price': trade.get('price')})
    return converted


def _count_years(price_data: pd.DataFrame) -> int:
    """Count distinct years in price data."""
    if 'timestamp' in price_data.columns:
        return price_data['timestamp'].dt.year.nunique()
    if isinstance(price_data.index, pd.DatetimeIndex):
        return price_data.index.year.nunique()
    return 1


def _log_results_to_mlflow(
    results: dict,
    strategy_id: str,
    initial_capital: float,
    chart_path,
) -> None:
    """Log run summary and optional chart artifact to MLflow."""
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
            'leverage': results.get('leverage', 1),
        },
    }
    chart_artifact = str(chart_path) if chart_path is not None else None
    run_id = _mlflow_tracker.log_run(mlflow_result, chart_path=chart_artifact)
    if run_id:
        results['mlflow_run_id'] = run_id
        results['mlflow_url'] = _mlflow_tracker.get_run_url(run_id)
        logger.info(f"Logged to MLflow: run_id={run_id}")


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

    def mark_cancelled() -> None:
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

    def run_selected_backtest(strategy_id: str, start_date: str, end_date: str, initial_capital: float):
        is_generic = (
            strategy_id in STRATEGY_REGISTRY
            or _is_tuned_strategy(strategy_id)
            or _has_base_strategy(strategy_id)
            or _is_new_config_strategy(strategy_id)
        )
        if is_generic:
            return _run_generic_backtest(strategy_id, start_date, end_date, initial_capital, job)
        if strategy_id in ('short_v1_baseline',):
            return _run_short_backtest(strategy_id, start_date, end_date, initial_capital, job)
        raise ValueError(
            f"No backtest runner available for strategy '{strategy_id}'. "
            "This is unexpected because strategy_id was validated earlier."
        )

    def _run():
        try:
            job.status = 'running'
            job.started_at = datetime.now().isoformat()
            job.progress = 0

            config = job.config
            strategy_id = config.get('strategy_id') or config.get('strategy', 'short_v1')
            start_date = config.get('start_date', '2024-01-01')
            end_date = config.get('end_date', '2024-12-31')
            initial_capital = config.get('initial_capital', 10000)

            # SECURITY: Validate strategy_id
            strategies = get_available_strategies()
            valid_ids = [s['id'] for s in strategies]
            if strategy_id not in valid_ids:
                raise ValueError(f"Invalid strategy: {strategy_id}")

            if job._cancelled:
                mark_cancelled()
                return

            job.progress = 10
            results, price_data = run_selected_backtest(
                strategy_id, start_date, end_date, initial_capital
            )

            if job._cancelled:
                mark_cancelled()
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
    regime_strategies = _build_tuned_regime_strategies(tuned_config)
    state = _run_tuned_backtest_loop(
        strategy_id=strategy_id,
        df=df,
        regime_strategies=regime_strategies,
        initial_capital=initial_capital,
        leverage=leverage,
        fee_rate=fee_rate,
        slippage=slippage,
        job=job,
    )
    if not state:
        return {}, df

    job.progress = 80
    return _finalize_tuned_results(state, strategy_id, df, initial_capital, leverage), df


def _build_tuned_regime_strategies(tuned_config: dict) -> dict:
    from trading.strategies.components.registry import (
        build_params_from_config,
        get_entry_class,
        get_entry_params_class,
        get_exit_class,
        get_exit_params_class,
    )

    regime_strategies = {}
    for regime, regime_config in tuned_config.get('regime_routing', {}).items():
        entry_name = regime_config.get('entry')
        exit_name = regime_config.get('exit')
        if entry_name == 'None' or not entry_name:
            regime_strategies[regime] = None
            continue
        try:
            entry_cls = get_entry_class(f"{entry_name}Strategy")
            exit_cls = get_exit_class(f"{exit_name}Strategy")
            entry_params_cls = get_entry_params_class(f"{entry_name}Strategy")
            exit_params_cls = get_exit_params_class(f"{exit_name}Strategy")
            entry_params_obj = (
                build_params_from_config(entry_params_cls, regime_config.get('entry_params', {}))
                if entry_params_cls else None
            )
            exit_params_obj = (
                build_params_from_config(exit_params_cls, regime_config.get('exit_params', {}))
                if exit_params_cls else None
            )
            regime_strategies[regime] = {
                'entry': entry_cls(entry_params_obj),
                'exit': exit_cls(exit_params_obj),
            }
        except Exception as exc:
            logger.warning(f"Failed to create components for {regime}: {exc}")
            regime_strategies[regime] = None
    return regime_strategies


def _close_tuned_position(state: dict, row: pd.Series, timestamp: str, reason: str, leverage: float, fee_rate: float, slippage: float) -> None:
    exit_price = row['close'] * (1 - slippage)
    pnl_ratio = (exit_price - state['entry_price']) / state['entry_price']
    pnl = state['position_size'] * pnl_ratio
    margin_return = state['position_size'] / leverage
    fee = state['position_size'] * fee_rate
    state['capital'] += margin_return + pnl - fee
    state['trades'].append({
        'type': 'sell',
        'time': timestamp,
        'entry_price': state['entry_price'],
        'exit_price': exit_price,
        'size': state['position_size'],
        'pnl': pnl,
        'pnl_pct': pnl_ratio * 100 * leverage,
        'reason': reason,
    })
    state['position_size'] = 0.0
    state['entry_price'] = 0.0
    state['position_data'] = None


def _append_tuned_equity_point(state: dict, row: pd.Series, timestamp: str, leverage: float) -> None:
    current_equity = state['capital']
    if state['position_size'] > 0 and state['position_data']:
        pnl_ratio = (row['close'] - state['entry_price']) / state['entry_price']
        unrealized_pnl = state['position_size'] * pnl_ratio
        current_equity += (state['position_size'] / leverage) + unrealized_pnl
    state['equity_curve'].append({'date': timestamp[:10], 'equity': current_equity})


def _build_tuned_market_data(row: pd.Series):
    from trading.strategies.components.models import MarketData

    timestamp_value = row.get('timestamp')
    epoch_ms = int(timestamp_value.timestamp() * 1000) if hasattr(timestamp_value, 'timestamp') else 0
    return MarketData(
        symbol='BTC',
        close=row['close'],
        timestamp=epoch_ms,
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


def _resolve_tuned_regime(row: pd.Series):
    from trading.strategies.components.models import build_market_context

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
    return context, context.regime


def _handle_tuned_open_position(state: dict, row: pd.Series, timestamp: str, strategy_id: str, strategy_components: dict, context, leverage: float, fee_rate: float, slippage: float) -> bool:
    from types import MappingProxyType
    from trading.strategies.components.models import Position, TradingContext

    if state['position_size'] <= 0 or not state['position_data']:
        return False

    market_data = _build_tuned_market_data(row)
    pos = Position(
        symbol='BTC',
        entry_price=state['entry_price'],
        quantity=state['position_data']['quantity'],
        strategy=strategy_id,
        market='futures',
        timestamp=state['position_data']['timestamp'],
    )
    exit_ctx = TradingContext(
        symbol='BTC',
        timestamp=market_data.timestamp,
        market=market_data,
        regime=context,
        positions=MappingProxyType({strategy_id: pos}),
    )
    exit_signal = strategy_components['exit'].check_exit(exit_ctx, pos)
    if exit_signal:
        _close_tuned_position(state, row, timestamp, exit_signal.reason, leverage, fee_rate, slippage)
    return True


def _handle_tuned_entry(state: dict, row: pd.Series, strategy_components: dict, context, leverage: float, fee_rate: float, slippage: float, timestamp: str) -> None:
    from types import MappingProxyType
    from trading.strategies.components.models import TradingContext

    market_data = _build_tuned_market_data(row)
    entry_ctx = TradingContext(
        symbol='BTC',
        timestamp=market_data.timestamp,
        market=market_data,
        regime=context,
        positions=MappingProxyType({}),
    )
    entry_signal = strategy_components['entry'].check_entry(entry_ctx)
    if not entry_signal:
        return

    fraction = 0.3
    margin = state['capital'] * fraction
    position_size = margin * leverage
    fee = position_size * fee_rate
    if state['capital'] < (margin + fee):
        return

    state['capital'] -= (margin + fee)
    state['position_size'] = position_size
    state['entry_price'] = row['close'] * (1 + slippage)
    state['position_data'] = {
        'quantity': getattr(entry_signal, 'quantity', 0.0),
        'timestamp': market_data.timestamp,
    }
    state['trades'].append({
        'type': 'buy',
        'time': timestamp,
        'price': state['entry_price'],
        'size': state['position_size'],
        'reason': entry_signal.reason,
    })


def _run_tuned_backtest_loop(strategy_id: str, df: pd.DataFrame, regime_strategies: dict, initial_capital: float, leverage: float, fee_rate: float, slippage: float, job: BacktestJob) -> dict:
    state = {
        'capital': initial_capital,
        'position_size': 0.0,
        'entry_price': 0.0,
        'position_data': None,
        'trades': [],
        'equity_curve': [],
    }
    for i in range(len(df)):
        if job._cancelled:
            return {}
        row = df.iloc[i]
        timestamp = str(row.get('timestamp', row.name))
        if i < TimePeriods.BACKTEST_WARMUP:
            state['equity_curve'].append({'date': timestamp[:10], 'equity': state['capital']})
            continue

        context, current_regime = _resolve_tuned_regime(row)
        strategy_components = regime_strategies.get(current_regime)
        _append_tuned_equity_point(state, row, timestamp, leverage)

        if strategy_components is None:
            if state['position_size'] > 0:
                _close_tuned_position(
                    state, row, timestamp,
                    f"Regime changed to {current_regime} (no trading)",
                    leverage, fee_rate, slippage,
                )
            continue

        if _handle_tuned_open_position(
            state, row, timestamp, strategy_id, strategy_components, context, leverage, fee_rate, slippage
        ):
            continue
        _handle_tuned_entry(state, row, strategy_components, context, leverage, fee_rate, slippage, timestamp)
    return state


def _compute_tuned_performance(state: dict, initial_capital: float, leverage: float) -> dict:
    final_capital = state['capital']
    total_return_pct = (final_capital - initial_capital) / initial_capital * 100
    close_trades, wins, losses, win_rate, profit_factor = _compute_trade_stats(
        state['trades'], {'sell'}
    )
    sharpe_ratio, max_drawdown = _compute_equity_stats(state['equity_curve'])
    return {
        'final_capital': final_capital,
        'total_return_pct': total_return_pct,
        'close_trades': close_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'max_drawdown': max_drawdown,
        'sharpe_ratio': sharpe_ratio,
    }


def _format_tuned_trades(close_trades: list[dict]) -> list[dict]:
    formatted = []
    for trade in close_trades[:100]:
        formatted.append({
            'timestamp': trade.get('time'),
            'symbol': 'BTC',
            'action': 'BUY',
            'price': trade.get('entry_price'),
            'profit': None,
        })
        formatted.append({
            'timestamp': trade.get('time'),
            'symbol': 'BTC',
            'action': 'SELL',
            'price': trade.get('exit_price'),
            'profit': round(trade.get('pnl', 0), 0),
        })
    return formatted


def _finalize_tuned_results(state: dict, strategy_id: str, df: pd.DataFrame, initial_capital: float, leverage: float) -> dict:
    if state['position_size'] > 0:
        last_price = df.iloc[-1]['close']
        pnl_ratio = (last_price - state['entry_price']) / state['entry_price']
        pnl = state['position_size'] * pnl_ratio
        state['capital'] += (state['position_size'] / leverage) + pnl

    perf = _compute_tuned_performance(state, initial_capital, leverage)
    trades_list = _format_tuned_trades(perf['close_trades'])

    return {
        'strategy': strategy_id,
        'preset': 'tuned',
        'start_date': str(df.iloc[0].get('timestamp', df.index[0]))[:10],
        'end_date': str(df.iloc[-1].get('timestamp', df.index[-1]))[:10],
        'initial_capital': initial_capital,
        'final_capital': round(perf['final_capital'], 0),
        'total_return': round(perf['final_capital'] - initial_capital, 0),
        'total_return_pct': round(perf['total_return_pct'], 2),
        'leverage': leverage,
        'total_trades': len(perf['close_trades']),
        'winning_trades': len(perf['wins']),
        'losing_trades': len(perf['losses']),
        'win_rate': round(perf['win_rate'], 2),
        'profit_factor': round(perf['profit_factor'], 2),
        'max_drawdown': round(perf['max_drawdown'], 2),
        'max_drawdown_pct': round(perf['max_drawdown'], 2),
        'sharpe_ratio': round(perf['sharpe_ratio'], 2),
        'equity_curve': state['equity_curve'],
        'trades': trades_list,
    }


def _load_allocation_config() -> dict:
    import json

    allocation_path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
    if not allocation_path.exists():
        return {}
    with open(allocation_path, 'r') as file:
        return json.load(file)


def _resolve_generic_strategy_context(strategy_id: str, allocation: dict) -> dict:
    strategy_config = allocation.get('strategies', {}).get(strategy_id, {})
    base_strategy_id = strategy_id
    is_tuned_strategy = False
    is_new_config = False
    tuned_config = None

    if strategy_id in STRATEGY_REGISTRY:
        return {
            'strategy_config': strategy_config,
            'base_strategy_id': base_strategy_id,
            'is_tuned_strategy': False,
            'is_new_config': False,
            'tuned_config': None,
        }

    if not strategy_config:
        raise ValueError(f"Strategy {strategy_id} not found in registry or allocation.json")

    if 'regime_routing' in strategy_config:
        is_tuned_strategy = True
        tuned_config = strategy_config
    elif has_new_config_format(strategy_config):
        is_new_config = True
        logger.info(f"Using new config format for strategy '{strategy_id}'")
    else:
        base_strategy = strategy_config.get('base_strategy')
        if not base_strategy:
            for reg_name in STRATEGY_REGISTRY.keys():
                if strategy_id.startswith(reg_name):
                    base_strategy = reg_name
                    break
        if not base_strategy or base_strategy not in STRATEGY_REGISTRY:
            raise ValueError(f"Strategy {strategy_id} has no regime_routing and no valid base_strategy")
        base_strategy_id = base_strategy
        logger.info(f"Using base strategy '{base_strategy}' for '{strategy_id}'")

    return {
        'strategy_config': strategy_config,
        'base_strategy_id': base_strategy_id,
        'is_tuned_strategy': is_tuned_strategy,
        'is_new_config': is_new_config,
        'tuned_config': tuned_config,
    }


def _resolve_generic_market_settings(context: dict) -> dict:
    if context['is_tuned_strategy']:
        market_type = context['tuned_config'].get('market', 'futures')
        leverage = float(context['tuned_config'].get('leverage', 3))
        timeframe = 'minute60'
    elif context['is_new_config']:
        config = context['strategy_config']
        market_type = config.get('market', 'futures')
        leverage = float(config.get('leverage', 3))
        timeframe = config.get('timeframe', 'minute240')
    else:
        spec = STRATEGY_REGISTRY[context['base_strategy_id']]
        market_type = spec.market
        leverage = 3.0 if market_type == 'futures' else 1.0
        timeframe = spec.timeframe

    if market_type == 'futures':
        fee_rate = FeeRates.FUTURES
        slippage = FeeRates.FUTURES_SLIPPAGE
    else:
        fee_rate = FeeRates.SPOT
        slippage = FeeRates.SPOT_SLIPPAGE

    timeframe_map = {'hour1': 'minute60', 'hour4': 'minute240', '1h': 'minute60', '4h': 'minute240', '1d': 'day'}
    db_timeframe = timeframe_map.get(timeframe, timeframe)
    return {
        'market_type': market_type,
        'leverage': leverage,
        'timeframe': timeframe,
        'db_timeframe': db_timeframe,
        'fee_rate': fee_rate,
        'slippage': slippage,
    }


def _resolve_strategy_symbol(strategy_config: dict) -> str:
    symbols = strategy_config.get('symbols', []) if strategy_config else []
    return symbols[0] if symbols else "BTC"


def _load_backtest_df(strategy_symbol: str, db_timeframe: str, start_date: str, end_date: str) -> pd.DataFrame:
    from core.data_loader import DataLoader

    db_path = SYMBOL_DB_MAPPING.get(strategy_symbol, SYMBOL_DB_MAPPING["BTC"])
    logger.info(f"Backtest using symbol={strategy_symbol}, db={db_path.name}")
    with DataLoader(db_path=str(db_path)) as loader:
        return loader.load_timeframe(db_timeframe, start_date, end_date)


def _build_adapter_config(allocation: dict, strategy_id: str, strategy_config: dict, fee_rate: float, slippage: float) -> dict:
    config = dict(strategy_config or allocation.get('strategies', {}).get(strategy_id, {}))
    config.setdefault('core_fee_rate', fee_rate)
    config.setdefault('core_slippage', slippage)
    for key, value in _ADAPTER_DEFAULTS.items():
        config.setdefault(key, value)

    defaults = allocation.get('defaults', {}).get('regime_v2', {})
    for key in ['bbw_block_threshold', 'bbw_confirm_threshold', 'volume_block_ratio', 'volume_boost_ratio', 'mtf_enabled']:
        if key not in strategy_config and key in defaults:
            config[key] = defaults[key]
    return config


def _build_core_state(config: dict, initial_capital: float, fee_rate: float, slippage: float) -> dict:
    core_hold_pct = max(min(float(config.get("core_hold_pct", 0.0)), 0.95), 0.0)
    return {
        'hold_pct': core_hold_pct,
        'exit_on_ema200': bool(config.get("core_exit_on_ema200", False)),
        'ema_hours': int(config.get("core_ema_hours", 0)),
        'ema_timeframe': str(config.get("core_ema_timeframe", "")).lower(),
        'ema_span': int(config.get("core_ema_span", 0)),
        'reentry_on_ema200': bool(config.get("core_reentry_on_ema200", True)),
        'fee_rate': float(config.get("core_fee_rate", fee_rate)),
        'slippage': float(config.get("core_slippage", slippage)),
        'drawdown_exit_pct': float(config.get("core_drawdown_exit_pct", 0.0)),
        'drawdown_reentry_pct': float(config.get("core_drawdown_reentry_pct", 0.0)),
        'cash': initial_capital * core_hold_pct,
        'qty': 0.0,
        'active': False,
        'peak_price': 0.0,
    }


def _prepare_core_ema_columns(df: pd.DataFrame, core_state: dict, start_date: str, end_date: str) -> pd.DataFrame:
    from core.data_loader import DataLoader

    if core_state['hold_pct'] <= 0:
        return df

    if core_state['ema_timeframe'] in ("day", "daily"):
        core_span = core_state['ema_span'] if core_state['ema_span'] > 0 else 200
        with DataLoader(exchange="binance") as loader:
            day_df = loader.load_timeframe("day", start_date, end_date)
        if day_df.empty:
            return df
        day_df = day_df.copy()
        day_df["date"] = day_df["timestamp"].dt.date
        day_df["core_ema"] = day_df["close"].ewm(span=core_span, adjust=False).mean()
        df = df.copy()
        df["date"] = df["timestamp"].dt.date
        df = df.merge(day_df[["date", "core_ema"]], on="date", how="left")
        df.drop(columns=["date"], inplace=True)
        df["core_ema"] = df["core_ema"].ffill()
        return df

    if core_state['ema_hours'] > 0:
        df = df.copy()
        df["core_ema"] = df["close"].ewm(span=core_state['ema_hours'], adjust=False).mean()
    return df


def _passes_core_entry_filter(row: pd.Series, core_state: dict) -> bool:
    ema_200 = float(row.get("ema_200", 0.0) or 0.0)
    core_ema = float(row.get("core_ema", 0.0) or 0.0)
    price = float(row["close"])
    if core_ema > 0 and price < core_ema:
        return False
    if core_state['exit_on_ema200'] and ema_200 > 0 and price < ema_200:
        return False
    return True


def _enter_core_position(row: pd.Series, core_state: dict) -> None:
    if core_state['cash'] <= 0:
        return
    price = float(row["close"])
    entry_price = price * (1 + core_state['slippage'])
    qty = core_state['cash'] / (entry_price * (1 + core_state['fee_rate']))
    cost = qty * entry_price * (1 + core_state['fee_rate'])
    core_state['cash'] -= cost
    core_state['qty'] = qty
    core_state['active'] = qty > 0
    core_state['peak_price'] = price


def _initialize_core_position(df: pd.DataFrame, core_state: dict) -> None:
    if core_state['hold_pct'] <= 0 or df.empty:
        return
    first_row = df.iloc[0]
    if _passes_core_entry_filter(first_row, core_state):
        _enter_core_position(first_row, core_state)


def _close_core_position(price: float, core_state: dict) -> None:
    exit_price = price * (1 - core_state['slippage'])
    proceeds = core_state['qty'] * exit_price * (1 - core_state['fee_rate'])
    core_state['cash'] += proceeds
    core_state['qty'] = 0.0
    core_state['active'] = False


def _can_core_reenter(price: float, row: pd.Series, core_state: dict) -> bool:
    if not core_state['reentry_on_ema200']:
        return False
    if not _passes_core_entry_filter(row, core_state):
        return False
    if core_state['drawdown_reentry_pct'] <= 0 or core_state['peak_price'] <= 0:
        return True
    drawdown_pct = (core_state['peak_price'] - price) / core_state['peak_price'] * 100
    return drawdown_pct <= core_state['drawdown_reentry_pct']


def _update_core_position(row: pd.Series, core_state: dict) -> None:
    if core_state['hold_pct'] <= 0:
        return

    price = float(row["close"])
    if core_state['active']:
        core_state['peak_price'] = max(core_state['peak_price'], price)
        drawdown_pct = 0.0
        if core_state['peak_price'] > 0:
            drawdown_pct = (core_state['peak_price'] - price) / core_state['peak_price'] * 100
        exit_on_drawdown = core_state['drawdown_exit_pct'] > 0 and drawdown_pct >= core_state['drawdown_exit_pct']
        exit_on_filter = not _passes_core_entry_filter(row, core_state)
        if exit_on_drawdown or exit_on_filter:
            _close_core_position(price, core_state)
        return

    if _can_core_reenter(price, row, core_state):
        _enter_core_position(row, core_state)


def _compute_position_equity(trade_state: dict, current_price: float, adapter: ComponentStrategyAdapter) -> float:
    if trade_state['position_size'] <= 0:
        return trade_state['capital']
    if adapter.current_position and adapter.current_position.side == 'short':
        pnl_ratio = (trade_state['entry_price'] - current_price) / trade_state['entry_price']
    else:
        pnl_ratio = (current_price - trade_state['entry_price']) / trade_state['entry_price']
    unrealized_pnl = trade_state['position_size'] * pnl_ratio
    return trade_state['capital'] + (trade_state['position_size'] / trade_state['position_leverage']) + unrealized_pnl


def _execute_open_trade(action: str, signal: dict, row: pd.Series, trade_state: dict, leverage: float, fee_rate: float, slippage: float, timestamp: str, reason: str) -> None:
    if trade_state['position_size'] != 0:
        return
    if action not in ('buy', 'open_short'):
        return

    fraction = signal.get('fraction', 1.0 if action == 'buy' else 0.3)
    effective_leverage = signal.get('leverage', leverage)
    margin = trade_state['capital'] * fraction / (1 + effective_leverage * fee_rate)
    position_size = margin * effective_leverage
    fee = position_size * fee_rate
    if trade_state['capital'] < (margin + fee):
        return

    trade_state['capital'] -= (margin + fee)
    trade_state['position_size'] = position_size
    trade_state['position_leverage'] = effective_leverage
    trade_state['entry_price'] = row['close'] * (1 + slippage) if action == 'buy' else row['close'] * (1 - slippage)
    trade_state['entry_timestamp'] = timestamp
    trade_state['trades'].append({
        'type': action,
        'time': timestamp,
        'price': trade_state['entry_price'],
        'size': position_size,
        'reason': reason,
        'leverage': effective_leverage,
    })


def _execute_close_trade(action: str, signal: dict, row: pd.Series, trade_state: dict, fee_rate: float, slippage: float, timestamp: str, reason: str) -> None:
    if action not in ('sell', 'close_short') or trade_state['position_size'] <= 0:
        return
    exit_fraction = signal.get('fraction', 1.0)
    exit_size = trade_state['position_size'] * exit_fraction
    is_short = action == 'close_short'
    exit_price = row['close'] * (1 + slippage) if is_short else row['close'] * (1 - slippage)
    if is_short:
        pnl_ratio = (trade_state['entry_price'] - exit_price) / trade_state['entry_price']
    else:
        pnl_ratio = (exit_price - trade_state['entry_price']) / trade_state['entry_price']
    pnl = exit_size * pnl_ratio
    margin_return = exit_size / trade_state['position_leverage']
    fee = exit_size * fee_rate
    trade_state['capital'] += margin_return + pnl - fee
    trade_state['trades'].append({
        'type': action,
        'time': timestamp,
        'entry_time': trade_state['entry_timestamp'],
        'entry_price': trade_state['entry_price'],
        'exit_price': exit_price,
        'size': exit_size,
        'pnl': pnl,
        'pnl_pct': pnl_ratio * 100 * trade_state['position_leverage'],
        'reason': reason,
        'leverage': trade_state['position_leverage'],
    })
    if exit_fraction >= 1.0:
        trade_state['position_size'] = 0.0
        trade_state['entry_price'] = 0.0
        trade_state['entry_timestamp'] = None
    else:
        trade_state['position_size'] -= exit_size


def _sample_trades(close_trades: list[dict], max_trades: int = 150) -> list[dict]:
    if len(close_trades) <= max_trades:
        return close_trades
    step = len(close_trades) / max_trades
    return [close_trades[int(i * step)] for i in range(max_trades)]


def _format_generic_trades(close_trades: list[dict]) -> list[dict]:
    trades_list = []
    for trade in _sample_trades(close_trades):
        is_short = trade['type'] == 'close_short'
        trades_list.append({
            'timestamp': trade.get('entry_time') or trade.get('time'),
            'symbol': 'BTC',
            'action': 'SHORT' if is_short else 'BUY',
            'price': trade.get('entry_price'),
            'profit': None,
        })
        trades_list.append({
            'timestamp': trade.get('time'),
            'symbol': 'BTC',
            'action': 'COVER' if is_short else 'SELL',
            'price': trade.get('exit_price'),
            'profit': round(trade.get('pnl', 0), 0),
        })
    return trades_list


def _finalize_generic_trade_state(trade_state: dict, adapter: ComponentStrategyAdapter, core_state: dict, df: pd.DataFrame) -> None:
    if trade_state['position_size'] > 0:
        last_price = float(df.iloc[-1]['close'])
        if adapter.current_position and adapter.current_position.side == 'short':
            pnl_ratio = (trade_state['entry_price'] - last_price) / trade_state['entry_price']
        else:
            pnl_ratio = (last_price - trade_state['entry_price']) / trade_state['entry_price']
        pnl = trade_state['position_size'] * pnl_ratio
        trade_state['capital'] += (trade_state['position_size'] / trade_state['position_leverage']) + pnl
    if core_state['hold_pct'] > 0:
        last_price = float(df.iloc[-1]['close'])
        trade_state['capital'] += core_state['cash'] + (core_state['qty'] * last_price)


def _build_generic_result(strategy_id: str, start_date: str, end_date: str, initial_capital: float, leverage: float, trade_state: dict) -> dict:
    close_trades, wins, losses, win_rate, profit_factor = _compute_trade_stats(
        trade_state['trades'], {'sell', 'close_short', 'partial_close'}
    )
    sharpe_ratio, max_drawdown = _compute_equity_stats(trade_state['equity_curve'])
    final_capital = trade_state['capital']
    return {
        'strategy': strategy_id,
        'preset': 'generic',
        'start_date': start_date,
        'end_date': end_date,
        'initial_capital': initial_capital,
        'final_capital': round(final_capital, 0),
        'total_return': round(final_capital - initial_capital, 0),
        'total_return_pct': round((final_capital - initial_capital) / initial_capital * 100, 2),
        'leverage': leverage,
        'total_trades': len(close_trades),
        'winning_trades': len(wins),
        'losing_trades': len(losses),
        'win_rate': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'max_drawdown': round(max_drawdown, 2),
        'max_drawdown_pct': round(max_drawdown, 2),
        'sharpe_ratio': round(sharpe_ratio, 2),
        'equity_curve': trade_state['equity_curve'],
        'trades': _format_generic_trades(close_trades),
    }


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
    allocation = _load_allocation_config()
    context = _resolve_generic_strategy_context(strategy_id, allocation)
    market_settings = _resolve_generic_market_settings(context)
    strategy_symbol = _resolve_strategy_symbol(context['strategy_config'])
    df = _load_backtest_df(strategy_symbol, market_settings['db_timeframe'], start_date, end_date)
    if df.empty:
        raise ValueError(f"No data available for {strategy_symbol} from {start_date} to {end_date}")

    job.progress = 20
    add_all_indicators(df)
    job.progress = 30

    if context['is_tuned_strategy']:
        return _run_tuned_strategy_backtest(
            strategy_id,
            context['tuned_config'],
            df,
            initial_capital,
            market_settings['leverage'],
            market_settings['fee_rate'],
            market_settings['slippage'],
            job,
        )

    config = _build_adapter_config(
        allocation,
        strategy_id,
        context['strategy_config'],
        market_settings['fee_rate'],
        market_settings['slippage'],
    )
    adapter = ComponentStrategyAdapter(StrategyFactory(redis=None), context['base_strategy_id'], config)
    adapter.symbol = strategy_symbol

    if adapter._uses_mlp_direction:
        adapter.precompute_mlp_predictions(df)
        job.progress = 45

    core_state = _build_core_state(config, initial_capital, market_settings['fee_rate'], market_settings['slippage'])
    df = _prepare_core_ema_columns(df, core_state, start_date, end_date)
    _initialize_core_position(df, core_state)

    trade_state = {
        'capital': initial_capital - core_state['cash'],
        'position_size': 0.0,
        'entry_price': 0.0,
        'entry_timestamp': None,
        'position_leverage': market_settings['leverage'],
        'trades': [],
        'equity_curve': [],
    }
    for i in range(len(df)):
        if job._cancelled:
            return {}, df
        row = df.iloc[i]
        timestamp = str(row.get('timestamp', row.name))
        _update_core_position(row, core_state)

        current_equity = _compute_position_equity(trade_state, float(row['close']), adapter)
        if core_state['hold_pct'] > 0:
            current_equity += core_state['cash'] + (core_state['qty'] * row['close'])
        adapter.update_equity(current_equity)
        signal = adapter(df, i)
        action = signal.get('action', 'hold')
        reason = signal.get('reason', '')
        trade_state['equity_curve'].append({'date': timestamp[:10], 'equity': current_equity})
        _execute_open_trade(
            action, signal, row, trade_state,
            market_settings['leverage'], market_settings['fee_rate'], market_settings['slippage'],
            timestamp, reason,
        )
        _execute_close_trade(
            action, signal, row, trade_state, market_settings['fee_rate'], market_settings['slippage'], timestamp, reason
        )

    job.progress = 80
    _finalize_generic_trade_state(trade_state, adapter, core_state, df)
    return _build_generic_result(
        strategy_id, start_date, end_date, initial_capital, market_settings['leverage'], trade_state
    ), df


class _EnhancedShortStrategyAdapter:
    def __init__(self, config=None):
        from trading.strategies.components.strategy_factory import StrategyFactory
        from core.component_adapter import ComponentStrategyAdapter

        self.config = config or {}
        self.factory = StrategyFactory(redis=None)
        self.adapter = ComponentStrategyAdapter(self.factory, "short_v1", self.config)
        self._indicators_added = False
        self._cached_df = None

    def _ensure_indicators(self, df: pd.DataFrame) -> None:
        if self._indicators_added:
            return
        from trading.indicators import add_all_indicators, technical as ta

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
            self._cached_df['adx'], self._cached_df['plus_di'], self._cached_df['minus_di'] = ta.adx(
                high, low, close, period=adx_period
            )
        self._cached_df['adx_slope'] = self._cached_df['adx'].diff()
        self._indicators_added = True

    def execute(self, df: pd.DataFrame, i: int) -> dict:
        if i < 200:
            return {'action': 'hold', 'reason': 'WARMUP'}
        self._ensure_indicators(df)
        return self.adapter(self._cached_df, i)


class _BasicShortStrategy:
    def __init__(self, config=None):
        self.config = config or {
            'ema_fast': 50, 'ema_slow': 200, 'adx_threshold': 25,
            'stop_loss_pct': 2.0, 'take_profit_pct': 5.0, 'position_size': 0.3,
        }
        self.in_position = False
        self.entry_price = 0.0
        self._cached_df = None

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        import numpy as np

        df = df.copy()
        df['ema_fast'] = df['close'].ewm(span=self.config['ema_fast'], adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=self.config['ema_slow'], adjust=False).mean()
        df['death_cross'] = (df['ema_fast'] < df['ema_slow']) & (df['ema_fast'].shift(1) >= df['ema_slow'].shift(1))
        df['golden_cross'] = (df['ema_fast'] > df['ema_slow']) & (df['ema_fast'].shift(1) <= df['ema_slow'].shift(1))
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))),
        )
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

    def _check_position_exit(self, row: pd.Series) -> dict:
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

    def _check_entry(self, row: pd.Series) -> dict:
        if not row.get('death_cross', False):
            return {'action': 'hold', 'reason': 'NO_SIGNAL'}
        adx = row.get('adx', 0)
        plus_di = row.get('plus_di', 0)
        minus_di = row.get('minus_di', 0)
        if adx < self.config['adx_threshold'] or minus_di <= plus_di:
            return {'action': 'hold', 'reason': 'NO_SIGNAL'}
        self.in_position = True
        self.entry_price = row['close']
        return {
            'action': 'open_short',
            'fraction': self.config.get('position_size', 0.3),
            'reason': f'DEATH_CROSS: ADX={adx:.1f}',
        }

    def execute(self, df: pd.DataFrame, i: int) -> dict:
        if i < 200:
            return {'action': 'hold', 'reason': 'WARMUP'}
        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = self._add_indicators(df)
        row = self._cached_df.iloc[i]
        if self.in_position:
            return self._check_position_exit(row)
        return self._check_entry(row)


def _build_short_strategy(preset: str):
    return _EnhancedShortStrategyAdapter() if preset == 'enhanced' else _BasicShortStrategy()


def _apply_short_signal(state: dict, row: pd.Series, signal: dict, leverage: float, fee_rate: float, slippage: float) -> None:
    action = signal.get('action', 'hold')
    timestamp = str(row.get('timestamp', row.name))
    if action == 'open_short' and state['position_size'] == 0:
        fraction = signal.get('fraction', 0.3)
        margin = state['capital'] * fraction
        state['position_size'] = margin * leverage
        state['initial_position_size'] = state['position_size']
        state['entry_price'] = row['close'] * (1 - slippage)
        fee = state['position_size'] * fee_rate
        state['capital'] -= margin + fee
        state['trades'].append({
            'type': 'open_short',
            'time': timestamp,
            'price': state['entry_price'],
            'size': state['position_size'],
            'reason': signal.get('reason', ''),
        })
        return

    if action == 'partial_close' and state['position_size'] > 0:
        close_fraction = signal.get('fraction', 0.5)
        close_size = state['initial_position_size'] * close_fraction
        exit_price = row['close'] * (1 + slippage)
        pnl_ratio = (state['entry_price'] - exit_price) / state['entry_price']
        pnl = close_size * pnl_ratio
        fee = close_size * fee_rate
        margin_return = close_size / leverage
        state['capital'] += margin_return + pnl - fee
        state['position_size'] -= close_size
        state['trades'].append({
            'type': 'partial_close',
            'time': timestamp,
            'entry_price': state['entry_price'],
            'exit_price': exit_price,
            'size': close_size,
            'pnl': pnl,
            'pnl_pct': pnl_ratio * 100 * leverage,
            'reason': signal.get('reason', ''),
        })
        return

    if action == 'close_short' and state['position_size'] > 0:
        exit_price = row['close'] * (1 + slippage)
        pnl_ratio = (state['entry_price'] - exit_price) / state['entry_price']
        pnl = state['position_size'] * pnl_ratio
        fee = state['position_size'] * fee_rate
        margin_return = state['position_size'] / leverage
        state['capital'] += margin_return + pnl - fee
        state['trades'].append({
            'type': 'close_short',
            'time': timestamp,
            'entry_price': state['entry_price'],
            'exit_price': exit_price,
            'size': state['position_size'],
            'pnl': pnl,
            'pnl_pct': pnl_ratio * 100 * leverage,
            'reason': signal.get('reason', ''),
        })
        state['position_size'] = 0.0
        state['entry_price'] = 0.0
        state['initial_position_size'] = 0.0


def _append_short_equity(state: dict, row: pd.Series, leverage: float) -> None:
    if state['position_size'] > 0:
        unrealized_ratio = (state['entry_price'] - row['close']) / state['entry_price']
        unrealized_pnl = state['position_size'] * unrealized_ratio
        current_equity = state['capital'] + (state['position_size'] / leverage) + unrealized_pnl
    else:
        current_equity = state['capital']
    state['equity_curve'].append({'date': str(row.get('timestamp', row.name))[:10], 'equity': current_equity})


def _run_short_loop(df: pd.DataFrame, strategy, initial_capital: float, leverage: float, fee_rate: float, slippage: float, job: BacktestJob) -> dict:
    state = {
        'capital': initial_capital,
        'position_size': 0.0,
        'entry_price': 0.0,
        'initial_position_size': 0.0,
        'trades': [],
        'equity_curve': [],
    }
    for i in range(len(df)):
        if job._cancelled:
            return {}
        row = df.iloc[i]
        signal = strategy.execute(df, i)
        _apply_short_signal(state, row, signal, leverage, fee_rate, slippage)
        _append_short_equity(state, row, leverage)
    return state


def _compute_trade_stats(trades: list[dict], close_types: set[str]) -> tuple[list[dict], list[float], list[float], float, float]:
    close_trades = []
    wins = []
    losses = []
    for trade in trades:
        if trade.get('type') not in close_types:
            continue
        close_trades.append(trade)
        pnl = trade.get('pnl', 0)
        if pnl > 0:
            wins.append(pnl)
        else:
            losses.append(pnl)
    win_rate = len(wins) / len(close_trades) * 100 if close_trades else 0
    profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 0
    return close_trades, wins, losses, win_rate, profit_factor


def _compute_equity_stats(equity_curve: list[dict]) -> tuple[float, float]:
    import numpy as np

    equity_series = pd.Series([entry['equity'] for entry in equity_curve])
    returns = equity_series.pct_change().dropna()
    sharpe = (
        float(returns.mean() / returns.std() * np.sqrt(TimePeriods.TRADING_DAYS_PER_YEAR))
        if len(returns) > 0 and returns.std() > 0 else 0
    )
    peak = equity_series.cummax()
    drawdown = (equity_series - peak) / peak * 100
    return sharpe, float(drawdown.min())


def _format_short_trades(close_trades: list[dict]) -> list[dict]:
    trades_list = []
    for trade in close_trades[:50]:
        if trade.get('entry_price'):
            trades_list.append({
                'timestamp': trade.get('entry_time', trade.get('time')),
                'symbol': 'BTC',
                'action': 'SHORT',
                'price': trade.get('entry_price', 0),
                'profit': None,
            })
        trades_list.append({
            'timestamp': trade.get('time'),
            'symbol': 'BTC',
            'action': 'COVER' if trade['type'] == 'close_short' else 'PARTIAL',
            'price': trade.get('exit_price', 0),
            'profit': round(trade.get('pnl', 0), 0),
        })
    return trades_list


def _finalize_short_results(state: dict, strategy_id: str, preset: str, start_date: str, end_date: str, initial_capital: float, leverage: float, last_close: float) -> dict:

    if state['position_size'] > 0:
        pnl_ratio = (state['entry_price'] - last_close) / state['entry_price']
        pnl = state['position_size'] * pnl_ratio
        state['capital'] += (state['position_size'] / leverage) + pnl

    final_capital = state['capital']
    close_trades, wins, losses, win_rate, profit_factor = _compute_trade_stats(
        state['trades'], {'close_short', 'partial_close'}
    )
    sharpe, mdd = _compute_equity_stats(state['equity_curve'])
    trades_list = _format_short_trades(close_trades)

    total_return_pct = (final_capital - initial_capital) / initial_capital * 100
    return {
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
        'equity_curve': state['equity_curve'],
        'trades': trades_list,
    }


def _run_short_backtest(
    strategy_id: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    job: BacktestJob
) -> dict:
    """Run short strategy backtest aligned with scripts/backtest_short.py logic."""
    from core.data_loader import DataLoader

    preset = 'baseline' if strategy_id == 'short_v1_baseline' else 'enhanced'
    leverage = 3
    timeframe = 'minute240'
    fee_rate = FeeRates.FUTURES
    slippage = FeeRates.FUTURES_SLIPPAGE

    job.progress = 20
    with DataLoader(exchange='binance') as loader:
        df = loader.load_timeframe(timeframe, start_date, end_date)
    if df.empty:
        raise ValueError(f"No data available for {start_date} to {end_date}")

    job.progress = 30
    strategy = _build_short_strategy(preset)
    job.progress = 40
    state = _run_short_loop(df, strategy, initial_capital, leverage, fee_rate, slippage, job)
    if not state:
        return {}, df

    job.progress = 80
    return _finalize_short_results(
        state,
        strategy_id,
        preset,
        start_date,
        end_date,
        initial_capital,
        leverage,
        float(df.iloc[-1]['close']),
    ), df





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
