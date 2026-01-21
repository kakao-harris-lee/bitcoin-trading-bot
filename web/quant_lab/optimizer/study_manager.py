"""Optuna study lifecycle management."""
from typing import List, Optional, Dict, Any
import optuna
from optuna.study import StudyDirection


class StudyManager:
    """
    Manages Optuna study lifecycle.

    Handles study creation, persistence, resumption, and Pareto front extraction.
    """

    def __init__(self, storage_path: str = "quant_lab_studies.db"):
        """
        Initialize study manager.

        Args:
            storage_path: Path to SQLite database for study persistence
        """
        self.storage_path = storage_path
        self.storage_url = f"sqlite:///{storage_path}"

    def create_study(
        self,
        study_name: str,
        directions: Optional[List[str]] = None,
    ) -> optuna.Study:
        """
        Create a new multi-objective study.

        Args:
            study_name: Unique name for the study
            directions: List of "maximize" or "minimize" for each objective
                       Defaults to [maximize, maximize, minimize] for
                       (win_rate, return, drawdown)

        Returns:
            Created Optuna study
        """
        if directions is None:
            # Default: maximize win_rate, maximize return, minimize drawdown
            study_directions = [
                StudyDirection.MAXIMIZE,
                StudyDirection.MAXIMIZE,
                StudyDirection.MINIMIZE,
            ]
        else:
            study_directions = [
                StudyDirection.MAXIMIZE if d == "maximize" else StudyDirection.MINIMIZE
                for d in directions
            ]

        study = optuna.create_study(
            study_name=study_name,
            storage=self.storage_url,
            directions=study_directions,
            sampler=optuna.samplers.NSGAIISampler(),
            load_if_exists=True,
        )

        return study

    def get_study(self, study_name: str) -> optuna.Study:
        """
        Get or resume an existing study.

        Args:
            study_name: Name of study to retrieve

        Returns:
            Existing Optuna study
        """
        return optuna.load_study(
            study_name=study_name,
            storage=self.storage_url,
        )

    def list_studies(self) -> List[optuna.study.StudySummary]:
        """
        List all studies in storage.

        Returns:
            List of study summaries
        """
        return optuna.get_all_study_summaries(storage=self.storage_url)

    def delete_study(self, study_name: str) -> None:
        """
        Delete a study from storage.

        Args:
            study_name: Name of study to delete
        """
        optuna.delete_study(
            study_name=study_name,
            storage=self.storage_url,
        )

    def get_pareto_front(self, study_name: str) -> List[optuna.trial.FrozenTrial]:
        """
        Get Pareto-optimal trials from a study.

        Args:
            study_name: Name of study

        Returns:
            List of Pareto-optimal trials
        """
        study = self.get_study(study_name)
        return study.best_trials

    def get_trial_config(self, study_name: str, trial_number: int) -> Dict[str, Any]:
        """
        Get the full configuration for a specific trial.

        Args:
            study_name: Name of study
            trial_number: Trial number to retrieve

        Returns:
            Dict with trial parameters and results
        """
        study = self.get_study(study_name)
        trial = study.trials[trial_number]

        return {
            "number": trial.number,
            "params": trial.params,
            "values": trial.values,
            "state": trial.state.name,
            "datetime_start": trial.datetime_start.isoformat() if trial.datetime_start else None,
            "datetime_complete": trial.datetime_complete.isoformat() if trial.datetime_complete else None,
        }

    def get_study_stats(self, study_name: str) -> Dict[str, Any]:
        """
        Get statistics for a study.

        Args:
            study_name: Name of study

        Returns:
            Dict with study statistics
        """
        study = self.get_study(study_name)

        completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
        failed = [t for t in study.trials if t.state == optuna.trial.TrialState.FAIL]
        pruned = [t for t in study.trials if t.state == optuna.trial.TrialState.PRUNED]

        return {
            "study_name": study_name,
            "total_trials": len(study.trials),
            "completed_trials": len(completed),
            "failed_trials": len(failed),
            "pruned_trials": len(pruned),
            "pareto_front_size": len(study.best_trials),
            "directions": [d.name for d in study.directions],
        }
