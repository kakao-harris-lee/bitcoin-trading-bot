"""RQ background tasks for optimization."""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from enum import Enum
import json
import redis
import os
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


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


QUANTLAB_ACTIVE_JOB_TTL_SEC = _env_int("QUANTLAB_ACTIVE_JOB_TTL_SEC", 3 * 24 * 3600)
QUANTLAB_FINISHED_JOB_TTL_SEC = _env_int("QUANTLAB_FINISHED_JOB_TTL_SEC", 14 * 24 * 3600)
QUANTLAB_JOB_INDEX_TTL_SEC = _env_int("QUANTLAB_JOB_INDEX_TTL_SEC", 30 * 24 * 3600)
QUANTLAB_JOB_INDEX_KEY = "quant_lab:jobs"


def _job_ttl_for_status(status: JobStatus) -> int:
    if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        return max(60, QUANTLAB_FINISHED_JOB_TTL_SEC)
    return max(60, QUANTLAB_ACTIVE_JOB_TTL_SEC)


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

    # Strategy type: regime-only (LLM optimization not implemented here)
    strategy_type: str = "regime"

    # Optional compatibility fields retained for persisted jobs.
    asset: Optional[str] = None
    config_path: Optional[str] = None

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
            "strategy_type": self.strategy_type,
            "asset": self.asset,
            "config_path": self.config_path,
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

    # Build objective (Quant Lab currently supports regime optimization only)
    study.set_user_attr("strategy_type", "regime")
    study.set_user_attr(
        "objective_names",
        ["win_rate", "total_return", "max_drawdown"],
    )
    study.set_user_attr(
        "objective_labels",
        ["Win Rate", "Total Return", "Max Drawdown"],
    )
    search_config = SearchSpaceConfig()
    if job.search_config:
        search_config.regime_configs = job.search_config
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
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
        data = {
            "status": status.value,
            "updated_at": datetime.utcnow().isoformat(),
        }
        if extra:
            data.update(extra)
        key = f"quant_lab:job:{job_id}"
        r.hset(key, mapping={k: json.dumps(v) for k, v in data.items()})
        r.sadd(QUANTLAB_JOB_INDEX_KEY, job_id)
        r.expire(QUANTLAB_JOB_INDEX_KEY, max(300, QUANTLAB_JOB_INDEX_TTL_SEC))
        r.expire(key, _job_ttl_for_status(status))
    except Exception:  # pylint: disable=broad-exception-caught
        pass  # Don't fail optimization if Redis update fails


def _on_trial_complete(job_id: str, study, trial) -> None:
    """Callback after each trial completes."""
    try:
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
        # trial.number is 0-indexed, so add 1 for display (trial 0 = "1 of N")
        key = f"quant_lab:job:{job_id}"
        r.hset(key, mapping={
            "current_trial": json.dumps(trial.number + 1),
            "best_values": json.dumps(study.best_trials[0].values if study.best_trials else None),
        })
        r.sadd(QUANTLAB_JOB_INDEX_KEY, job_id)
        r.expire(QUANTLAB_JOB_INDEX_KEY, max(300, QUANTLAB_JOB_INDEX_TTL_SEC))
        r.expire(key, _job_ttl_for_status(JobStatus.RUNNING))
    except Exception:  # pylint: disable=broad-exception-caught
        pass
