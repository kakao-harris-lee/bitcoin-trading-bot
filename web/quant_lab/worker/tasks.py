"""RQ background tasks for optimization."""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
import json
import redis
from datetime import datetime

from ..optimizer.study_manager import StudyManager
from ..optimizer.objective import RegimeBacktestObjective
from ..optimizer.search_space import SearchSpaceConfig


class JobStatus(Enum):
    """Status of an optimization job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OptimizationJob:
    """Configuration for an optimization job."""
    job_id: str
    study_name: str
    data_path: str
    start_date: str
    end_date: str
    symbols: List[str]

    # Budget
    max_trials: Optional[int] = 500
    max_hours: Optional[float] = None

    # Search space config (serialized)
    search_config: Optional[Dict[str, Any]] = None

    # Constraints config (serialized)
    constraints: Optional[Dict[str, Any]] = None

    # MLflow tracking
    mlflow_experiment: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize job to dict."""
        return {
            "job_id": self.job_id,
            "study_name": self.study_name,
            "data_path": self.data_path,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "symbols": self.symbols,
            "max_trials": self.max_trials,
            "max_hours": self.max_hours,
            "search_config": self.search_config,
            "constraints": self.constraints,
            "mlflow_experiment": self.mlflow_experiment,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OptimizationJob':
        """Deserialize job from dict."""
        return cls(**data)


def run_optimization(job: OptimizationJob) -> Dict[str, Any]:
    """
    Main optimization task executed by RQ worker.

    Args:
        job: Optimization job configuration

    Returns:
        Dict with final results
    """
    # Initialize study manager
    manager = StudyManager()
    study = manager.create_study(job.study_name)

    # Build search config
    search_config = SearchSpaceConfig()
    if job.search_config:
        search_config.regime_configs = job.search_config

    # Build objective
    objective = RegimeBacktestObjective(
        data_path=job.data_path,
        start_date=job.start_date,
        end_date=job.end_date,
        symbols=job.symbols,
        search_config=search_config,
    )

    # Update job status with initial metadata
    _update_job_status(job.job_id, JobStatus.RUNNING, {
        "study_name": job.study_name,
        "max_trials": job.max_trials,
        "current_trial": 0,
        "start_date": job.start_date,
        "end_date": job.end_date,
        "symbols": job.symbols,
    })

    try:
        # Run optimization
        study.optimize(
            objective,
            n_trials=job.max_trials,
            timeout=job.max_hours * 3600 if job.max_hours else None,
            callbacks=[
                lambda study, trial: _on_trial_complete(job.job_id, study, trial)
            ],
        )

        # Get results
        stats = manager.get_study_stats(job.study_name)
        pareto = manager.get_pareto_front(job.study_name)

        _update_job_status(job.job_id, JobStatus.COMPLETED, stats)

        return {
            "status": "completed",
            "stats": stats,
            "pareto_size": len(pareto),
        }

    except Exception as e:
        _update_job_status(job.job_id, JobStatus.FAILED, {"error": str(e)})
        raise


def _update_job_status(
    job_id: str,
    status: JobStatus,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Update job status in Redis."""
    try:
        r = redis.from_url("redis://localhost:6379")
        data = {
            "status": status.value,
            "updated_at": datetime.utcnow().isoformat(),
        }
        if extra:
            data.update(extra)
        r.hset(f"quant_lab:job:{job_id}", mapping={k: json.dumps(v) for k, v in data.items()})
    except Exception:
        pass  # Don't fail optimization if Redis update fails


def _on_trial_complete(job_id: str, study, trial) -> None:
    """Callback after each trial completes."""
    try:
        r = redis.from_url("redis://localhost:6379")
        # trial.number is 0-indexed, so add 1 for display (trial 0 = "1 of N")
        r.hset(f"quant_lab:job:{job_id}", mapping={
            "current_trial": str(trial.number + 1),
            "best_values": json.dumps(study.best_trials[0].values if study.best_trials else None),
        })
    except Exception:
        pass


# =============================================================================
# V35 Unified Tuning Tasks
# =============================================================================

def run_v35_optimization(
    strategy_name: str,
    param_groups: List[str],
    n_trials: int = 100,
    capital: float = 10_000.0,
    start_date: str = "2024-01-01",
    end_date: str = "2024-12-31",
    symbol: str = "BTC",
) -> Dict[str, Any]:
    """Run V35 parameter optimization with Optuna.

    Uses GrowthObjective for growth-focused optimization with MDD constraints.
    Leverages ComponentStrategyAdapter for full V35 feature support.

    Args:
        strategy_name: V35 strategy to optimize (e.g., "v35_long_v2").
        param_groups: List of parameter groups to tune (e.g., ["risk", "sizing"]).
        n_trials: Number of optimization trials (default 100).
        capital: Initial capital in USD (default $10,000).
        start_date: Backtest start date (default "2024-01-01").
        end_date: Backtest end date (default "2024-12-31").
        symbol: Trading symbol (default "BTC").

    Returns:
        Dict with best params, score, and optimization stats.

    Raises:
        FileNotFoundError: If data file not found.
        ValueError: If strategy_name not recognized.
    """
    import os
    import sys
    from pathlib import Path
    import optuna
    import logging

    logger = logging.getLogger(__name__)

    # Ensure project root in path
    project_root = Path(__file__).parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from ..optimizer.v35_objective import GrowthObjective, create_v35_study
    from ..optimizer.v35_search_space import V35_STRATEGY_PARAMS

    # Validate strategy
    if strategy_name not in V35_STRATEGY_PARAMS:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    # Find data path
    data_path = project_root / "data" / "btc_data.db"
    if not data_path.exists():
        # Try alternative paths
        alt_paths = [
            project_root / "data" / "binance_bitcoin.db",
            project_root / "data" / "bitcoin_data.db",
        ]
        for alt in alt_paths:
            if alt.exists():
                data_path = alt
                break

    if not data_path.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    logger.info(f"Starting V35 optimization: {strategy_name}")
    logger.info(f"  Param groups: {param_groups}")
    logger.info(f"  Trials: {n_trials}, Capital: ${capital:,.0f}")
    logger.info(f"  Period: {start_date} to {end_date}")

    # Create objective
    objective = GrowthObjective(
        strategy_name=strategy_name,
        data_path=str(data_path),
        start_date=start_date,
        end_date=end_date,
        symbol=symbol,
        capital=capital,
        enabled_groups=param_groups if param_groups else None,
    )

    # Create study with SQLite persistence
    db_path = Path(__file__).parent.parent / "quant_lab_studies.db"
    storage = f"sqlite:///{db_path}"

    study = create_v35_study(
        strategy_name=strategy_name,
        start_date=start_date,
        end_date=end_date,
        storage=storage,
        sampler_seed=42,
    )

    # Run optimization
    study.optimize(
        objective,
        n_trials=n_trials,
        show_progress_bar=True,
        callbacks=[
            lambda s, t: logger.info(
                f"Trial {t.number}: score={t.value:.4f}" if t.value else f"Trial {t.number}: pruned"
            )
        ],
    )

    # Get results
    best = study.best_trial

    result = {
        "strategy": strategy_name,
        "best_score": best.value,
        "best_params": best.params,
        "n_trials": len(study.trials),
        "n_completed": len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]),
        "n_pruned": len([t for t in study.trials if t.state == optuna.trial.TrialState.PRUNED]),
        "param_groups": param_groups,
        "capital": capital,
        "period": f"{start_date} to {end_date}",
        "study_name": study.study_name,
    }

    logger.info(f"Optimization complete: best_score={best.value:.4f}")
    logger.info(f"  Best params: {best.params}")

    return result
