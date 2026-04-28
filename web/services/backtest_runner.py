"""
Backtest runner service for executing backtests via web dashboard.

Runs backtests using the shared component adapter and registry.
Integrates with MLflow visualization for chart generation and experiment tracking.
"""

# pylint: disable=broad-exception-caught

import sys
from pathlib import Path
import logging
import os
import time

# Add project root to path for imports (core, scripts, etc.)
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional
import traceback
import pandas as pd

# MLflow visualization imports
from core.backtest_visualizer import BacktestVisualizer
from core.mlflow_tracker import MLflowTracker
from core.metrics import calculate_benchmark

# Database persistence
from web.services import backtest_db
from trading.strategies.components.strategy_factory import (
    StrategyFactory,
    STRATEGY_REGISTRY,
)
from trading.strategies.components.config_schema import has_new_config_format
from core.component_adapter import ComponentStrategyAdapter
from trading.indicators import add_all_indicators
from trading.config.constants import FeeRates, TimePeriods
from trading.core.runtime_defaults import default_backtest_date_range

logger = logging.getLogger(__name__)

INTERNAL_ONLY_BACKTEST_STRATEGIES = {"llm_direction"}
BACKTEST_ONLY_STRATEGIES = (
    {
        "id": "wf_tree60_btc",
        "name": "Walk-Forward Tree60 BTC",
        "description": "Backtest-only walk-forward XGB+LGB ensemble (BTC spot)",
    },
    {
        "id": "wf_tree60_eth",
        "name": "Walk-Forward Tree60 ETH",
        "description": "Backtest-only walk-forward XGB+LGB ensemble (ETH spot)",
    },
    {
        "id": "wf_tree60_sol",
        "name": "Walk-Forward Tree60 SOL",
        "description": "Backtest-only walk-forward XGB+LGB ensemble (SOL spot)",
    },
)

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
STALE_DB_JOB_MINUTES = 10

# Chart output directory
CHART_OUTPUT_DIR = PROJECT_ROOT / "web" / "static" / "charts"
CHART_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Timestamp guard for stale job reconciliation
_stale_reconcile_state = {"last_at": 0.0}

# Initialize visualization components
_visualizer = BacktestVisualizer()
_mlflow_tracker = MLflowTracker()

_ADAPTER_DEFAULTS = {
    "regime_version": "v2",
    "position_size": 0.01,
    "position_pct": 0.3,
    "dynamic_sizing": False,
    "core_hold_pct": 0.0,
    "core_exit_on_ema200": False,
    "core_ema_hours": 0,
    "core_ema_timeframe": "",
    "core_ema_span": 0,
    "core_reentry_on_ema200": True,
    "core_drawdown_exit_pct": 0.0,
    "core_drawdown_reentry_pct": 0.0,
    "use_breakout_filter": True,
    "bbw_block_threshold": 25,
    "bbw_confirm_threshold": 50,
    "volume_block_ratio": 0.8,
    "volume_boost_ratio": 1.2,
    "mtf_enabled": True,
    "stop_loss_cooldown": 24,
    "trailing_enabled": False,
    "trailing_activation": 3.0,
    "trailing_distance": 2.0,
    "atr_stop_enabled": False,
    "atr_stop_multiplier": 2.0,
    "atr_stop_min_pct": 1.5,
    "atr_stop_max_pct": 4.0,
    "dynamic_leverage": False,
    "leverage_bull_strong": 3.0,
    "leverage_bull_moderate": 2.0,
    "leverage_sideways": 1.0,
    "leverage_bear": 0.0,
    "cash_in_bear": False,
    "cash_below_ema200": False,
    "max_consecutive_losses": 3,
    "loss_pause_candles": 48,
    "drawdown_enabled": True,
    "drawdown_warning_pct": 8.0,
    "drawdown_reduce_pct": 10.0,
    "drawdown_exit_pct": 12.0,
    "drawdown_leverage_reduction": 0.5,
    "drawdown_partial_exit_fraction": 0.5,
    "v2_exit_on_filter": False,
    "bull_prob_threshold": 0.0,
    "panic_sell_below_ma120": False,
    "prob_leverage_enabled": False,
    "prob_leverage_max": 3.0,
    "prob_leverage_high": 2.5,
    "prob_leverage_mid": 2.0,
    "prob_leverage_low": 1.0,
    "prob_leverage_min": 0.5,
}


def _is_tuned_strategy(strategy_id: str) -> bool:
    """Check if a strategy is a tuned strategy from allocation.json with regime_routing."""
    import json

    allocation_path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
    if not allocation_path.exists():
        return False
    try:
        with open(allocation_path, "r", encoding="utf-8") as f:
            allocation = json.load(f)
        strategy_config = allocation.get("strategies", {}).get(strategy_id, {})
        return "regime_routing" in strategy_config
    except Exception:
        return False


def _is_new_config_strategy(strategy_id: str) -> bool:
    """Check if a strategy in allocation.json uses new config format (entry.class/exit.class)."""
    import json

    allocation_path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
    if not allocation_path.exists():
        return False
    try:
        with open(allocation_path, "r", encoding="utf-8") as f:
            allocation = json.load(f)
        strategy_config = allocation.get("strategies", {}).get(strategy_id, {})
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
        with open(allocation_path, "r", encoding="utf-8") as f:
            allocation = json.load(f)
        if strategy_id not in allocation.get("strategies", {}):
            return False
        strategy_config = allocation["strategies"][strategy_id]
        # Check explicit base_strategy field
        base_strategy = strategy_config.get("base_strategy")
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
    results: dict, price_data: pd.DataFrame, strategy_id: str, job_id: str
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
        initial_capital = results.get("initial_capital", 10000000)
        benchmark_curve = _add_benchmark_to_results(
            results, price_data, initial_capital
        )
        chart_path = _generate_equity_chart(
            results, strategy_id, job_id, benchmark_curve
        )
        _generate_regime_charts(results, price_data, strategy_id, job_id)
        _log_results_to_mlflow(results, strategy_id, initial_capital, chart_path)

    except Exception as e:
        logger.warning("Visualization/MLflow logging failed: %s", e)
        traceback.print_exc()

    return results


def _add_benchmark_to_results(
    results: dict,
    price_data: pd.DataFrame,
    initial_capital: float,
):
    """Calculate benchmark curve and append frontend-friendly benchmark data."""
    if price_data.empty or "close" not in price_data.columns:
        return None

    if "timestamp" not in price_data.columns:
        price_data = price_data.copy()
        price_data["timestamp"] = price_data.index

    benchmark_curve, benchmark_return_pct = calculate_benchmark(
        price_data, initial_capital
    )
    results["benchmark_return_pct"] = round(benchmark_return_pct, 2)

    if benchmark_curve is not None and len(benchmark_curve) > 0:
        results["benchmark_curve"] = [
            {"date": str(ts)[:10], "equity": equity}
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
    equity_data = results.get("equity_curve", [])
    if not equity_data:
        return None

    equity_df = pd.DataFrame(equity_data)
    equity_df["timestamp"] = pd.to_datetime(equity_df["date"])
    equity_df["total_equity"] = equity_df["equity"]

    chart_filename = f"backtest_{strategy_id}_{job_id}.png"
    chart_path = CHART_OUTPUT_DIR / chart_filename
    chart_result = {
        "equity_curve": equity_df,
        "benchmark_curve": benchmark_curve,
        "strategy_name": strategy_id,
        "symbol": results.get("symbol", "BTC"),
        "total_return": results.get("total_return_pct", 0),
        "benchmark_return_pct": results.get("benchmark_return_pct", 0),
    }

    saved_path = _visualizer.create_chart(
        chart_result,
        output_path=str(chart_path),
        title=f"{strategy_id} Backtest",
    )
    if saved_path:
        results["chart_path"] = f"/static/charts/{chart_filename}"
        logger.info("Generated chart: %s", saved_path)
        return chart_path
    return None


def _generate_regime_charts(
    results: dict,
    price_data: pd.DataFrame,
    strategy_id: str,
    job_id: str,
) -> None:
    """Generate regime and yearly regime charts."""
    if price_data.empty or "close" not in price_data.columns:
        return
    try:
        regime_filename = f"regime_{strategy_id}_{job_id}.png"
        regime_path = CHART_OUTPUT_DIR / regime_filename
        trades_for_chart = _convert_trades_for_regime_chart(results.get("trades", []))

        saved_regime_path = _visualizer.create_regime_chart(
            price_data,
            trades=trades_for_chart if trades_for_chart else None,
            equity_curve=results.get("equity_curve"),
            output_path=str(regime_path),
            title=f"{strategy_id} Regime Analysis",
        )
        if saved_regime_path:
            results["regime_chart_path"] = f"/static/charts/{regime_filename}"
            logger.info("Generated regime chart: %s", saved_regime_path)

        years = _count_years(price_data)
        if years >= 2:
            yearly_dir = CHART_OUTPUT_DIR / f"yearly_{strategy_id}_{job_id}"
            yearly_paths = _visualizer.create_yearly_regime_charts(
                price_data,
                trades=trades_for_chart,
                equity_curve=results.get("equity_curve"),
                output_dir=str(yearly_dir),
                title_prefix=f"{strategy_id}",
            )
            if yearly_paths:
                results["yearly_chart_paths"] = [
                    f"/static/charts/yearly_{strategy_id}_{job_id}/{Path(p).name}"
                    for p in yearly_paths
                ]
                logger.info("Generated %d yearly charts", len(yearly_paths))
    except Exception as e:
        logger.warning("Regime chart generation failed: %s", e)


def _convert_trades_for_regime_chart(raw_trades: list[dict]) -> list[dict]:
    """Convert frontend trade actions to regime chart buy/sell markers."""
    converted = []
    for trade in raw_trades:
        action = trade.get("action", "").upper()
        if action in ("BUY", "LONG", "ENTRY"):
            converted.append(
                {
                    "timestamp": trade.get("timestamp"),
                    "action": "buy",
                    "price": trade.get("price"),
                }
            )
        elif action in ("SELL", "SHORT", "EXIT", "COVER"):
            converted.append(
                {
                    "timestamp": trade.get("timestamp"),
                    "action": "sell",
                    "price": trade.get("price"),
                }
            )
    return converted


def _count_years(price_data: pd.DataFrame) -> int:
    """Count distinct years in price data."""
    if "timestamp" in price_data.columns:
        return price_data["timestamp"].dt.year.nunique()
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
        "strategy_name": strategy_id,
        "symbol": results.get("symbol", "BTC"),
        "total_return": results.get("total_return_pct", 0),
        "sharpe_ratio": results.get("sharpe_ratio", 0),
        "max_drawdown_pct": results.get("max_drawdown_pct", 0),
        "win_rate": results.get("win_rate", 0),
        "total_trades": results.get("total_trades", 0),
        "profit_factor": results.get("profit_factor", 0),
        "benchmark_return_pct": results.get("benchmark_return_pct", 0),
        "params": {
            "start_date": results.get("start_date"),
            "end_date": results.get("end_date"),
            "initial_capital": initial_capital,
            "leverage": results.get("leverage", 1),
        },
    }
    chart_artifact = str(chart_path) if chart_path is not None else None
    run_id = _mlflow_tracker.log_run(mlflow_result, chart_path=chart_artifact)
    if run_id:
        results["mlflow_run_id"] = run_id
        results["mlflow_url"] = _mlflow_tracker.get_run_url(run_id)
        logger.info("Logged to MLflow: run_id=%s", run_id)


class BacktestJob:
    """Represents a backtest job."""

    def __init__(self, job_id: str, config: dict):
        self.job_id = job_id
        self.config = config
        self.status = "pending"  # pending, running, completed, failed, cancelled
        self.progress = 0
        self.result = None
        self.error = None
        self.created_at = datetime.now().isoformat()
        self.started_at = None
        self.completed_at = None
        self._thread: Optional[threading.Thread] = None
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @cancelled.setter
    def cancelled(self, value: bool) -> None:
        self._cancelled = bool(value)

    @property
    def thread(self) -> Optional[threading.Thread]:
        return self._thread

    @thread.setter
    def thread(self, value: Optional[threading.Thread]) -> None:
        self._thread = value

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "config": self.config,
            "status": self.status,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


def get_available_strategies() -> list:
    """Get list of available strategies dynamically from StrategyFactory and allocation.json."""
    strategies: list[dict] = []
    existing_ids: set[str] = set()
    allocation_strategies = _load_allocation_strategies()
    _append_factory_strategies(strategies, existing_ids, allocation_strategies)
    _append_allocation_only_strategies(strategies, existing_ids, allocation_strategies)
    _append_backtest_only_strategies(strategies, existing_ids)
    return strategies


def _load_allocation_strategies() -> dict:
    import json

    allocation_path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
    if not allocation_path.exists():
        return {}
    try:
        with open(allocation_path, "r", encoding="utf-8") as f:
            allocation = json.load(f)
        return allocation.get("strategies", {})
    except Exception as e:
        print(f"Error preloading allocation.json strategies: {e}")
        return {}


def _append_factory_strategies(
    strategies: list, existing_ids: set[str], allocation_strategies: dict
) -> None:
    try:
        for name, spec in STRATEGY_REGISTRY.items():
            if name in INTERNAL_ONLY_BACKTEST_STRATEGIES:
                continue
            if getattr(spec, "market", "spot") != "spot":
                continue
            # Dashboard backtest list should mirror operational strategy management:
            # only include registry bases when they are explicitly configured and enabled.
            if name not in allocation_strategies:
                continue
            if not allocation_strategies[name].get("enabled", True):
                continue
            strategies.append(
                {
                    "id": name,
                    "name": name.replace("_", " ").title(),
                    "description": f"Spot strategy ({name})",
                    "exchange": "binance",
                    "default_params": {},
                }
            )
            existing_ids.add(name)
    except Exception as e:
        print(f"Error loading factory strategies: {e}")


def _append_allocation_only_strategies(
    strategies: list, existing_ids: set[str], allocation_strategies: dict
) -> None:
    try:
        for name, config in allocation_strategies.items():
            if name in INTERNAL_ONLY_BACKTEST_STRATEGIES:
                continue
            if not config.get("enabled", True) or name in existing_ids:
                continue
            if config.get("market", "spot") != "spot":
                continue
            is_tuned = "tuned_config" in config or "regime_routing" in config
            strategy_kind = "Tuned" if is_tuned else "Custom"
            strategies.append(
                {
                    "id": name,
                    "name": name.replace("_", " ").title(),
                    "description": f"{strategy_kind} Spot strategy",
                    "exchange": "binance",
                    "default_params": {},
                    "is_tuned": is_tuned,
                }
            )
            existing_ids.add(name)
    except Exception as e:
        print(f"Error loading allocation.json strategies: {e}")


def _append_backtest_only_strategies(strategies: list, existing_ids: set[str]) -> None:
    for strategy in BACKTEST_ONLY_STRATEGIES:
        sid = strategy["id"]
        if sid in existing_ids:
            continue
        strategies.append(
            {
                "id": sid,
                "name": strategy["name"],
                "description": strategy["description"],
                "exchange": "binance",
                "default_params": {},
                "backtest_only": True,
            }
        )
        existing_ids.add(sid)


def create_backtest_job(config: dict) -> BacktestJob:
    """Create a new backtest job."""
    job_id = str(uuid.uuid4())[:8]
    job = BacktestJob(job_id, config)

    with _jobs_lock:
        _backtest_jobs[job_id] = job

    # Save to database
    backtest_db.save_backtest(
        job_id=job_id, config=config, status="pending", created_at=job.created_at
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
        if job and job.status in ("pending", "running"):
            job.cancelled = True
            job.status = "cancelled"
            job.completed_at = datetime.now().isoformat()

            # Persist cancellation so history is accurate even if polling stops.
            try:
                backtest_db.save_backtest(
                    job_id=job.job_id,
                    config=job.config,
                    status="cancelled",
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
        job.status = "cancelled"
        job.completed_at = datetime.now().isoformat()
        backtest_db.save_backtest(
            job_id=job.job_id,
            config=job.config,
            status="cancelled",
            created_at=job.created_at,
            completed_at=job.completed_at,
            result=None,
            error=None,
        )

    def run_selected_backtest(
        strategy_id: str, start_date: str, end_date: str, initial_capital: float
    ):
        if strategy_id.startswith("wf_tree60_"):
            return _run_walkforward_backtest(
                strategy_id, start_date, end_date, initial_capital, job
            )
        is_generic = (
            strategy_id in STRATEGY_REGISTRY
            or _is_tuned_strategy(strategy_id)
            or _has_base_strategy(strategy_id)
            or _is_new_config_strategy(strategy_id)
        )
        if is_generic:
            return _run_generic_backtest(
                strategy_id, start_date, end_date, initial_capital, job
            )
        raise ValueError(
            f"No backtest runner available for strategy '{strategy_id}'. "
            "This is unexpected because strategy_id was validated earlier."
        )

    def _run():
        try:
            job.status = "running"
            job.started_at = datetime.now().isoformat()
            job.progress = 0
            backtest_db.save_backtest(
                job_id=job.job_id,
                config=job.config,
                status="running",
                created_at=job.created_at,
                completed_at=None,
                result=None,
                error=None,
            )

            config = job.config
            strategy_id = config.get("strategy_id") or config.get(
                "strategy", "llm_direction_btc"
            )
            default_start_date, default_end_date = default_backtest_date_range()
            start_date = config.get("start_date") or default_start_date
            end_date = config.get("end_date") or default_end_date
            initial_capital = config.get("initial_capital", 10000)

            # SECURITY: Validate strategy_id
            strategies = get_available_strategies()
            valid_ids = [s["id"] for s in strategies]
            if strategy_id not in valid_ids:
                raise ValueError(f"Invalid strategy: {strategy_id}")

            if job.cancelled:
                mark_cancelled()
                return

            job.progress = 10
            results, price_data = run_selected_backtest(
                strategy_id, start_date, end_date, initial_capital
            )

            if job.cancelled:
                mark_cancelled()
                return

            job.progress = 90

            # Generate visualization and log to MLflow
            results = _generate_visualization(
                results, price_data, strategy_id, job.job_id
            )

            job.result = results
            job.status = "completed"
            job.progress = 100
            job.completed_at = datetime.now().isoformat()

            # Save to database
            backtest_db.save_backtest(
                job_id=job.job_id,
                config=job.config,
                status="completed",
                created_at=job.created_at,
                completed_at=job.completed_at,
                result=results,
            )

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.completed_at = datetime.now().isoformat()
            traceback.print_exc()

            # Save to database
            backtest_db.save_backtest(
                job_id=job.job_id,
                config=job.config,
                status="failed",
                created_at=job.created_at,
                completed_at=job.completed_at,
                error=str(e),
            )

    job.thread = threading.Thread(target=_run, daemon=True)
    job.thread.start()


def _run_tuned_strategy_backtest(
    strategy_id: str,
    tuned_config: dict,
    df: "pd.DataFrame",
    initial_capital: float,
    leverage: float,
    fee_rate: float,
    slippage: float,
    job: BacktestJob,
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
    return (
        _finalize_tuned_results(state, strategy_id, df, initial_capital, leverage),
        df,
    )


def _build_tuned_regime_strategies(tuned_config: dict) -> dict:
    from trading.strategies.components.registry import (
        build_params_from_config,
        get_entry_class,
        get_entry_params_class,
        get_exit_class,
        get_exit_params_class,
    )

    regime_strategies = {}
    for regime, regime_config in tuned_config.get("regime_routing", {}).items():
        entry_name = regime_config.get("entry")
        exit_name = regime_config.get("exit")
        if entry_name == "None" or not entry_name:
            regime_strategies[regime] = None
            continue
        try:
            entry_cls = get_entry_class(f"{entry_name}Strategy")
            exit_cls = get_exit_class(f"{exit_name}Strategy")
            entry_params_cls = get_entry_params_class(f"{entry_name}Strategy")
            exit_params_cls = get_exit_params_class(f"{exit_name}Strategy")
            entry_params_obj = (
                build_params_from_config(
                    entry_params_cls, regime_config.get("entry_params", {})
                )
                if entry_params_cls
                else None
            )
            exit_params_obj = (
                build_params_from_config(
                    exit_params_cls, regime_config.get("exit_params", {})
                )
                if exit_params_cls
                else None
            )
            regime_strategies[regime] = {
                "entry": entry_cls(entry_params_obj),
                "exit": exit_cls(exit_params_obj),
            }
        except Exception as exc:
            logger.warning("Failed to create components for %s: %s", regime, exc)
            regime_strategies[regime] = None
    return regime_strategies


def _close_tuned_position(
    state: dict,
    row: pd.Series,
    timestamp: str,
    reason: str,
    leverage: float,
    fee_rate: float,
    slippage: float,
) -> None:
    exit_price = row["close"] * (1 - slippage)
    pnl_ratio = (exit_price - state["entry_price"]) / state["entry_price"]
    pnl = state["position_size"] * pnl_ratio
    margin_return = state["position_size"] / leverage
    fee = state["position_size"] * fee_rate
    state["capital"] += margin_return + pnl - fee
    state["trades"].append(
        {
            "type": "sell",
            "time": timestamp,
            "entry_price": state["entry_price"],
            "exit_price": exit_price,
            "size": state["position_size"],
            "pnl": pnl,
            "pnl_pct": pnl_ratio * 100 * leverage,
            "reason": reason,
        }
    )
    state["position_size"] = 0.0
    state["entry_price"] = 0.0
    state["position_data"] = None


def _append_tuned_equity_point(
    state: dict, row: pd.Series, timestamp: str, leverage: float
) -> None:
    current_equity = state["capital"]
    if state["position_size"] > 0 and state["position_data"]:
        pnl_ratio = (row["close"] - state["entry_price"]) / state["entry_price"]
        unrealized_pnl = state["position_size"] * pnl_ratio
        current_equity += (state["position_size"] / leverage) + unrealized_pnl
    state["equity_curve"].append({"date": timestamp[:10], "equity": current_equity})


def _build_tuned_market_data(row: pd.Series):
    from trading.strategies.components.models import MarketData

    timestamp_value = row.get("timestamp")
    epoch_ms = (
        int(timestamp_value.timestamp() * 1000)
        if hasattr(timestamp_value, "timestamp")
        else 0
    )
    return MarketData(
        symbol="BTC",
        close=row["close"],
        timestamp=epoch_ms,
        mfi=row.get("mfi", 50.0),
        adx=row.get("adx", 20.0),
        rsi=row.get("rsi", 50.0),
        atr=row.get("atr", 0.0),
        macd=row.get("macd", 0.0),
        macd_signal=row.get("macd_signal", 0.0),
        stoch_k=row.get("stoch_k", 50.0),
        stoch_d=row.get("stoch_d", 50.0),
        bb_upper=row.get("bb_upper", 0.0),
        bb_lower=row.get("bb_lower", 0.0),
        bb_middle=row.get("bb_middle", 0.0),
        volume=row.get("volume", 0.0),
        avg_volume_20=row.get("avg_volume_20", 0.0),
        prev_high_20=row.get("prev_high_20", 0.0),
        prev_low_20=row.get("prev_low_20", 0.0),
    )


def _resolve_tuned_regime(row: pd.Series):
    from trading.strategies.components.models import build_market_context

    high_30d = row.get("high_30d", 0.0)
    recent_high = high_30d if high_30d > 0 else row.get("prev_high_20", 0.0)
    context = build_market_context(
        mfi=row.get("mfi", 50.0),
        adx=row.get("adx", 20.0),
        atr=row.get("atr", 0.0),
        close=row["close"],
        volume=row.get("volume", 0.0),
        avg_volume=row.get("avg_volume_20", 0.0),
        recent_high=recent_high,
    )
    return context, context.regime


def _handle_tuned_open_position(
    state: dict,
    row: pd.Series,
    timestamp: str,
    strategy_id: str,
    strategy_components: dict,
    context,
    leverage: float,
    fee_rate: float,
    slippage: float,
) -> bool:
    from types import MappingProxyType
    from trading.strategies.components.models import Position, TradingContext

    if state["position_size"] <= 0 or not state["position_data"]:
        return False

    market_data = _build_tuned_market_data(row)
    pos = Position(
        symbol="BTC",
        entry_price=state["entry_price"],
        quantity=state["position_data"]["quantity"],
        strategy=strategy_id,
        market="spot",
        timestamp=state["position_data"]["timestamp"],
    )
    exit_ctx = TradingContext(
        symbol="BTC",
        timestamp=market_data.timestamp,
        market=market_data,
        regime=context,
        positions=MappingProxyType({strategy_id: pos}),
    )
    exit_signal = strategy_components["exit"].check_exit(exit_ctx, pos)
    if exit_signal:
        _close_tuned_position(
            state, row, timestamp, exit_signal.reason, leverage, fee_rate, slippage
        )
    return True


def _handle_tuned_entry(
    state: dict,
    row: pd.Series,
    strategy_components: dict,
    context,
    leverage: float,
    fee_rate: float,
    slippage: float,
    timestamp: str,
) -> None:
    from types import MappingProxyType
    from trading.strategies.components.models import TradingContext

    market_data = _build_tuned_market_data(row)
    entry_ctx = TradingContext(
        symbol="BTC",
        timestamp=market_data.timestamp,
        market=market_data,
        regime=context,
        positions=MappingProxyType({}),
    )
    entry_signal = strategy_components["entry"].check_entry(entry_ctx)
    if not entry_signal:
        return

    fraction = 0.3
    margin = state["capital"] * fraction
    position_size = margin * leverage
    fee = position_size * fee_rate
    if state["capital"] < (margin + fee):
        return

    state["capital"] -= margin + fee
    state["position_size"] = position_size
    state["entry_price"] = row["close"] * (1 + slippage)
    state["position_data"] = {
        "quantity": getattr(entry_signal, "quantity", 0.0),
        "timestamp": market_data.timestamp,
    }
    state["trades"].append(
        {
            "type": "buy",
            "time": timestamp,
            "price": state["entry_price"],
            "size": state["position_size"],
            "reason": entry_signal.reason,
        }
    )


def _run_tuned_backtest_loop(
    strategy_id: str,
    df: pd.DataFrame,
    regime_strategies: dict,
    initial_capital: float,
    leverage: float,
    fee_rate: float,
    slippage: float,
    job: BacktestJob,
) -> dict:
    state = {
        "capital": initial_capital,
        "position_size": 0.0,
        "entry_price": 0.0,
        "position_data": None,
        "trades": [],
        "equity_curve": [],
    }
    for i in range(len(df)):
        if job.cancelled:
            return {}
        row = df.iloc[i]
        timestamp = str(row.get("timestamp", row.name))
        if i < TimePeriods.BACKTEST_WARMUP:
            state["equity_curve"].append(
                {"date": timestamp[:10], "equity": state["capital"]}
            )
            continue

        context, current_regime = _resolve_tuned_regime(row)
        strategy_components = regime_strategies.get(current_regime)
        _append_tuned_equity_point(state, row, timestamp, leverage)

        if strategy_components is None:
            if state["position_size"] > 0:
                _close_tuned_position(
                    state,
                    row,
                    timestamp,
                    f"Regime changed to {current_regime} (no trading)",
                    leverage,
                    fee_rate,
                    slippage,
                )
            continue

        if _handle_tuned_open_position(
            state,
            row,
            timestamp,
            strategy_id,
            strategy_components,
            context,
            leverage,
            fee_rate,
            slippage,
        ):
            continue
        _handle_tuned_entry(
            state,
            row,
            strategy_components,
            context,
            leverage,
            fee_rate,
            slippage,
            timestamp,
        )
    return state


def _compute_tuned_performance(state: dict, initial_capital: float) -> dict:
    final_capital = state["capital"]
    total_return_pct = (final_capital - initial_capital) / initial_capital * 100
    close_trades, wins, losses, win_rate, profit_factor = _compute_trade_stats(
        state["trades"], {"sell"}
    )
    sharpe_ratio, max_drawdown = _compute_equity_stats(state["equity_curve"])
    return {
        "final_capital": final_capital,
        "total_return_pct": total_return_pct,
        "close_trades": close_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
    }


def _format_tuned_trades(close_trades: list[dict]) -> list[dict]:
    formatted = []
    for trade in close_trades[:100]:
        formatted.append(
            {
                "timestamp": trade.get("time"),
                "symbol": "BTC",
                "action": "BUY",
                "price": trade.get("entry_price"),
                "profit": None,
            }
        )
        formatted.append(
            {
                "timestamp": trade.get("time"),
                "symbol": "BTC",
                "action": "SELL",
                "price": trade.get("exit_price"),
                "profit": round(trade.get("pnl", 0), 0),
            }
        )
    return formatted


def _finalize_tuned_results(
    state: dict,
    strategy_id: str,
    df: pd.DataFrame,
    initial_capital: float,
    leverage: float,
) -> dict:
    if state["position_size"] > 0:
        last_price = df.iloc[-1]["close"]
        pnl_ratio = (last_price - state["entry_price"]) / state["entry_price"]
        pnl = state["position_size"] * pnl_ratio
        state["capital"] += (state["position_size"] / leverage) + pnl

    perf = _compute_tuned_performance(state, initial_capital)
    trades_list = _format_tuned_trades(perf["close_trades"])

    return {
        "strategy": strategy_id,
        "preset": "tuned",
        "start_date": str(df.iloc[0].get("timestamp", df.index[0]))[:10],
        "end_date": str(df.iloc[-1].get("timestamp", df.index[-1]))[:10],
        "initial_capital": initial_capital,
        "final_capital": round(perf["final_capital"], 0),
        "total_return": round(perf["final_capital"] - initial_capital, 0),
        "total_return_pct": round(perf["total_return_pct"], 2),
        "leverage": leverage,
        "total_trades": len(perf["close_trades"]),
        "winning_trades": len(perf["wins"]),
        "losing_trades": len(perf["losses"]),
        "win_rate": round(perf["win_rate"], 2),
        "profit_factor": round(perf["profit_factor"], 2),
        "max_drawdown": round(perf["max_drawdown"], 2),
        "max_drawdown_pct": round(perf["max_drawdown"], 2),
        "sharpe_ratio": round(perf["sharpe_ratio"], 2),
        "equity_curve": state["equity_curve"],
        "trades": trades_list,
    }


def _load_allocation_config() -> dict:
    import json

    allocation_path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
    if not allocation_path.exists():
        return {}
    with open(allocation_path, "r", encoding="utf-8") as file:
        return json.load(file)


def _resolve_generic_strategy_context(strategy_id: str, allocation: dict) -> dict:
    strategy_config = allocation.get("strategies", {}).get(strategy_id, {})
    base_strategy_id = strategy_id
    is_tuned_strategy = False
    is_new_config = False
    tuned_config = None

    if strategy_id in STRATEGY_REGISTRY:
        return {
            "strategy_config": strategy_config,
            "base_strategy_id": base_strategy_id,
            "is_tuned_strategy": False,
            "is_new_config": False,
            "tuned_config": None,
        }

    if not strategy_config:
        raise ValueError(
            f"Strategy {strategy_id} not found in registry or allocation.json"
        )

    if "regime_routing" in strategy_config:
        is_tuned_strategy = True
        tuned_config = strategy_config
    elif has_new_config_format(strategy_config):
        is_new_config = True
        logger.info("Using new config format for strategy '%s'", strategy_id)
    else:
        base_strategy = strategy_config.get("base_strategy")
        if not base_strategy:
            for reg_name in STRATEGY_REGISTRY.keys():
                if strategy_id.startswith(reg_name):
                    base_strategy = reg_name
                    break
        if not base_strategy or base_strategy not in STRATEGY_REGISTRY:
            raise ValueError(
                f"Strategy {strategy_id} has no regime_routing and no valid base_strategy"
            )
        base_strategy_id = base_strategy
        logger.info("Using base strategy '%s' for '%s'", base_strategy, strategy_id)

    return {
        "strategy_config": strategy_config,
        "base_strategy_id": base_strategy_id,
        "is_tuned_strategy": is_tuned_strategy,
        "is_new_config": is_new_config,
        "tuned_config": tuned_config,
    }


def _resolve_generic_market_settings(context: dict) -> dict:
    if context["is_tuned_strategy"]:
        market_type = "spot"
        leverage = 1.0
        timeframe = "minute60"
    elif context["is_new_config"]:
        config = context["strategy_config"]
        market_type = "spot"
        leverage = 1.0
        timeframe = config.get("timeframe", "minute240")
    else:
        spec = STRATEGY_REGISTRY[context["base_strategy_id"]]
        market_type = "spot"
        leverage = 1.0
        timeframe = spec.timeframe

    fee_rate = FeeRates.SPOT
    slippage = FeeRates.SPOT_SLIPPAGE

    timeframe_map = {
        "hour1": "minute60",
        "hour4": "minute240",
        "1h": "minute60",
        "4h": "minute240",
        "1d": "day",
    }
    db_timeframe = timeframe_map.get(timeframe, timeframe)
    return {
        "market_type": market_type,
        "leverage": leverage,
        "timeframe": timeframe,
        "db_timeframe": db_timeframe,
        "fee_rate": fee_rate,
        "slippage": slippage,
    }


def _resolve_strategy_symbol(strategy_config: dict) -> str:
    symbols = strategy_config.get("symbols", []) if strategy_config else []
    return symbols[0] if symbols else "BTC"


def _load_backtest_df(
    strategy_symbol: str, db_timeframe: str, start_date: str, end_date: str
) -> pd.DataFrame:
    from core.data_loader import DataLoader

    db_path = SYMBOL_DB_MAPPING.get(strategy_symbol, SYMBOL_DB_MAPPING["BTC"])
    logger.info("Backtest using symbol=%s, db=%s", strategy_symbol, db_path.name)
    with DataLoader(db_path=str(db_path)) as loader:
        return loader.load_timeframe(db_timeframe, start_date, end_date)


def _build_adapter_config(
    allocation: dict,
    strategy_id: str,
    strategy_config: dict,
    fee_rate: float,
    slippage: float,
) -> dict:
    config = dict(
        strategy_config or allocation.get("strategies", {}).get(strategy_id, {})
    )
    config.setdefault("core_fee_rate", fee_rate)
    config.setdefault("core_slippage", slippage)
    for key, value in _ADAPTER_DEFAULTS.items():
        config.setdefault(key, value)

    defaults = allocation.get("defaults", {}).get("regime_v2", {})
    for key in [
        "bbw_block_threshold",
        "bbw_confirm_threshold",
        "volume_block_ratio",
        "volume_boost_ratio",
        "mtf_enabled",
    ]:
        if key not in strategy_config and key in defaults:
            config[key] = defaults[key]
    return config


def _build_core_state(
    config: dict, initial_capital: float, fee_rate: float, slippage: float
) -> dict:
    core_hold_pct = max(min(float(config.get("core_hold_pct", 0.0)), 0.95), 0.0)
    return {
        "hold_pct": core_hold_pct,
        "exit_on_ema200": bool(config.get("core_exit_on_ema200", False)),
        "ema_hours": int(config.get("core_ema_hours", 0)),
        "ema_timeframe": str(config.get("core_ema_timeframe", "")).lower(),
        "ema_span": int(config.get("core_ema_span", 0)),
        "reentry_on_ema200": bool(config.get("core_reentry_on_ema200", True)),
        "fee_rate": float(config.get("core_fee_rate", fee_rate)),
        "slippage": float(config.get("core_slippage", slippage)),
        "drawdown_exit_pct": float(config.get("core_drawdown_exit_pct", 0.0)),
        "drawdown_reentry_pct": float(config.get("core_drawdown_reentry_pct", 0.0)),
        "cash": initial_capital * core_hold_pct,
        "qty": 0.0,
        "active": False,
        "peak_price": 0.0,
    }


def _prepare_core_ema_columns(
    df: pd.DataFrame, core_state: dict, start_date: str, end_date: str
) -> pd.DataFrame:
    from core.data_loader import DataLoader

    if core_state["hold_pct"] <= 0:
        return df

    if core_state["ema_timeframe"] in ("day", "daily"):
        core_span = core_state["ema_span"] if core_state["ema_span"] > 0 else 200
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

    if core_state["ema_hours"] > 0:
        df = df.copy()
        df["core_ema"] = (
            df["close"].ewm(span=core_state["ema_hours"], adjust=False).mean()
        )
    return df


def _passes_core_entry_filter(row: pd.Series, core_state: dict) -> bool:
    ema_200 = float(row.get("ema_200", 0.0) or 0.0)
    core_ema = float(row.get("core_ema", 0.0) or 0.0)
    price = float(row["close"])
    if core_ema > 0 and price < core_ema:
        return False
    if core_state["exit_on_ema200"] and ema_200 > 0 and price < ema_200:
        return False
    return True


def _enter_core_position(row: pd.Series, core_state: dict) -> None:
    if core_state["cash"] <= 0:
        return
    price = float(row["close"])
    entry_price = price * (1 + core_state["slippage"])
    qty = core_state["cash"] / (entry_price * (1 + core_state["fee_rate"]))
    cost = qty * entry_price * (1 + core_state["fee_rate"])
    core_state["cash"] -= cost
    core_state["qty"] = qty
    core_state["active"] = qty > 0
    core_state["peak_price"] = price


def _initialize_core_position(df: pd.DataFrame, core_state: dict) -> None:
    if core_state["hold_pct"] <= 0 or df.empty:
        return
    first_row = df.iloc[0]
    if _passes_core_entry_filter(first_row, core_state):
        _enter_core_position(first_row, core_state)


def _close_core_position(price: float, core_state: dict) -> None:
    exit_price = price * (1 - core_state["slippage"])
    proceeds = core_state["qty"] * exit_price * (1 - core_state["fee_rate"])
    core_state["cash"] += proceeds
    core_state["qty"] = 0.0
    core_state["active"] = False


def _can_core_reenter(price: float, row: pd.Series, core_state: dict) -> bool:
    if not core_state["reentry_on_ema200"]:
        return False
    if not _passes_core_entry_filter(row, core_state):
        return False
    if core_state["drawdown_reentry_pct"] <= 0 or core_state["peak_price"] <= 0:
        return True
    drawdown_pct = (core_state["peak_price"] - price) / core_state["peak_price"] * 100
    return drawdown_pct <= core_state["drawdown_reentry_pct"]


def _update_core_position(row: pd.Series, core_state: dict) -> None:
    if core_state["hold_pct"] <= 0:
        return

    price = float(row["close"])
    if core_state["active"]:
        core_state["peak_price"] = max(core_state["peak_price"], price)
        drawdown_pct = 0.0
        if core_state["peak_price"] > 0:
            drawdown_pct = (
                (core_state["peak_price"] - price) / core_state["peak_price"] * 100
            )
        exit_on_drawdown = (
            core_state["drawdown_exit_pct"] > 0
            and drawdown_pct >= core_state["drawdown_exit_pct"]
        )
        exit_on_filter = not _passes_core_entry_filter(row, core_state)
        if exit_on_drawdown or exit_on_filter:
            _close_core_position(price, core_state)
        return

    if _can_core_reenter(price, row, core_state):
        _enter_core_position(row, core_state)


def _compute_position_equity(
    trade_state: dict, current_price: float, adapter: ComponentStrategyAdapter
) -> float:
    if trade_state["position_size"] <= 0:
        return trade_state["capital"]
    if adapter.current_position and adapter.current_position.side == "short":
        pnl_ratio = (trade_state["entry_price"] - current_price) / trade_state[
            "entry_price"
        ]
    else:
        pnl_ratio = (current_price - trade_state["entry_price"]) / trade_state[
            "entry_price"
        ]
    unrealized_pnl = trade_state["position_size"] * pnl_ratio
    return (
        trade_state["capital"]
        + (trade_state["position_size"] / trade_state["position_leverage"])
        + unrealized_pnl
    )


def _execute_open_trade(
    action: str,
    signal: dict,
    row: pd.Series,
    trade_state: dict,
    leverage: float,
    fee_rate: float,
    slippage: float,
    timestamp: str,
    reason: str,
) -> None:
    if trade_state["position_size"] != 0:
        return
    if action not in ("buy", "open_short"):
        return

    fraction = signal.get("fraction", 1.0 if action == "buy" else 0.3)
    effective_leverage = signal.get("leverage", leverage)
    margin = trade_state["capital"] * fraction / (1 + effective_leverage * fee_rate)
    position_size = margin * effective_leverage
    fee = position_size * fee_rate
    # Allow full-allocation entries despite tiny floating-point drift.
    if trade_state["capital"] + 1e-9 < (margin + fee):
        return

    trade_state["capital"] -= margin + fee
    trade_state["position_size"] = position_size
    trade_state["position_leverage"] = effective_leverage
    trade_state["entry_price"] = (
        row["close"] * (1 + slippage)
        if action == "buy"
        else row["close"] * (1 - slippage)
    )
    trade_state["entry_timestamp"] = timestamp
    trade_state["trades"].append(
        {
            "type": action,
            "time": timestamp,
            "price": trade_state["entry_price"],
            "size": position_size,
            "reason": reason,
            "leverage": effective_leverage,
        }
    )


def _execute_close_trade(
    action: str,
    signal: dict,
    row: pd.Series,
    trade_state: dict,
    fee_rate: float,
    slippage: float,
    timestamp: str,
    reason: str,
) -> None:
    if action not in ("sell", "close_short") or trade_state["position_size"] <= 0:
        return
    exit_fraction = signal.get("fraction", 1.0)
    exit_size = trade_state["position_size"] * exit_fraction
    is_short = action == "close_short"
    exit_price = (
        row["close"] * (1 + slippage) if is_short else row["close"] * (1 - slippage)
    )
    if is_short:
        pnl_ratio = (trade_state["entry_price"] - exit_price) / trade_state[
            "entry_price"
        ]
    else:
        pnl_ratio = (exit_price - trade_state["entry_price"]) / trade_state[
            "entry_price"
        ]
    pnl = exit_size * pnl_ratio
    margin_return = exit_size / trade_state["position_leverage"]
    fee = exit_size * fee_rate
    trade_state["capital"] += margin_return + pnl - fee
    trade_state["trades"].append(
        {
            "type": action,
            "time": timestamp,
            "entry_time": trade_state["entry_timestamp"],
            "entry_price": trade_state["entry_price"],
            "exit_price": exit_price,
            "size": exit_size,
            "pnl": pnl,
            "pnl_pct": pnl_ratio * 100 * trade_state["position_leverage"],
            "reason": reason,
            "leverage": trade_state["position_leverage"],
        }
    )
    if exit_fraction >= 1.0:
        trade_state["position_size"] = 0.0
        trade_state["entry_price"] = 0.0
        trade_state["entry_timestamp"] = None
    else:
        trade_state["position_size"] -= exit_size


def _compute_trade_stats(
    trades: list[dict], close_actions: set[str]
) -> tuple[list[dict], list[dict], list[dict], float, float]:
    """Compute closed-trade statistics from generic backtest trade records."""
    close_trades = [t for t in trades if t.get("type") in close_actions]
    wins = [t for t in close_trades if float(t.get("pnl", 0.0) or 0.0) > 0]
    losses = [t for t in close_trades if float(t.get("pnl", 0.0) or 0.0) <= 0]
    win_rate = (len(wins) / len(close_trades) * 100.0) if close_trades else 0.0

    gross_profit = sum(max(float(t.get("pnl", 0.0) or 0.0), 0.0) for t in close_trades)
    gross_loss = abs(
        sum(min(float(t.get("pnl", 0.0) or 0.0), 0.0) for t in close_trades)
    )
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
    return close_trades, wins, losses, win_rate, profit_factor


def _compute_equity_stats(equity_curve: list[dict]) -> tuple[float, float]:
    """Compute Sharpe ratio and max drawdown (%) from equity curve records."""
    if not equity_curve:
        return 0.0, 0.0

    equity_df = pd.DataFrame(equity_curve)
    if "equity" not in equity_df:
        return 0.0, 0.0
    equity_series = pd.to_numeric(equity_df["equity"], errors="coerce").dropna()
    if equity_series.empty:
        return 0.0, 0.0

    returns = equity_series.pct_change().dropna()
    sharpe_ratio = 0.0
    if not returns.empty and returns.std() > 0:
        sharpe_ratio = float((returns.mean() / returns.std()) * (365**0.5))

    roll_max = equity_series.cummax()
    drawdown = (
        ((equity_series - roll_max) / roll_max * 100.0)
        if not roll_max.empty
        else pd.Series(dtype=float)
    )
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
    return sharpe_ratio, max_drawdown


def _sample_trades(close_trades: list[dict], max_trades: int = 150) -> list[dict]:
    if len(close_trades) <= max_trades:
        return close_trades
    step = len(close_trades) / max_trades
    return [close_trades[int(i * step)] for i in range(max_trades)]


def _format_generic_trades(close_trades: list[dict], symbol: str) -> list[dict]:
    trades_list = []
    for trade in _sample_trades(close_trades):
        is_short = trade["type"] == "close_short"
        trades_list.append(
            {
                "timestamp": trade.get("entry_time") or trade.get("time"),
                "symbol": symbol,
                "action": "SHORT" if is_short else "BUY",
                "price": trade.get("entry_price"),
                "profit": None,
            }
        )
        trades_list.append(
            {
                "timestamp": trade.get("time"),
                "symbol": symbol,
                "action": "COVER" if is_short else "SELL",
                "price": trade.get("exit_price"),
                "profit": round(trade.get("pnl", 0), 0),
            }
        )
    return trades_list


def _finalize_generic_trade_state(
    trade_state: dict,
    adapter: ComponentStrategyAdapter,
    core_state: dict,
    df: pd.DataFrame,
) -> None:
    if trade_state["position_size"] > 0:
        last_price = float(df.iloc[-1]["close"])
        if adapter.current_position and adapter.current_position.side == "short":
            pnl_ratio = (trade_state["entry_price"] - last_price) / trade_state[
                "entry_price"
            ]
        else:
            pnl_ratio = (last_price - trade_state["entry_price"]) / trade_state[
                "entry_price"
            ]
        pnl = trade_state["position_size"] * pnl_ratio
        trade_state["capital"] += (
            trade_state["position_size"] / trade_state["position_leverage"]
        ) + pnl
    if core_state["hold_pct"] > 0:
        last_price = float(df.iloc[-1]["close"])
        trade_state["capital"] += core_state["cash"] + (core_state["qty"] * last_price)


def _build_generic_result(
    strategy_id: str,
    strategy_symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    leverage: float,
    trade_state: dict,
) -> dict:
    close_trades, wins, losses, win_rate, profit_factor = _compute_trade_stats(
        trade_state["trades"], {"sell", "close_short", "partial_close"}
    )
    sharpe_ratio, max_drawdown = _compute_equity_stats(trade_state["equity_curve"])
    final_capital = trade_state["capital"]
    return {
        "strategy": strategy_id,
        "symbol": strategy_symbol,
        "preset": "generic",
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
        "final_capital": round(final_capital, 0),
        "total_return": round(final_capital - initial_capital, 0),
        "total_return_pct": round(
            (final_capital - initial_capital) / initial_capital * 100, 2
        ),
        "leverage": leverage,
        "total_trades": len(close_trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown": round(max_drawdown, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "equity_curve": trade_state["equity_curve"],
        "trades": _format_generic_trades(close_trades, strategy_symbol),
    }


def _run_generic_backtest(
    strategy_id: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    job: BacktestJob,
) -> dict:
    """
    Run any strategy using ComponentStrategyAdapter and generic loop.
    Supports both Spot (Long-only) and Futures (Long/Short).
    Also supports tuned strategies from allocation.json with regime_routing.
    """
    allocation = _load_allocation_config()
    context = _resolve_generic_strategy_context(strategy_id, allocation)
    market_settings = _resolve_generic_market_settings(context)
    strategy_symbol = _resolve_strategy_symbol(context["strategy_config"])
    df = _load_backtest_df(
        strategy_symbol, market_settings["db_timeframe"], start_date, end_date
    )
    if df.empty:
        raise ValueError(
            f"No data available for {strategy_symbol} from {start_date} to {end_date}"
        )

    job.progress = 20
    add_all_indicators(df)
    job.progress = 30

    if context["is_tuned_strategy"]:
        return _run_tuned_strategy_backtest(
            strategy_id,
            context["tuned_config"],
            df,
            initial_capital,
            market_settings["leverage"],
            market_settings["fee_rate"],
            market_settings["slippage"],
            job,
        )

    config = _build_adapter_config(
        allocation,
        strategy_id,
        context["strategy_config"],
        market_settings["fee_rate"],
        market_settings["slippage"],
    )
    adapter = ComponentStrategyAdapter(
        StrategyFactory(redis=None), context["base_strategy_id"], config
    )
    adapter.symbol = strategy_symbol

    core_state = _build_core_state(
        config,
        initial_capital,
        market_settings["fee_rate"],
        market_settings["slippage"],
    )
    df = _prepare_core_ema_columns(df, core_state, start_date, end_date)
    _initialize_core_position(df, core_state)

    trade_state = {
        "capital": initial_capital - core_state["cash"],
        "position_size": 0.0,
        "entry_price": 0.0,
        "entry_timestamp": None,
        "position_leverage": market_settings["leverage"],
        "trades": [],
        "equity_curve": [],
    }
    for i in range(len(df)):
        if job.cancelled:
            return {}, df
        row = df.iloc[i]
        timestamp = str(row.get("timestamp", row.name))
        _update_core_position(row, core_state)

        current_equity = _compute_position_equity(
            trade_state, float(row["close"]), adapter
        )
        if core_state["hold_pct"] > 0:
            current_equity += core_state["cash"] + (core_state["qty"] * row["close"])
        adapter.update_equity(current_equity)
        signal = adapter(df, i)
        action = signal.get("action", "hold")
        reason = signal.get("reason", "")
        trade_state["equity_curve"].append(
            {"date": timestamp[:10], "equity": current_equity}
        )
        _execute_open_trade(
            action,
            signal,
            row,
            trade_state,
            market_settings["leverage"],
            market_settings["fee_rate"],
            market_settings["slippage"],
            timestamp,
            reason,
        )
        _execute_close_trade(
            action,
            signal,
            row,
            trade_state,
            market_settings["fee_rate"],
            market_settings["slippage"],
            timestamp,
            reason,
        )

    job.progress = 80
    _finalize_generic_trade_state(trade_state, adapter, core_state, df)
    return (
        _build_generic_result(
            strategy_id,
            strategy_symbol,
            start_date,
            end_date,
            initial_capital,
            market_settings["leverage"],
            trade_state,
        ),
        df,
    )


_WF_ALLOWED_ASSETS = ("BTC", "ETH", "SOL")
_WF_PARAM_DEFAULTS = {
    "BTC": {
        "cooldown_reentry_enabled": True,
        "cooldown_reentry_requires_buy": True,
        "min_bars_after_risk_exit": 24,
        "trailing_drawdown_exit_pct": 10.0,
        "reentry_trend_filter_enabled": True,
        "reentry_ema_span": 50,
        "reentry_require_ema_rising": True,
        "staged_reentry_enabled": True,
        "reentry_stage1_fraction": 0.55,
        "reentry_stage2_fraction": 0.8,
        "stage2_confirm_bars": 6,
        "stage2_trigger_pct": 0.8,
    },
    "ETH": {
        "cooldown_reentry_enabled": True,
        "cooldown_reentry_requires_buy": True,
        "min_bars_after_risk_exit": 24,
        "trailing_drawdown_exit_pct": 10.0,
        "reentry_trend_filter_enabled": True,
        "reentry_ema_span": 50,
        "reentry_require_ema_rising": True,
        "staged_reentry_enabled": True,
        "reentry_stage1_fraction": 0.55,
        "reentry_stage2_fraction": 0.8,
        "stage2_confirm_bars": 6,
        "stage2_trigger_pct": 0.8,
    },
    "SOL": {
        "cooldown_reentry_enabled": True,
        "cooldown_reentry_requires_buy": True,
        "min_bars_after_risk_exit": 24,
        "trailing_drawdown_exit_pct": 12.0,
        "reentry_trend_filter_enabled": False,
        "reentry_ema_span": 50,
        "reentry_require_ema_rising": True,
        "staged_reentry_enabled": False,
        "reentry_stage1_fraction": 0.45,
        "reentry_stage2_fraction": 0.8,
        "stage2_confirm_bars": 6,
        "stage2_trigger_pct": 1.5,
    },
}


def _resolve_walkforward_asset(strategy_id: str) -> str:
    asset = strategy_id.replace("wf_tree60_", "").upper()
    if asset not in _WF_ALLOWED_ASSETS:
        raise ValueError(f"Unknown walk-forward asset: {asset}")
    return asset


def _env_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_wf_param(asset: str, param_key: str, default_value):
    raw = os.getenv(f"WF_TREE60_{asset}_{param_key.upper()}")
    if raw is None:
        raw = os.getenv(f"WF_TREE60_{param_key.upper()}")
    if raw is None:
        return default_value
    if isinstance(default_value, bool):
        return _env_bool(raw)
    if isinstance(default_value, int) and not isinstance(default_value, bool):
        return int(raw)
    if isinstance(default_value, float):
        return float(raw)
    return raw


def _resolve_walkforward_params(asset: str) -> dict:
    defaults = _WF_PARAM_DEFAULTS[asset]
    return {
        key: _resolve_wf_param(asset, key, value) for key, value in defaults.items()
    }


def _load_walkforward_runtime_settings() -> dict:
    return {
        "n_splits": int(os.getenv("WF_N_SPLITS", "7")),
        "max_train_folds": int(os.getenv("WF_MAX_TRAIN_FOLDS", "3")),
        "temporal_decay": float(os.getenv("WF_TEMPORAL_DECAY", "2.0")),
        "xgb_rounds": int(os.getenv("WF_XGB_ROUNDS", "500")),
        "lgb_rounds": int(os.getenv("WF_LGB_ROUNDS", "500")),
    }


def _make_walkforward_progress_callback(job: BacktestJob):
    last_heartbeat = 0.0

    def _progress_callback(fraction: float) -> None:
        nonlocal last_heartbeat
        bounded = max(0.0, min(float(fraction), 1.0))
        job.progress = max(job.progress, int(round(10 + (bounded * 65))))

        now = time.monotonic()
        if now - last_heartbeat < 10:
            return
        last_heartbeat = now
        backtest_db.save_backtest(
            job_id=job.job_id,
            config=job.config,
            status="running",
            created_at=job.created_at,
            completed_at=None,
            result=None,
            error=None,
        )

    return _progress_callback


def _build_walkforward_equity_curve(
    equity_df: pd.DataFrame, initial_capital: float
) -> list[dict]:
    points: list[dict] = []
    if equity_df is None or equity_df.empty:
        return points
    for _, row in equity_df.iterrows():
        ts = row.get("timestamp", row.name)
        points.append(
            {
                "date": str(ts)[:10],
                "equity": float(
                    row.get("total_equity", row.get("equity", initial_capital))
                ),
            }
        )
    return points


def _sample_walkforward_trades(
    raw_trades: list, max_trades: int = 150
) -> tuple[list, list]:
    closed_trades = [t for t in raw_trades if t.exit_time is not None]
    if len(closed_trades) <= max_trades:
        return closed_trades, closed_trades
    step = len(closed_trades) / max_trades
    indices = [int(i * step) for i in range(max_trades)]
    sampled = [closed_trades[i] for i in indices]
    return closed_trades, sampled


def _format_walkforward_trades(trades: list, asset: str) -> list[dict]:
    formatted: list[dict] = []
    for trade in trades:
        raw_reason = str(getattr(trade, "reason", "") or "")
        entry_reason = (
            raw_reason.split(" -> ", 1)[0] if " -> " in raw_reason else raw_reason
        )
        if "[" in raw_reason and raw_reason.endswith("]"):
            exit_reason = raw_reason.rsplit("[", 1)[1][:-1]
        else:
            exit_reason = raw_reason
        formatted.append(
            {
                "timestamp": str(trade.entry_time)[:19],
                "symbol": asset,
                "action": "BUY",
                "price": trade.entry_price,
                "profit": None,
                "reason": entry_reason,
            }
        )
        formatted.append(
            {
                "timestamp": str(trade.exit_time)[:19],
                "symbol": asset,
                "action": "SELL",
                "price": trade.exit_price,
                "profit": round(trade.profit_loss, 0) if trade.profit_loss else 0,
                "reason": exit_reason,
            }
        )
    return formatted


def _compute_walkforward_trade_metrics(
    closed_trades: list,
) -> tuple[list, list, float, float]:
    wins = [t for t in closed_trades if t.profit_loss and t.profit_loss > 0]
    losses = [
        t for t in closed_trades if t.profit_loss is not None and t.profit_loss <= 0
    ]
    win_rate = (len(wins) / len(closed_trades) * 100) if closed_trades else 0.0
    gross_profit = sum(t.profit_loss for t in wins) if wins else 0.0
    gross_loss = abs(sum(t.profit_loss for t in losses)) if losses else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
    return wins, losses, win_rate, profit_factor


def _load_walkforward_price_data(
    asset: str, start_date: str, end_date: str
) -> pd.DataFrame:
    from core.data_loader import DataLoader

    db_path = SYMBOL_DB_MAPPING.get(asset, SYMBOL_DB_MAPPING["BTC"])
    with DataLoader(db_path=str(db_path)) as loader:
        return loader.load_timeframe("minute240", start_date, end_date)


def _build_walkforward_response(
    strategy_id: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    total_return_pct: float,
    metrics: dict,
    results_inner: dict,
    closed_trades: list,
    wins: list,
    losses: list,
    win_rate: float,
    profit_factor: float,
    equity_curve: list[dict],
    trades_list: list[dict],
) -> dict:
    final_capital = initial_capital * (1 + total_return_pct / 100)
    max_drawdown = round(
        metrics.get("mdd", results_inner.get("max_drawdown_pct", 0)), 2
    )
    return {
        "strategy": strategy_id,
        "preset": "walkforward",
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
        "final_capital": round(final_capital, 0),
        "total_return": round(final_capital - initial_capital, 0),
        "total_return_pct": round(total_return_pct, 2),
        "leverage": 1,
        "total_trades": len(closed_trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown": max_drawdown,
        "max_drawdown_pct": max_drawdown,
        "sharpe_ratio": round(
            metrics.get("sharpe", results_inner.get("sharpe_ratio", 0)), 2
        ),
        "equity_curve": equity_curve,
        "trades": trades_list,
    }


def _run_walkforward_backtest(
    strategy_id: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    job: BacktestJob,
) -> tuple:
    """Run walk-forward backtest for a single asset using tree_60 XGB+LGB ensemble.

    Calls run_walkforward_asset() with recommended sliding-window config
    and converts the Backtester output to dashboard format.
    """
    from scripts.backtest.walkforward_backtest import run_walkforward_asset

    asset = _resolve_walkforward_asset(strategy_id)
    job.progress = 10
    runtime = _load_walkforward_runtime_settings()
    wf_params = _resolve_walkforward_params(asset)
    wf_result = run_walkforward_asset(
        asset=asset,
        start_date=start_date,
        end_date=end_date,
        capital=initial_capital,
        n_splits=runtime["n_splits"],
        max_train_folds=runtime["max_train_folds"],
        temporal_decay=runtime["temporal_decay"],
        xgb_rounds=runtime["xgb_rounds"],
        lgb_rounds=runtime["lgb_rounds"],
        cooldown_reentry_enabled=wf_params["cooldown_reentry_enabled"],
        cooldown_reentry_requires_buy=wf_params["cooldown_reentry_requires_buy"],
        trailing_drawdown_exit_pct=wf_params["trailing_drawdown_exit_pct"],
        min_bars_after_risk_exit=wf_params["min_bars_after_risk_exit"],
        reentry_trend_filter_enabled=wf_params["reentry_trend_filter_enabled"],
        reentry_ema_span=wf_params["reentry_ema_span"],
        reentry_require_ema_rising=wf_params["reentry_require_ema_rising"],
        staged_reentry_enabled=wf_params["staged_reentry_enabled"],
        reentry_stage1_fraction=wf_params["reentry_stage1_fraction"],
        reentry_stage2_fraction=wf_params["reentry_stage2_fraction"],
        stage2_confirm_bars=wf_params["stage2_confirm_bars"],
        stage2_trigger_pct=wf_params["stage2_trigger_pct"],
        progress_callback=_make_walkforward_progress_callback(job),
        should_cancel=lambda: job.cancelled,
    )

    if not wf_result:
        raise ValueError(f"Walk-forward backtest produced no results for {asset}")

    job.progress = 75

    results_inner = wf_result["results"]
    metrics = wf_result.get("metrics", {})
    equity_df = wf_result.get("equity_curve", pd.DataFrame())
    equity_curve = _build_walkforward_equity_curve(equity_df, initial_capital)
    raw_trades = results_inner.get("trades", [])
    closed_trades, sampled_trades = _sample_walkforward_trades(raw_trades)
    trades_list = _format_walkforward_trades(sampled_trades, asset)
    wins, losses, win_rate, profit_factor = _compute_walkforward_trade_metrics(
        closed_trades
    )
    total_return_pct = metrics.get("total_return", results_inner.get("total_return", 0))
    price_data = _load_walkforward_price_data(asset, start_date, end_date)
    job.progress = 85

    return (
        _build_walkforward_response(
            strategy_id=strategy_id,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            total_return_pct=total_return_pct,
            metrics=metrics,
            results_inner=results_inner,
            closed_trades=closed_trades,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            profit_factor=profit_factor,
            equity_curve=equity_curve,
            trades_list=trades_list,
        ),
        price_data,
    )


def get_running_job_count() -> int:
    """Count currently running jobs."""
    with _jobs_lock:
        return sum(
            1 for job in _backtest_jobs.values() if job.status in ("pending", "running")
        )


def start_backtest(config: dict) -> BacktestJob:
    """Create and start a backtest job."""
    if get_running_job_count() >= MAX_CONCURRENT_JOBS:
        raise RuntimeError(
            f"Too many concurrent jobs. Maximum is {MAX_CONCURRENT_JOBS}."
        )

    job = create_backtest_job(config)
    run_backtest(job)
    return job


def cleanup_old_jobs(max_age_hours: int = 24) -> int:
    """Remove jobs older than max_age_hours."""
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    removed = 0

    with _jobs_lock:
        to_remove = []
        for job_id, job in _backtest_jobs.items():
            created = datetime.fromisoformat(job.created_at)
            if created < cutoff and job.status in ("completed", "failed", "cancelled"):
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
    _reconcile_stale_db_jobs()
    jobs_by_id = {}

    # First, load history from database
    db_history = backtest_db.get_history(limit=limit)
    for db_job in db_history:
        jobs_by_id[db_job["job_id"]] = db_job

    # Then, overlay in-memory jobs (for real-time progress on running jobs)
    with _jobs_lock:
        for job in _backtest_jobs.values():
            # Create summary without large data fields
            summary = {
                "job_id": job.job_id,
                "config": job.config,
                "status": job.status,
                "progress": job.progress,
                "created_at": job.created_at,
                "completed_at": job.completed_at,
                "error": job.error,
            }
            # Add key metrics from result if available
            if job.result:
                summary["metrics"] = {
                    "total_return_pct": job.result.get("total_return_pct", 0),
                    "win_rate": job.result.get("win_rate", 0),
                    "total_trades": job.result.get("total_trades", 0),
                    "sharpe_ratio": job.result.get("sharpe_ratio", 0),
                    "max_drawdown_pct": job.result.get("max_drawdown_pct", 0),
                }
            # In-memory jobs override DB entries (for real-time updates)
            jobs_by_id[job.job_id] = summary

    # Convert to list and sort by created_at descending (newest first)
    jobs = list(jobs_by_id.values())
    jobs.sort(key=lambda x: x["created_at"], reverse=True)
    return jobs


def _reconcile_stale_db_jobs(scan_limit: int = 200) -> int:
    """Mark stale persisted pending/running jobs as failed.

    Stale = pending/running in DB, not active in-memory, older than threshold.
    This avoids indefinitely "stuck" jobs after process restarts/crashes.
    """
    now_monotonic = time.monotonic()
    if now_monotonic - _stale_reconcile_state["last_at"] < 60:
        return 0
    _stale_reconcile_state["last_at"] = now_monotonic

    with _jobs_lock:
        active_ids = {
            job.job_id
            for job in _backtest_jobs.values()
            if job.status in ("pending", "running")
        }

    stale_cutoff = datetime.now() - timedelta(minutes=STALE_DB_JOB_MINUTES)
    fixed = 0
    for db_job in backtest_db.get_history(limit=scan_limit):
        status = db_job.get("status")
        job_id = db_job.get("job_id")
        if status not in ("pending", "running") or not job_id:
            continue
        if job_id in active_ids:
            continue
        created_at_raw = db_job.get("created_at")
        if not created_at_raw:
            continue
        try:
            created_at = datetime.fromisoformat(created_at_raw)
        except Exception:
            continue
        if created_at > stale_cutoff:
            continue
        backtest_db.save_backtest(
            job_id=job_id,
            config=db_job.get("config") or {},
            status="failed",
            created_at=created_at_raw,
            completed_at=datetime.now().isoformat(),
            error="Marked stale after process restart/crash (no active worker)",
            result=None,
        )
        fixed += 1
    return fixed
