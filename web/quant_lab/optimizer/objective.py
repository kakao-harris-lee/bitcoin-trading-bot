"""Multi-objective optimization function for regime-based strategies."""
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional
import optuna
from optuna.study import StudyDirection

from .search_space import SearchSpaceConfig, sample_trial_config, REGIMES


@dataclass
class RegimeBacktestObjective:
    """
    Callable objective function for Optuna multi-objective optimization.

    Returns (win_rate, total_return, max_drawdown) tuple.
    """
    data_path: str
    start_date: str
    end_date: str
    symbols: List[str]
    search_config: SearchSpaceConfig = None

    def __post_init__(self):
        if self.search_config is None:
            self.search_config = SearchSpaceConfig()

    def __call__(self, trial: optuna.Trial) -> Tuple[float, float, float]:
        """
        Evaluate a trial configuration.

        Args:
            trial: Optuna trial with hyperparameters

        Returns:
            Tuple of (win_rate, total_return, max_drawdown)
        """
        # Sample configuration from trial
        config = sample_trial_config(trial, self.search_config)

        # Run backtest with this configuration
        metrics = self._run_backtest(config)

        return (
            metrics["win_rate"],
            metrics["total_return"],
            metrics["max_drawdown"],
        )

    def _run_backtest(self, config: Dict[str, Any]) -> Dict[str, float]:
        """
        Run backtest with the given regime configuration.

        Args:
            config: Dict mapping regime -> {entry, exit, params}

        Returns:
            Dict with win_rate, total_return, max_drawdown
        """
        # Placeholder implementation - will be connected to real backtester
        # This is a stub that returns zeros
        return {
            "win_rate": 0.0,
            "total_return": 0.0,
            "max_drawdown": 0.0,
        }


def create_multi_objective(
    study_name: str,
    storage: Optional[str] = None,
) -> optuna.Study:
    """
    Create an Optuna study with 3 objectives.

    Objectives:
        1. Win Rate (maximize)
        2. Total Return (maximize)
        3. Max Drawdown (minimize)

    Args:
        study_name: Name for the study
        storage: Optional SQLite URL for persistence

    Returns:
        Configured Optuna study
    """
    return optuna.create_study(
        study_name=study_name,
        storage=storage,
        directions=[
            StudyDirection.MAXIMIZE,  # win_rate
            StudyDirection.MAXIMIZE,  # total_return
            StudyDirection.MINIMIZE,  # max_drawdown
        ],
        sampler=optuna.samplers.NSGAIISampler(),
        load_if_exists=True,
    )
